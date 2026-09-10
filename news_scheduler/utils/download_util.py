import os
import sys
import pandas as pd

# Add playground directory to path for yf_util imports (like colleague's setup)
playground_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'playground')
if playground_dir not in sys.path:
    sys.path.insert(0, playground_dir)

from utils.db.news_db_util import map_to_db, add_news_items, remove_duplicates
from utils.enrich_util import enrich_tag_from_url
from tasks.ai.predict import predict
from tasks.enrich.enrich_reason import enrich_reason  # Uses XAI via xai_util
from utils.logging.log_util import get_logger
from utils.db.instrument_db_util import get_instrument_by_company_name, save_instrument, insert_instrument, create_and_get_instrument
from utils.translate_util import translate_dataframe
from yf_util import search_instrument_info
from utils.static.tag_util import tags as EVENT_TAGS
from tasks.enrich.analysts import fetch_and_store_analyst_data
from utils.enrichment_validation import partition_fully_enriched
try:
    from utils.ai.xai_util import extract_issuer, extract_ticker, tag_news
    _XAI_AVAILABLE = True
    _OPENAI_AVAILABLE = True  # Alias for backward compatibility
except Exception as _e:
    logger = get_logger(__name__)
    logger.warning(f"XAI utilities unavailable, skipping AI enrichment: {_e}")
    _XAI_AVAILABLE = False
    _OPENAI_AVAILABLE = False
from dotenv import load_dotenv

logger = get_logger(__name__)

load_dotenv()

SECTORS_FILE_PATH = os.path.join('config', 'sectors.txt')
GNW_INDUSTRY_FILE_PATH = os.path.join('config', 'gnw_industry_rss_urls.txt')
EVENTS_FILE_PATH = os.path.join('config', 'events.txt')

