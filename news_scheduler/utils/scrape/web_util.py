import requests
from bs4 import BeautifulSoup
from requests.exceptions import RequestException
import logging
from typing import Optional
import contextlib
import re

logger = logging.getLogger(__name__)

def _extract_text_from_html(html: str, max_len: int = 1000) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    paragraphs = soup.find_all('p')
    if not paragraphs:
        text = soup.get_text(separator=' ', strip=True)
    else:
        text = ' '.join(p.get_text(separator=' ', strip=True) for p in paragraphs)
    return text[:max_len]

def _extract_article_content_improved(html: str, url: str = "") -> str:
    """
    Improved content extraction that targets article content specifically
    Used for euronext and prnewswire to get better content quality
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Remove scripts, styles, nav, header, footer
    for element in soup(['script', 'style', 'noscript', 'nav', 'header', 'footer', 'aside']):
        element.decompose()

    # Try to find article-specific containers
    article_selectors = [
        'article',
        '[role="article"]',
        '.article-content',
        '.article-body',
        '.news-content',
        '.content-body',
        '.post-content',
        'main article',
        '.main-content',
        '#content',
        '.entry-content'
    ]

    article_content = None
    for selector in article_selectors:
        article = soup.select_one(selector)
        if article:
            article_content = article
            logger.debug(f"Found article content using selector: {selector}")
            break

    # If no article tag found, try to find the main content area
    if not article_content:
        # Look for divs with common content class names
        content_divs = soup.find_all('div', class_=lambda x: x and any(
            keyword in str(x).lower() for keyword in ['content', 'article', 'body', 'main', 'text', 'post']
        ))

        if content_divs:
            # Get the largest content div (likely the main article)
            article_content = max(content_divs, key=lambda x: len(x.get_text()))
            logger.debug("Found article content using div class matching")

    # Extract text from article content
    if article_content:
        # Get all paragraphs
        paragraphs = article_content.find_all('p')
        if paragraphs:
            text = ' '.join(p.get_text(separator=' ', strip=True) for p in paragraphs)
        else:
            text = article_content.get_text(separator=' ', strip=True)
    else:
        # Fallback: get all paragraphs from body
        paragraphs = soup.find_all('p')
        if paragraphs:
            # Filter out very short paragraphs (likely navigation/menu items)
            paragraphs = [p for p in paragraphs if len(p.get_text(strip=True)) > 50]
            text = ' '.join(p.get_text(separator=' ', strip=True) for p in paragraphs)
        else:
            text = soup.get_text(separator=' ', strip=True)

    # Clean up the text
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # Skip very short lines and common navigation text
        if len(line) > 30 and not any(skip in line.lower() for skip in [
            'cookie', 'privacy', 'terms', 'subscribe', 'newsletter',
            'follow us', 'share this', 'related articles', 'searching for your content',
            'in-language news', 'contact us', '888-776-0942'
        ]):
            cleaned_lines.append(line)

    text = ' '.join(cleaned_lines)

    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def _fetch_with_playwright(url: str, timeout: int = 10) -> Optional[str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent="Mozilla/5.0 (compatible; finespresso-bot/1.0)")
            page.set_default_navigation_timeout(timeout * 1000)
            page.goto(url, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
            return _extract_text_from_html(html)
    except Exception as e:
        logger.debug(f"Playwright fetch failed for {url}: {e}")
        return None


def _fetch_with_selenium(url: str, timeout: int = 10) -> Optional[str]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager
    except Exception:
        return None

    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--user-agent=Mozilla/5.0 (compatible; finespresso-bot/1.0)")
        driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        html = driver.page_source
        with contextlib.suppress(Exception):
            driver.quit()
        return _extract_text_from_html(html)
    except Exception as e:
        logger.debug(f"Selenium fetch failed for {url}: {e}")
        return None


def fetch_url_content(url, timeout=10, use_improved_extraction=False):
    """
    Fetch content from URL with optional improved extraction for better article content

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds
        use_improved_extraction: If True, uses improved article extraction (for euronext, prnewswire)
    """
    try:
        logger.debug(f"Attempting to fetch content from URL: {url}")

        # Use better headers for improved extraction
        if use_improved_extraction:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
        else:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; finespresso-bot/1.0)"}

        response = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
        logger.debug(f"Response status code: {response.status_code}")
        response.raise_for_status()
        logger.debug(f"Response content length: {len(response.content)} bytes")

        html = response.content.decode('utf-8', errors='ignore')

        # Use improved extraction if requested
        if use_improved_extraction:
            return _extract_article_content_improved(html, url)
        else:
            return _extract_text_from_html(html)

    except RequestException as e:
        logger.error(f"Failed to fetch content from {url}: {str(e)}")
        # Attempt browser-based fallbacks for common block codes
        if any(code in str(e) for code in ["403", "406", "429"]):
            # Try Playwright first
            with contextlib.suppress(Exception):
                text = _fetch_with_playwright(url, timeout)
                if text:
                    return text
            # Then Selenium
            with contextlib.suppress(Exception):
                text = _fetch_with_selenium(url, timeout)
                if text:
                    return text
        return f"Failed to fetch content: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error while fetching {url}: {str(e)}")
        return "Failed to parse content"
