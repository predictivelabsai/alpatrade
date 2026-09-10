import argparse
import re
import sys
import os
from datetime import datetime, timezone
from dateutil import parser as date_parser
import pandas as pd
import feedparser
import pytz

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import utilities (only import database-related ones if not in CSV mode)
from utils.logging.log_util import get_logger
from utils.scrape.web_util import fetch_url_content
from bs4 import BeautifulSoup

# Lazy import for database functions (only when needed)
_process_download = None
_save_log = None

def get_process_download():
    """Lazy import of process_download to avoid database connection issues in CSV mode."""
    global _process_download
    if _process_download is None:
        from utils.download_util import process_download
        _process_download = process_download
    return _process_download

def get_save_log():
    """Lazy import of save_log to avoid database connection issues in CSV mode."""
    global _save_log
    if _save_log is None:
        from utils.db.logs_db import save_log
        _save_log = save_log
    return _save_log

logger = get_logger(__name__)

CHECK_UNIQUENESS = True
DEFAULT_TIMEZONE = 'US/Eastern'  # PR Newswire is US-based
RSS_URLS_FILE = 'data/prnewswire_rss_urls.txt'

def _format_datetime_no_tz(dt: datetime) -> str:
    """Format datetime to string without timezone."""
    if not dt:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def load_rss_urls() -> list:
    """Load RSS URLs from the text file."""
    urls = []
    try:
        # Try multiple possible paths
        possible_paths = [
            RSS_URLS_FILE,
            os.path.join('data', 'prnewswire_rss_urls.txt')
        ]

        for file_path in possible_paths:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            urls.append(line)
                logger.info(f"Loaded {len(urls)} RSS URLs from {file_path}")
                return urls

        logger.warning(f"RSS URLs file not found in any of the expected locations: {possible_paths}")
        # Fallback to default URL
        urls = ["https://www.prnewswire.com/rss/news-releases-list.rss"]
        logger.info(f"Using default RSS URL: {urls[0]}")
        return urls
    except Exception as e:
        logger.error(f"Error loading RSS URLs: {e}")
        # Fallback to default URL
        return ["https://www.prnewswire.com/rss/news-releases-list.rss"]

