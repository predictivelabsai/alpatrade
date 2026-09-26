# Hedge Funds: 13F filters and 13F-implied performance (plan)

Status: **phase 1 shipped** (2026-09-26). This doc covers the plan, the method, and what's left.

## 1. Where things stood

`/hedge-funds` (`engine/web/ph_hedgefunds.py`, backend `engine/publicmarkets/hedge_funds.py`) had:

* a Plotly treemap of the ~40 largest managers by 13F portfolio value (`/hedge-funds/data`),
* a table of recent activist filings (13D / 13D/A) with ticker, form and sort filters.

It reads the shared **`hedgefolio`** schema. Another project fills that schema, not this repo:

| table | rows (2026-09) | notes |
|---|---|---|
| `coverpage` | 23k | manager name, report quarter, report type (holdings / combination / notice) |
| `submission` | 23k | CIK, form type (13F-HR, 13F-HR/A, 13F-NT), filing date |
| `summarypage` | 19k | total value, number of entries |
| `infotable` | 7.3M | per-security rows: CUSIP, value, shares, SH/PRN, PUT/CALL. Indexed on CUSIP |
| `activist_filing` | 12.5k | 13D/G filings |

Coverage is broad only for **2025-12-31 and 2026-03-31** (about 11k filers each). Earlier quarters are
sparse (under 300 filers), and the loader last ran on 2026-06-18, so Q2-2026 filings (due 2026-08-14)
are missing. The old docstring said the infotable wasn't loaded. That was wrong: it is loaded, but
it only covers a couple of quarters, so it can't produce multi-year returns. The page had no 13F
filters and no performance data.

## 2. Goals

1. **Filter by 13F:** screen every 13F filer for a report quarter by report type (13F-HR holdings,
   combination, 13F-NT notice), manager name, 13F portfolio value bucket, number of positions, and
   ticker held (long, non-option rows). Optionally show only funds that have 13F-implied returns.
   Sort by value, positions, latest filing, name or TTM.
2. **Estimate performance from 13F holdings:** for each fund, show calendar-year, YTD and
   trailing-12-month (TTM) *13F-implied* returns next to SPY, labelled as estimates, with a
   methodology note.
3. Keep it honest. Missing data shows **n/a** and is never filled in. Every figure is labelled
   "estimated from 13F holdings".

## 3. Data

* **Source:** SEC EDGAR. `data.sec.gov/submissions/CIK##########.json` lists filings (`13F-HR`,
  `13F-HR/A`). Each filing folder's `index.json` names the information-table XML (the largest
  non-`primary_doc.xml` XML). `primary_doc.xml` gives the amendment type (`RESTATEMENT` or
  `NEW HOLDINGS`).
