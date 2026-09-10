#!/usr/bin/env python3
"""
GlobeNewswire Industry News Fetcher
Fetches and processes news from GlobeNewswire industry RSS feeds.
"""

import sys
import os

# Add the project root to Python path for direct execution
if __name__ == "__main__":
    # Get the directory containing this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Get the project root (parent of tasks directory)
    project_root = os.path.dirname(script_dir)
    # Add project root to Python path
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

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
from utils.ai.xai_util import extract_ticker, extract_issuer, detect_language, translate_to_english
import argparse
import time
import re

logger = get_logger(__name__)

TIMEZONE = "US/Eastern"
CHECK_UNIQUENESS = True

def fetch_news_for_industry(industry_name, rss_url):
    """Fetch news for a specific industry from its RSS feed."""
    all_news_items = []

    current_time = datetime.now(pytz.utc)
    logger.info(f"Starting news fetch for {industry_name} at {current_time}")
    save_log(f"GlobeNewswire {industry_name}: Starting news fetch at {current_time}", "Info")

    try:
        feed = feedparser.parse(rss_url)

        if not feed.entries:
            logger.warning(f"No entries found in RSS feed for {industry_name}")
            save_log(f"GlobeNewswire {industry_name}: No entries found in RSS feed", "Warning")
            return pd.DataFrame()

        for index, newsitem in enumerate(feed.entries, 1):
            try:
                # Extract basic information
                title = newsitem.get('title', '')
                content = clean_text(newsitem.get('description', ''))
                link = newsitem.get('link', '')

                # Parse publication date
                try:
                    published_date_gmt = date_parser.parse(newsitem.get('published', ''))
                    adjusted_date = adjust_date_to_est(published_date_gmt)
                except (ValueError, TypeError):
                    logger.warning(f"Unable to parse date for {industry_name} news item {index}. Skipping.")
                    continue

                # Extract language and translate if needed
                language = newsitem.get('dc_language', '')
                if not language:
                    language = detect_language(title)

                # Translate content to English if not already in English
                content_en = content
                title_en = title
                if language and language != 'en':
                    try:
                        content_en = translate_to_english(content, language)
                        title_en = translate_to_english(title, language)
                    except Exception as e:
                        logger.warning(f"Failed to translate content for {industry_name}: {e}")

                # Extract company name and ticker
                company_name = extract_company_from_title(title, content)
                ticker = extract_ticker_from_news(title, content, company_name)

                # Extract last subject from tags if available
                last_subject = None
                if hasattr(newsitem, 'tags') and newsitem.tags:
                    last_subject = newsitem.tags[-1].get('term', '')

                news_item = {
                    'title': title_en,
                    'publisher_summary': clean_text(content_en),
                    'published_date_gmt': published_date_gmt,
                    'published_date': adjusted_date,
                    'content': content_en,
                    'link': link,
                    'company': company_name,
                    'reason': '',
                    'industry': industry_name,
                    'publisher_topic': last_subject,
                    'event': '',
                    'publisher': f'globenewswire_{industry_name}',
                    'downloaded_at': datetime.now(pytz.utc),
                    'status': 'raw',
                    'instrument_id': None,
                    'yf_ticker': ticker,
                    'timezone': 'US/Eastern',
                    'ticker_url': '',
                    'language': language,
                }

                all_news_items.append(news_item)

            except Exception as e:
                logger.error(f"Error processing news item {index} for {industry_name}: {e}")
                continue

        logger.info(f"Successfully processed {len(all_news_items)} news items for {industry_name}")
        return pd.DataFrame(all_news_items)

    except Exception as e:
        logger.error(f"Error fetching news for {industry_name}: {e}")
        save_log(f"GlobeNewswire {industry_name}: Error fetching news: {e}", "Error")
        return pd.DataFrame()

