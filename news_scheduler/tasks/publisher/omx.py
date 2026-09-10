import requests
import pandas as pd
from datetime import datetime
import pytz
from utils.logging.log_util import get_logger
from utils.download_util import process_download
from utils.db.logs_db import save_log
from utils.scrape.web_util import fetch_url_content

# Initialize logger
logger = get_logger(__name__)

API_URL = "https://api.news.eu.nasdaq.com/news/query.action"
TIMEZONE = "UTC"  # API returns UTC timestamps
CHECK_UNIQUENESS = True

def fetch_nasdaq_news():
    """Fetch news from Nasdaq API"""
    logger.info("Fetching news from Nasdaq API")
    save_log("OMX: Fetching news from Nasdaq API", "Info")

    try:
        response = requests.get(API_URL)
        if response.status_code != 200:
            error_msg = f"OMX: API request failed with status {response.status_code}"
            logger.error(error_msg)
            save_log(error_msg, "Error")
            return pd.DataFrame()

        data = response.json()

    except Exception as e:
        error_msg = f"OMX: Error fetching data: {str(e)}"
        logger.error(error_msg)
        save_log(error_msg, "Error")
        return pd.DataFrame()

    news_items = []
    items = data.get('results', {}).get('item', [])

    if not items:
        error_msg = "OMX: No items found in API response"
        logger.error(error_msg)
        save_log(error_msg, "Error")
        return pd.DataFrame()

    logger.info(f"Processing {len(items)} news items")
    save_log(f"OMX: Processing {len(items)} news items", "Info")

    for index, item in enumerate(items, 1):
        try:
            # Log every 10th item to avoid flooding
            if index % 10 == 0:
                save_log(f"OMX: Processing item {index}/{len(items)}", "Debug")

            # Convert timestamp to datetime
            pub_date = datetime.strptime(item['published'], '%Y-%m-%d %H:%M:%S %z')
            pub_date_gmt = pub_date.astimezone(pytz.UTC)

            # Only process English news
            if 'en' not in item.get('languages', []):
                continue

            # Fetch content from URL if available
            content = ''
            message_url = item.get('messageUrl', '')

            if message_url and message_url.strip():  # Make sure URL is not empty or whitespace
                try:
                    logger.debug(f"Attempting to fetch content for item {index} from URL: {message_url}")
                    content = fetch_url_content(message_url)
                    #logger.info(f"Successfully fetched CONTENT: {content}")
                    if content.startswith("Failed to"):
                        logger.warning(f"Content fetch failed for item {index}: {content}")
                        save_log(f"OMX: Content fetch failed for item {index}: {content}", "Warning")
                    else:
                        logger.debug(f"Successfully fetched content for item {index}")
                        logger.debug(f"Content preview: {content[:200]}...")
                        logger.debug(f"Content length: {len(content)} characters")
                        save_log(f"OMX: Successfully fetched content for item {index}, length: {len(content)}", "Debug")

                except Exception as e:
                    error_msg = f"OMX: Error fetching content for item {index}: {e}"
                    logger.error(error_msg)
                    save_log(error_msg, "Error")
            else:
                logger.debug(f"No valid URL found for item {index}")
                save_log(f"OMX: No valid URL found for item {index}", "Debug")

            news_items.append({
                'published_date': pub_date.strftime("%Y-%m-%d %H:%M:%S"),
                'published_date_gmt': pub_date_gmt.strftime("%Y-%m-%d %H:%M:%S"),
                'company': item.get('company', ''),
                'title': item.get('headline', ''),
                'link': message_url,
                'publisher_topic': item.get('cnsCategory', ''),
                'content': content,
                'ticker': '',
                'reason': '',
                'industry': '',
                'publisher': 'omx',
                'status': 'raw',
                'timezone': TIMEZONE,
                'publisher_summary': '',
                'market': item.get('market', ''),
                'language': item.get('language', ''),
                'category_id': item.get('categoryId', ''),
            })

        except Exception as e:
            error_msg = f"OMX: Error processing item {index}: {str(e)}"
            logger.error(error_msg)
            save_log(error_msg, "Error")
            continue

    df = pd.DataFrame(news_items)
    logger.info(f"Created dataframe with {len(df)} rows")
    save_log(f"OMX: Created dataframe with {len(df)} rows", "Info")
    return df

def main():
    save_log("OMX task started", "Info")
    try:
        df = fetch_nasdaq_news()
        logger.info(f"Got OMX dataframe with {len(df)} rows")
        save_log(f"OMX: Got dataframe with {len(df)} rows", "Info")

        added_count = process_download(df, 'omx', CHECK_UNIQUENESS)
        if added_count > 0:
            logger.info(f"OMX: Enriched {added_count} items.")
            save_log(f"OMX: Enriched {added_count} items", "Info")
        else:
            logger.info("OMX: No new items to enrich.")
            save_log("OMX: No new items to enrich.", "Info")

        save_log("OMX task completed successfully", "Info")
    except Exception as e:
        error_msg = f"OMX: An error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        save_log(error_msg, "Error")
    finally:
        save_log("OMX task finished", "Info")

if __name__ == "__main__":
    main()
