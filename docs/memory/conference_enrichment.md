---
name: conference-enrichment
description: "`enrich conference` pipeline (added 2026-09-10): investing.py conferences → transcripts/conferences/ → depth-rule enrich (multi-agent + verify loop) → memory; progress log of which companies/conferences were pulled and enriched"
metadata:
  type: project
---

Added 2026-09-10 at the user's request ("investing.py에 conferences 붙여봐"): `python investing.py conferences`
walks Investing.com's /news/transcripts listing pages, saves the verbatim fireside-chat part of every
"<Company> at <Conference> YYYY: …" article for ANY company in company_metadata.json (US included),
into `transcripts/conferences/`, queue rows `kind: "conference"` in investing/pending.json.
Rules live in `.claude/skills/enrich/references/conferences.md` (trigger `enrich conference`).
Run history is in `investing/conferences_state.json` → `runs[]`.

**NOTE — investing.py needs `C:/Users/calif/AppData/Local/Python/bin/python.exe`** (the bare
`python` on PATH has no `curl_cffi` and every investing.py subcommand dies on import).

**Progress log**
- 2026-09-10 — pull: 130 listing pages back to **2026-08-06**, then 403 (bot cool-off).
  **84 files saved, 2026-08-10 → 09-10, 56 companies.** Window still short of 180 days (June
  conferences: BofA, Mizuho, Nasdaq, Stifel not reached); a later run continues past page 130.
