import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, func, and_, select, update, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import TIMESTAMP
import logging
from datetime import datetime
import pandas as pd
import streamlit as st
from sqlalchemy import exists, or_  # Add 'or_' to the imports
from utils.logging.log_util import get_logger
from sqlalchemy.exc import ProgrammingError
from sqlalchemy import text

logger = get_logger(__name__)

# Load environment variables
load_dotenv()

# Get DATABASE_URL from environment variables
DATABASE_URL = os.getenv('DATABASE_URL')

# Create SQLAlchemy engine and session
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

class News(Base):
    __tablename__ = 'news'

    id = Column(Integer, primary_key=True)
    title = Column(Text)
    link = Column(Text)
    company = Column(Text)
    published_date = Column(TIMESTAMP(timezone=True))
    content = Column(Text)
    reason = Column(Text)
    industry = Column(Text)
    publisher_topic = Column(Text)
    event = Column(String(255))
    publisher = Column(String(255))
    downloaded_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)
    status = Column(String(255))
    instrument_id = Column(BigInteger)
    yf_ticker = Column(String(255))
    ticker = Column(String(16))
    published_date_gmt = Column(TIMESTAMP(timezone=True))
    timezone = Column(String(50))
    publisher_summary = Column(Text)
    ticker_url = Column(String(500))
    predicted_side = Column(String(10))
    predicted_move = Column(Float)
    language = Column(String(50), nullable=True)
    title_en = Column(Text, nullable=True)
    content_en = Column(Text, nullable=True)


class NewsPredictions(Base):
    __tablename__ = 'news_predictions'

    id = Column(Integer, primary_key=True)
    news_id = Column(Integer, nullable=False)
    published_date = Column(TIMESTAMP(timezone=True), nullable=True)
    market_status = Column(String(50), nullable=True)
    link = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    event_standardized = Column(String(255), nullable=True)
    publisher = Column(String(255), nullable=True)
    yf_ticker = Column(String(50), nullable=True)
    predicted_side = Column(String(50), nullable=True)
    predicted_price_change_percentage = Column(Float, nullable=True)
    model_id_classifier = Column(String(255), nullable=True)
    model_id_regressor = Column(String(255), nullable=True)
    classifier_prob = Column(Float, nullable=True)  # Model accuracy from model_tracking
    regressor_prob = Column(Float, nullable=True)  # Model r2_score from model_tracking
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)

    # Keep event for backward compatibility
    event = Column(String(255), nullable=True)




def sanitize_string(value):
    """Remove NUL (0x00) characters from strings that PostgreSQL cannot handle"""
    if value is None:
        return None
    if isinstance(value, str):
        # Remove NUL characters
        return value.replace('\x00', '')
    return value


def add_news_items(news_items, check_uniqueness=True):
    logger.info(f"Adding {len(news_items)} news items to the database")
    added_count = 0
    duplicate_count = 0

    with Session() as session:
        for item in news_items:
            if check_uniqueness:
                logger.debug(f"Checking item with content length: {len(item.content) if item.content else 0}")

                existing_item = session.query(News).filter(
                    News.link == item.link,
                    News.publisher == item.publisher
                ).first()

                if existing_item:
                    duplicate_count += 1
                    logger.debug(f"Duplicate found for link: {item.link}")
                    continue

            # Sanitize all text fields to remove NUL characters
            item.title = sanitize_string(item.title)
            item.link = sanitize_string(item.link)
            item.company = sanitize_string(item.company)
            item.content = sanitize_string(item.content)
            item.reason = sanitize_string(item.reason)
            item.industry = sanitize_string(item.industry)
            item.publisher_topic = sanitize_string(item.publisher_topic)
            item.event = sanitize_string(item.event)
            item.publisher = sanitize_string(item.publisher)
            item.status = sanitize_string(item.status)
            item.yf_ticker = sanitize_string(item.yf_ticker)
            item.ticker = sanitize_string(item.ticker)
            item.timezone = sanitize_string(item.timezone)
            item.publisher_summary = sanitize_string(item.publisher_summary)
            item.ticker_url = sanitize_string(item.ticker_url)
            item.predicted_side = sanitize_string(item.predicted_side)
            item.language = sanitize_string(item.language)
            item.title_en = sanitize_string(item.title_en)
            item.content_en = sanitize_string(item.content_en)

            session.add(item)
            added_count += 1
            logger.debug(f"Added item with content length: {len(item.content) if item.content else 0}")

        try:
            session.commit()
            logger.info(f"Successfully committed {added_count} items to database")
        except Exception as e:
            logger.error(f"Error committing to database: {str(e)}")
            session.rollback()
            raise

    logger.info(f"Added {added_count} news items to the database, {duplicate_count} duplicates skipped")
    return added_count, duplicate_count

