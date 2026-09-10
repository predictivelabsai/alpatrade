import asyncio
import aiohttp
from bs4 import BeautifulSoup
import pandas as pd
from utils.logging.log_util import get_logger
from datetime import datetime, timedelta
import pytz
from utils.instrument_util import get_ticker
from utils.download_util import process_download
from utils.db.logs_db import save_log
from utils.scrape.web_util import fetch_url_content

logger = get_logger(__name__)

URL_PREFIX = 'https://live.euronext.com'
DEFAULT_URL = "https://live.euronext.com/en/products/equities/company-news"
CHECK_UNIQUENESS = True

# Timezone mapping
TIMEZONE_MAPPING = {
    'CEST': 'Europe/Paris',
    'CET': 'Europe/Paris',
    'BST': 'Europe/London',
    'GMT': 'GMT',
}

async def fetch_html(session, url):
    logger.debug(f"Fetching HTML from: {url}")
    save_log(f"Euronext: Fetching HTML from: {url}", "Debug")
    async with session.get(url) as response:
        return await response.text()

async def scrape_euronext_news():
    async with aiohttp.ClientSession() as session:
        logger.info(f"Fetching {DEFAULT_URL}")
        save_log(f"Euronext: Fetching {DEFAULT_URL}", "Info")
        html = await fetch_html(session, DEFAULT_URL)

        logger.info("Parsing HTML")
        save_log("Euronext: Parsing HTML", "Info")
        soup = BeautifulSoup(html, 'html.parser')

        logger.info("Extracting news data")
        save_log("Euronext: Extracting news data", "Info")
        news_data = []
        table = soup.find('table', class_='table')
        if table:
            rows = table.find('tbody').find_all('tr')
            for index, row in enumerate(rows, 1):
                columns = row.find_all('td')
                if len(columns) >= 5:
                    date = columns[0].text.strip()
                    company = columns[1].text.strip()
                    title_link = columns[2].find('a')
                    title = title_link.text.strip() if title_link else "N/A"
                    link = URL_PREFIX + title_link['href'] if title_link else "N/A"
                    industry = columns[3].text.strip()
                    topic = columns[4].text.strip()

                    logger.debug(f"Processing item {index}: {title}")
                    if index % 10 == 0:
                        save_log(f"Euronext: Processing item {index}", "Debug")

                    # Extract timezone and convert published_date to GMT
                    try:
                        date_parts = date.split('\n')
                        if len(date_parts) == 2:
                            date_str, time_str = date_parts
                            time_parts = time_str.split()
                            if len(time_parts) == 2:
                                time, extracted_timezone = time_parts
                                date_str = f"{date_str} {time}"
                                local_dt = datetime.strptime(date_str, "%d %b %Y %H:%M")
                                timezone = TIMEZONE_MAPPING.get(extracted_timezone, 'UTC')
                            else:
                                raise ValueError("Unexpected time format")
                        else:
                            raise ValueError("Unexpected date format")
                    except ValueError as e:
                        error_msg = f"Euronext: Unable to parse date: {date}. Error: {str(e)}"
                        logger.error(error_msg)
                        save_log(error_msg, "Error")
                        continue

                    local_tz = pytz.timezone(timezone)
                    local_dt = local_tz.localize(local_dt)
                    gmt_dt = local_dt.astimezone(pytz.UTC)

                    # Adjust GMT date if it's a future date
                    current_time = datetime.now(pytz.UTC)
                    if gmt_dt > current_time:
                        gmt_dt -= timedelta(days=1)

                    # Fetch content from URL if available (using improved extraction)
                    content = ''
                    if link and link != "N/A":
                        try:
                            logger.debug(f"Attempting to fetch content for item {index} from URL: {link}")
                            content = fetch_url_content(link, timeout=15, use_improved_extraction=True)

                            if content.startswith("Failed to"):
                                logger.warning(f"Content fetch failed for item {index}: {content}")
                            else:
                                logger.debug(f"Successfully fetched content for item {index}")
                                logger.debug(f"Content preview: {content[:200]}...")
                                logger.debug(f"Content length: {len(content)} characters")

                        except Exception as e:
                            error_msg = f"Euronext: Error fetching content for item {index}: {e}"
                            logger.error(error_msg)
                            save_log(error_msg, "Error")

                    news_data.append({
                        'published_date': local_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        'published_date_gmt': gmt_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        'company': company,
                        'title': title,
                        'link': link,
                        'industry': industry,
                        'publisher_topic': topic,
                        'publisher': 'euronext',
                        'content': content,
                        'ticker': '',
                        'reason': '',
                        'status': 'raw',
                        'timezone': timezone,
                        'publisher_summary': '',
                    })
        else:
            logger.warning("No table found in the HTML")
            save_log("Euronext: No table found in the HTML", "Warning")

        df = pd.DataFrame(news_data)
        logger.info(f"Scraped {len(df)} news items")
        save_log(f"Euronext: Scraped {len(df)} news items", "Info")
        return df

async def main():
    save_log("Euronext task started", "Info")
    try:
        df = await scrape_euronext_news()
        logger.info(f"Got Euronext dataframe with {len(df)} rows")
        save_log(f"Euronext: Got dataframe with {len(df)} rows", "Info")

        added_count = process_download(df, 'euronext', CHECK_UNIQUENESS)

        if added_count > 0:
            logger.info(f"Euronext: Enriched {added_count} items")
            save_log(f"Euronext: Enriched {added_count} items", "Info")
        else:
            logger.info("Euronext: No new items to enrich.")
            save_log("Euronext: No new items to enrich.", "Info")

        save_log("Euronext task completed successfully", "Info")
    except Exception as e:
        error_msg = f"Euronext: An error occurred: {str(e)}"
        logger.error(error_msg, exc_info=True)
        save_log(error_msg, "Error")
    finally:
        save_log("Euronext task finished", "Info")

if __name__ == "__main__":
    asyncio.run(main())
