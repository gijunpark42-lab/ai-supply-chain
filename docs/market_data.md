# Daily market data (added 2026-10-17)

Free data that scripts record every day, with no model tokens, shown on nodus42.com next to the supply-chain map.
It is **not** a supply-chain signal: nothing here is written to `quarterly_data`, `chains/`, `patches/` or
`derive.py`. Each dataset has its own history files, its own web file and its own section on the site (the
**Markets** tab, the **Capex** tab table, and the company panel's Cash flow / AI lab / Financing / Insider trades
sections). Every row carries its source name and a link.

## Schedule

`routine/nightly.ps1` (Windows Task Scheduler, every night at 23:00 Pacific) does this in order:

1. `python -X utf8 market/run_all.py`: every collector below, in a fixed order, at most 45 minutes. One line per
   collector per day goes to `market/run_log.jsonl`, and the summary line goes to `.claude/nightly.log`. The full
   output is in `.claude/market_data.log` and `.claude/market_data.err.log`. `financing_us` runs last but one (only
   the financing build follows), and it stops after 5 SEC filers fail in a row, so a slow or blocking SEC cannot use
   up the 45 minutes of the other collectors. Before the first collector, a history file whose last line was cut
   off by a killed run gets that line moved to `<dataset>.rejected.txt` (kept), so every later night still reads it.
2. `python -X utf8 utils/transcript_quality.py` writes `graph/transcript_quality.json` (see the end of this page).
3. The nightly enrich session. It also appends hand-found AI-lab deals and financing events (enrich skill §10).
4. Publishing. When the session finishes as done, the script commits the data paths (`market/history`,
   `market/run_log.jsonl`, `market/ai_lab_deals.json`, `graph`, `web/public`) on a branch, opens a PR and merges it.
   Vercel then deploys the site.

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
| `insiders_us.py` | `insiders.json` | `insiders_us.jsonl` | SEC Form 4: quarterly insider-transaction data sets (backfill) plus the EDGAR daily index (daily) |
| `insiders_asia.py` | `insiders.json` | `insiders_kr.jsonl`, `insiders_tw.jsonl`, `insiders_jp.jsonl` | Korea: OpenDART executive / 10% holder and 5% holder reports. Taiwan: TWSE and TPEx OpenAPI insider pre-sale declarations. Japan: EDINET large-shareholding reports (350 / 360) |
| `insiders.py` | `insiders.json` | reads every `insiders_*.jsonl` | builder only, no network |
| `financing_us.py` | `financing.json` | `financing_us.jsonl` | SEC EDGAR 8-K (items 1.01 / 2.03 / 3.02), 424B2 / 424B3 / 424B5, 6-K |
| `financing_asia.py` | `financing.json` | `financing_kr.jsonl`, `financing_tw.jsonl`, `financing_jp.jsonl` | Korea: OpenDART major-issues reports and debt registrations. Taiwan: MOPS material information. Japan: TDnet timely disclosures |
| `financing.py` | `financing.json` | reads every `financing_*.jsonl`, including `financing_manual.jsonl` | builder only, no network |
| `hyperscaler_cash.py` | `hyperscaler_cash.json` | `hyperscaler_cash.jsonl`, `earnings_calendar.jsonl` | SEC XBRL companyconcept API (capex, operating cash flow, finance-lease principal); Alpha Vantage EARNINGS_CALENDAR (1 call a day); Yahoo Finance via yfinance; the companies' own IR event pages |
| `ai_labs.py` | `ai_labs.json` | `ai_lab_revenue.jsonl`, `ai_lab_funding.jsonl`, `ai_lab_compute.jsonl`, `ai_model_scores.jsonl` | Epoch AI "Data on AI companies" and "Benchmarking Hub" downloads; the curated deals log `market/ai_lab_deals.json` |

What each web file holds:

- **memory_prices.json / gpu_prices.json** (contract 1): daily price series, the latest value and its change, and
  tables (latest session, provider list prices, TrendForce releases). Spot boxes say when the page itself was last
  updated; the site shows each series' own latest date.
- **insiders.json** (contract 2): insider trades of the last 365 days per company, newest first; type is buy,
  sell, option_exercise, tax_withholding, grant, gift or other. Lines of one filing that are one trade split by
  fill price are merged per holder (an indirect holder is named in brackets, e.g. "(By Trust for Child 1)"); the
  history keeps every raw line. For the site only: a price more than 20x away from the company's other trades of
  the same weeks (a typo in the filing) is shown without price and value; an amendment (4/A, or a later Korean
  report of the same line) replaces the trade it restates; one block trade filed by two related persons (same day,
  shares, price and holding after) is one row with both names; grants and gifts have no value. The 10b5-1 flag is
  per line: when a footnote names the plan, only the lines that point at it are plan trades.
- **financing.json** (contract 3): debt, convertible, equity, credit-facility, ABS, lease-financing and rating
  events of the last 365 days, newest first. The same deal filed twice (a prospectus and its closing 8-K) is shown
  once; two prospectuses, two series / issue numbers, or an ATM program next to another deal are never merged. A
  repayment, redemption or buyback (money going out) is type `other` with no `amount_usd`, and a board approval of a
  program has no `amount_usd` (its issues are their own rows). Korean, Taiwanese and Japanese amounts are converted
  at the filing day's rate (`market/history/fx_usd.jsonl`), like the US rows.
- **hyperscaler_cash.json** (contract 4): the last quarters of capex, operating cash flow, free cash flow and FCF
  after finance-lease principal for Microsoft, Google, Amazon, Meta, Oracle, CoreWeave, Nebius and IREN, plus the
  next 60 days of earnings dates for every public company in the graph (confirmed = the company's IR page, or
  Alpha Vantage and Yahoo agree).
- **ai_labs.json** (contract 5): AI-lab revenue run rates, funding rounds, compute deals, and frontier models'
  benchmark scores.

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
  unofficial and personal-use; only earnings dates are read, paced at about 2 per second.

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
  `graph_build.py --sync` and before every `next build`).

## Run, rerun and backfill

From the repo root, with the project's Python:

```
python -X utf8 market/run_all.py                          # today's run (what the nightly routine does)
python -X utf8 market/run_all.py --only gpu_prices,ai_labs
python -X utf8 market/run_all.py --backfill                # every collector's backfill (slow: an hour or more)
python -X utf8 -m market.gpu_prices                       # one collector
python -X utf8 -m market.insiders_us --backfill           # one collector's backfill
python -X utf8 -m market.memory_prices --build-only       # rebuild a web file from history, no network
python -X utf8 -m market.financing                        # rebuild graph/financing.json only
```

Backfill per collector: `insiders_us` scans the last four SEC quarterly data sets; `insiders_asia` reads every
Korean company's reports and walks 365 days of EDINET lists; `financing_us` / `financing_asia` re-read the 365-day
window; `gpu_prices` records every week GetDeploying still has; `memory_prices` walks the TrendForce press list
back 365 days (DRAMeXchange history is members-only, so spot prices start on the first run); `hyperscaler_cash`
records every quarter XBRL can derive; `ai_labs` forces a fresh download. Re-running a backfill adds no duplicates.

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
