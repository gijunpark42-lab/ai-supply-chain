# `enrich waitlist` — onboard the queued new companies

`enrich_waitlist.json` (repo root) holds companies missing from the universe, found by a gap scan on 2026-09-28
(e.g. RF Materials → Lumentum). **The user pre-approved every company in it as a new node** — the litmus / "ask the
user" judgement of JOB 3 is already made; do not re-ask it. Nothing in the file is applied until this command runs.

`enrich waitlist` = every market with pending rows · `enrich waitlist <us|korea|taiwan|japan|europe|china|other>` =
one market. A row's market is its `market` field (`taxonomy.market_of(exchange)`).

## File shape
- `companies[]`: `name` (canonical English node name), `ticker`, `exchange`, `market`, `country`, `chains`,
  `supplies` (→ the player's `product`), `customers` (existing nodes the scan tied it to), `evidence` (press /
  blog URLs — pointers only, never a source label, §2), `group`, `status` (`pending` → `added` | `dropped`), and
  after the run `label` (the source that added it) / `why` (for `dropped`).
- `groups`: what each group means. `weak_evidence` / `unnamed_tenant` / `kr_early` rows had thin sourcing: add the
  node, but take edges only from what a company document states (below).
- `edges[]`: companies that ARE already nodes but are missing from a chain (Kyocera → optical packages, TFME →
  AMD packaging, …). Handle them as ordinary JOB 1/4 work on the company's next source: add the placement / edge
  when a company document supports it; mark `added` or leave `pending` with a `why`.

## Steps (coordinator), per market, under the enrich skill's common rules §0–§8
1. Read `ENRICH_STATUS.md` (§0). Take this market's `pending` rows.
2. **Identity check (script/web, cheap):** confirm each row is listed under that ticker/exchange (fill a `null`
   ticker; a `KONEX` or renamed ticker is fine) and is not an existing node under another spelling (naming rules,
   `utils/check_patch.py` collision check). Unlisted / delisted / duplicate → `status: "dropped"` + `why`, or,
   for a duplicate, move it to `edges[]`.
3. **Metadata first:** add each surviving row to `company_metadata.json` (`ticker` in that market's usual form,
   `exchange`, `country`, `status: "public"`). Every collector keys off this file, so this is what puts the new
   names into the pipelines.
4. **Collect with the market's own rules** (`references/markets.md`, the matching `enrich <market>` section):
   - **KR:** `python dart.py fetch "<Company>"` (latest periodic report; also its 공급계약 in `supply_contracts/`),
     `python kind.py sync` (IR decks), `ir_pull.py discover --company` → `sync --company`.
   - **US:** `av.py` / `utils/defeatbeta_fetch.py "<Company>" <TICKER>` for the latest call; `ir_pull.py discover`;
     `python edgar_pull.py` for the 10-K customer/supplier paragraphs when the call does not name the relationship.
   - **TW / JP / EU / CN / other:** `investing.py sync` → `pending --kind transcript --market …` (≤ 2 latest
     quarters), `tw.py` for Taiwan Chinese-language calls (add the company to its `COMPANIES` if it holds one),
     `ir_pull.py discover` → `sync --company`.
   - Nothing on any pipeline: save the company's own latest annual report / results deck / IR release by hand
     (`ir_pull.py fetch <url> --company`) — label as a company IR press release or "other company document" (§5).
     Still nothing company-issued → `status: "dropped"`, `why: "no company source (checked <date>)"`, and remove
     the metadata entry this run added (a node is never added on press evidence alone).
5. **Enrich (parallel `enricher` agents, split by company, ≤ 5 companies per agent):** the FIRST patch for each
   company adds it as a player in each of its `chains` (fixed layer slug, an existing sector, `product` =
   `supplies`, made specific) with the `new_nodes` block
   `"approved": "user pre-approved <decided> (enrich_waitlist.json, group <group>)"`. Then JOB 1–5 as usual.
   **Edges** to `customers` (or anyone else) only when a company document — this company's or the customer's —
   states the relationship (JOB 4). A scan customer no document confirms stays out of chains/; write it in the
   row as `unconfirmed_customers` so a later run can pick it up.
   An `enricher` verifier still checks each new node, but only for naming, duplicates, slugs / sector and
   `product` — not litmus.
6. `utils/check_patch.py` every patch → `python graph_build.py --sync` once → fix until 0 fail. Close the
   pipeline queues as the market command does; append labels to `verify_queue.json`.
7. **Logo** for every added node (user, 2026-10-01; SKILL.md JOB 3 step 5): parallel agents by market per
   `docs/memory/logo_fetching.md` (ticker + name identity proof, SVG preferred, contact-sheet check) write only
   `static/logos/<node>.<ext>`; the coordinator alone appends `static/logos/manifest.json`, then `npm run sync`.
8. Update `enrich_waitlist.json`: `status: "added"` + `label`, or `dropped` + `why`. Report every added node by
   name (JOB 3.4) and the waitlist count left per market; `enrich_status.py note <market>` if the run stopped
   partway (big markets — TW 39, KR 39, CN 30 — may take more than one run; newest-evidence `clear` rows first).