def load_rss_urls():
    """Load all RSS URLs from the industry RSS URLs file."""
    config_file = "config/gnw_industry_rss_urls.txt"
    try:
        with open(config_file, 'r') as file:
            lines = file.readlines()

        rss_dict = {}
        for line in lines:
            line = line.strip()
            if line and ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    industry_name = parts[0].strip()
                    rss_url = parts[1].strip()
                    rss_dict[industry_name] = rss_url

        logger.info(f"Loaded {len(rss_dict)} RSS URLs from {config_file}")
        return rss_dict
    except Exception as e:
        error_msg = f"Error loading {config_file}: {e}"
        logger.error(error_msg)
        save_log(f"GlobeNewswire Industry: {error_msg}", "Error")
        return None

def clean_text(raw_html):
    """Clean HTML content and extract plain text."""
    return BeautifulSoup(raw_html, "lxml").text

def extract_company_from_title(title, content):
    """Extract company name from title and content."""
    try:
        # Combine title and content for better extraction
        combined_text = f"{title} {content}"
        return extract_issuer(combined_text)
    except Exception as e:
        logger.warning(f"Failed to extract company from title: {e}")
        return ""

def extract_ticker_from_news(title, content, company_name):
    """Extract ticker from news title and content."""
    try:
        # Combine title and content for better extraction
        combined_text = f"{title} {content}"
        return extract_ticker(combined_text)
    except Exception as e:
        logger.warning(f"Failed to extract ticker from news: {e}")
        return ""

def process_industry(industry_name, rss_url):
    """Process a single industry RSS feed."""
    logger.info(f"Processing industry: {industry_name}")
    logger.info(f"RSS URL: {rss_url}")

    try:
        # Fetch news for the industry
        df = fetch_news_for_industry(industry_name, rss_url)

        if df.empty:
            logger.warning(f"No news items found for industry: {industry_name}")
            return 0

        logger.info(f"Found {len(df)} news items for {industry_name}")

        # Process the download
        added_count = process_download(df, f'globenewswire_{industry_name}', CHECK_UNIQUENESS)

        logger.info(f"Completed processing {industry_name}. Added {added_count} items.")
        return added_count

    except Exception as e:
        logger.error(f"Error processing industry {industry_name}: {e}")
        return 0

def main(industry_filter=None, max_industries=None):
    """Main function to process GlobeNewswire industry news."""
    try:
        save_log("GlobeNewswire Industry task started", "Info")
        logger.info("Starting GlobeNewswire Industry news processing")

        # Load RSS URLs
        rss_dict = load_rss_urls()
        if not rss_dict:
            save_log("GlobeNewswire Industry: Failed to load RSS URLs", "Error")
            return

        # Filter industries if specified
        if industry_filter:
            filtered_dict = {k: v for k, v in rss_dict.items() if industry_filter.lower() in k.lower()}
            rss_dict = filtered_dict
            logger.info(f"Filtered to {len(rss_dict)} industries containing '{industry_filter}'")

        # Limit number of industries if specified
        if max_industries:
            items = list(rss_dict.items())[:max_industries]
            rss_dict = dict(items)
            logger.info(f"Limited to {len(rss_dict)} industries")

        total_processed = 0
        total_added = 0

        for index, (industry_name, rss_url) in enumerate(rss_dict.items(), 1):
            logger.info(f"Processing industry {index}/{len(rss_dict)}: {industry_name}")

            added_count = process_industry(industry_name, rss_url)
            total_processed += 1
            total_added += added_count

            # Add delay between industries to avoid overwhelming the system
            if index < len(rss_dict):
                time.sleep(2)

        logger.info(f"Completed processing {total_processed} industries. Total items added: {total_added}")
        save_log(f"GlobeNewswire Industry: Completed processing {total_processed} industries. Total items added: {total_added}", "Info")

    except Exception as e:
        error_msg = f"GlobeNewswire Industry: An error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        save_log(error_msg, "Error")
    finally:
        save_log("GlobeNewswire Industry task finished", "Info")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch news for GlobeNewswire industries.")
    parser.add_argument("-i", "--industry", help="Filter industries by name (partial match)")
    parser.add_argument("-m", "--max", type=int, help="Maximum number of industries to process")
    parser.add_argument("--test", action="store_true", help="Run in test mode (process only first 2 industries)")
    args = parser.parse_args()

    if args.test:
        main(max_industries=2)
    else:
        main(industry_filter=args.industry, max_industries=args.max)