def parse_rss_feed(url: str, max_items: int | None = None, use_db_logging: bool = True) -> pd.DataFrame:
    """Parse RSS feed with optional max_items limit."""
    """Parse a single RSS feed and return a DataFrame."""
    logger.info(f"PRNewswire: Parsing RSS feed from: {url}")
    if use_db_logging:
        try:
            get_save_log()(f"PRNewswire: Parsing RSS feed from: {url}", "Info")
        except:
            pass  # Skip if database not available

    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            logger.warning(f"PRNewswire: No entries found in feed: {url}")
            if use_db_logging:
                try:
                    get_save_log()(f"PRNewswire: No entries found in feed: {url}", "Warning")
                except:
                    pass
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"PRNewswire: Error parsing RSS feed {url}: {e}")
        if use_db_logging:
            try:
                get_save_log()(f"PRNewswire: Error parsing RSS feed {url}: {e}", "Error")
            except:
                pass
        return pd.DataFrame()

    items = feed.entries
    if max_items is not None:
        items = items[:max_items]
        logger.info(f"PRNewswire: Limiting to {max_items} items from {url}")
    data = []

    for index, item in enumerate(items, 1):
        try:
            title = item.get('title', 'No Title')
            link = item.get('link', '')
            published_raw = item.get('published', None) or item.get('updated', None)

            published_dt = None
            published_dt_gmt = None
            if published_raw:
                try:
                    # Parse the date
                    parsed_dt = date_parser.parse(published_raw)

                    # Convert to ET timezone first, then to UTC
                    if parsed_dt.tzinfo is None:
                        # Assume ET if no timezone info
                        et_tz = pytz.timezone('US/Eastern')
                        parsed_dt = et_tz.localize(parsed_dt)

                    # Convert to UTC for GMT
                    published_dt_utc = parsed_dt.astimezone(pytz.UTC)
                    published_dt_gmt = _format_datetime_no_tz(published_dt_utc)

                    # Convert to ET for published_date
                    et_tz = pytz.timezone('US/Eastern')
                    published_dt_et = parsed_dt.astimezone(et_tz)
                    published_dt = _format_datetime_no_tz(published_dt_et)
                except Exception as e:
                    logger.warning(f"PRNewswire: Failed to parse date '{published_raw}': {e}")
                    published_dt = published_dt_gmt = None

            # Extract description/summary
            description = item.get('description', '') or item.get('summary', '')
            summary_html = description

            # Fetch content from the URL (using improved extraction)
            content = ''
            if link:
                try:
                    safe_link = link.replace('http://', 'https://')
                    content = fetch_url_content(safe_link, timeout=15, use_improved_extraction=True)
                except Exception as e:
                    logger.debug(f"PRNewswire: Error fetching content for item {index}: {e}")

            # Fallback to summary/description text if content is empty or blocked
            if not content or (isinstance(content, str) and content.startswith("Failed to")):
                if summary_html:
                    try:
                        text = BeautifulSoup(summary_html, 'html.parser').get_text(separator=' ')
                        content = text[:2000]  # Limit content length
                    except Exception:
                        content = summary_html[:2000] if summary_html else ''

            # Extract language
            language = item.get('dc_language', '') or item.get('language', 'en')
            if not language:
                language = 'en'

            # Extract company and ticker from title/content (basic extraction)
            company = ''
            ticker = ''
            full_text = f"{title} {content}".upper()

            # Simple ticker extraction patterns
            ticker_patterns = [
                r'\(NASDAQ:\s*([A-Z]{1,5})\)',
                r'\(NYSE:\s*([A-Z]{1,5})\)',
                r'NASDAQ:\s*([A-Z]{1,5})',
                r'NYSE:\s*([A-Z]{1,5})',
            ]

            for pattern in ticker_patterns:
                match = re.search(pattern, full_text)
                if match:
                    ticker = match.group(1).upper()
                    break

            data.append({
                'title': title,
                'link': link,
                'company': company,
                'published_date': published_dt,
                'published_date_gmt': published_dt_gmt,
                'publisher': 'prnewswire',
                'industry': '',
                'content': content,
                'ticker': ticker,
                'reason': '',
                'publisher_topic': '',
                'status': 'raw',
                'publisher_summary': description[:500] if description else '',
                'ticker_url': '',
                'event': '',
                'language': language,
                'timezone': DEFAULT_TIMEZONE,
            })
        except Exception as e:
            logger.error(f"PRNewswire: Error processing item {index} from {url}: {e}")
            if use_db_logging:
                try:
                    get_save_log()(f"PRNewswire: Error processing item {index} from {url}: {e}", "Error")
                except:
                    pass
            continue

    df = pd.DataFrame(data)
    logger.info(f"PRNewswire: Created dataframe with {len(df)} rows from {url}")
    if use_db_logging:
        try:
            get_save_log()(f"PRNewswire: Created dataframe with {len(df)} rows from {url}", "Info")
        except:
            pass
    return df

