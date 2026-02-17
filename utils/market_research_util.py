"""
Market Research Utility — Bloomberg-style terminal commands.

Provides news, profile, financials, price, movers, analysts, and valuation
data using Polygon.io (via MASSIVE_API_KEY), yfinance, XAI Grok, and Tavily.
"""

import os
import logging
from datetime import datetime, timezone

import requests
import yfinance as yf
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class MarketResearch:
    """Bloomberg-style market research commands."""

    def __init__(self):
        self.api_key = os.getenv("MASSIVE_API_KEY")
        self.base_url = "https://api.polygon.io"
        self.xai_key = os.getenv("XAI_API_KEY")
        self.tavily_key = os.getenv("TAVILY_API_KEY")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_large(n) -> str:
        """Format large numbers: $1.57T, $435.6B, $56.1M."""
        if n is None:
            return "\u2014"
        n = float(n)
        if abs(n) >= 1e12:
            return f"${n / 1e12:,.2f}T"
        if abs(n) >= 1e9:
            return f"${n / 1e9:,.1f}B"
        if abs(n) >= 1e6:
            return f"${n / 1e6:,.1f}M"
        return f"${n:,.0f}"

    @staticmethod
    def _fmt_pct(n) -> str:
        """Format ratio as percentage: 0.27 → 27.0%."""
        if n is None:
            return "\u2014"
        return f"{float(n) * 100:.1f}%"

    @staticmethod
    def _safe(val, fmt="{}", mult=1):
        """Safely format a value, returning — for None/missing."""
        if val is None:
            return "\u2014"
        try:
            return fmt.format(float(val) * mult)
        except (ValueError, TypeError):
            return str(val)

    def _fmt_val(self, val, fmt) -> str:
        """Format a value based on type: 'ratio' (*100 → %), 'pct' (as-is %), 'large' ($B/T), 'num' (plain)."""
        if val is None:
            return "\u2014"
        if fmt == "large":
            return self._fmt_large(val)
        if fmt == "ratio":
            return self._fmt_pct(val)
        if fmt == "pct":
            # Already a percentage (e.g. yfinance dividendYield: 0.41 = 0.41%)
            return f"{float(val):.2f}%"
        return self._safe(val, "{:.2f}")

    def _polygon_get(self, path, params=None):
        """Make an authenticated GET to Polygon.io."""
        if not self.api_key:
            return None
        p = {"apiKey": self.api_key}
        if params:
            p.update(params)
        try:
            r = requests.get(f"{self.base_url}{path}", params=p, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"Polygon {path}: {e}")
            return None

    # ------------------------------------------------------------------
    # 1. news
    # ------------------------------------------------------------------

    def news(self, ticker=None, limit=10, provider=None) -> str:
        """Get news for a ticker (or general market news).

        Args:
            provider: Force a specific provider ("polygon", "xai", "tavily").
                      If None, tries XAI → Tavily → Polygon in order
                      (XAI/Tavily return fresher results than Polygon free tier).
        """
        if ticker:
            ticker = ticker.upper()

        # Map of provider → (fetch_fn, display_name)
        # XAI and Tavily first — Polygon free tier often returns stale news
        providers = [
            ("xai", self._news_xai, "XAI Grok"),
            ("tavily", self._news_tavily, "Tavily"),
            ("polygon", self._news_polygon, "Polygon"),
        ]

        # If a specific provider is requested, try only that one
        if provider:
            for key, fetch_fn, display in providers:
                if key == provider.lower():
                    articles = fetch_fn(ticker, limit)
                    if articles:
                        return self._format_news(ticker, articles, provider=display)
                    return f"# News{f': {ticker}' if ticker else ''}\n\nNo results from {display}."
            return f"# News\n\nUnknown provider: `{provider}`. Use `polygon`, `xai`, or `tavily`."

        # Default: try all in order
        for key, fetch_fn, display in providers:
            articles = fetch_fn(ticker, limit)
            if articles:
                return self._format_news(ticker, articles, provider=display)

        return f"# News{f': {ticker}' if ticker else ''}\n\nNo news found."

    def _news_polygon(self, ticker, limit):
        params = {"limit": limit, "order": "desc", "sort": "published_utc"}
        if ticker:
            params["ticker"] = ticker.upper()
        data = self._polygon_get("/v2/reference/news", params)
        if not data or not data.get("results"):
            return None
        articles = []
        for a in data["results"][:limit]:
            pub = a.get("published_utc", "")
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                time_str = dt.strftime("%b %d %I:%M %p")
            except Exception:
                time_str = pub[:16]
            articles.append({
                "time": time_str,
                "title": a.get("title", ""),
                "source": a.get("publisher", {}).get("name", ""),
                "url": a.get("article_url", ""),
            })
        return articles

    def _news_xai(self, ticker, limit):
        if not self.xai_key:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.xai_key, base_url="https://api.x.ai/v1")
            topic = f"{ticker} ({ticker} stock)" if ticker else "US stock market"
            today = datetime.now().strftime("%B %d, %Y")
            resp = client.chat.completions.create(
                model="grok-3-mini-fast",
                messages=[{
                    "role": "user",
                    "content": (
                        f"Today is {today}. "
                        f"List the {limit} most recent and important news headlines about {topic} "
                        "from the last 24 hours. Include breaking news, earnings, analyst upgrades/downgrades, "
                        "SEC filings, and market-moving events. "
                        "For each item return a JSON array of objects with keys: "
                        '"time" (e.g. "2h ago" or "Today 3:15 PM"), "title" (factual headline), '
                        '"source" (publication name like Reuters, Bloomberg, CNBC), '
                        '"url" (direct URL to the source article). '
                        "Return ONLY the JSON array, no other text."
                    ),
                }],
                temperature=0.1,
            )
            import json, re
            text = resp.choices[0].message.content.strip()
            # Strip markdown code fences if present
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            items = json.loads(text)
            if isinstance(items, list) and items:
                return [{"time": i.get("time", ""), "title": i.get("title", ""),
                          "source": i.get("source", ""), "url": i.get("url", "")} for i in items[:limit]]
        except Exception as e:
            logger.warning(f"XAI news failed: {e}")
        return None

    def _news_tavily(self, ticker, limit):
        if not self.tavily_key:
            return None
        try:
            today = datetime.now().strftime("%B %d, %Y")
            if ticker:
                query = f"{ticker} stock latest news headlines {today}"
            else:
                query = f"US stock market breaking news headlines {today}"
            r = requests.post("https://api.tavily.com/search", json={
                "api_key": self.tavily_key,
                "query": query,
                "search_depth": "advanced",
                "topic": "news",
                "max_results": limit,
                "days": 3,
            }, timeout=15)
            r.raise_for_status()
            data = r.json()
            articles = []
            for item in data.get("results", [])[:limit]:
                # Parse published_date if available
                time_str = ""
                pub = item.get("published_date", "")
                if pub:
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(pub)
                        time_str = dt.strftime("%b %d %I:%M %p")
                    except Exception:
                        time_str = pub[:16]
                articles.append({
                    "time": time_str,
                    "title": item.get("title", ""),
                    "source": item.get("url", "").split("/")[2] if item.get("url") else "",
                    "url": item.get("url", ""),
                })
            return articles if articles else None
        except Exception as e:
            logger.warning(f"Tavily news failed: {e}")
        return None

    def _format_news(self, ticker, articles, provider="Polygon"):
        label = f": {ticker.upper()}" if ticker else ""
        md = f"# News{label}\n\n"
        md += "| # | Time | Title | Source | Provider |\n|---|------|-------|--------|----------|\n"
        for i, a in enumerate(articles, 1):
            title = a["title"][:80]
            if a.get("url"):
                title = f"[{title}]({a['url']})"
            md += f"| {i} | {a['time']} | {title} | {a['source']} | {provider} |\n"
        return md

    # ------------------------------------------------------------------
    # 2. profile
    # ------------------------------------------------------------------

    def profile(self, ticker) -> str:
        """Get company profile."""
        ticker = ticker.upper()

        # Source 1: Polygon
        data = self._polygon_get(f"/v3/reference/tickers/{ticker}")
        if data and data.get("results"):
            return self._format_profile_polygon(data["results"])

        # Source 2: yfinance
        try:
            info = yf.Ticker(ticker).info
            if info and info.get("shortName"):
                return self._format_profile_yfinance(ticker, info)
        except Exception as e:
            logger.debug(f"yfinance profile: {e}")

        return f"# Profile: {ticker}\n\nNo data found."

    def _format_profile_polygon(self, r):
        md = f"# {r.get('name', r.get('ticker', ''))}\n\n"
        md += "| Field | Value |\n|-------|-------|\n"
        md += f"| Ticker | {r.get('ticker', '')} |\n"
        md += f"| Exchange | {r.get('primary_exchange', '')} |\n"
        md += f"| Market Cap | {self._fmt_large(r.get('market_cap'))} |\n"
        md += f"| Employees | {self._safe(r.get('total_employees'), '{:,.0f}')} |\n"
        md += f"| Industry | {r.get('sic_description', '\u2014')} |\n"
        md += f"| Website | {r.get('homepage_url', '\u2014')} |\n"
        md += f"| Listed | {r.get('list_date', '\u2014')} |\n"
        addr = r.get("address", {})
        if addr:
            loc = ", ".join(filter(None, [addr.get("city"), addr.get("state")]))
            md += f"| Location | {loc or '\u2014'} |\n"
        desc = r.get("description", "")
        if desc:
            md += f"\n{desc[:500]}{'...' if len(desc) > 500 else ''}\n"
        return md

    def _format_profile_yfinance(self, ticker, info):
        md = f"# {info.get('longName', ticker)}\n\n"
        md += "| Field | Value |\n|-------|-------|\n"
        md += f"| Ticker | {ticker} |\n"
        md += f"| Exchange | {info.get('exchange', '\u2014')} |\n"
        md += f"| Sector | {info.get('sector', '\u2014')} |\n"
        md += f"| Industry | {info.get('industry', '\u2014')} |\n"
        md += f"| Market Cap | {self._fmt_large(info.get('marketCap'))} |\n"
        md += f"| Employees | {self._safe(info.get('fullTimeEmployees'), '{:,.0f}')} |\n"
        md += f"| Website | {info.get('website', '\u2014')} |\n"
        desc = info.get("longBusinessSummary", "")
        if desc:
            md += f"\n{desc[:500]}{'...' if len(desc) > 500 else ''}\n"
        return md

    # ------------------------------------------------------------------
    # 3. financials
    # ------------------------------------------------------------------

    def financials(self, ticker, period="annual") -> str:
        """Get financial statements."""
        ticker = ticker.upper()
        tf = "annual" if period == "annual" else "quarterly"

        # Source 1: Polygon
        data = self._polygon_get("/vX/reference/financials", {
            "ticker": ticker, "timeframe": tf, "limit": 4, "order": "desc",
            "sort": "period_of_report_date",
        })
        if data and data.get("results"):
            return self._format_financials_polygon(ticker, data["results"], period)

        # Source 2: yfinance
        try:
            t = yf.Ticker(ticker)
            inc = t.income_stmt if period == "annual" else t.quarterly_income_stmt
            if inc is not None and not inc.empty:
                bs = t.balance_sheet if period == "annual" else t.quarterly_balance_sheet
                return self._format_financials_yfinance(ticker, inc, bs, period)
        except Exception as e:
            logger.debug(f"yfinance financials: {e}")

        return f"# Financials: {ticker}\n\nNo data found."

    def _format_financials_polygon(self, ticker, results, period):
        md = f"# Financials: {ticker} ({period.title()})\n\n"
        md += "*Source: Polygon*\n\n"
        md += "## Income Statement\n\n"
        md += "| Metric |"
        periods = []
        for r in results[:4]:
            p = r.get("fiscal_period", "")
            y = str(r.get("fiscal_year", ""))
            label = f"{p} {y}" if p else y
            periods.append(label)
            md += f" {label} |"
        md += "\n|--------|" + "|".join(["--------"] * len(periods)) + "|\n"

        metrics = [
            ("Revenue", "revenues"),
            ("Gross Profit", "gross_profit"),
            ("Operating Income", "operating_income_loss"),
            ("Net Income", "net_income_loss"),
            ("EPS (Basic)", "basic_earnings_per_share"),
        ]
        for label, key in metrics:
            md += f"| {label} |"
            for r in results[:4]:
                inc = r.get("financials", {}).get("income_statement", {})
                val = inc.get(key, {}).get("value")
                if key == "basic_earnings_per_share":
                    md += f" {self._safe(val, '${:.2f}')} |"
                else:
                    md += f" {self._fmt_large(val)} |"
            md += "\n"
        return md

    def _format_financials_yfinance(self, ticker, inc, bs, period):
        md = f"# Financials: {ticker} ({period.title()})\n\n"
        md += "*Source: yfinance*\n\n"
        md += "## Income Statement\n\n"

        cols = inc.columns[:4]
        md += "| Metric |"
        for c in cols:
            md += f" {c.strftime('%Y-%m') if hasattr(c, 'strftime') else str(c)} |"
        md += "\n|--------|" + "|".join(["--------"] * len(cols)) + "|\n"

        row_map = [
            ("Revenue", "Total Revenue"),
            ("Gross Profit", "Gross Profit"),
            ("Operating Income", "Operating Income"),
            ("Net Income", "Net Income"),
            ("EPS (Basic)", "Basic EPS"),
        ]
        for label, idx in row_map:
            md += f"| {label} |"
            for c in cols:
                try:
                    val = inc.loc[idx, c] if idx in inc.index else None
                except Exception:
                    val = None
                if idx == "Basic EPS":
                    md += f" {self._safe(val, '${:.2f}')} |"
                else:
                    md += f" {self._fmt_large(val)} |"
            md += "\n"

        # Balance sheet snapshot
        if bs is not None and not bs.empty:
            md += "\n## Balance Sheet (latest)\n\n"
            md += "| Metric | Value |\n|--------|-------|\n"
            latest = bs.iloc[:, 0]
            for label, idx in [("Total Assets", "Total Assets"),
                                ("Total Liabilities", "Total Liabilities Net Minority Interest"),
                                ("Total Equity", "Stockholders Equity"),
                                ("Cash", "Cash And Cash Equivalents")]:
                val = latest.get(idx)
                md += f"| {label} | {self._fmt_large(val)} |\n"

        return md

    # ------------------------------------------------------------------
    # 4. price
    # ------------------------------------------------------------------

    def price(self, ticker) -> str:
        """Get current price quote and technicals."""
        ticker = ticker.upper()
        try:
            info = yf.Ticker(ticker).info
        except Exception as e:
            return f"# Price: {ticker}\n\nError: {e}"

        if not info or not info.get("shortName"):
            return f"# Price: {ticker}\n\nNo data found."

        current = info.get("currentPrice") or info.get("regularMarketPrice")
        prev = info.get("previousClose")
        change = (current - prev) if current and prev else None
        change_pct = (change / prev * 100) if change and prev else None

        md = f"# {info.get('shortName', ticker)} ({ticker})\n\n"
        md += "| Metric | Value |\n|--------|-------|\n"
        md += f"| Price | ${current:,.2f} |\n" if current else "| Price | \u2014 |\n"
        if change is not None:
            sign = "+" if change >= 0 else ""
            md += f"| Change | {sign}${change:,.2f} ({sign}{change_pct:.2f}%) |\n"
        md += f"| Previous Close | {self._safe(prev, '${:,.2f}')} |\n"
        md += f"| Day Range | {self._safe(info.get('dayLow'), '${:,.2f}')} \u2013 {self._safe(info.get('dayHigh'), '${:,.2f}')} |\n"
        md += f"| 52-Week Range | {self._safe(info.get('fiftyTwoWeekLow'), '${:,.2f}')} \u2013 {self._safe(info.get('fiftyTwoWeekHigh'), '${:,.2f}')} |\n"
        md += f"| Volume | {self._safe(info.get('volume'), '{:,.0f}')} |\n"
        md += f"| Avg Volume | {self._safe(info.get('averageVolume'), '{:,.0f}')} |\n"
        md += f"| Market Cap | {self._fmt_large(info.get('marketCap'))} |\n"

        # Technicals from yfinance info (50/200 day MAs are available)
        ma50 = info.get("fiftyDayAverage")
        ma200 = info.get("twoHundredDayAverage")
        if ma50 or ma200:
            md += "\n## Technicals\n\n"
            md += "| Indicator | Value | Signal |\n|-----------|-------|--------|\n"
            if ma50:
                signal = "Above" if current and current > ma50 else "Below"
                md += f"| 50-Day MA | ${ma50:,.2f} | {signal} |\n"
            if ma200:
                signal = "Above" if current and current > ma200 else "Below"
                md += f"| 200-Day MA | ${ma200:,.2f} | {signal} |\n"

        # Try Polygon technicals (RSI, MACD)
        technicals_md = self._get_polygon_technicals(ticker)
        if technicals_md:
            if not (ma50 or ma200):
                md += "\n## Technicals\n\n"
                md += "| Indicator | Value | Signal |\n|-----------|-------|--------|\n"
            md += technicals_md

        return md

    def _get_polygon_technicals(self, ticker):
        """Try to fetch RSI and MACD from Polygon (may require paid tier)."""
        md = ""
        # RSI
        data = self._polygon_get(f"/v1/indicators/rsi/{ticker}", {
            "timespan": "day", "window": 14, "limit": 1,
        })
        if data and data.get("results", {}).get("values"):
            rsi = data["results"]["values"][0].get("value")
            if rsi is not None:
                if rsi < 30:
                    signal = "Oversold"
                elif rsi > 70:
                    signal = "Overbought"
                else:
                    signal = "Neutral"
                md += f"| RSI (14) | {rsi:.1f} | {signal} |\n"

        # MACD
        data = self._polygon_get(f"/v1/indicators/macd/{ticker}", {
            "timespan": "day", "limit": 1,
        })
        if data and data.get("results", {}).get("values"):
            v = data["results"]["values"][0]
            macd_val = v.get("value")
            signal_val = v.get("signal")
            if macd_val is not None and signal_val is not None:
                sig = "Bullish" if macd_val > signal_val else "Bearish"
                md += f"| MACD | {macd_val:.3f} | {sig} |\n"

        return md

    # ------------------------------------------------------------------
    # 5. movers
    # ------------------------------------------------------------------

    def movers(self, direction="both") -> str:
        """Get top gainers and/or losers."""
        md = "# Market Movers\n\n"

        if direction in ("both", "gainers"):
            data = self._polygon_get("/v2/snapshot/locale/us/markets/stocks/gainers")
            if data and data.get("tickers"):
                md += "## Top Gainers\n\n"
                md += self._format_movers_table(data["tickers"][:10])
            elif direction == "gainers":
                md += "No gainers data available (requires Polygon subscription).\n"

        if direction in ("both", "losers"):
            data = self._polygon_get("/v2/snapshot/locale/us/markets/stocks/losers")
            if data and data.get("tickers"):
                md += "\n## Top Losers\n\n"
                md += self._format_movers_table(data["tickers"][:10])
            elif direction == "losers":
                md += "No losers data available (requires Polygon subscription).\n"

        if md == "# Market Movers\n\n":
            md += "No data available. Movers requires a Polygon.io subscription.\n"

        return md

    def _format_movers_table(self, tickers):
        md = "| # | Ticker | Price | Change | Change % | Volume |\n"
        md += "|---|--------|-------|--------|----------|--------|\n"
        for i, t in enumerate(tickers, 1):
            day = t.get("day", {})
            prev = t.get("prevDay", {})
            price = day.get("c") or t.get("lastTrade", {}).get("p", 0)
            prev_close = prev.get("c", 0)
            change = price - prev_close if price and prev_close else 0
            change_pct = (change / prev_close * 100) if prev_close else 0
            vol = day.get("v", 0)
            sign = "+" if change >= 0 else ""
            md += (
                f"| {i} | {t.get('ticker', '')} | ${price:,.2f} | "
                f"{sign}${change:,.2f} | {sign}{change_pct:.2f}% | "
                f"{vol:,.0f} |\n"
            )
        return md

    # ------------------------------------------------------------------
    # 6. analysts
    # ------------------------------------------------------------------

    def analysts(self, ticker) -> str:
        """Get analyst ratings and price targets."""
        ticker = ticker.upper()
        try:
            t = yf.Ticker(ticker)
            info = t.info
        except Exception as e:
            return f"# Analysts: {ticker}\n\nError: {e}"

        if not info or not info.get("shortName"):
            return f"# Analysts: {ticker}\n\nNo data found."

        md = f"# Analyst Coverage: {info.get('shortName', ticker)} ({ticker})\n\n"

        # Recommendations summary
        try:
            recs = t.recommendations
            if recs is not None and not recs.empty:
                latest = recs.iloc[-1]
                md += "## Consensus Rating\n\n"
                md += "| Rating | Count |\n|--------|-------|\n"
                for col in recs.columns:
                    if col.lower() not in ("period", "date"):
                        val = latest.get(col, 0)
                        if val:
                            md += f"| {col} | {val} |\n"
                md += "\n"
        except Exception:
            pass

        # Price targets
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        num_analysts = info.get("numberOfAnalystOpinions")

        if target_mean:
            md += "## Price Targets\n\n"
            md += "| Metric | Value |\n|--------|-------|\n"
            md += f"| Current Price | {self._safe(current, '${:,.2f}')} |\n"
            md += f"| Mean Target | ${target_mean:,.2f} |\n"
            md += f"| High Target | {self._safe(target_high, '${:,.2f}')} |\n"
            md += f"| Low Target | {self._safe(target_low, '${:,.2f}')} |\n"
            if current and target_mean:
                upside = (target_mean - current) / current * 100
                md += f"| Upside | {upside:+.1f}% |\n"
            if num_analysts:
                md += f"| # Analysts | {num_analysts} |\n"
            md += "\n"

        # Growth estimates
        eg = info.get("earningsGrowth")
        rg = info.get("revenueGrowth")
        eps_fwd = info.get("epsForward")
        eps_cur = info.get("epsCurrentYear")

        if eg is not None or rg is not None or eps_fwd is not None:
            md += "## Growth Estimates\n\n"
            md += "| Metric | Value |\n|--------|-------|\n"
            if eg is not None:
                md += f"| Earnings Growth | {self._fmt_pct(eg)} |\n"
            if rg is not None:
                md += f"| Revenue Growth | {self._fmt_pct(rg)} |\n"
            if eps_cur is not None:
                md += f"| EPS (Current Year) | ${eps_cur:.2f} |\n"
            if eps_fwd is not None:
                md += f"| EPS (Forward) | ${eps_fwd:.2f} |\n"

        return md

    def analysts_rich(self, ticker):
        """Return Rich renderable with 3-column analyst layout."""
        from rich.table import Table
        from rich.columns import Columns
        from rich.text import Text
        from rich.console import Group

        ticker = ticker.upper()
        try:
            t = yf.Ticker(ticker)
            info = t.info
        except Exception as e:
            return Text(f"Analysts: {ticker} — Error: {e}", style="red")

        if not info or not info.get("shortName"):
            return Text(f"Analysts: {ticker} — No data found.", style="yellow")

        header = Text(
            f"Analyst Coverage: {info.get('shortName', ticker)} ({ticker})",
            style="bold cyan",
        )

        # Column 1: Consensus Rating
        t1 = Table(title="Consensus Rating", show_lines=True, expand=True)
        t1.add_column("Rating", style="white")
        t1.add_column("Count", justify="right")
        try:
            recs = t.recommendations
            if recs is not None and not recs.empty:
                latest = recs.iloc[-1]
                for col in recs.columns:
                    if col.lower() not in ("period", "date"):
                        val = latest.get(col, 0)
                        if val:
                            t1.add_row(str(col), str(val))
        except Exception:
            pass
        if t1.row_count == 0:
            t1.add_row("—", "—")

        # Column 2: Price Targets
        t2 = Table(title="Price Targets", show_lines=True, expand=True)
        t2.add_column("Metric", style="white")
        t2.add_column("Value", justify="right")
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        target_low = info.get("targetLowPrice")
        num_analysts = info.get("numberOfAnalystOpinions")
        if target_mean:
            if current:
                t2.add_row("Current Price", f"${current:,.2f}")
            t2.add_row("Mean Target", f"${target_mean:,.2f}")
            if target_high:
                t2.add_row("High Target", f"${target_high:,.2f}")
            if target_low:
                t2.add_row("Low Target", f"${target_low:,.2f}")
            if current and target_mean:
                upside = (target_mean - current) / current * 100
                t2.add_row("Upside", f"{upside:+.1f}%")
            if num_analysts:
                t2.add_row("# Analysts", str(num_analysts))
        if t2.row_count == 0:
            t2.add_row("—", "—")

        # Column 3: Growth Estimates
        t3 = Table(title="Growth Estimates", show_lines=True, expand=True)
        t3.add_column("Metric", style="white")
        t3.add_column("Value", justify="right")
        eg = info.get("earningsGrowth")
        rg = info.get("revenueGrowth")
        eps_fwd = info.get("epsForward")
        eps_cur = info.get("epsCurrentYear")
        if eg is not None:
            t3.add_row("Earnings Growth", self._fmt_pct(eg))
        if rg is not None:
            t3.add_row("Revenue Growth", self._fmt_pct(rg))
        if eps_cur is not None:
            t3.add_row("EPS (Current Year)", f"${eps_cur:.2f}")
        if eps_fwd is not None:
            t3.add_row("EPS (Forward)", f"${eps_fwd:.2f}")
        if t3.row_count == 0:
            t3.add_row("—", "—")

        cols = Columns([t1, t2, t3], equal=True, expand=True)
        return Group(header, Text(""), cols)

    # ------------------------------------------------------------------
    # 7. valuation
    # ------------------------------------------------------------------

    def valuation(self, tickers) -> str:
        """Get valuation metrics. Single ticker = vertical, multiple = comparison table."""
        tickers = [t.strip().upper() for t in tickers if t.strip()]
        if not tickers:
            return "# Valuation\n\nNo tickers specified."

        # (label, key, format): "ratio" = *100 for %, "pct" = already %, "large" = $B/T, "num" = plain
        metrics_keys = [
            ("P/E (Trailing)", "trailingPE", "num"),
            ("P/E (Forward)", "forwardPE", "num"),
            ("PEG Ratio", "trailingPegRatio", "num"),
            ("Price/Book", "priceToBook", "num"),
            ("Price/Sales", "priceToSalesTrailing12Months", "num"),
            ("EV/EBITDA", "enterpriseToEbitda", "num"),
            ("Dividend Yield", "dividendYield", "pct"),      # yfinance: 0.41 = 0.41%
            ("Profit Margin", "profitMargins", "ratio"),      # yfinance: 0.27 = 27%
            ("ROE", "returnOnEquity", "ratio"),               # yfinance: 1.52 = 152%
            ("Market Cap", "marketCap", "large"),
        ]

        # Fetch data for all tickers
        all_info = {}
        for t in tickers:
            try:
                info = yf.Ticker(t).info
                all_info[t] = info if info and info.get("shortName") else {}
            except Exception:
                all_info[t] = {}

        if all(not v for v in all_info.values()):
            return f"# Valuation: {', '.join(tickers)}\n\nNo data found."

        # Single ticker: vertical table
        if len(tickers) == 1:
            t = tickers[0]
            info = all_info[t]
            md = f"# Valuation: {info.get('shortName', t)} ({t})\n\n"
            md += "| Metric | Value |\n|--------|-------|\n"
            for label, key, fmt in metrics_keys:
                val = info.get(key)
                md += f"| {label} | {self._fmt_val(val, fmt)} |\n"
            return md

        # Multiple tickers: comparison table
        md = f"# Valuation Comparison\n\n"
        md += "| Metric |"
        for t in tickers:
            name = all_info[t].get("shortName", t)
            md += f" {name} |"
        md += "\n|--------|" + "|".join(["--------"] * len(tickers)) + "|\n"

        for label, key, fmt in metrics_keys:
            md += f"| {label} |"
            for t in tickers:
                val = all_info[t].get(key)
                md += f" {self._fmt_val(val, fmt)} |"
            md += "\n"

        return md
