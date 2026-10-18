# Daily market data (added 2026-10-17)

Free data that scripts record every day, with no model tokens, shown on nodus42.com next to the supply-chain map.
It is **not** a supply-chain signal: nothing here is written to `quarterly_data`, `chains/`, `patches/` or
`derive.py`. Each dataset has its own history files, its own web file and its own section on the site (the
**Markets** tab, the **Capex** tab table, and the company panel's Financials (with the quarterly cash flow and
the next earnings date) / AI lab / Financing / Insider trades sections). Every row carries its source name and a
link.

## Schedule

Two Windows Task Scheduler tasks (Pacific time, the laptop's clock). Both wake the laptop and catch up as soon as
it is on again after a missed run.

**`earnings-ai market data`, every day at 22:00: `routine/market_data.ps1`** (since 2026-10-17). Scripts only, no
Claude session, so it runs even when last night's enrich session is still working (the night `nightly.ps1` skips).
One line per event goes to `.claude/market_data_task.log`; each step's full output goes to `.claude/<step>.log` and
`.claude/<step>.err.log`. It first logs the branch and commit that will run the collectors. On `main`, when no
`nightly enrich*` session is working in the checkout, it runs `git pull --ff-only`, so a collector fix merged on
GitHub runs the same day; on another branch it logs a warning, and nothing is pulled or published. Steps, in order,
each time-boxed (a failure or timeout is logged and the next step runs):

1. `python -X utf8 market/selftest.py` (10 min): the offline regression tests, result in `market/selftest_result.json`.
2. `python -X utf8 market/run_all.py` (45 min): every collector below, in a fixed order. One line per collector per
   day goes to `market/run_log.jsonl`; the full output is in `.claude/market_data.log` and
   `.claude/market_data.err.log`. `financing_us` runs last but one (only the financing build follows), and it stops
   after 5 SEC filers fail in a row, so a slow or blocking SEC cannot use up the 45 minutes of the other collectors.
   Before the first collector, a history file whose last line was cut off by a killed run gets that line moved to
   `<dataset>.rejected.txt` (kept), so every later night still reads it.
3. `python -X utf8 utils/transcript_quality.py` (10 min) writes `graph/transcript_quality.json` (see the end of this
   page).
3b. `python -X utf8 media_pull.py --days 2` (20 min, since 2026-10-17): transcripts of news-outlet interviews in which
   a named company executive speaks, saved in `transcripts/media/` (gitignored: kept in this checkout only, never
   published) as enrich inputs: unlike the market data, the
   enrich session may turn the executive's own words into signals (enrich skill §11); the site shows nothing of them. It
   starts only when at most 75 minutes of the task have passed, so the task stays inside its 2-hour limit; a skipped
   day is caught up the next day. Rules, channels and files: `docs/media_interviews.md`.
4. `python -X utf8 market/health.py` (5 min): reads the run log and the test result and sends the phone alert.
5. Publishing (15 min), only when the checkout is on `main`, no `nightly enrich*` Claude session is working and the
   collectors added rows to `market/history` (or `market/ai_lab_deals.json` changed):
   `routine/nightly.ps1 -PublishOnly -MarketOnly` commits only the market-data files (`market/history`,
   `market/run_log.jsonl`, `market/ai_lab_deals.json`, the market web files in `graph/`: `memory_prices.json`,
   `gpu_prices.json`, `insiders_index.json` + `insiders/`, `financing_index.json` + `financing/`,
   `hyperscaler_cash.json`, `financials_index.json` + `financials/`, `ai_labs.json`, `transcript_quality.json`, and
   step 3b's state, roster and channel list in `media/`) on a branch, opens a PR and merges it. Vercel
   then deploys the site (its build copies `graph/` into `web/public/data`). What an enrich session writes
   (transcripts, patches, chains, the rest of `graph/`) is never part of it, so a blocked session's leftovers wait
   for a night that finishes as done. While an enrich session works, nothing is published: `nightly.ps1` publishes
   everything when the session ends.

Steps 1 and 4 run even when the market-data lock (below) is busy; steps 2, 3, 3b and 5 need it. A step whose script does
not exist is skipped (logged). Test it in a worktree, without publishing and without a phone alert (the collectors
really run there):
`powershell -NoProfile -ExecutionPolicy Bypass -File routine\market_data.ps1 -RepoRoot <worktree> -NoPublish -NoAlert`.

**`earnings-ai nightly enrich`, every night at 23:00: `routine/nightly.ps1`.** It skips the whole night when last
night's session is still working. Otherwise, before the enrich session, it runs steps 1 to 4 above only as a
fallback: when `market/run_log.jsonl` lacks today's line for some collector (the 22:00 task did not run today), and
step 2 then runs only the missing collectors (all of them when the log cannot be read). The log line in
`.claude/nightly.log` says which. Then the nightly enrich session (it also appends hand-found AI-lab deals and
financing events, enrich skill §10), and publishing when the session finishes as done.

The two scripts never collect at the same time: both take one lock (a named Windows mutex,
`Global\earnings-ai-market-data`) around their market-data steps, and the one that comes second waits
(`market_data.ps1` at most 30 minutes, then it skips its steps 2, 3 and 5 because `nightly.ps1` is collecting;
`nightly.ps1` at most 125 minutes, then it skips its data steps). Windows frees the lock when its holder dies.
Switching to `main`, pulling and publishing take a second lock, `Global\earnings-ai-git`, so the two scripts never run
those git steps at the same time in one checkout. Every publish commits only its own path list (a file staged by
hand stays staged and out of the PR), and nothing is published from a branch other than `main`.

## Phone alerts

`market/health.py` (step 4) reads `market/run_log.jsonl` and `market/selftest_result.json` and pushes one phone
notification (a tiny background Claude Code session with Remote Control, on the user's own login, never the API)
when:

1. a collector did not succeed on its last 2 run days (a run day with no line for it counts too: `run_all.py` was
   stopped before it);
2. a collector's latest run failed and its last success is 2 or more days older (days without any run in between,
   e.g. the laptop was off, do not hide a broken source);
3. `market/run_log.jsonl` has no line from the last 2 days at all;
4. the regression tests failed on their latest run, or have no result for 2 or more days.

Each problem is pushed at most once a day (`market/health_state.json`), however often the check runs; a crash of
the check itself is pushed too, once a day. The full result goes to `market/health.json`. These two files and
`market/selftest_result.json` are local only (gitignored). `python -X utf8 market/health.py --dry-run` prints the
alerts and writes and sends nothing. `python -X utf8 market/health.py --test-alert` sends one harmless test
notification: run it once from the main checkout after setting up the 22:00 task, and check that it reaches the
phone.

A collector whose source is down logs a warning, keeps its earlier history and rebuilds its web file from it, so the
site keeps showing the last good data with its date. `run_all.py` exits 0 unless every collector failed, and a
failure never stops the enrich session.

Requests are polite: each source is fetched once a day with pauses between requests. SEC requests stay at 4 per
second or less and send the descriptive `EDGAR_USER_AGENT` header (`market.common.sec_headers()`). API keys come
from `.env` (`DART_API_KEY`, `EDINET_API_KEY`, `ALPHAVANTAGE_API_KEY`, `EDGAR_USER_AGENT`, optional
`SHADEFORM_API_KEY`) and are never printed or written to any file.

## Datasets

| Collector (`market/…`) | Web file (`graph/…`) | History (`market/history/…`) | Sources |
|---|---|---|---|
| `memory_prices.py` | `memory_prices.json` | `memory_spot.jsonl`, `memory_press.jsonl` | DRAMeXchange home page (DRAM, GDDR, module and NAND wafer spot prices); TrendForce press-center RSS (memory price releases) |
| `gpu_prices.py` | `gpu_prices.json` | `gpu_shadeform.jsonl`, `gpu_getdeploying.jsonl`, `gpu_list.jsonl` | Shadeform public marketplace API; GetDeploying weekly GPU price dataset; list prices from the CoreWeave, Nebius, Lambda, Together AI and Crusoe pricing pages |
| `insiders_us.py` | `insiders_index.json` + `insiders/<company>.json` | `insiders_us.jsonl` | SEC Form 4: quarterly insider-transaction data sets (backfill) plus the EDGAR daily index (daily) |
| `insiders_asia.py` | `insiders_index.json` + `insiders/<company>.json` | `insiders_kr.jsonl`, `insiders_tw.jsonl`, `insiders_jp.jsonl` | Korea: OpenDART executive / 10% holder and 5% holder reports. Taiwan: TWSE and TPEx OpenAPI insider pre-sale declarations. Japan: EDINET large-shareholding reports (350 / 360) |
| `insiders.py` | `insiders_index.json` + `insiders/<company>.json` | reads every `insiders_*.jsonl` | builder only, no network |
| `financing_us.py` | `financing_index.json` + `financing/<company>.json` | `financing_us.jsonl` | SEC EDGAR 8-K (items 1.01 / 2.03 / 3.02), 424B2 / 424B3 / 424B5, 6-K |
| `financing_asia.py` | `financing_index.json` + `financing/<company>.json` | `financing_kr.jsonl`, `financing_tw.jsonl`, `financing_jp.jsonl` | Korea: OpenDART major-issues reports and debt registrations. Taiwan: MOPS material information. Japan: TDnet timely disclosures |
| `financing.py` | `financing_index.json` + `financing/<company>.json` | reads every `financing_*.jsonl`, including `financing_manual.jsonl` | builder only, no network |
| `hyperscaler_cash.py` | `hyperscaler_cash.json` | `hyperscaler_cash.jsonl`, `earnings_calendar.jsonl` | SEC XBRL companyconcept API (capex, operating cash flow, finance-lease principal); Alpha Vantage EARNINGS_CALENDAR (1 call a day); Yahoo Finance via yfinance; the companies' own IR event pages |
| `financials.py` (+ `financials_sec.py`, `financials_dart.py`) | `financials_index.json` + `financials/<company>.json` | `financials_snapshots.jsonl`, `financials_eps_adjusted.jsonl` (+ `financials_state.json`) | Yahoo Finance via yfinance's session: fundamentals timeseries (quarterly / annual income statement, balance sheet and cash flow), quoteSummary (earnings summary, estimates, key statistics, calendar), monthly price chart with dividends and splits; Yahoo FX for currency conversion. The companies' own filings: SEC XBRL company facts (US filers: 10-K / 10-Q, cash flow included; 20-F filers for per-share checks and dates) and OpenDART (Korea: quarterly / annual statements with the cash-flow statement, share counts, preliminary-results disclosures) |
| `ai_labs.py` | `ai_labs.json` | `ai_lab_revenue.jsonl`, `ai_lab_funding.jsonl`, `ai_lab_compute.jsonl`, `ai_model_scores.jsonl` | Epoch AI "Data on AI companies" and "Benchmarking Hub" downloads; the curated deals log `market/ai_lab_deals.json` |

What each web file holds:

- **memory_prices.json / gpu_prices.json** (contract 1): daily price series, the latest value and its change, and
  tables (latest session, provider list prices, TrendForce releases). Spot boxes say when the page itself was last
  updated; the site shows each series' own latest date.
- **insiders_index.json + insiders/<company>.json** (contract 2, split per company on 2026-10-17 so a company panel
  downloads only its own trades instead of one 10 MB file): the index maps each node id to its file name, row count
  and latest trade date, plus the sources list; each company file is {company, rows} (no date inside, and an unchanged file is not rewritten, so a nightly commit
  touches only companies with new trades). graph/insiders/ is
  generated and stale files are deleted on every build. Rows: insider trades of the last 365 days, newest first; type is buy,
  sell, option_exercise, tax_withholding, grant, gift or other. Lines of one filing that are one trade split by
  fill price are merged per holder (an indirect holder is named in brackets, e.g. "(By Trust for Child 1)"); the
  history keeps every raw line. For the site only: a price more than 20x away from the company's other trades of
  the same weeks (a typo in the filing) is shown without price and value; an amendment (4/A, or a later Korean
  report of the same line) replaces the trade it restates; one block trade filed by two related persons (same day,
  shares, price and holding after) is one row with both names; grants and gifts have no value. The 10b5-1 flag is
  per line: when a footnote names the plan, only the lines that point at it are plan trades.
- **financing_index.json + financing/<company>.json** (contract 3, split per company on 2026-10-17 like the
  insider feed: index {updated, sources, companies: {node id: {file, count, latest}}}, company file {company, rows}): debt, convertible, equity, credit-facility, ABS, lease-financing and rating
  events of the last 365 days, newest first. The same deal filed twice (a prospectus and its closing 8-K) is shown
  once; two prospectuses, two series / issue numbers, or an ATM program next to another deal are never merged. A
  repayment, redemption or buyback (money going out) is type `other` with no `amount_usd`, and a board approval of a
  program has no `amount_usd` (its issues are their own rows). Korean, Taiwanese and Japanese amounts are converted
  at the filing day's rate (`market/history/fx_usd.jsonl`), like the US rows.
- **hyperscaler_cash.json** (contract 4): the last quarters of capex, operating cash flow, free cash flow and FCF
  after finance-lease principal for Microsoft, Google, Amazon, Meta, Oracle, CoreWeave, Nebius and IREN, plus the
  next 60 days of earnings dates for every public company in the graph (confirmed = the company's IR page, or
  Alpha Vantage and Yahoo agree). The Capex tab shows its cash-flow table; the company panel reads only the
  earnings dates (in the Financials header) since 2026-10-17, when its separate Cash flow section was merged into
  the Financials table (whose collector draws the same SEC quarters for these 8 companies).
- **ai_labs.json** (contract 5): AI-lab revenue run rates, funding rounds, compute deals, and frontier models'
  benchmark scores.
- **financials_index.json + financials/<company>.json** (contract 6, added 2026-10-17 for the company panel's
  financial-statement table, like Naver Finance's 재무제표): index {updated, source, companies: {node id: {file,
  latest_end, currency}}}; company file {company, ticker (Yahoo symbol), currency, unit (1000000), fiscal_year_end
  ("MM-DD"), updated, quarterly (up to 8, oldest first), annual (up to 4), estimates {quarter, fy, next_fy},
  preliminary (Korea: a quarter's preliminary results, or null), source, sources (Yahoo plus SEC EDGAR / DART when
  the filings filled figures), notes}. Each period: end (the company's own period end date), label (the company's
  own fiscal label, "Q3 26" / "FY26"), fiscal_year, fiscal_quarter, revenue, gross_profit, ebitda, ebit,
  operating_income (as reported), pretax_income, net_income_after_tax (세후손익), net_income (당기순이익,
  attributable), eps_diluted (reported: GAAP / IFRS), eps_adjusted (Yahoo's EPS on the analysts' basis: for US
  companies usually the company's adjusted / non-GAAP EPS, elsewhere usually the reported one; the estimates'
  basis; kept past Yahoo's 4-quarter window, see below), per, pbr, dividend_yield_pct, roa_pct, ocf (operating
  cash flow), capex (a positive number), fcf (ocf - capex), fcf_after_leases (fcf - finance-lease principal
  payments; null unless the company files those), qoq, yoy and derived (fields computed rather than read from a
  statement).
  Money is in millions of the reporting currency; EPS in full units.
  The rules (all in the collector's docstring, and in each file's notes when they apply):
  - Every public node (all markets). An ADR whose home listing yahoo.ts already maps (TSM -> 2330.TW, ASML ->
    ASML.AS, ...) uses the home listing, so price and per-share figures share a currency; another US-listed ADR
    reporting in a foreign currency gets no PER / PBR (unknown ADR ratio).
  - Dates are the companies' own period ends (the user, 2026-10-17: the column shows the date, so no calendar
    label; Micron FY26 = 2026-09-03, NVIDIA Q2 27 = 2026-07-26): from the SEC filings, Yahoo's mostRecentQuarter /
    lastFiscalYearEnd, and for every other period (estimates too) the company's 52/53-week rule (the weekday its
    periods end on: the last one of the month, NVIDIA, or the nearest one, Micron / Broadcom). Month-end reporters
    keep the month end. Inside the collector, periods are keyed by Yahoo's month end. Fiscal years are named by
    the calendar year they end in (Micron's quarter ending May 2026 = "Q3 26", NVIDIA's ending July 2026 = "Q2
    27"); the fiscal year end month is the most recent year's (a company that moved its year end, like Daifuku,
    is labelled on its new calendar).
  - Filings first: for SEC 10-K / 10-Q filers the XBRL facts fill what Yahoo lacks (the newest filed quarter and
    year before Yahoo has them, and the quarters before Yahoo's 5-quarter window, so YoY has its base): a fiscal
    Q4 = the 10-K year - the 10-Q nine months, its diluted EPS = Q4 net income / Q4 diluted shares, EBIT / EBITDA
    = pre-tax income + interest (+ D&A) only where that matches Yahoo's own figures; each XBRL concept is checked
    against Yahoo's figures on the periods both have. A 20-F filer's facts (they can be on another GAAP than the
    home listing, e.g. TSMC) only check the EPS and give the dates. For Korea, DART's reports fill the same way
    (Q4 = the annual report - the Q3 report's nine months, diluted EPS included), and book value per share uses
    DART's shares outstanding of all classes (common + preferred - treasury), as Korean BPS does.
  - Then Yahoo's earnings summary: revenue and net income of the newest periods neither has yet (a 0 there means
    "not reported yet" and stays blank; only periods newer than the newest known one are added, so an old series
    some small listings carry is ignored; a summary series that disagrees with the statements on revenue or net
    income is not used). Checks: a statement net income that does not match diluted EPS x diluted shares while the
    summary does is replaced (TSMC, whose statements mix 20-F IFRS net income with Taiwan-IFRS EPS); an EPS that
    does not match net income / shares while the SEC filing's does is replaced (ASML FY22); an EBITDA equal to
    EBIT (D&A missing) is left blank. Gaps: one missing quarter of a year = FY - the other three; a missing EPS =
    Yahoo's reported EPS when it is within 1% of net income / diluted shares, else net income / diluted shares.
    EPS filed before a recent split is put on today's share basis. All computed values are listed in derived.
  - per = month-end price / trailing-4-quarter diluted EPS (annual: the year's EPS), pbr = price / book value per
    share, dividend_yield_pct = last 12 months' dividends / price, roa_pct = trailing net income / average total
    assets (now and 12 months earlier); a foreign-currency price is converted at the month-end Yahoo FX rate. QoQ /
    YoY of revenue, ebit, net_income, eps_diluted and eps_adjusted (each basis against itself only); null from a
    zero or negative base. QoQ / YoY of fcf only between two positive values.
  - Cash flow (2026-10-17; the panel's separate Cash flow section was merged into this table), one source per
    company so a table never mixes capex definitions: a 10-K / 10-Q filer's SEC XBRL facts with
    `hyperscaler_cash.py`'s tags and quarter logic (imported: NetCashProvidedByUsedInOperatingActivities,
    PaymentsToAcquirePropertyPlantAndEquipment, or PaymentsToAcquireProductiveAssets where the company files that
    (Amazon, NVIDIA), FinanceLeasePrincipalPayments; 10-Q cash flows are year-to-date, so a quarter without a
    3-month figure is the difference of two, Q4 = FY - 9 months), so the 8 companies of `hyperscaler_cash.json`
    show the same quarters (a test pins this on real Amazon / Alphabet facts); else a Korean company's DART
    cash-flow statements (영업활동 현금흐름, capex = 유형자산의 취득; year-to-date too: Q2 = H1 - Q1 ... Q4 = FY - 9M);
    else Yahoo's rows (Operating Cash Flow, Capital Expenditure with its sign turned, Free Cash Flow where one of
    the two is missing). Differenced quarters are listed in derived, and fcf / fcf_after_leases when an input is.
    A DART report cached before this change is read once more for its cash-flow statement (its share counts are
    kept), and an SEC or Yahoo cache written before it is fetched again even on the same day.
  - Estimates: Yahoo's earningsTrend 0q (the next unreported quarter), 0y (this fiscal year) and +1y, labelled with
    the same fiscal labels, with the exact period end; an estimate for a period already reported is dropped. The
    EPS consensus is on Yahoo's basis (for US companies usually adjusted), so the panel shows it only in the
    "EPS (adjusted)" row, never next to the reported EPS.
  - EPS rows (user, 2026-10-17: "조정, GAAP, net income 다 볼 수 있게"): the panel always shows "Net income", "EPS (GAAP,
    diluted)" (eps_diluted) and, when it has any value, "EPS (adjusted)" (eps_adjusted, with the (E) consensus), each
    with its own QoQ / YoY. For most non-US companies Yahoo's basis is the reported EPS, so the two EPS rows (nearly)
    match. Yahoo's earningsChart gives the adjusted EPS of the last ~4 quarters only, so every daily fetch records the
    adjusted actuals it sees (and those of the older cache it replaces) in `financials_eps_adjusted.jsonl` (ADD-only,
    key company + period_type + month-end key, with the fiscal label, the day seen and Yahoo's EPS currency), and the
    web file is built from Yahoo's current answer plus that history: older quarters stay after Yahoo drops them. A
    recorded figure seen before a later stock split is divided by the split. A fiscal year's adjusted EPS is Yahoo's own
    annual figure (the 0y estimate's year-ago EPS) where given, else the sum of its four fiscal quarters only when all
    four are known (listed in derived), else blank; nothing is estimated. A listing whose Yahoo EPS is in another
    currency than its statements (6805.TW, HYFT) gets no adjusted actuals.
  - Preliminary results (Korea): a 연결재무제표기준영업(잠정)실적(공정공시) filing for a quarter without its report yet
    becomes a "(P)" column (revenue, operating income and whatever else it gives, with QoQ / YoY).
  - Refresh: daily for companies 10 days before to 4 days after their earnings date (hyperscaler_cash's calendar
    or Yahoo's), plus companies never fetched or whose fetch failed, plus a rotating 1/7 of the rest (each company
    at least weekly), at most 15 minutes a day; `--backfill` fetches all (about 2.5 s per company, 3 requests).
    The same companies' filings follow, at most 5 more minutes: SEC company facts (1 request, at most daily) and
    DART (only reports not read yet; a first read is about 13 reports x ~8 s, so `--filings-only --workers 8`
    does the first fill of every company). The latest raw answers are cached in `market/cache/financials/`
    (Yahoo per symbol, `sec/`, `dart/`; local), so `--build-only` rebuilds without the network; a company
    without a cache keeps its published file. `financials_snapshots.jsonl` keeps
    every reported period as first seen (key company + end + period_type), to spot restatements and to keep
    quarters that dropped out of Yahoo's 5-quarter window.

## Licences and terms

- **DRAMeXchange** spot prices: DRAMeXchange's terms restrict republishing. The user chose to show them anyway
  (2026-10-17), with a kill switch: `market/config.json` → `"show": {"dramexchange_spot": false}` hides them on the
  site at the next build while collection continues for internal history. TrendForce press releases have their
  own switch, `trendforce_press`.
- **GetDeploying** weekly GPU prices: CC BY 4.0. Credit is required; the site shows
  "GetDeploying (CC BY 4.0)" with a link to the dataset and the licence.
- **Epoch AI** data (AI companies, benchmarks): CC BY 4.0. The site credits "Epoch AI (CC BY 4.0)". Some benchmark
  columns (HLE, ARC-AGI-2, Terminal-Bench, METR, WebDev Arena) are third-party leaderboards that Epoch compiles;
  they are labelled as external.
- **Shadeform** marketplace API: public, read without a key today. If `SHADEFORM_API_KEY` is in `.env`, it is sent
  as `X-API-KEY`.
- **Provider pricing pages** (CoreWeave, Nebius, Lambda, Together AI, Crusoe): public list prices, one read a day.
- **RunPod and vast.ai are excluded**: their terms of service do not allow this use. Do not add them.
- **SEC EDGAR, OpenDART, EDINET, TDnet, MOPS, TWSE / TPEx OpenAPI**: official public disclosures. SEC's fair-access
  rules are followed (descriptive User-Agent, at most 4 requests per second). EDINET and OpenDART need their free
  API keys.
- **Alpha Vantage**: free key, 1 calendar call a day (the free tier allows 25). **Yahoo Finance via yfinance**:
  unofficial and personal-use: earnings dates (hyperscaler_cash, about 2 requests per second) and the
  financial-statement table (financials: 3 requests per company, 0.6 s apart, backing off on HTTP 429).

## Files

- `market/common.py`: shared helpers (paths, Pacific date, SEC headers, polite GET, atomic JSON writes, ADD-only
  history with a dedup key, graph universe, show switches).
- `market/config.json`: the show switches (`dramexchange_spot`, `trendforce_press`, `shadeform`, `getdeploying`,
  `provider_list_prices`, `epoch_ai`).
- `market/history/*.jsonl`: ADD-only history. A row whose key is already there is skipped, so re-running on the
  same day adds nothing. Never hand-edit these files, except appending to `financing_manual.jsonl`.
- `market/history/corrections.jsonl`: fixes for rows a parser read wrongly, applied by `insiders.py` and
  `financing.py` when they build the web files (`market/corrections.py`; the raw rows stay as they were). Recorded so
  far (2026-10-17): Korean unit prices whose cell held two numbers or a footnote mark
  (`python -X utf8 -m market.insiders_asia --recheck-kr-prices`), per-line 10b5-1 flags and the holder of indirect
  lines for Form 4 rows (`python -X utf8 -m market.insiders_us --recheck`), and a few financing rows (Alphabet's
  two-class share offering, Supermicro's common-stock offering, series names, TSMC / ASE bond tranches, SK Hynix's
  ADR offering).
- `market/history/fx_usd.jsonl`: daily USD rates of KRW, TWD, JPY, CNY and EUR (Yahoo Finance), recorded by
  `financing_asia.py` for the filing-day conversion.
- `market/history/financing_manual.jsonl`: financing events and credit-rating actions the enrich session adds by
  hand, in the contract-3 row shape plus `"company"` (the graph node id). Lines that are not valid JSON are moved to
  `financing_manual.rejected.txt` by `run_all.py`, so the build never breaks.
- `market/ai_lab_deals.json`: curated, ADD-only log of AI-lab deals (compute, GW, contract terms), each row with
  verbatim quotes, the public `url` the site links to (the SEC filing, or the company's investor-relations events
  page for a call) and `url_or_path` (where the quote can be checked, e.g. a transcript path). The enrich session
  appends to it; `ai_labs.py` only reads it. Deals can overlap, so the site never adds their GW up.
- `market/run_log.jsonl`: one line per collector per day: `{date, collector, ok, seconds, new_rows, runs,
  error?, warning?}`. A second run on the same day updates that day's line and adds its new rows to the count.
- `market/cache/`: download caches (SEC data-set zips, Epoch zips, same-day responses). Gitignored and never
  published; deleting it only makes the next run download again.
- `web/scripts/sync-data.mjs` copies the six web files to `web/public/data/` (`npm run sync`, also run by
  `graph_build.py --sync` and before every `next build`), and mirrors the per-company folders `graph/insiders/`,
  `graph/financing/` and `graph/financials/` into `web/public/data/<feed>/` (stale company files removed). The
  mirrored files are committed with the feature that adds them, like `insiders/` and `financing/`.

## Run, rerun and backfill

From the repo root, with the project's Python:

```
python -X utf8 market/run_all.py                          # today's run (what the 22:00 routine does)
python -X utf8 market/run_all.py --only gpu_prices,ai_labs
python -X utf8 market/run_all.py --backfill                # every collector's backfill (slow: an hour or more)
python -X utf8 -m market.gpu_prices                       # one collector
python -X utf8 -m market.insiders_us --backfill           # one collector's backfill
python -X utf8 -m market.memory_prices --build-only       # rebuild a web file from history, no network
python -X utf8 -m market.financing                        # rebuild graph/financing.json only
python -X utf8 -m market.financials --only "Micron,NVIDIA" # refetch a few companies
python -X utf8 -m market.financials --build-only          # rebuild graph/financials/ from the local cache
python -X utf8 -m market.financials --filings-only --workers 8   # (re)fill the SEC / DART caches, then rebuild
```

Backfill per collector: `insiders_us` scans the last four SEC quarterly data sets; `insiders_asia` reads every
Korean company's reports and walks 365 days of EDINET lists; `financing_us` / `financing_asia` re-read the 365-day
window; `gpu_prices` records every week GetDeploying still has; `memory_prices` walks the TrendForce press list
back 365 days (DRAMeXchange history is members-only, so spot prices start on the first run); `hyperscaler_cash`
records every quarter XBRL can derive; `financials` fetches every public company (highest graph degree first, about
35 minutes, then their SEC facts, about 4 minutes, and their DART reports, about an hour with 8 workers the first
time); `ai_labs` forces a fresh download. Re-running a backfill adds no duplicates.

After a manual run, `cd web && npm run sync` copies the new files for local viewing; the nightly PR publishes them.

## Hide a source

1. Set its switch to `false` in `market/config.json`, e.g. `"dramexchange_spot": false`.
2. Rebuild the web file: `python -X utf8 -m market.memory_prices --build-only` (or wait for the nightly run).
   The source then disappears from the web file's series, tables, notes and attribution, and is listed in
   `hidden_sources`. Collection continues, so the history stays complete.
3. Publish: `cd web && npm run sync`, then commit `graph/` and `web/public/data/` (or let the nightly PR do it).
   `market/config.json` is a code file, so the nightly PR does not publish it; commit it yourself.

Switches exist for the price and AI-lab sources (`dramexchange_spot`, `trendforce_press`, `shadeform`,
`getdeploying`, `provider_list_prices`, `epoch_ai`). Insider trades, financing and cash flow come from official
public filings and have no switch.

## Transcript quality check

`utils/transcript_quality.py` scans the call-transcript folders of `transcripts/` (calls, conferences, Investing.com
and defeatbeta files; not filings or press releases) and writes `graph/transcript_quality.json`:
`{updated, scanned, flagged: [{path, label, problem, suggestion}]}`. It flags two problems:

- **condensed**: the header claims a full transcript, but the body is notes: bracketed "[Speaker — role]"
  summaries, "Q&A highlights" or "KEY FACTS" sections, mostly bullet lines, and far smaller than the same company's
  other calls.
- **no speaker labels**: a verbatim-sized call with no "Name:" lines and no name-on-its-own-line turns, or a Q&A
  section without any labels. Files whose header already says they have no speaker labels (the Taiwan
  speech-to-text files) are skipped.

The enrich session reads the list and re-fetches verbatim, speaker-labelled copies (enrich skill §10a).