* **Cadence and lag:** 13F-HR is due **45 days after quarter end** (about Feb 14, May 15, Aug 14 and
  Nov 14). Confidential positions can show up months later as `NEW HOLDINGS` amendments (for
  example, Berkshire's 2023 Q3/Q4 amendments).
* **Units:** values are in dollars for filings from 2023-01-03 and in $ thousands before that. Some
  filers still report thousands (Baupost and Duquesne report about $5M "totals"). We infer this from
  the median value/share (under $0.50 means thousands) and store `value_multiplier`.
* **CUSIP to ticker:** OpenFIGI `/v3/mapping` (`ID_CUSIP`, `exchCode=US`, first listed equity line).
  Share-class `/` becomes `-` for Yahoo (BRK/B becomes BRK-B). Results are cached in
  `alpatrade.hf13f_cusip_map`. Unmapped CUSIPs are retried after 30 days. CUSIPs are normalised by
  uppercasing, stripping separators and left-padding dropped leading zeros (`37833100` becomes
  `037833100`). A check-digit validator is included.
* **SEC fair access:** a descriptive `User-Agent` with a contact (`SEC_USER_AGENT`, default
  `AlpaTrade/1.0 (info@predictivelabs.co.uk)`), at most about 5 req/s from the job (the SEC limit is
  10/s), and no parallel crawling.
* **OpenFIGI:** without a key, 25 requests/min × 10 CUSIPs. Set `OPENFIGI_API_KEY` for about 25
  requests/6 s × 100.
* **Prices:** Yahoo via `yfinance` (already a dependency), `auto_adjust=True`. Closes are split and
  dividend adjusted, which approximates total return. SPY is the benchmark and defines the trading
  calendar.

## 4. Performance method (13F-implied)

For each fund and quarter:

1. Take the effective holdings: the original 13F-HR, or the latest `RESTATEMENT`, plus any
   `NEW HOLDINGS` amendments.
2. Keep **long equity rows only**: drop `PUT`/`CALL` rows, `PRN` (principal/debt) rows and
   non-positive values. Aggregate by ticker.
3. Weights are proportional to **reported market value at quarter end**. Unmapped or unpriced
   positions are dropped and the remaining weights renormalised. **Coverage** is the priced value
   divided by the long-equity value, reported per period and averaged per window.
4. **`quarter_end` (headline, "13F-implied"):** buy at the report-date close and hold buy-and-hold
   (weights drift) until the next report date, then rebalance to the next filing. This estimates the
   disclosed book's return. It is **not investable** because of the 45-day lag.
5. **`follow_filing` (optional, investable):** buy at the close of the first trading day *after*
   the filing date, using holdings known by then (later confidential amendments are excluded).
   Quarter-end weights are drifted to the entry date by price, and the position is held until the
   next filing becomes actionable.
6. Daily portfolio returns are chained into:
   * **calendar years** (last close of Y-1 to last close of Y),
   * **YTD** for the current year,
   * **TTM** (the latest close vs the close 365 days earlier).
   Each window is compared with SPY over exactly the same dates.
7. If the next report date is more than 120 days away (a missing filing), the chain breaks. Any window
   that touches an uncovered day is **n/a**.
8. A name that goes unpriced partway through a period (delisted or acquired) is held at its last
   traded price.

Code: pure maths in `engine/publicmarkets/hf13f_perf.py` (unit-tested with synthetic prices),
EDGAR/OpenFIGI in `engine/publicmarkets/hf13f.py`, and DB plus job in
`engine/publicmarkets/hf13f_store.py`.

Extra rules added during phase 1:

* **Stale book cap.** The latest book is held for at most 140 days after its quarter end (one
  quarter, plus the 45-day deadline, plus slack). After that the estimate stops. This matters for
  Scion, which stopped filing after Q3-2025.
* **Affiliate filers** (`hf13f.ALT_CIKS`). Pershing Square Capital Mgmt filed a 13F-NT for Q2-2026,
  and Pershing Square Inc. (CIK 2026053) filed the holdings. For each quarter the larger long book
  wins.
* **Issuer-prefix fallback.** Old CUSIPs from reverse splits or re-domiciles stop resolving on
  OpenFIGI. For common shares only, they reuse the ticker of a mapped CUSIP with the same 6-character
  issuer ID.

### Phase-1 results (computed 2026-09-26, prices to 2026-09-25)

13F-implied (quarter-end) returns vs SPY:

| Fund | 2021 | 2022 | 2023 | 2024 | 2025 | YTD 2026 | TTM | TTM coverage |
|---|---|---|---|---|---|---|---|---|
| SPY | +28.7% | -18.2% | +26.2% | +24.9% | +17.7% | +14.0% | +18.5% | |
| Berkshire Hathaway | +30.2% | -16.3% | +24.1% | +22.4% | +11.4% | +12.2% | +16.7% | 96% |
| Renaissance Technologies | +21.8% | -14.5% | +21.8% | +22.6% | +21.6% | +19.5% | +20.6% | 91% |
| Pershing Square | +38.6% | -22.6% | +35.7% | +15.1% | +13.4% | +1.8% | +5.1% | 100% |
| Tiger Global | -11.7% | -51.4% | +57.3% | +46.5% | +25.8% | +3.7% | +2.6% | 93% |
| Duquesne Family Office | +13.1% | -25.7% | +47.1% | +71.2% | +37.0% | +35.9% | +51.6% | 86% |

Sanity check:

* The SPY window returns match SPY's published total returns (2022 -18.2%, 2023 +26.2%,
  2024 +24.9%).
* Berkshire's 13F book tracks its Apple, BAC, AXP, KO and energy weights. It is *not* BRK-B stock,
  which returned +29.0%, +3.3%, +15.5%, +27.1%, +10.9% and +0.6% YTD over the same years.
* Mapping coverage: OpenFIGI resolved about 60% of all CUSIPs seen, most of the unresolved ones
  delisted or acquired. By value, the priced share of long books averages about 92% over TTM windows.
  Baupost is the lowest (about 45% in 2024).

## 5. Caveats (shown in the UI)

* Only **long US-listed 13(f) securities** are covered. There are no shorts, cash, bonds, credit,
  futures, FX, private or non-US assets, and no fees or leverage. For macro, quant and credit funds
  (for example Bridgewater and Renaissance) the 13F book is only a small slice of the strategy.
* **No intra-quarter trading.** Holdings are a quarter-end snapshot, so turnover-heavy funds such as
  RenTec diverge a lot from the estimate.
* **Filing lag:** `quarter_end` has look-ahead relative to what an outsider could trade.
  `follow_filing` is the investable version.