def get_news_by_links(links, publisher):
    """Get news items by links and publisher after they have been inserted"""
    logger.info(f"Getting news items for {len(links)} links from {publisher}")
    session = Session()
    try:
        news_items = session.query(News).filter(
            and_(
                News.link.in_(links),
                News.publisher == publisher
            )
        ).all()

        logger.info(f"Found {len(news_items)} news items with IDs")
        return news_items
    except Exception as e:
        logger.error(f"Error getting news by links: {str(e)}")
        raise
    finally:
        session.close()

def remove_duplicates(news_items):
    logger.info(f"Checking for duplicates in the database for {len(news_items)} items")
    session = Session()
    try:
        unique_items = []
        duplicate_count = 0
        processed_count = 0

        for item in news_items:
            processed_count += 1

            # Check if the item already exists in the database using both link and publisher
            is_duplicate = session.query(exists().where(
                and_(
                    News.link == item.link,
                    News.publisher == item.publisher
                )
            )).scalar()

            if not is_duplicate:
                unique_items.append(item)
            else:
                duplicate_count += 1
                logger.debug(f"Found duplicate for link: {item.link} and publisher: {item.publisher}")

            # Log progress every 50 items
            if processed_count % 50 == 0:
                logger.info(f"Duplicate check progress: {processed_count}/{len(news_items)} items processed")

        logger.info(f"Duplicate check completed: {duplicate_count} duplicates found, {len(unique_items)} unique items kept")
        logger.info(f"Duplicate rate: {(duplicate_count/len(news_items)*100):.1f}%")

        return unique_items, duplicate_count
    except Exception as e:
        logger.error(f"An error occurred while checking for duplicates: {e}")
        return [], 0
    finally:
        session.close()

def map_to_db(df, source):
    logging.info(f"Mapping dataframe to News objects for source: {source}")

    news_items = []
    for _, row in df.iterrows():
        # Handle instrument_id - convert nan or float to proper integer or None
        instrument_id = row.get('instrument_id')
        if pd.isna(instrument_id):
            instrument_id = None
        elif isinstance(instrument_id, float):
            instrument_id = int(instrument_id) if instrument_id.is_integer() else None

        # Pandas uses NaN for missing DataFrame values. Convert it to a real
        # database NULL instead of storing the string/float value "NaN".
        predicted_side = row.get('predicted_side')
        if pd.isna(predicted_side) or str(predicted_side).strip().upper() == 'NAN':
            predicted_side = None
        else:
            predicted_side = str(predicted_side).strip().upper()

        predicted_move = row.get('predicted_move')
        if pd.isna(predicted_move):
            predicted_move = None
        else:
            predicted_move = float(predicted_move)

        news_item = News(
            title=row.get('title', ''),
            link=row.get('link', ''),
            company=row.get('company', ''),
            published_date=row.get('published_date'),
            content=row.get('content', ''),
            reason=row.get('reason', ''),
            industry=row.get('industry', ''),
            publisher_topic=row.get('publisher_topic', ''),
            event=row.get('event', ''),
            publisher=row.get('publisher', source),
            downloaded_at=datetime.utcnow(),
            status=row.get('status', 'raw'),
            instrument_id=instrument_id,  # Use the cleaned instrument_id
            yf_ticker=row.get('yf_ticker', ''),
            ticker=row.get('ticker', ''),
            published_date_gmt=row.get('published_date_gmt'),
            timezone=row.get('timezone', ''),
            publisher_summary=row.get('publisher_summary', ''),
            ticker_url=row.get('ticker_url', ''),
            predicted_side=predicted_side,
            predicted_move=predicted_move,
            language=row.get('language', ''),
            title_en=row.get('title_en'),
            content_en=row.get('content_en')
        )
        news_items.append(news_item)

    logging.info(f"Created {len(news_items)} News objects")

    return news_items

