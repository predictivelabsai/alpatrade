import yfinance as yf
from typing import Optional, List, Dict
import requests

def classify_market_cap(market_cap):
    if isinstance(market_cap, str):
        market_cap = float(market_cap.replace(',', ''))
        
    market_cap = float(market_cap)
    
    if market_cap >= 200_000_000_000:  # $200B
        return 'Mega Cap'
    elif market_cap >= 10_000_000_000:  # $10B
        return 'Large Cap'
    elif market_cap >= 2_000_000_000:   # $2B
        return 'Mid Cap'
    elif market_cap >= 300_000_000:     # $300M
        return 'Small Cap'
    elif market_cap >= 50_000_000:      # $50M
        return 'Micro Cap'
    else:
        return 'Nano Cap'

def format_market_cap(market_cap):
    if market_cap >= 1_000_000_000:
        return f"${market_cap/1_000_000_000:.2f}B"
    else:
        return f"${market_cap/1_000_000:.2f}M"

def lookup_ticker(company_name: str) -> Optional[List[Dict]]:
    try:
        # Yahoo Finance API endpoint for symbol lookup
        url = "https://query2.finance.yahoo.com/v1/finance/search"

        # Parameters for the API request
        params = {
            "q": company_name,
            "quotesCount": 5,   # Increased to get more results
            "newsCount": 0,     # Don't include news
            "enableFuzzyQuery": True,
            "quotesQueryId": "tss_match_phrase_query"
        }

        # Make the API request
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        # Parse the response
        data = response.json()

        # Check if any quotes were found
        if not data.get("quotes"):
            print(f"No ticker found for company: {company_name}")
            return None

        # Process all matches
        results = []
        for quote in data["quotes"]:
            result = {
                "symbol": quote.get("symbol"),
                "name": quote.get("longname") or quote.get("shortname"),  # Try longname first, fall back to shortname
                "exchange": quote.get("exchange"),
                "type": quote.get("quoteType", "").upper()
            }
            # Only add if we have both symbol and name
            if result["symbol"] and result["name"]:
                results.append(result)

        return results if results else None

    except Exception as e:
        print(f"Error looking up ticker for {company_name}: {str(e)}")
        return None

def get_stock_info(company_name: str) -> None:
    # First look up the ticker
    ticker_info = lookup_ticker(company_name)

    if not ticker_info:
        return

    try:
        # Get the stock information using yfinance
        ticker = yf.Ticker(ticker_info["symbol"])

        # Get basic info
        info = ticker.info
        shares_outstanding = info.get('sharesOutstanding', 0)
        float_shares = info.get('floatShares', 0)
        float_ratio = (float_shares / shares_outstanding * 100) if shares_outstanding else 0
        exchange_code = ticker_info['exchange']
        market_cap = info.get('marketCap', 'N/A')
        market_cap_class = classify_market_cap(market_cap)
        # Print relevant information

    except Exception as e:
        print(f"Error getting stock information: {str(e)}")

def get_company_by_ticker(ticker: str) -> Optional[Dict]:
    try:
        # Yahoo Finance API endpoint for symbol lookup
        url = "https://query2.finance.yahoo.com/v1/finance/search"
        
        # Parameters for the API request
        params = {
            "q": ticker,
            "quotesCount": 5,  # Get multiple results to find best match
            "newsCount": 0,
            "enableFuzzyQuery": False,
            "quotesQueryId": "tss_match_phrase_query"
        }

        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        data = response.json()
        quotes = data.get("quotes", [])
        
        if not quotes:
            return None

        # Sort by volume if available, otherwise take first match
        matches = []
        for quote in quotes:
            if quote.get("symbol") == ticker:
                try:
                    ticker_obj = yf.Ticker(quote.get("symbol"))
                    info = ticker_obj.info
                    volume = info.get('volume', 0)
                    matches.append({
                        "symbol": quote.get("symbol"),
                        "name": quote.get("shortname"),
                        "exchange": quote.get("exchange"),
                        "volume": volume
                    })
                except Exception:
                    continue

        if not matches:
            return None

        # Return the match with highest volume
        return max(matches, key=lambda x: x['volume'])

    except Exception as e:
        print(f"Error looking up company for ticker {ticker}: {str(e)}")
        return None

