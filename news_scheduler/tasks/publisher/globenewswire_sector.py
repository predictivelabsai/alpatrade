import feedparser
import json
from bs4 import BeautifulSoup
from datetime import datetime
import pandas as pd
import pytz
from utils.download_util import process_download
from utils.logging.log_util import get_logger
from utils.date.date_util import adjust_date_to_est
from dateutil import parser as date_parser
from utils.db.logs_db import save_log
import argparse
logger = get_logger(__name__)

TIMEZONE = "US/Eastern"
CHECK_UNIQUENESS = True

def load_config(sector):
    config_file = f"data/{sector}.json"
    try:
        with open(config_file, 'r') as file:
            return json.load(file)
    except Exception as e:
        error_msg = f"Error loading {config_file}: {e}"
        logger.error(error_msg)
        save_log(f"GlobeNewswire {sector}: {error_msg}", "Error")
        return None

def clean_text(raw_html):
    return BeautifulSoup(raw_html, "lxml").text

def fetch_news(rss_dict, sector):
    all_news_items = []

    current_time = datetime.now(pytz.utc)
    logger.info(f"Starting news fetch for {sector} at {current_time}")
    save_log(f"GlobeNewswire {sector}: Starting news fetch at {current_time}", "Info")

    for index, (ticker, company_info) in enumerate(rss_dict.items(), 1):
        if 'url' not in company_info:
            logger.warning(f"Skipping ticker {ticker}: No RSS URL found")
            save_log(f"GlobeNewswire {sector}: Skipping ticker {ticker}: No RSS URL found", "Warning")
            continue

        rss_url = company_info['url']
        company_name = company_info['company']

        logger.info(f"Fetching news for ticker: {ticker} ({company_name})")
        feed = feedparser.parse(rss_url)

        for newsitem in feed['items']:
            last_subject = newsitem['tags'][-1]['term'] if 'tags' in newsitem and newsitem['tags'] else None
            try:
                published_date_gmt = date_parser.parse(newsitem['published'])
                adjusted_date = adjust_date_to_est(published_date_gmt)
            except ValueError:
                logger.warning(f"Unable to parse date '{newsitem['published']}' for ticker {ticker}. Skipping this news item.")
                save_log(f"GlobeNewswire {sector}: Unable to parse date '{newsitem['published']}' for ticker {ticker}. Skipping this news item.", "Warning")
                continue

            # Extract language from dc:language field if available
            language = newsitem.get('dc_language', '')

            all_news_items.append({
                'ticker': ticker,
                'title': newsitem['title'],
                'publisher_summary': clean_text(newsitem['summary']),
                'published_date_gmt': published_date_gmt,
                'published_date': adjusted_date,
                'content': clean_text(newsitem['description']),
                'link': newsitem['link'],
                'company': company_name,
                'reason': '',
                'industry': sector,
                'publisher_topic': last_subject,
                'event': '',
                'publisher': f'globenewswire_{sector}',
                'downloaded_at': datetime.now(pytz.utc),
                'status': 'raw',
                'instrument_id': None,
                'yf_ticker': ticker,
                'timezone': 'US/Eastern',
                'ticker_url': '',
                'language': language,
            })

        if index % 10 == 0:
            save_log(f"GlobeNewswire {sector}: Processed {index} tickers", "Debug")

    return pd.DataFrame(all_news_items)

def main(sector):
    save_log(f"GlobeNewswire {sector} task started", "Info")
    try:
        rss_dict = load_config(sector)
        if rss_dict is None:
            logger.error(f"Failed to load config for sector: {sector}")
            save_log(f"GlobeNewswire {sector}: Failed to load config", "Error")
            return

        df = fetch_news(rss_dict, sector)
        logger.info(f"Got GlobeNewswire {sector} dataframe with {len(df)} rows")
        save_log(f"GlobeNewswire {sector}: Got dataframe with {len(df)} rows", "Info")

        added_count = process_download(df, f'globenewswire_{sector}', CHECK_UNIQUENESS)

        if added_count > 0:
            logger.info(f"GlobeNewswire {sector}: Enriched {added_count} items.")
            save_log(f"GlobeNewswire {sector}: Enriched {added_count} items", "Info")
        else:
            save_log(f"GlobeNewswire {sector}: No new items to enrich.", "Info")

        save_log(f"GlobeNewswire {sector} task completed successfully", "Info")
    except Exception as e:
        error_msg = f"GlobeNewswire {sector}: An error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        save_log(error_msg, "Error")
    finally:
        save_log(f"GlobeNewswire {sector} task finished", "Info")

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Fetch news for a specific sector.")
    parser.add_argument("-s", "--sector", default="biotech", help="Name of the sector. Default is 'biotech'")
    args = parser.parse_args()

    main(args.sector)