def remove_duplicate_news_db():
    session = Session()
    try:
        subquery = session.query(News.link, func.min(News.downloaded_at).label('min_downloaded_at')) \
                          .group_by(News.link) \
                          .subquery()

        duplicates = session.query(News.id) \
                            .join(subquery, and_(News.link == subquery.c.link,
                                                 News.downloaded_at != subquery.c.min_downloaded_at))

        deleted_count = session.query(News).filter(News.id.in_(duplicates)).delete(synchronize_session='fetch')

        updated_count = session.query(News).filter(News.status == 'raw').update({News.status: 'clean'}, synchronize_session='fetch')

        session.commit()
        logging.info(f"Successfully removed {deleted_count} duplicate news items.")
        logging.info(f"Updated status to 'clean' for {updated_count} news items.")

        return deleted_count, updated_count
    except Exception as e:
        logging.error(f"An error occurred while removing duplicates and updating status: {e}")
        session.rollback()
        return 0, 0
    finally:
        session.close()

def get_news_df_date_range(publishers, start_date, end_date):
    session = Session()
    try:
        query = select(News).where(
            News.publisher.in_(publishers),
            News.published_date >= start_date,
            News.published_date <= end_date
        ).order_by(News.published_date.desc())

        result = session.execute(query)
        news_items = result.scalars().all()

        data = [{
            'news_id': item.id,
            'ticker': item.ticker,
            'ticker_url': item.ticker_url,
            'title': item.title,
            'link': item.link,
            'published_date': item.published_date,
            'company': item.company,
            'event': item.event,
            'reason': item.reason,
            'publisher': item.publisher,
            'industry': item.industry,
            'publisher_topic': item.publisher_topic,
            'instrument_id': item.instrument_id,
            'yf_ticker': item.yf_ticker,
            'published_date_gmt': item.published_date_gmt,
            'timezone': item.timezone,
            'publisher_summary': item.publisher_summary,
            'predicted_side': item.predicted_side,
            'predicted_move': item.predicted_move,
            'event': item.event,
            'language': item.language
        } for item in news_items]

        return pd.DataFrame(data)
    finally:
        session.close()

def get_news_without_tickers():
    logging.info("Retrieving news items without tickers from database")

    session = Session()
    try:
        query = select(News).where(News.ticker.is_(None))
        result = session.execute(query)
        news_items = result.scalars().all()
        count = len(news_items)
        logging.info(f"Retrieved {count} news items without tickers")

        return news_items
    finally:
        session.close()

def update_news_tickers(news_items_with_data):
    logging.info("Updating database with extracted tickers, yf_tickers, and instrument IDs")

    session = Session()
    try:
        updated_count = 0
        total_items = len(news_items_with_data)
        for index, (news_id, ticker, yf_ticker, instrument_id, ticker_url) in enumerate(news_items_with_data):
            update_values = {}
            if ticker:
                update_values['ticker'] = ticker
            if yf_ticker:
                update_values['yf_ticker'] = yf_ticker
            if instrument_id:
                update_values['instrument_id'] = instrument_id
            if ticker_url:
                update_values['ticker_url'] = ticker_url

            if update_values:
                stmt = update(News).where(News.id == news_id).values(**update_values)
                session.execute(stmt)
                updated_count += 1

            if (index + 1) % 10 == 0 or index == total_items - 1:
                session.commit()
                logging.info(f"Processed {index + 1}/{total_items} items")

        logging.info(f"Successfully updated {updated_count} news items with tickers, yf_tickers, and instrument IDs")
    except Exception as e:
        logging.error(f"Error updating news items: {str(e)}")
        session.rollback()
    finally:
        session.close()

def update_news_status(news_ids, new_status):
    logging.info(f"Updating status to '{new_status}' for {len(news_ids)} news items")

    session = Session()
    try:
        updated_count = session.query(News).filter(News.id.in_(news_ids)).update({News.status: new_status}, synchronize_session='fetch')
        session.commit()
        logging.info(f"Successfully updated status for {updated_count} news items")

        return updated_count
    except Exception as e:
        logging.error(f"An error occurred while updating news status: {e}")
        session.rollback()
        return 0
    finally:
        session.close()