- **2026-09-16 — ALL 84 ENRICHED AND APPLIED. Queue now empty (pending 0).**
  Run shape (user asked for maximum parallelism): 20 enricher agents (companies batched, all of one
  company's conferences in one batch), then 20 adversarial verifier agents on the same batches, then
  ONE `graph_build.py --sync`. 81 patches (3 files produced none: Dell / Seagate / NVIDIA at the
  Six Five Summit — thought-leadership sessions with no supply-chain content).
  Applied: **387 quarterly_data + 37 contracts + 19 new edges**; graph 351 nodes / 1376 edges.
  `verify_graph`: of the 424 checked conference entries **294 pass, 130 unchecked, 0 fail, 0 warn**.
  New edges: X-Fab→Navitas, GlobalFoundries→onsemi, Cadence→Intel, Cisco→NVIDIA, Cisco→Supermicro,
  AMD→Cerebras, NVIDIA→Cisco, Photronics→Samsung, Photronics→TSMC, Credo→SpaceX(xAI), Credo→Oracle,
  NetApp→Google, GlobalWafers→Micron, Qualcomm→Amazon, Qualcomm→Meta, onsemi→Lite-On,
  Samsung→MaxLinear, Eaton→Powell Industries, Siemens→Powell Industries.

- **2026-09-16 (run 2) — supplement + backfill, ALL APPLIED, queue 0.** Coverage now 93 files / 89 in graph /
  4 no-data (Dell, Seagate, NVIDIA Six Five; NVIDIA SIGGRAPH). Graph 352 nodes / 1,377 edges.
  - **Backfill reality:** `investing.py conferences --since 2026-05-15` walked 285 listing pages to 05-14 and found
    only 9 new files (Equinix Barclays 09-14, KLA/Keysight/AMD Goldman 09-11, STMicro Citi 09-09, Silicon Motion
    Piper Sandler 09-15, AMD Advancing AI x2 07-23, NVIDIA SIGGRAPH 07-20). **Investing.com barely published tech
    conference transcripts before late July 2026** — June (BofA, Nasdaq, Mizuho, Bernstein) is simply not on the site.
    Don't re-walk May–July expecting more; only NEW conferences (after 09-15) will appear.
  - `investing.py get()` now retries connection resets / DNS errors (curl 6/56) like a 403 — a transient reset at
    listing page 32 had silently ended the first walk.
  - **Supplement pass:** verifier-reported omissions from run 1 → 26 `_supp` patches (Marvell Innovium $1B+, Micron
    HBM3E 30% lower power, KLA services 80% contract, AMAT +300bps GM, Nebius 22-month payback, SiTime mil-aero $100M…).
    Leads the graph already held were dropped (e.g. Dell $95B backlog / $74B were ALREADY in Q2 FY2027 — run-1
    verifiers only saw the last 10 entries per company; run-2 briefs print 25).
  - Reputable-host filter used for run 2 (major banks/brokers/exchanges + company-own events); media events
    (Six Five) are low-yield — 3 of 3 produced nothing in run 1.
  - **INCIDENT: a verifier ran `apply_patches.py --help`; the script ignored the flag and APPLIED all 36 pending
    patches mid-verification** (same thing nearly happened in run 1). Fixed: apply_patches.py now exits on any
    argument other than `--dry-run`. Recovery: verifiers audited the applied receipts read-only and the coordinator
    applied their rulings to chains/ AND receipts with a label+search-string script (2 deletions, 14 edits), so a
    re-apply can't resurrect removed text. Lesson: when agents must not write, remove the temptation — tell them
    never to run repo scripts at all, and keep `patches/` empty of anything unverified if possible.
  - Harness limit: max **20 concurrent subagents** — a 30-agent wave silently drops the overflow; launch in two waves.
  - Result: conference entries in verify_graph 502 → 346 pass / 156 unchecked / 0 fail / 0 warn.
  - User structure rulings this run: **onsemi→Lite-On edge removed** (list-named customer — no edges from example
    lists); **SK Telecom added** (cloud_infra / Neocloud in neocloud.json, 017670.KS, logo SKM from companieslogo)
    with edges Penguin Solutions→SK Telecom (Haein cluster) and NVIDIA→SK Telecom (NVIDIA 8-K 08-26 DSX partnership).
  - Open for the user: **Terafab** (named by KLA as a new customer; not a node; the graph elsewhere calls it Tesla's
    fab initiative — fold into Tesla/SpaceX or leave as text?); STMicro→SpaceX (Starlink ~90% share, satellite chips —
    edge or not?); Sanmina/Wiwynn as Helios rack partners (named in a list → left as text).

**What the verifiers caught (worth repeating on the next multi-agent run)**
- **Cross-transcript contamination** — the single most common defect: a number or phrase from one
  company's OTHER conference (or from its 8-K) pasted into this file's entry. Seen in Seagate,
  TE Connectivity, NetApp, onsemi, Flex. Always grep the string against THIS file.
- **Moderator/analyst numbers presented as management's** (Powell "Brett Cope" surname invented,
  Lam's "Samsung Foundry/Intel", Cadence "supply-constrained", Nova "2x WFE", KLA "12-hi→8-hi").
- **False novelty framing** — "disclosed for the first time" over figures already in the graph
  (Broadcom Jalapeño, Micron SCA terms, Lam WFE/packaging, Microsoft Foundry 100k customers).
- **Invented strings** — Cisco "G-series" (real: G300), Lam "drill and fill" (0 hits in the file).
- **Wrong `value` semantics** — Photronics→TSMC carried TSMC's own mask-spend estimate in `value`,
  which would have read as a multi-billion contract.
- Enrichers also paraphrased/contracted quotes ("do not" for "don't"), which breaks the verbatim
  grep in verify_graph — verifiers restored the speaker's exact wording.

**Structure ruling (user, 2026-09-16): xAI is under SpaceX** — the Credo enricher created an `xAI`
node; SpaceX already sits in `ai_models / Foundation Models`, so it was a duplicate.
`utils/merge_company.py --from "xAI" --into "SpaceX"` folded it (graph back to 351 nodes).
See [[naming_rules]] — subsidiaries fold into the parent node.

**Why:** conference talk is management speech between calls (mid-quarter guidance, new customers) and
no other pipeline carries it; user chose this over YouTube captions / GDELT (2026-09-10).
**How to apply:** never commit ([[feedback_no_auto_commit]]); patches only ([[concurrent_job_race]]);
transcript-grounded only ([[feedback_transcript_only]]).
Related: [[feedback_transcript_sourcing]], [[edgar_enrichment_2026_09_10]] (the multi-agent recipe reused).

**Queue-empty does not mean enriched (2026-09-18).** All five pending.json files read 0 while 7 transcripts
sat on disk with no graph data at all. The reliable check is to match every `# source label:` header under
transcripts/ against the graph's label set, not to read the queue files. (EDGAR is the exception: 336 of its
1,012 done files legitimately yield nothing — routine 8-Ks.)

**Investing.com fiscal years are unreliable.** `iqe_q2_2024.txt` was labelled `IQE Q2 FY2024` from the site's
auto-generated title; the transcript body header read "Full transcript - IQE PLC (IQE) H1 2026", a question
cited a 16-June-2025 RNS and management spoke of 2026/2027. Renamed to `iqe_q2_2026.txt` and relabelled
`IQE Q2 FY2026 (09-07-2026)`. Always check the body header and management's own dating.

**Conference speaker attribution.** A vendor-branded conference track can feature speakers with no company
label ("Matt, Infrastructure Expert" on Dell's Six Five track). Only company-labelled management counts —
3 of 4 Dell entries were dropped for this. Korean dual-filers post consolidated AND separate 잠정실적 the same
day; judge the `_separate` file on its own, it often has no counterpart in the graph.
