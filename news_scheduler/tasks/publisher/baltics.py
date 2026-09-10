import feedparser
import pandas as pd
from datetime import datetime
import pytz
from utils.download_util import process_download
from utils.logging.log_util import get_logger
from utils.static.tag_util import tags
from utils.db.logs_db import save_log
from utils.scrape.web_util import fetch_url_content

logger = get_logger(__name__)

TIMEZONE = "EET"
CHECK_UNIQUENESS = True
RSS_URL = 'https://nasdaqbaltic.com/statistics/en/news?rss=1&num=100'

def parse_date(date_string):
    logger.debug(f"Parsing date: {date_string}")
    save_log(f"Baltics: Parsing date: {date_string}", "Debug")
    try:
        return datetime.strptime(date_string, '%a, %d %b %Y %H:%M:%S %z')
    except ValueError as e:
        error_msg = f"Baltics: Error parsing date: {e}"
        logger.error(error_msg)
        save_log(error_msg, "Error")
        return None

def parse_rss_feed(url, tags):
    logger.info(f"Parsing RSS feed from: {url}")
    save_log(f"Baltics: Parsing RSS feed from: {url}", "Info")

    try:
        feed = feedparser.parse(url)
        if hasattr(feed, 'bozo_exception'):
            error_msg = f"Baltics: Warning - Feed parsing had issues: {feed.bozo_exception}"
            logger.warning(error_msg)
            save_log(error_msg, "Warning")

        if not feed.entries:
            error_msg = "Baltics: No entries found in feed"
            logger.error(error_msg)
            save_log(error_msg, "Error")
            return pd.DataFrame()

    except Exception as e:
        error_msg = f"Baltics: Error parsing RSS feed: {e}"
        logger.error(error_msg)
        save_log(error_msg, "Error")
        return pd.DataFrame()

    items = feed.entries[:100]  # Limit to 100 news items
    logger.info(f"Found {len(items)} items in the feed")
    save_log(f"Baltics: Found {len(items)} items in the feed", "Info")

    data = []

    for index, item in enumerate(items, 1):
        try:
            logger.debug(f"Processing item {index}/{len(items)}: {item.title}")
            if index % 10 == 0:
                save_log(f"Baltics: Processing item {index}/{len(items)}", "Debug")

            # Safely get item attributes with defaults
            title = getattr(item, 'title', 'No Title')
            link = getattr(item, 'link', '')
            pub_date = parse_date(getattr(item, 'published', ''))
            company = item.get('issuer', 'N/A')

            logger.debug(f"Company name for item {index}: '{company}'")

            # Convert published_date to GMT
            if pub_date:
                try:
                    gmt_dt = pub_date.astimezone(pytz.UTC)
                    pub_date_str = pub_date.strftime("%Y-%m-%d %H:%M:%S")
                    pub_date_gmt_str = gmt_dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    logger.error(f"Error converting date for item {index}: {e}")
                    pub_date_str = pub_date_gmt_str = None
            else:
                pub_date_str = pub_date_gmt_str = None

            # Extract language if available
            language = item.get('dc_language', '')

            # Fetch content from the URL - only if we have a valid link
            content = ''
            if link:
                try:
                    logger.debug(f"Attempting to fetch content for item {index} from URL: {link}")
                    content = fetch_url_content(link)

                    if content.startswith("Failed to"):
                        logger.warning(f"Content fetch failed for item {index}: {content}")
                    else:
                        logger.debug(f"Successfully fetched content for item {index}")
                        logger.debug(f"Content preview: {content[:200]}...")
                        logger.debug(f"Content length: {len(content)} characters")

                except Exception as e:
                    error_msg = f"Error fetching content for item {index}: {e}"
                    logger.error(error_msg)
                    save_log(error_msg, "Error")

            data.append({
                'title': title,
                'link': link,
                'company': company,
                'published_date': pub_date_str,
                'published_date_gmt': pub_date_gmt_str,
                'publisher': 'baltics',
                'industry': '',
                'content': content,
                'ticker': '',
                'reason': '',
                'publisher_topic': '',
                'status': 'raw',
                'timezone': TIMEZONE,
                'publisher_summary': '',
                'ticker_url': '',
                'event': '',
                'language': language,
            })

        except Exception as e:
            error_msg = f"Error processing item {index}: {e}"
            logger.error(error_msg)
            save_log(error_msg, "Error")
            continue

    df = pd.DataFrame(data)
    logger.info(f"Created dataframe with {len(df)} rows")
    save_log(f"Baltics: Created dataframe with {len(df)} rows", "Info")
    return df

def main():
    save_log("Baltics task started", "Info")
    try:
        df = parse_rss_feed(RSS_URL, tags)
        logger.info(f"Got Baltics dataframe with {len(df)} rows")
        save_log(f"Baltics: Got dataframe with {len(df)} rows", "Info")

        added_count = process_download(df, 'baltics', CHECK_UNIQUENESS)

        # Call process_publisher after adding news items
        if added_count > 0:
            logger.info(f"Baltics: Enriched {added_count} items.")
            save_log(f"Baltics: Enriched {added_count} items.", "Info")
        else:
            save_log("Baltics: No new items to enrich.", "Info")

        save_log("Baltics task completed successfully", "Info")
    except Exception as e:
        error_msg = f"Baltics: An error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        save_log(error_msg, "Error")
    finally:
        save_log("Baltics task finished", "Info")

if __name__ == "__main__":
    main()
