### Taiwan MOPS filings — 法說會 decks, important 重大訊息, monthly revenue (`mops.py`; part of `enrich taiwan`)

Built 2026-10-01 (user: a pipeline for the Taiwanese companies' MOPS documents so an agent does not have to look each
time). Every TWSE / TPEx company files to MOPS (公開資訊觀測站): the deck of each 法人說明會, its 重大訊息 (material
information) and its monthly revenue. `mops.py` reads them for every company in `company_metadata.json` whose market
is TW (75 on 2026-10-01; TSMC and ASE are NYSE-listed in the metadata = market US and are NOT covered), saves each new
document once (by its MOPS id) to `transcripts/mops/` and queues it in `mops/pending.json`.

**Three kinds (pending row `kind`)**
| kind | What | Label (the file's `# source label:` line — take it verbatim) |
|---|---|---|
| `deck` | the presentation PDF filed for a 法說會 — the English file (`…E001.pdf`) when one is filed, else the Chinese one; the same deck re-filed for another broker event is saved once (sha256) | `<Company> IR presentation: MOPS <file id> (MM-DD-YYYY)`, dated the conference — e.g. `Quanta IR presentation: MOPS 238220260813E001 (08-13-2026)` |
| `material` | an IMPORTANT 重大訊息 (filter below), its full text | `<Company> MOPS material information: release <code>-<YYYYMMDD>-<serial> (MM-DD-YYYY)`, dated the filing day — e.g. `Gold Circuit MOPS material information: release 2368-20260929-2 (09-29-2026)` |
| `revenue` | the monthly revenue report — ONLY for companies with no `ir/feeds.json` entry (the feed companies post their revenue release there; user, 2026-10-01) | `<Company> MOPS monthly revenue: <Month YYYY> (MM-DD-YYYY)` — e.g. `Auras Technology MOPS monthly revenue: August 2026 (09-10-2026)` |

Material information subjects are Chinese, so the label carries the MOPS id instead of an English title. MOPS shows
no filing time for monthly revenue: its label is dated the day `sync` first saw it, capped at the legal deadline (the
10th of the next month).

**Which 重大訊息 are kept** (the subject decides; the full lists are `SKIP` / `KEEP` in mops.py and `skip_rules` in
`mops/sync_state.json`; every skipped id is recorded there with its reason and subject)
- Kept: customer / supply orders, contracts, partnerships, licences; capacity and capex (資本支出 / 資本預算 / 擴建 /
  建廠 / 產能 plans at any amount; single purchases of machinery, equipment or right-of-use assets at ≥ NT$1 billion;
  land / buildings / plant facility works at ≥ NT$200 million); plant incidents (fire, explosion, outage, earthquake,
  cyberattack, stoppage); financial forecasts / guidance; M&A (merger, acquisition, tender offer, JV at any amount;
  a share purchase at ≥ NT$1 billion). The amount is read from items 1-5 of the filing and converted to NT$ for the
  filter only.
- Skipped: dividends, treasury stock / buybacks, personnel and committees, board-meeting dates, financial statements
  and other routine governance, financing (bonds, convertibles, capital increases, private placements, loans,
  endorsements / guarantees, lending of funds), conference / 說明會 notices (the deck comes as its own kind), monthly
  revenue notices, media clarifications and trading-attention notices, treasury investments (funds, bonds), awards /
  ESG, subsidiary housekeeping, litigation, and intra-group capital injections or transfers (item 6 counterparty
  `母子公司`). Anything matching no KEEP rule is skipped as "not an important type".

**Overlap with the other Taiwan pipelines (nothing is saved twice)**
- `tw.py` reads the same 法說會 list but only for the CALL (video → whisper); `investing.py` holds the English calls.
  The call is the primary source; the deck adds only what the call did not state (skill §6).
- `ir_pull.py` already skips 法說會 notices by headline, so it never saves these decks. A 重大訊息 can repeat a
  company press release of the same day: the saved file then carries `# SEE ALSO: transcripts/ir/…` — enrich each
  fact once, from either file (one label per entry).
- Monthly revenue is saved only for the companies ir_pull has no feed for.
- A deck saved earlier by hand (its MOPS file id on a `SOURCE:` line under transcripts/) is skipped.

**Loop**
1. `python -X utf8 mops.py sync` — per company from 7 days before its last sync (first sync: its latest earnings call
   in the graph, capped at 120 days, else 30 days — the ir_pull rule); decks are listed up to 14 days ahead.
   `--company "<Company>"` runs one company, `--since YYYY-MM-DD` overrides the window. A deck not yet on the document
   server and revenue not yet filed are retried on the next sync. If `mopsov.twse.com.tw` is unreachable the deck step
   is reported and retried from the same start next time; material information and revenue still run.
2. `python -X utf8 mops.py pending [--company …] [--kind deck|material|revenue]` — the queue.
3. Enrich each row under the enrich skill's common rules (parallel `enricher` agents, split by company — one company's
   MOPS rows, calls and IR releases go to the same agent):
   - Company filings, NOT transcripts: facts, company guidance and targets; attribute claims; nothing inferred from a
     chart without printed numbers. Everything in English (§8): "NT$1,484 million", "THB 250 million".
   - `material`: what was acquired / ordered / decided, the counterparty when named (no new node unless JOB 3 approves),
     the stated purpose ("for future business development", "capacity expansion"), dates. Never financing terms, and
     never the price of an acquisition (§2) — the asset's own scale (area, capacity, units) is a fact; a capex budget
     amount is a capex fact.
   - `revenue`: the month's net revenue and the YoY change as filed (no arithmetic); the filed reason for a ±50% change
     is the company's own statement — attribute it.
   - Slots (`utils/check_patch.py` enforces them): `deck` and `material` = the "Company IR presentation / press
     release" row (`guidance`, `next_catalyst`, `backlog_or_b2b`, `supply_status` — never `revenue_growth`);
     `revenue` = `revenue_growth` only (like DART preliminary results; the call supersedes it).
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync` (coordinator).
5. `python -X utf8 mops.py done --label "<label>"` per handled row (`--why "no material facts"` when it gave nothing);
   `status [--company …]` shows saved / enriched / pending per company and the skip counts.

**Endpoints** (documented in the mops.py docstring; no login, no token, one request every 1.1 s): the 法說會 list
`mopsov.twse.com.tw/mops/web/ajax_t100sb02_1`; deck files from TWSE's document server
`doc.twse.com.tw/nas/STR/<file>` (the list's own download form is WAF-blocked for scripts — never POST to
`/server-java/FileDownLoad`: a WAF hit blocks mopsov for this IP for a while, which also stops `tw.py`); material
information and revenue from the MOPS web app's JSON API `mops.twse.com.tw/mops/api/t05st01`, `t05st01_detail`,
`t05st10_ifrs`.