def get_news_without_company(publisher):
    logging.info(f"Retrieving news items without company names for publisher: {publisher}")

    session = Session()
    try:
        query = select(News).where(
            News.company.is_(None),
            News.publisher == publisher
        )
        result = session.execute(query)
        news_items = result.scalars().all()
        count = len(news_items)
        logging.info(f"Retrieved {count} news items without company names for {publisher}")

        return news_items
    finally:
        session.close()

def update_companies(enriched_df):
    logging.info("Updating database with enriched company names")

    session = Session()
    try:
        updated_count = 0
        total_items = len(enriched_df)
        for index, row in enriched_df.iterrows():
            news_item = session.get(News, row['id'])
            if news_item and 'company' in row and row['company']:
                news_item.company = row['company']
                updated_count += 1

            if (index + 1) % 10 == 0 or index == total_items - 1:
                logging.info(f"Updated {index + 1}/{total_items} items")

        session.commit()
        logging.info(f"Successfully updated {updated_count} news items with company names")
    except Exception as e:
        logging.error(f"Error updating company names: {str(e)}")
        session.rollback()
    finally:
        session.close()

def get_news_by_id(news_id):
    logging.info(f"Retrieving news item with id: {news_id}")

    session = Session()
    try:
        query = select(News).where(News.id == news_id)
        result = session.execute(query)
        news_item = result.scalars().first()

        if news_item:
            return pd.DataFrame([{
                'news_id': news_item.id,
                'ticker': news_item.ticker,
                'ticker_url': news_item.ticker_url,
                'title': news_item.title,
                'link': news_item.link,
                'published_date': news_item.published_date,
                'company': news_item.company,
                'event': news_item.event,
                'reason': news_item.reason,
                'publisher': news_item.publisher,
                'industry': news_item.industry,
                'publisher_topic': news_item.publisher_topic,
                'instrument_id': news_item.instrument_id,
                'yf_ticker': news_item.yf_ticker,
                'published_date_gmt': news_item.published_date_gmt,
                'timezone': news_item.timezone,
                'publisher_summary': news_item.publisher_summary,
                'predicted_side': news_item.predicted_side,
                'predicted_move': news_item.predicted_move,
                'event': news_item.event,
                'language': news_item.language
            }])
        else:
            logging.warning(f"No news item found with id: {news_id}")
            return pd.DataFrame()
    finally:
        session.close()

def get_news_df(publisher=None, limit=None):
    """
    Retrieve news items from database
    Args:
        publisher: Optional publisher filter
        limit: Optional limit on number of items to fetch (applied at SQL level for performance)
    """
    if limit:
        logging.info(f"Retrieving {limit} news items ordered by published date{' for publisher: ' + publisher if publisher else ''}")
    else:
        logging.info(f"Retrieving all news items ordered by published date{' for publisher: ' + publisher if publisher else ''}")

    session = Session()
    try:
        query = select(News).order_by(News.published_date.asc())

        if publisher:
            query = query.filter(News.publisher == publisher)

        if limit:
            query = query.limit(limit)

        result = session.execute(query)
        news_items = result.scalars().all()

        data = [{
            'news_id': item.id,
            'ticker': item.ticker,
            'ticker_url': item.ticker_url,
            'title': item.title,
            'link': item.link,
            'published_date': item.published_date,
            'company': item.company,
            'event': item.event,
            'reason': item.reason,  # Make sure 'reason' is included here
            'publisher': item.publisher,
            'industry': item.industry,
            'publisher_topic': item.publisher_topic,
            'instrument_id': item.instrument_id,
            'yf_ticker': item.yf_ticker,
            'published_date_gmt': item.published_date_gmt,
            'timezone': item.timezone,
            'publisher_summary': item.publisher_summary,
            'predicted_side': item.predicted_side,
            'predicted_move': item.predicted_move,
            'content': item.content,  # Include 'content' as it's used in enrich_reason
            'content_en': item.content_en,  # Include English content for prediction
            'title_en': item.title_en,  # Include English title for prediction
            'language': item.language
        } for item in news_items]

        df = pd.DataFrame(data)
        logging.info(f"Retrieved {len(df)} news items")
        return df
    finally:
        session.close()

