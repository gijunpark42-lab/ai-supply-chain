### Workflow 2c — US earnings calls via Alpha Vantage (`enrich us calls`; step 1 of `enrich us`)

US-listed names (NASDAQ/NYSE ticker in `company_metadata.json`, 102 companies) get their full
earnings-call transcript from Alpha Vantage instead of a hand-found Motley Fool URL. `av.py` mirrors
`dart.py`: `sync` → `pending` → enrich → `graph_build.py --sync` → `done`.

**Trigger: `enrich us calls` runs only this loop; `enrich us` runs it as step 1 of the US market command
(references/markets.md), followed by conference talks and IR releases.** The loop, for every new call:
1. `python av.py sync` — reads the earnings calendar, finds OUR companies that reported since the
   last sync, and pulls each transcript that Alpha Vantage has posted. Prints `saved` / `waiting`
   (reported, transcript not up yet — retried next sync, usually the next morning) / `skip`
   (already in `transcripts/` from the Motley Fool days) / `QUOTA` (25 requests/day spent — the
   rest carries over to tomorrow). A `waiting` call or a `QUOTA` stop: fetch it from defeatbeta —
   `python utils/defeatbeta_fetch.py "<Canonical Name>" <TICKER>` (no quota, ~1-2 day lag, same file
   format and label). Still nothing (not posted on either yet, or not covered): **Perplexity Finance** (user, 2026-10-20: "api 쓰는게 더 빠르면 ... 그거 써도 되고 없으면 그 퍼플렉시티 파이낸스 쓰면 된다 앞으로 enrich할 때도").
   Since 2026-10-21 `pplx.py` does this without a hand in the browser: the nightly `pplx.py sync` takes the US
   board gaps, and `python -X utf8 pplx.py fetch "<Canonical Name>"` fetches one company now (references/pplx.md).
   By hand only when that fails: in Chrome (Claude in Chrome) open `https://www.perplexity.ai/finance/<TICKER>`, its
   earnings / transcript view, and copy the transcript text from the page (`get_page_text` or JS). It counts only when it is the FULL verbatim
   call (prepared remarks + the whole Q&A, speaker turns), never a summary. Save it as
   `transcripts/perplexity/<company-slug>_q<N>_<yyyy>.txt` with the av.py-style header:
   `SOURCE: Perplexity Finance (copied in Chrome) <URL>`, `CALL DATE: MM-DD-YYYY`, `QUARTER: Q<N> FY<YYYY>`,
   `# source label: <Company> Q<N> FY<YYYY> (MM-DD-YYYY)`, then the transcript verbatim. It is not in the av.py queue:
   enrich it in the same run like a queued call. A Motley Fool paste (Workflow 2) is the last resort.
2. `python av.py pending` — the queue. Enrich every row (Workflow 2, all four jobs + JOB 5 tags),
   reading the whole file. Never re-enrich a file that is not in the queue.
3. `python graph_build.py --sync` (runs `verify_graph.py` on the labels just applied — read its
   `[fail]`/`[warn]` lines), then `python av.py done`.
4. Report per company: label, what was added, verify result.
If the queue is empty after `sync`, say so and stop.

File format `transcripts/av/<slug>_q<N>_<year>.txt`: `SOURCE:` / `CALL DATE:` / `QUARTER:` /
`# source label:` header (use that label verbatim), then one paragraph per speaker turn,
`Speaker (Title): text`. It is the whole call — prepared remarks and every analyst question.
The quarter in the label is the company's FISCAL quarter, derived from the company's latest label
already in the graph (+1), so labels stay consistent with history (`NVIDIA Q3 FY2027 (…)`).
Manual pull: `python av.py fetch NVDA 2027Q3 --date 2026-11-19`; `python av.py calendar` lists
upcoming calls for our companies.

