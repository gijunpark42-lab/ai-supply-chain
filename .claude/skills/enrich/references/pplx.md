### Perplexity Finance calls — every market (`pplx.py`, 2026-10-21)

**What it is.** Perplexity Finance (perplexity.ai/finance/<SYMBOL>/earnings) shows listed companies' earnings calls
with the full transcript: every paragraph of the prepared remarks and the whole Q&A, timestamped, with the speaker's
name and the call's sections. The transcripts are made by Quartr, a call-recording vendor (each transcript links its
audio on files.quartr.com): the call **as spoken**, not a summary and not a company document. It is a CALL source,
like Alpha Vantage or Investing.com, and it comes **after** each market's own call source (user, 2026-10-20: "api
쓰는게 더 빠르면 그거 써도 되고 없으면 그 퍼플렉시티 파이낸스"; 2026-10-21: every market, "안 막히게").

**How it runs.** `pplx.py sync` runs every night in `routine/nightly.ps1` before the session (one run a day, at most
150 call lists and 30 transcripts, 40 minutes, a 4–9 s pause between requests). It drives the installed Chrome through
Playwright with its own profile (`%LOCALAPPDATA%\nodus42-pplx-profile`) because Cloudflare refuses plain HTTP clients
and anonymous Jina; inside the page it calls the site's own JSON (`/rest/finance/earnings/<SYMBOL>` and
`…/transcript/<id>`). No login, no key, no model call. A block mid-run stops it cleanly; the next night carries on.

Who it looks at: graph nodes with a listed ticker whose call is due — the board's call gaps (never had a call /
overdue) first, then non-US companies whose last call is 75+ days old; US companies only when they are a board gap
(Alpha Vantage / defeatbeta serve the rest). A call is taken only when it is 2+ days old and no other source has
it: no call label within 5 days in the graph, no row in another call queue (av / investing / tw / kind), no saved
call file for the same label. Perplexity lists a company's results dates even when no call transcript exists
(most KOSDAQ / A-share / TPEx small caps): those end as `skip:no transcript on Perplexity` and the company is looked
at again after its next results date.

**The loop (part of `enrich all` and of every market command, after the market's own calls):**
1. `python -X utf8 pplx.py pending` — the queue (`transcript` rows: company, label, file).
2. Enrich every row as a call (Workflow 2, all jobs + JOB 5 tags), reading the whole file. Same depth rule as any
   call: a filing / deck / IR release of the same quarter adds only what the call did not say.
3. Apply (graph_build through `utils/build_outside.py` in the nightly), read the verify lines.
4. `python -X utf8 pplx.py done --label "<label>"` per handled row (`done` alone clears the queue).

Other commands: `pplx.py targets` (tonight's list, no requests), `pplx.py status`, `pplx.py fetch "<Company>"` (one
company by hand: its newest call no other source has; for `Transcript:<company>` when the market source is empty).

**What to capture.** As for every call (§2): facts, guidance, management's own words. In the Q&A only the company's
answers are facts; analysts' questions are context and never an entry.

**Label.** `<Company> Q<N> FY<YYYY> (MM-DD-YYYY)` — e.g. `Prysmian Q2 FY2026 (07-30-2026)`. The date is the call's
date in the exchange's own time; the quarter follows the company's own labels in the graph (Perplexity's fiscal
period shifted by the offset seen on a call both have), else Perplexity's fiscal period. The file is
`transcripts/perplexity/<slug>_q<N>_<yyyy>.txt` with the av.py-style header (`SOURCE:` = the Perplexity URL and call
id, `CALL DATE:`, `QUARTER:`, `# source label:`), then `## Prepared Remarks` / `## Q&A` and the paragraphs, the
speaker's name at each turn.

**Gotchas.**
- Speaker titles are not in the transcript (names only): take the title from the operator's introduction or the
  company's own documents, never guess it.
- A call held in Korean / Japanese / Chinese may come as Quartr's transcript of the English interpretation line;
  attribute it to the speaker as usual. Entries in English (§8).
- A Perplexity file and another source's file for the same call never both get enriched: the collector checks, and
  if one slips through (a pasted copy), enrich the fuller one and `done --label … ` the other with `--why`.
- `pplx.py` never logs in; a call marked `requiresLogin` is skipped.
- When a whole night is `BLOCKED`, `pplx.py status` shows it; two blocked nights in a row → note it on the board
  (`enrich_status.py note pplx "…"`), never work around it by hand in the user's own Chrome during the nightly.
