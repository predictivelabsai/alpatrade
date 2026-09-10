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
import re
import sys
import os

# Add playground directory to path for yf_util imports (like colleague's setup)
playground_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'playground')
if playground_dir not in sys.path:
    sys.path.insert(0, playground_dir)

from yf_util import get_company_by_ticker
from utils.scrape.web_util import fetch_url_content

logger = get_logger(__name__)

TIMEZONE = "Europe/Stockholm"
CHECK_UNIQUENESS = True

def load_config():
    config_file = "config/gnw_countries.json"
    try:
        with open(config_file, 'r') as file:
            return json.load(file)
    except Exception as e:
        error_msg = f"Error loading {config_file}: {e}"
        logger.error(error_msg)
        save_log("GlobeNewswire Countries: {error_msg}", "Error")
        return None

def clean_text(raw_html):
    return BeautifulSoup(raw_html, "lxml").text

def extract_ticker(categories, ticker_suffix):
    for category in categories:
        if category.get('scheme') == 'https://www.globenewswire.com/rss/stock':
            # Extract ticker from format like "Stockholm:POLY"
            match = re.search(r':\s*(\w+)$', category.get('term', ''))
            if match:
                ticker = match.group(1)
                return f"{ticker}.{ticker_suffix}"
    return None

def fetch_news(countries_config):
    all_news_items = []
    current_time = datetime.now(pytz.utc)
    logger.info(f"Starting news fetch for countries at {current_time}")
    save_log("GlobeNewswire Countries: Starting news fetch", "Info")

    for country_code, country_info in countries_config.items():
        rss_url = country_info['rss_url']
        ticker_suffix = country_info['ticker_suffix']

        logger.info(f"Fetching news for country: {country_code}")
        feed = feedparser.parse(rss_url)

        for newsitem in feed['items']:
            ticker = None
            if 'tags' in newsitem:
                ticker = extract_ticker(newsitem['tags'], ticker_suffix)

            # Skip items without a valid ticker
            if not ticker:
                continue

            # Look up company information using ticker
            company_info = get_company_by_ticker(ticker)
            company_name = ''
            if company_info:
                company_name = company_info.get('name', '')
                logger.info(f"Found company: {company_name} for ticker: {ticker}")
            else:
                logger.warning(f"Could not find company information for ticker: {ticker}")

            last_subject = newsitem['tags'][-1]['term'] if 'tags' in newsitem and newsitem['tags'] else None

            try:
                published_date_gmt = date_parser.parse(newsitem['published'])
                adjusted_date = adjust_date_to_est(published_date_gmt)
            except ValueError:
                logger.warning(f"Unable to parse date '{newsitem['published']}' for country {country_code}. Skipping this news item.")
                save_log(f"GlobeNewswire Countries: Unable to parse date '{newsitem['published']}' for country {country_code}", "Warning")
                continue

            # Extract language from dc:language field
            language = newsitem.get('dc_language', '')

            # Fetch content from URL instead of using description
            content = ''
            if newsitem['link']:
                try:
                    logger.debug(f"Attempting to fetch content from URL: {newsitem['link']}")
                    content = fetch_url_content(newsitem['link'])

                    if content.startswith("Failed to"):
                        logger.warning(f"Content fetch failed for {newsitem['link']}: {content}")
                    else:
                        logger.debug(f"Successfully fetched content from {newsitem['link']}")
                except Exception as e:
                    error_msg = f"Error fetching content from {newsitem['link']}: {e}"
                    logger.error(error_msg)
                    save_log(error_msg, "Error")
                    content = clean_text(newsitem['description'])  # Fallback to description if fetch fails

            all_news_items.append({
                'ticker': ticker,
                'title': newsitem['title'],
                'publisher_summary': clean_text(newsitem['summary']),
                'published_date_gmt': published_date_gmt,
                'published_date': adjusted_date,
                'content': content,  # Now using fetched content instead of description
                'link': newsitem['link'],
                'company': company_name,
                'reason': '',
                'industry': f'country_{country_code}',
                'publisher_topic': last_subject,
                'event': '',
                'publisher': f'globenewswire_country_{country_code}',
                'downloaded_at': datetime.now(pytz.utc),
                'status': 'raw',
                'instrument_id': None,
                'yf_ticker': ticker,
                'timezone': TIMEZONE,
                'ticker_url': '',
                'language': language,
            })

    return pd.DataFrame(all_news_items)

def main(country=None):
    save_log("GlobeNewswire Countries task started", "Info")
    try:
        countries_config = load_config()
        if countries_config is None:
            logger.error("Failed to load countries config")
            save_log("GlobeNewswire Countries: Failed to load config", "Error")
            return

        if country:
            if country not in countries_config:
                logger.error(f"Country {country} not found in config")
                save_log(f"GlobeNewswire Countries: Country {country} not found in config", "Error")
                return
            countries_config = {country: countries_config[country]}

        df = fetch_news(countries_config)
        logger.info(f"Got GlobeNewswire Countries dataframe with {len(df)} rows")
        save_log(f"GlobeNewswire Countries: Got dataframe with {len(df)} rows", "Info")

        for country_code in countries_config.keys():
            country_df = df[df['publisher'] == f'globenewswire_country_{country_code}']
            if len(country_df) > 0:
                added_count = process_download(country_df, f'globenewswire_country_{country_code}', CHECK_UNIQUENESS)
                if added_count > 0:
                    logger.info(f"GlobeNewswire {country_code}: Enriched {added_count} items.")
                    save_log(f"GlobeNewswire {country_code}: Enriched {added_count} items", "Info")
                else:
                    save_log(f"GlobeNewswire {country_code}: No new items to enrich.", "Info")

        save_log("GlobeNewswire Countries task completed successfully", "Info")
    except Exception as e:
        error_msg = f"GlobeNewswire Countries: An error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        save_log(error_msg, "Error")
    finally:
        save_log("GlobeNewswire Countries task finished", "Info")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch news for countries from GlobeNewswire.")
    parser.add_argument("-c", "--country", help="Two-letter country code (e.g., 'se' for Sweden)")
    args = parser.parse_args()

    main(args.country)