def get_news_latest_df(publisher=None):
    logging.info(f"Retrieving latest 1000 news items ordered by published date{' for publisher: ' + publisher if publisher else ''}")

    session = Session()
    try:
        query = select(News).order_by(News.published_date.asc())

        if publisher:
            query = query.filter(News.publisher == publisher)

        query = query.limit(1000)

        result = session.execute(query)
        news_items = result.scalars().all()

        data = [{
            'news_id': item.id,
            'ticker': item.ticker,
            'ticker_url': item.ticker_url,
            'title': item.title,
            'link': item.link,
            'published_date': item.published_date,
            'company': item.company,
            'event': item.event,
            'reason': item.reason,
            'publisher': item.publisher,
            'industry': item.industry,
            'publisher_topic': item.publisher_topic,
            'instrument_id': item.instrument_id,
            'yf_ticker': item.yf_ticker,
            'published_date_gmt': item.published_date_gmt,
            'timezone': item.timezone,
            'publisher_summary': item.publisher_summary,
            'predicted_side': item.predicted_side,
            'predicted_move': item.predicted_move,
            'event': item.event,
            'language': item.language
        } for item in news_items]

        df = pd.DataFrame(data)
        logging.info(f"Retrieved {len(df)} latest news items")
        return df
    finally:
        session.close()

def update_news_predictions(df):
    logging.info("Updating news table with predictions")

    session = Session()
    try:
        updated_count = 0
        total_items = len(df)
        for index, row in df.iterrows():
            news_item = session.get(News, row['news_id'])
            if news_item:
                if pd.notnull(row['predicted_side']):
                    news_item.predicted_side = row['predicted_side']
                    logging.info(f"Updating predicted_side for news_id {row['news_id']}: {row['predicted_side']}")
                else:
                    logging.warning(f"Null predicted_side for news_id {row['news_id']}")
                if pd.notnull(row['predicted_move']):
                    news_item.predicted_move = row['predicted_move']
                    logging.info(f"Updating predicted_move for news_id {row['news_id']}: {row['predicted_move']}")
                else:
                    logging.warning(f"Null predicted_move for news_id {row['news_id']}")
                updated_count += 1
            else:
                logging.warning(f"No news item found for news_id {row['news_id']}")

            if (index + 1) % 100 == 0 or index == total_items - 1:
                session.commit()
                logging.info(f"Updated {index + 1}/{total_items} items")

        logging.info(f"Successfully updated {updated_count} news items with predictions")
    except Exception as e:
        logging.error(f"Error updating news predictions: {str(e)}")
        session.rollback()
    finally:
        session.close()