* **Options:** PUT/CALL rows are excluded. The 13F value for options is the *underlying*'s value,
  not the premium, so including them would badly distort weights.
* **Unmapped CUSIPs:** warrants, rights, some ADRs, recent listings and delisted names may fail to
  map or price. Coverage shows how much of the book was priced.
* **Survivorship and data vendor:** Yahoo has gaps for delisted tickers. Fund selection is a curated
  list of well-known funds, not a random sample.
* The label is always **"13F-implied / estimated from 13F holdings"**. These are never the fund's
  reported returns.

## 6. Storage (sql/38_hedge_fund_13f.sql, `alpatrade` schema)

* `hf13f_funds`: curated funds (CIK, display name).
* `hf13f_filings`: one row per 13F-HR(/A): period, filing date, amendment type, value multiplier,
  total, positions.
* `hf13f_holdings`: information-table rows (value already in USD).
* `hf13f_cusip_map`: CUSIP to Yahoo ticker cache (mapped / unmapped).
* `hf13f_performance`: fund × method × period label (year / YTD / TTM): fund return, SPY return,
  coverage, quarters used.
* `hf13f_period_returns`: per-holding-period detail that the windows are chained from.

`hedgefolio` stays read-only for this app.

## 7. Jobs

`scripts/hedge_fund_13f.py`:

```
python run_migration.py sql/38_hedge_fund_13f.sql
python scripts/hedge_fund_13f.py ingest --since 2020-12-31   # EDGAR -> hf13f_filings/holdings
python scripts/hedge_fund_13f.py map --top 3000              # OpenFIGI; +3000 most widely held CUSIPs
python scripts/hedge_fund_13f.py compute                     # yfinance prices -> hf13f_performance
```

Cadence: `ingest` + `map` after each 13F deadline (mid Feb/May/Aug/Nov, plus a week for stragglers).
`compute` weekly (or daily) keeps YTD and TTM fresh. Phase 2 adds this to the scheduled jobs.

## 8. UI (`/hedge-funds`)

* **13F-implied performance:** starter funds × {years, YTD, TTM}, an SPY row, TTM vs SPY and
  coverage. A method toggle switches between 13F-implied and follow-the-filing. There is an
  "estimated from 13F holdings" badge, a tooltip on each return header, and a methodology
  `<details>` block that links here.
* **13F filers:** filter form (`q`, `period`, `rtype`, `min_aum`, `pos`, `holds`, `perf`, `hsort`)
  over `hedgefolio`, with TTM and last-full-year 13F-implied columns where available. Values that a
  filer reported in $ thousands are scaled and marked `*`.
* JSON: `/hedge-funds/13f.json` (screener) and `/hedge-funds/performance.json`.
* The existing treemap and activist-filings sections are unchanged.

## 9. Tests

`tests/test_hedge_funds_13f.py` (in CI) covers:

* CUSIP normalisation and check digit
* OpenFIGI pick and unmapped handling
* info-table XML parsing (namespace, PUT, PRN)
* amendment handling and value-unit inference
* value-weighted buy-and-hold returns
* coverage and reweighting
* annual chaining vs single asset, and gap giving n/a
* follow-the-filing entry date and delisted last price
* screener SQL filters, unmapped holds-ticker, and page render with filters and performance
  columns.

## 10. Phases

* **Phase 1 (done):**
  * 13F screener filters
  * EDGAR ingestion for 10 starter funds (Berkshire, Bridgewater, Renaissance, Pershing Square,
    Scion, Appaloosa, Tiger Global, Third Point, Baupost, Duquesne Family Office), 2020-12-31 onward
  * OpenFIGI map (starter holdings plus the 3,000 most widely held CUSIPs)
  * 13F-implied and follow-the-filing annual/YTD/TTM vs SPY
  * UI, tests and CI
* **Phase 2:**
  * scheduled quarterly ingest and weekly compute
  * fund detail page (`/hedge-funds/<cik>`) with holdings, quarter-by-quarter returns, top
    contributors and a cumulative chart vs SPY
  * add funds on demand (any CIK), and admin "add fund"
* **Phase 3:**
  * compute 13F-implied returns for all filers from `hedgefolio.infotable` once it has four or more
    consecutive quarters (or backfill it from the SEC's quarterly *Form 13F data sets*)
  * a precomputed value-multiplier column so value filters handle $-thousand filers
  * a sector/industry breakdown
  * concentration metrics (top-10 weight, HHI) as extra filters
  * holding-overlap search ("funds most similar to X")
* **Later:**
  * risk stats (volatility, beta, max drawdown of the 13F-implied series)
  * a price source switch (MASSIVE) for delisted coverage