def search_instrument_info(company_name: str) -> Optional[Dict]:
    """
    Search for instrument information using company name.
    Returns instrument info dict with highest volume if found, None otherwise.
    """
    try:
        # First lookup the ticker
        ticker_info = lookup_ticker(company_name)
        if not ticker_info:
            return None
            
        # Get detailed info using yfinance
        ticker_obj = yf.Ticker(ticker_info['symbol'])
        info = ticker_obj.info
        
        if not info:
            return None
            
        return {
            'issuer': company_name,
            'ticker': ticker_info['symbol'],
            'yf_ticker': ticker_info['symbol'],
            'exchange': ticker_info['exchange'],
            'exchange_code': ticker_info['exchange'],
            'country': info.get('country'),
            'url': f"https://finance.yahoo.com/quote/{ticker_info['symbol']}",
            'isin': None,  # Add ISIN as None since it's not available from yfinance
            'asset_class': 'STOCK'  # Default to STOCK for new instruments
        }
    except Exception as e:
        print(f"Error searching instrument info for {company_name}: {str(e)}")
        return None

def search_tickers(company_name: str) -> Optional[List[Dict]]:
    try:
        # Yahoo Finance API endpoint for symbol lookup
        url = "https://query2.finance.yahoo.com/v1/finance/search"

        # Parameters for the API request
        params = {
            "q": company_name,
            "quotesCount": 5,
            "newsCount": 0,
            "enableFuzzyQuery": True,
            "quotesQueryId": "tss_match_phrase_query"
        }

        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        data = response.json()

        if not data.get("quotes"):
            print(f"No ticker found for company: {company_name}")
            return None

        results = []
        for quote in data["quotes"]:
            try:
                # Get additional info using yfinance
                ticker = yf.Ticker(quote.get("symbol"))
                info = ticker.info
                
                # Get volume information
                volume = info.get('volume', 0)
                avg_volume = info.get('averageVolume', 0)
                
                # Calculate float ratio
                shares_outstanding = info.get('sharesOutstanding', 0)
                float_shares = info.get('floatShares', 0)
                float_ratio = round(float_shares / shares_outstanding, 4) if shares_outstanding else 0
                
                # Get market cap and classify it
                market_cap = info.get('marketCap', 0)
                market_cap_class = classify_market_cap(market_cap) if market_cap else ''
                
                result = {
                    "symbol": quote.get("symbol"),
                    "name": quote.get("longname") or quote.get("shortname"),
                    "exchange": quote.get("exchange"),
                    "type": quote.get("quoteType", "").upper(),
                    "float_ratio": float_ratio,
                    "market_cap": market_cap,
                    "market_cap_class": market_cap_class,
                    "volume": volume,
                    "avg_volume": avg_volume
                }
                if result["symbol"] and result["name"]:
                    results.append(result)
            except Exception as e:
                print(f"Error getting additional info for {quote.get('symbol')}: {str(e)}")
                continue

        # Sort results by volume in descending order
        if results:
            results.sort(key=lambda x: x['volume'], reverse=True)

        return results if results else None

    except Exception as e:
        print(f"Error looking up ticker for {company_name}: {str(e)}")
        return None

def get_real_time_price(symbol: str):
    """
    Get the most recent price for a symbol using Yahoo Finance
    
    Args:
        symbol: Stock ticker symbol
        
    Returns:
        Current price (may be delayed up to 15 minutes) or None if error
    """
    try:
        ticker = yf.Ticker(symbol)
        # Get the most recent data
        hist = ticker.history(period='1d', interval='1m')
        
        if hist.empty:
            # Fallback to daily data if intraday not available
            hist = ticker.history(period='2d')
            if hist.empty:
                return None
        
        # Return the most recent close price
        return float(hist['Close'].iloc[-1])
        
    except Exception as e:
        print(f"Error getting real-time price for {symbol}: {str(e)}")
        return None


def get_historical_data(symbol: str, from_date=None, to_date=None):
    """
    Get historical price data for a symbol using Yahoo Finance
    
    Args:
        symbol: Stock ticker symbol
        from_date: Start date in YYYY-MM-DD format (optional)
        to_date: End date in YYYY-MM-DD format (optional)
        
    Returns:
        DataFrame with OHLCV data or empty DataFrame if error
    """
    import pandas as pd
    
    try:
        ticker = yf.Ticker(symbol)
        
        if from_date and to_date:
            hist = ticker.history(start=from_date, end=to_date)
        elif from_date:
            hist = ticker.history(start=from_date)
        else:
            # Default to last 30 days
            hist = ticker.history(period='30d')
        
        return hist
        
    except Exception as e:
        print(f"Error getting historical data for {symbol}: {str(e)}")
        import pandas as pd
        return pd.DataFrame()