def check_news_predictions_table():
    """Check what's in news_predictions table using raw SQL"""
    logger.info("Checking news_predictions table...")

    session = Session()
    try:
        # Use raw SQL to check table structure and count
        count_query = text("SELECT COUNT(*) as count FROM news_predictions")
        result = session.execute(count_query).fetchone()
        count = result[0] if result else 0

        logger.info(f"Total records in news_predictions: {count}")

        if count > 0:
            # Get sample records using raw SQL
            sample_query = text("""
                SELECT id, news_id, publisher, event, predicted_side, predicted_price_change_percentage, created_at
                FROM news_predictions
                LIMIT 5
            """)
            samples = session.execute(sample_query).fetchall()

            logger.info("\nSample records:")
            for sample in samples:
                logger.info(f"  ID: {sample.id}, News ID: {sample.news_id}, Publisher: {sample.publisher}, "
                          f"Event: {sample.event}, Side: {sample.predicted_side}, "
                          f"Move: {sample.predicted_price_change_percentage}")

            # Get statistics using raw SQL
            stats_query = text("""
                SELECT
                    COUNT(*) FILTER (WHERE predicted_side IS NOT NULL) as with_side,
                    COUNT(*) FILTER (WHERE predicted_price_change_percentage IS NOT NULL) as with_move
                FROM news_predictions
            """)
            stats = session.execute(stats_query).fetchone()

            logger.info(f"\nStatistics:")
            logger.info(f"  Records with predicted_side: {stats[0] if stats else 0}")
            logger.info(f"  Records with predicted_move: {stats[1] if stats else 0}")
        else:
            logger.info("Table is empty")

        return count
    except Exception as e:
        logger.error(f"Error checking news_predictions table: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0
    finally:
        session.close()

def save_predictions_to_news_predictions(df):
    """
    Save predictions to news_predictions table
    Saves: news_id, published_date, market_status, link, title, event_standardized, publisher, yf_ticker, predicted_side, predicted_move
    Args:
        df: DataFrame with columns: id (news_id), published_date, market_status, link, title, event_standardized, publisher, yf_ticker, predicted_side, predicted_move
    """
    logger.info(f"Saving predictions to news_predictions table for {len(df)} news items")

    session = Session()
    try:
        saved_count = 0
        updated_count = 0
        skipped_count = 0

        for index, row in df.iterrows():
            news_id = row.get('id') or row.get('news_id')
            logger.warning(f"Row {index}: news_id from 'id': {row.get('id')}, from 'news_id': {row.get('news_id')}, final: {news_id}, type: {type(news_id)}")
            if not news_id:
                logger.warning(f"Row {index} missing news_id, skipping")
                skipped_count += 1
                continue

            # Get values for all columns
            published_date = row.get('published_date', None)
            market_status = row.get('market_status', None)
            link = row.get('link', None)
            title = row.get('title', None)
            event_standardized = row.get('event_standardized', None)
            publisher = row.get('publisher', '') or None
            yf_ticker = row.get('yf_ticker', None)
            predicted_side = row.get('predicted_side', None) or row.get('prediction_side', None)
            predicted_move = row.get('predicted_move', None) or row.get('prediction_move', None)
            model_id_classifier = row.get('model_id_classifier', None)
            model_id_regressor = row.get('model_id_regressor', None)
            classifier_prob = row.get('classifier_prob', None)
            regressor_prob = row.get('regressor_prob', None)

            # Keep event for backward compatibility (use event_standardized if event not available)
            event = row.get('event', None) or event_standardized

            # Skip if no predictions
            if pd.isna(predicted_side) and pd.isna(predicted_move):
                logger.warning(f"Skipping news_id {news_id}: no predictions")
                skipped_count += 1
                continue

            # Check if prediction already exists for this news_id using raw SQL
            check_query = text("SELECT id FROM news_predictions WHERE news_id = :news_id")
            existing = session.execute(check_query, {"news_id": int(news_id)}).fetchone()

            if existing:
                # Update existing record using raw SQL
                update_query = text("""
                    UPDATE news_predictions
                    SET published_date = :published_date,
                        market_status = :market_status,
                        link = :link,
                        title = :title,
                        event_standardized = :event_standardized,
                        publisher = :publisher,
                        yf_ticker = :yf_ticker,
                        event = :event,
                        predicted_side = :predicted_side,
                        predicted_price_change_percentage = :predicted_move,
                        model_id_classifier = :model_id_classifier,
                        model_id_regressor = :model_id_regressor,
                        classifier_prob = :classifier_prob,
                        regressor_prob = :regressor_prob
                    WHERE news_id = :news_id
                """)
                session.execute(update_query, {
                    "news_id": int(news_id),
                    "published_date": published_date,
                    "market_status": market_status,
                    "link": link,
                    "title": title,
                    "event_standardized": event_standardized,
                    "publisher": publisher,
                    "yf_ticker": yf_ticker,
                    "event": event,
                    "predicted_side": str(predicted_side).upper() if pd.notna(predicted_side) else None,
                    "predicted_move": float(predicted_move) if pd.notna(predicted_move) else None,
                    "model_id_classifier": model_id_classifier if pd.notna(model_id_classifier) else None,
                    "model_id_regressor": model_id_regressor if pd.notna(model_id_regressor) else None,
                    "classifier_prob": float(classifier_prob) if pd.notna(classifier_prob) else None,
                    "regressor_prob": float(regressor_prob) if pd.notna(regressor_prob) else None
                })
                updated_count += 1
            else:
                # Insert new record using raw SQL
                insert_query = text("""
                    INSERT INTO news_predictions (news_id, published_date, market_status, link, title, event_standardized, publisher, yf_ticker, event, predicted_side, predicted_price_change_percentage, model_id_classifier, model_id_regressor, classifier_prob, regressor_prob)
                    VALUES (:news_id, :published_date, :market_status, :link, :title, :event_standardized, :publisher, :yf_ticker, :event, :predicted_side, :predicted_move, :model_id_classifier, :model_id_regressor, :classifier_prob, :regressor_prob)
                """)
                session.execute(insert_query, {
                    "news_id": int(news_id),
                    "published_date": published_date,
                    "market_status": market_status,
                    "link": link,
                    "title": title,
                    "event_standardized": event_standardized,
                    "publisher": publisher,
                    "yf_ticker": yf_ticker,
                    "event": event,
                    "predicted_side": str(predicted_side).upper() if pd.notna(predicted_side) else None,
                    "predicted_move": float(predicted_move) if pd.notna(predicted_move) else None,
                    "model_id_classifier": model_id_classifier if pd.notna(model_id_classifier) else None,
                    "model_id_regressor": model_id_regressor if pd.notna(model_id_regressor) else None,
                    "classifier_prob": float(classifier_prob) if pd.notna(classifier_prob) else None,
                    "regressor_prob": float(regressor_prob) if pd.notna(regressor_prob) else None
                })
                saved_count += 1

            # Commit in batches
            if (saved_count + updated_count) % 100 == 0:
                session.commit()
                logger.info(f"Saved/updated {saved_count + updated_count} predictions...")

        # Final commit
        session.commit()
        logger.info(f"âœ… Saved {saved_count} new predictions, updated {updated_count} existing, skipped {skipped_count}")
        return saved_count + updated_count

    except Exception as e:
        logger.error(f"Error saving predictions to news_predictions: {e}")
        session.rollback()
        import traceback
        logger.error(traceback.format_exc())
        return 0
    finally:
        session.close()

def update_records(df):
    logging.info(f"Updating {len(df)} records in the database")

    session = Session()
    try:
        updated_count = 0
        for index, row in df.iterrows():
            stmt = update(News).where(News.id == row['news_id'])
            update_values = {}
            for column in row.index:
                if column != 'news_id':
                    value = row[column]
                    if pd.notnull(value):
                        if isinstance(value, pd.Timestamp):
                            value = value.to_pydatetime()
                        update_values[column] = value

            if update_values:
                stmt = stmt.values(**update_values)
                result = session.execute(stmt)
                if result.rowcount > 0:
                    updated_count += 1

            if (index + 1) % 100 == 0 or index == len(df) - 1:
                session.commit()
                logging.info(f"Updated {updated_count}/{index + 1} records")

        logging.info(f"Successfully updated {updated_count} records")
        return updated_count
    except Exception as e:
        logging.error(f"Error updating records: {str(e)}")
        session.rollback()
        return 0
    finally:
        session.close()

def get_instrument_by_company_name(company_name):
    logging.info(f"Looking up instrument for company: {company_name}")

    session = Session()
    try:
        # Use both exact match (case-insensitive) and LIKE match on the issuer field
        try:
            instruments = session.query(Instrument).filter(
                or_(
                    func.lower(Instrument.issuer) == func.lower(company_name),
                    func.lower(Instrument.issuer).like(f"%{company_name.lower()}%")
                )
            ).all()

            if instruments:
                # Select the first instrument if there are multiple matches
                instrument = instruments[0]
                logging.info(f"Found instrument for {company_name}: {instrument.ticker}")
                if len(instruments) > 1:
                    logging.warning(f"Multiple instruments found for {company_name}. Using the first match: {instrument.ticker}")
            else:
                instrument = None
                logging.info(f"No instrument found for {company_name}")

            return instrument
        except ProgrammingError as e:
            if 'relation "instruments" does not exist' in str(e):
                logging.error("The 'instruments' table does not exist in the database. Please ensure the table is created and populated.")
            else:
                logging.error(f"An error occurred while querying the database: {str(e)}")
            return None
    finally:
        session.close()