def main(save_to_csv=False, csv_output_path=None, max_items=None):
    """
    Main function to fetch and process PRNewswire news.

    Args:
        save_to_csv: If True, save to CSV file instead of database
        csv_output_path: Path to save CSV file (default: data/prnewswire_output.csv)
        max_items: If set, limit the number of items to process (useful for testing)
    """
    if save_to_csv:
        logger.info("PRNewswire: Running in CSV mode (no database save)")
    else:
        try:
            get_save_log()("PRNewswire task started", "Info")
        except:
            logger.info("PRNewswire task started (database logging unavailable)")

    try:
        # Load RSS URLs
        urls = load_rss_urls()
        if not urls:
            logger.error("PRNewswire: No RSS URLs found")
            if not save_to_csv:
                try:
                    get_save_log()("PRNewswire: No RSS URLs found", "Error")
                except:
                    pass
            return

        # Parse all feeds and combine
        all_dataframes = []
        for url in urls:
            try:
                df = parse_rss_feed(url, max_items=max_items, use_db_logging=not save_to_csv)
                if not df.empty:
                    all_dataframes.append(df)
            except Exception as e:
                logger.error(f"PRNewswire: Error processing feed {url}: {e}")
                if not save_to_csv:
                    try:
                        get_save_log()(f"PRNewswire: Error processing feed {url}: {e}", "Error")
                    except:
                        pass
                continue

        # Initialize variables for tracking duplicates
        initial_combined_count = 0
        in_process_duplicates_removed = 0

        # Combine all dataframes
        if all_dataframes:
            df = pd.concat(all_dataframes, ignore_index=True)
            initial_combined_count = len(df)
            logger.info(f"PRNewswire: Got combined dataframe with {initial_combined_count} rows from {len(all_dataframes)} feed(s)")

            # STEP 1: Remove duplicates within the combined dataframe (same link = duplicate)
            # This removes duplicates that appear in multiple RSS feeds
            logger.info(f"PRNewswire: [STEP 1] Removing in-process duplicates (same link in multiple feeds)...")
            df = df.drop_duplicates(subset=['link'], keep='first')
            in_process_duplicates_removed = initial_combined_count - len(df)
            if in_process_duplicates_removed > 0:
                logger.info(f"PRNewswire: âœ… Removed {in_process_duplicates_removed} in-process duplicate(s) (same link in multiple feeds)")
                if not save_to_csv:
                    try:
                        get_save_log()(f"PRNewswire: Removed {in_process_duplicates_removed} in-process duplicate entries", "Info")
                    except:
                        pass
            else:
                logger.info(f"PRNewswire: âœ… No in-process duplicates found")

            logger.info(f"PRNewswire: After in-process deduplication: {len(df)} unique rows remain")
            if not save_to_csv:
                try:
                    get_save_log()(f"PRNewswire: After in-process deduplication: {len(df)} unique rows", "Info")
                except:
                    pass
        else:
            logger.warning("PRNewswire: No data collected from any feed")
            if not save_to_csv:
                try:
                    get_save_log()("PRNewswire: No data collected from any feed", "Warning")
                except:
                    pass
            df = pd.DataFrame()

        if not df.empty:
            if save_to_csv:
                # Save to CSV
                if csv_output_path is None:
                    csv_output_path = os.path.join('data', 'prnewswire_output.csv')

                # Ensure directory exists
                os.makedirs(os.path.dirname(csv_output_path), exist_ok=True)

                # Save to CSV
                df.to_csv(csv_output_path, index=False, encoding='utf-8')
                logger.info(f"PRNewswire: Saved {len(df)} items to CSV: {csv_output_path}")
                print(f"\n[SUCCESS] PRNewswire: Successfully saved {len(df)} items to CSV")
                print(f"File location: {csv_output_path}")
                print(f"\nSample data (first 3 rows):")
                print(df.head(3).to_string())
            else:
                # Save to database
                try:
                    logger.info(f"PRNewswire: [STEP 2] Checking for duplicates in database (link + publisher)...")
                    process_download = get_process_download()
                    items_before_db_check = len(df)
                    added_count = process_download(df, 'prnewswire', CHECK_UNIQUENESS)
                    db_duplicates_removed = items_before_db_check - added_count

                    if added_count > 0:
                        logger.info(f"PRNewswire: âœ… Successfully added {added_count} new items to database")
                        if db_duplicates_removed > 0:
                            logger.info(f"PRNewswire: âœ… Skipped {db_duplicates_removed} duplicate(s) already in database")
                        get_save_log()(f"PRNewswire: Added {added_count} new items, skipped {db_duplicates_removed} duplicates", "Info")
                    else:
                        logger.info(f"PRNewswire: âš ï¸  No new items to add (all {items_before_db_check} items already exist in database)")
                        get_save_log()(f"PRNewswire: No new items (all {items_before_db_check} already in database)", "Info")

                    # Summary
                    total_duplicates = in_process_duplicates_removed + db_duplicates_removed
                    logger.info(f"PRNewswire: ðŸ“Š SUMMARY - Initial: {initial_combined_count}, In-process duplicates: {in_process_duplicates_removed}, DB duplicates: {db_duplicates_removed}, Added: {added_count}, Total duplicates removed: {total_duplicates}")
                except Exception as db_error:
                    logger.error(f"PRNewswire: Database error: {db_error}")
                    raise
        else:
            logger.info("PRNewswire: No news items to process")
            if not save_to_csv:
                try:
                    get_save_log()("PRNewswire: No news items to process", "Info")
                except:
                    pass

        if not save_to_csv:
            try:
                get_save_log()("PRNewswire task completed successfully", "Info")
            except:
                pass
    except Exception as e:
        error_msg = f"PRNewswire: An error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        if not save_to_csv:
            try:
                get_save_log()(error_msg, "Error")
            except:
                pass
        raise
    finally:
        if not save_to_csv:
            try:
                get_save_log()("PRNewswire task finished", "Info")
            except:
                pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch news from PRNewswire RSS feeds.")
    parser.add_argument('--csv', action='store_true', help='Save to CSV file instead of database')
    parser.add_argument('--output', type=str, default=None, help='CSV output file path (only used with --csv)')
    parser.add_argument('--max-items', type=int, default=None, help='Limit number of items to process (useful for testing)')
    args = parser.parse_args()
    main(save_to_csv=args.csv, csv_output_path=args.output, max_items=args.max_items)