def _ensure_sectors_file():
    if os.path.exists(SECTORS_FILE_PATH):
        return
    try:
        sectors = []
        if os.path.exists(GNW_INDUSTRY_FILE_PATH):
            with open(GNW_INDUSTRY_FILE_PATH, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if ':' in line:
                        key = line.split(':', 1)[0].strip()
                        if key:
                            sectors.append(key)
        if sectors:
            os.makedirs(os.path.dirname(SECTORS_FILE_PATH), exist_ok=True)
            with open(SECTORS_FILE_PATH, 'w') as f:
                f.write('\n'.join(sorted(set(sectors))))
            logger.info(f"Wrote {len(sectors)} sectors to {SECTORS_FILE_PATH}")
    except Exception as e:
        logger.error(f"Error ensuring sectors file: {str(e)}")

def _load_sectors_list():
    _ensure_sectors_file()
    try:
        with open(SECTORS_FILE_PATH, 'r') as f:
            sectors = [line.strip() for line in f if line.strip()]
            return sectors
    except Exception as e:
        logger.error(f"Error loading sectors file: {str(e)}")
        return []

def _load_events_list():
    try:
        if os.path.exists(EVENTS_FILE_PATH):
            with open(EVENTS_FILE_PATH, 'r') as f:
                events = []
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if ':' in line:
                        key = line.split(':', 1)[0].strip()
                        events.append(key)
                    else:
                        events.append(line)
                return [e for e in events if e]
    except Exception as e:
        logger.error(f"Error loading events file: {str(e)}")
    # Fallback to static tags string
    return [t.strip() for t in EVENT_TAGS.split(',') if t.strip()]

def process_download(df, publisher, check_uniqueness=True):
    initial_count = len(df)
    logger.info(f"{publisher.upper()}: Starting download process with {initial_count} items")

    news_items = map_to_db(df, publisher)
    logger.info(f"{publisher.upper()}: Mapped {len(news_items)} items to database objects")

    if check_uniqueness:
        logger.info(f"{publisher.upper()}: Checking for duplicates in database...")
        unique_items, duplicate_count = remove_duplicates(news_items)
        logger.info(f"{publisher.upper()}: Duplicate check completed")
        logger.info(f"{publisher.upper()}: Removed {duplicate_count} duplicate items")
        logger.info(f"{publisher.upper()}: Keeping {len(unique_items)} unique items")
        news_items = unique_items
    else:
        logger.info(f"{publisher.upper()}: Skipping duplicate check (check_uniqueness=False)")

    if not news_items:
        logger.info(f"{publisher.upper()}: No items to process after removing duplicates")
        return 0

    logger.info(f"{publisher.upper()}: Processing {len(news_items)} unique items")

    # Convert news_items to DataFrame for further processing
    # Use a more reliable method to preserve all fields including publisher_topic and publisher_summary
    news_dicts = []
    for item in news_items:
        item_dict = {}
        # Get all columns from the News model
        for column in item.__table__.columns:
            value = getattr(item, column.name, None)
            # Convert datetime objects to strings for DataFrame compatibility
            if hasattr(value, 'strftime'):
                value = value.strftime("%Y-%m-%d %H:%M:%S")
            item_dict[column.name] = value
        news_dicts.append(item_dict)
    df = pd.DataFrame(news_dicts)

    # 0. XAI-based enrichment: issuer/company, ticker, sector, and fallback event classification
    if _XAI_AVAILABLE:
        try:
            sectors_list = _load_sectors_list()
            events_list = _load_events_list()
            for index, row in df.iterrows():
                try:
                    # Company/Issuer
                    if not row.get('company'):
                        issuer = extract_issuer(row.get('title', '') or row.get('content', '') or '')
                        if issuer:
                            df.at[index, 'company'] = issuer
                    # Ticker
                    if not row.get('ticker') and row.get('company'):
                        maybe_ticker = extract_ticker(row.get('company'))
                        if maybe_ticker:
                            df.at[index, 'ticker'] = maybe_ticker
                            df.at[index, 'yf_ticker'] = maybe_ticker
                    # Sector -> store in industry
                    if sectors_list:
                        news_text = f"{row.get('title','')} {row.get('content','')}".strip()
                        if news_text:
                            sector = tag_news(news_text, sectors_list)
                            if sector:
                                df.at[index, 'industry'] = sector
                    # Event classification via XAI tagger
                    # For Euronext, always re-classify to ensure correct classification (not ESG)
                    # For other publishers, only classify if event is empty
                    should_classify = False
                    if publisher == 'euronext':
                        # Always re-classify Euronext to fix ESG misclassification
                        should_classify = True
                    elif not row.get('event'):
                        # For other publishers, only if event is empty
                        should_classify = True

                    if should_classify and events_list:
                        # Build comprehensive text for better classification (like test script)
                        title = row.get('title', '') or ''
                        content = row.get('content', '') or row.get('content_en', '') or ''
                        company = row.get('company', '') or ''

                        # Combine title, company, and content for better classification
                        # This matches the approach in test_euronext_event_classification.py
                        if company:
                            news_text = f"{title}\n\nCompany: {company}\n\n{content[:1000]}"
                        else:
                            news_text = f"{title}\n\n{content[:1000]}"

                        if news_text.strip():
                            event_guess = tag_news(news_text.strip(), events_list)
                            if event_guess:
                                df.at[index, 'event'] = event_guess
                except Exception as inner_e:
                    logger.warning(f"XAI enrichment failed for row {index}: {str(inner_e)}")
        except Exception as e:
            logger.error(f"Error during XAI-based enrichment: {str(e)}")

    # Enrich instrument ID
    logger.info("Starting instrument ID enrichment")
    new_instruments = []

    for index, row in df.iterrows():
        company = row['company']
        if not company or str(company).strip() in ['.', '']:
            continue

        # Clean company name - remove extra whitespace and newlines
        company = str(company).strip().replace('\n', ' ').replace('\r', ' ')
        # Remove multiple spaces
        company = ' '.join(company.split())

        if not company or company in ['.', '']:
            continue

        instrument = get_instrument_by_company_name(company)
        if instrument:
            # Handle both dictionary and object returns
            instrument_id = instrument.get('id') if isinstance(instrument, dict) else getattr(instrument, 'id', None)
            ticker = instrument.get('ticker') if isinstance(instrument, dict) else getattr(instrument, 'ticker', None)
            yf_ticker = instrument.get('yf_ticker') if isinstance(instrument, dict) else getattr(instrument, 'yf_ticker', None)
            url = instrument.get('url') if isinstance(instrument, dict) else getattr(instrument, 'url', None)

            if instrument_id:
                df.at[index, 'instrument_id'] = instrument_id
                df.at[index, 'ticker'] = ticker
                df.at[index, 'yf_ticker'] = yf_ticker
                df.at[index, 'ticker_url'] = url
                logger.info(f"Enriched instrument ID for {company}: {instrument_id}")
            else:
                logger.warning(f"Found instrument for {company} but ID was missing")
        else:
            # Try to find instrument info using yfinance with cleaned company name
            instrument_info = search_instrument_info(company)
            if instrument_info:
                try:
                    # Create new instrument using the better function
                    new_instrument = create_and_get_instrument(instrument_info)
                    if new_instrument and new_instrument.get('id'):
                        instrument_id = int(new_instrument['id'])  # Ensure it's an integer
                        logger.info(f"Successfully created instrument with ID {instrument_id}")
                        df.at[index, 'instrument_id'] = instrument_id
                        df.at[index, 'ticker'] = new_instrument.get('ticker')
                        df.at[index, 'yf_ticker'] = new_instrument.get('yf_ticker')
                        df.at[index, 'ticker_url'] = new_instrument.get('url')
                        new_instruments.append(new_instrument)
                        logger.info(f"Created and enriched new instrument for {company}: {instrument_id}")
                    else:
                        logger.warning(f"Failed to create instrument for {company} - no ID returned")
                        df.at[index, 'instrument_id'] = None
                except Exception as e:
                    logger.error(f"Error creating instrument for {company}: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                    df.at[index, 'instrument_id'] = None
            else:
                logger.info(f"No instrument found and couldn't create one for company: {company}")

    if new_instruments:
        logger.info(f"Created {len(new_instruments)} new instruments")
    logger.info("Instrument ID enrichment completed")

    # Analyst datasets ingestion for involved tickers
    try:
        yf_tickers = sorted(set([str(t).strip() for t in df.get('yf_ticker', []) if isinstance(t, str) and t.strip()]))
        if yf_tickers:
            logger.info(f"Starting analyst datasets ingestion for {len(yf_tickers)} tickers")
            for tkr in yf_tickers:
                try:
                    fetch_and_store_analyst_data(tkr)
                except Exception as inner_e:
                    logger.warning(f"Analyst ingestion failed for {tkr}: {inner_e}")
        else:
            logger.info("No yf_ticker values present for analyst ingestion")
    except Exception as e:
        logger.error(f"Error during analyst ingestion step: {str(e)}", exc_info=True)

    # 1. Enrich event from URL (but for Euronext, XAI classification already happened with proper format)
    # Skip URL enrichment for Euronext since we already classified with XAI using proper format
    if publisher != 'euronext':
        try:
            df = enrich_tag_from_url(df)
            logger.info("Event enrichment completed successfully.")
            for index, row in df.iterrows():
                logger.info(f"Event for {row['link']}: {row['event']}")
        except Exception as e:
            logger.error(f"Error during event enrichment: {str(e)}", exc_info=True)
    else:
        logger.info("Skipping URL-based event enrichment for Euronext (using XAI classification from step 0)")

    # Log the dataframe state before translation
    logger.info(f"Before translation - Content sample: {df['content'].iloc[0][:200] if not df.empty else 'No content'}")
    logger.info(f"Before translation - Number of rows: {len(df)}")

    # 2. Enrich language and translate if needed
    try:
        df = translate_dataframe(df)
        logger.info("Translation completed successfully.")
        logger.info(f"After translation - Content sample: {df['content'].iloc[0][:200] if not df.empty else 'No content'}")
        logger.info(f"After translation - Number of rows: {len(df)}")
    except Exception as e:
        logger.error(f"Error during translation: {str(e)}", exc_info=True)

    # 3. Add predictions using AI model
    try:
        df = predict(df)
        logger.info("Prediction completed successfully.")
        logger.info(f"Predictions added - Number of rows with predictions: {df['predicted_move'].notna().sum()}")
        # Add sample prediction logging
        if not df.empty and df['predicted_move'].notna().any():
            sample_idx = df[df['predicted_move'].notna()].index[0]
            logger.info(f"Sample prediction - Move: {df.at[sample_idx, 'predicted_move']}, "
                       f"Side: {df.at[sample_idx, 'predicted_side']}")
    except Exception as e:
        logger.error(f"Error during prediction: {str(e)}", exc_info=True)

    # 4. Enrich reason
    try:
        df = enrich_reason(df)
        logger.info("Reason enrichment completed successfully.")
    except Exception as e:
        logger.error(f"Error during reason enrichment: {str(e)}", exc_info=True)

        # Log all reasons after enrichment
        logger.info("=== All Reasons After Enrichment ===")
        logger.info(f"Dataframe shape: {df.shape}")
        logger.info(f"Columns in dataframe: {df.columns.tolist()}")
        for idx, row in df.iterrows():
            if pd.notna(row['reason']):
                logger.info(f"Row {idx} reason: {row['reason']}")
            else:
                logger.info(f"Row {idx} has no reason")

        reasons_count = df['reason'].notna().sum()
        logger.info(f"Total reasons added: {reasons_count}")

    except Exception as e:
        logger.error(f"Error during reason enrichment: {str(e)}", exc_info=True)

    # Never persist partially enriched new rows. A rejected row is not inserted,
    # so the publisher can discover and retry it on its next scheduled run.
    df, rejected_rows = partition_fully_enriched(df)
    for rejected in rejected_rows:
        logger.error(
            "Skipping incomplete news row before database insertion: "
            f"link={rejected['link']}, missing={rejected['missing']}"
        )
    if rejected_rows:
        logger.error(
            f"{publisher.upper()}: rejected {len(rejected_rows)} incomplete rows; "
            "they remain eligible for the next publisher run"
        )
    if df.empty:
        logger.error(f"{publisher.upper()}: no fully enriched rows available for database insertion")
        return 0

    # Log before database insertion
    logger.info(f"Before database insertion - Number of rows: {len(df)}")
    logger.info(f"Before database insertion - Columns: {df.columns.tolist()}")

    # Map enriched DataFrame back to news items
    enriched_news_items = map_to_db(df, publisher)
    logger.info(f"Created {len(enriched_news_items)} news items for database insertion")

    # Add all items to the database
    added_count, _ = add_news_items(enriched_news_items, check_uniqueness=False)
    logger.info(f"{publisher.upper()}: added {added_count} news items to the database")

    # Final summary
    logger.info(f"{publisher.upper()}: === PROCESSING SUMMARY ===")
    logger.info(f"{publisher.upper()}: Initial items: {initial_count}")
    logger.info(f"{publisher.upper()}: Items after duplicate check: {len(news_items)}")
    logger.info(f"{publisher.upper()}: Final items added to database: {added_count}")
    logger.info(f"{publisher.upper()}: Success rate: {(added_count/initial_count*100):.1f}%")
    logger.info(f"{publisher.upper()}: =========================")

    return added_count
