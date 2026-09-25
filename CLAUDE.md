# CLAUDE.md

This file gives Claude (and any AI coding assistant) the full context for this project.
Read it before making changes. Keep it updated as the project evolves.

---

## What this project is

An agentic system that maps the **global AI / semiconductor supply chain** as a connected
**graph** (not a flat list of layers), and enriches it with real data pulled from earnings call
transcripts, news articles, and event transcripts (e.g. GTC).

The end goal is a **web app** where the user clicks any company/product node and the whole supply
web lights up — like a multidimensional scaling map — every supplier, customer, and the actual
deals/figures connecting them. Search a company → drill deep into the web.

The builder is a transfer student learning Python through this project. Code should be
**explicit and beginner-friendly**, commented in English. Explain reasoning when introducing
new concepts. Prefer clarity over cleverness.

---

## Core philosophy (do not violate)

1. **Map preservation > hallucination avoidance.**
   The chain structure (who supplies whom, the edges, multi-layer links) is the project's real
   value and is curated by the user. When updating, NEVER drop or overwrite existing nodes, edges,
   or data. Only ADD. When in doubt, preserve.

2. **Division of labor:**
   - The **human** owns the chain STRUCTURE — which companies, which layers/sectors, which edges, multi-layer
     placement. This is domain research and is the competitive moat. AI must not silently change it.
   - The **AI** owns the repetitive enrichment — extracting deal/figure data from a transcript and
     attaching it to the right existing node or edge.

3. **Specific, not vague.**
   Never "lasers → some laser companies." Always the specific component → its real suppliers →
   the segment it feeds → the actual figure. Each company carries the SPECIFIC product it makes
   in THAT chain (e.g. Marvell → "1.6T DSP", SK Hynix → "HBM4", NVIDIA → "Vera Rubin").

4. **Only real supply-chain participants.**
   A node belongs only if it directly builds, supplies, packages, manufactures, hosts, or
   consumes the product. Exclude mere tool vendors, partners, or unrelated customers.
   Litmus test: "Does this company's stock directly benefit from {product} being built and sold?"
   If no, exclude it.

5. **Build for the web from day one.**
   Keep LOGIC (functions that do the work) separate from EXECUTION (how it's triggered).

---

## THE GRAPH MODEL (most important section)

This is NOT a layer cake where every company in layer N connects to every company in layer N+1.
Layers exist as a **top-down stack**, but every connection is a **specific directed edge** between two nodes.

Example of the difference:
- WRONG (flat layers): "cloud_infra" layer → "ai_models" layer, implying AWS+Google+Meta all feed
  OpenAI+Anthropic+xAI equally.
- RIGHT (graph): AWS → [OpenAI, Anthropic, xAI]; Google Cloud → [Gemini, Anthropic];
  Azure → [OpenAI, Anthropic]; Meta → [] (self-hosted, no outgoing edge).
  Result: the Anthropic node is a HUB with incoming edges from AWS, Google, and Azure.

### Two kinds of connection

**(1) Edges INSIDE a chain file — the `connects_to` field on each player.**
- Edges usually go up one layer (SK Hynix HBM → TSMC packaging), but **same-layer edges are
  allowed and expected** when companies genuinely connect (e.g. SK Hynix's HBM gets attached to
  TSMC's CoWoS → SK Hynix connects_to TSMC).
- Only create an edge where a REAL supply/customer relationship exists. Do not fully connect layers.
- A node with no real outgoing relationship gets `"connects_to": []`.

**(2) Edges ACROSS chain files — automatic, by company name (built later).**
- Each product has its own chain file ON PURPOSE, so that the same company appearing in many
  chains becomes a shared hub when merged. (This is why nodes are split per product — to connect
  them later, not to keep them separate forever.)
- **Generation separation (core differentiator).** "Product" means an investment-significant
  *generation*, not a vendor. Split accelerators by generation — `nvda_b200` (Blackwell) vs
  `nvidia_vera_rubin` (Rubin), and likewise MI450/Helios, Trainium2, Trainium3, TPU v7, TPU v8t/v8i.
  This is a STOCK tool: the value is the generational transition delta (HBM3E→HBM4 content growth,
  copper→optical scale-up, CPO penetration 2026→2028, attach ratio 1:2→1:4→1:8), not a static
  snapshot. **Split when a transition materially shifts content or winners** (CPO intro, HBM jump,
  packaging/foundry change). Do NOT split trivial SKUs/refreshes — those accumulate as
  `contracts`/`quarterly_data` entries on the same chain. Accuracy over volume.
- `vera_rubin.json`'s TSMC == `tpu_v6.json`'s TSMC == `b200.json`'s TSMC → one TSMC hub after merge.
- A future `graph build` step reads ALL chain files and merges by company name into one big
  nodes+edges graph. Current data is not lost; this is a one-time automated merge.

### An EDGE is an object that carries data, not just a line

An edge is not "A → B (supplies)". It holds the concrete deals/figures on that relationship,
and ACCUMULATES new entries over time as transcripts/articles are read.

```json
"connects_to": [
  {
    "company": "Anthropic",
    "relationship": "GPU compute supply",
    "contracts": [
      {
        "source": "NVIDIA Q1 FY2027 (05-28-2026)",
        "signal": "AWS expanding Anthropic's compute capacity",
        "units": "1M+ Blackwell and Rubin GPUs",
        "value": "no specific figure",
        "date_signed": "2026",
        "type": "infrastructure deployment"
      }
    ]
  }
]
```

- The skeleton creates edges with **empty `contracts: []`** (structure only).
- Transcript/article analysis ADDS entries to `contracts` (units, $ value, dates, deal type).
- This deal-level detail comes almost entirely from transcripts/news, not from the skeleton.

---

## Data model (full shape)

Each product gets its own JSON file in `chains/` (e.g. `nvidia_vera_rubin.json`).
The vocabulary (13 layers, 4 domains, colors, order) lives in **`taxonomy.py`** — the single
source of truth, imported by `app.py`, `graph_build.py`, `main.py`.

```json
{
  "company": "NVIDIA",
  "chain_focus": "Vera Rubin GPU platform",
  "flow": [
    {
      "layer": "memory",
      "sectors": [
        {
          "sector": "HBM",
          "players": [
            {
              "company": "SK Hynix",
              "product": "HBM4 stacks",
              "connects_to": [
                { "company": "TSMC", "relationship": "HBM integrated into CoWoS package", "contracts": [] }
              ],
              "quarterly_data": [
                { "quarter": "NVIDIA Q1 FY2027 (05-28-2026)", "signal": "...", "figure": "..." }
              ]
            }
          ]
        }
      ]
    },
    {
      "layer": "interconnect",
      "sectors": [
        { "sector": "Scale-up",
          "sub_sectors": [ { "sub_sector": "Co-Packaged Optics (CPO)", "players": [] } ] }
      ]
    }
  ],
  "domains": [
    { "domain": "power",
      "sectors": [ { "sector": "Power Semiconductors", "players": [] } ] }
  ]
}
```

- `flow`: ordered list of **layers** (top→bottom). Each layer has `sectors`.
- A `sector` holds EITHER `players` directly OR `sub_sectors` (each sub-sector then holds `players`).
  Use `sub_sectors` only where a sector genuinely splits (e.g. Interconnect → Scale-up/out/across/Components).
- `domains` (optional, parallel to `flow`): cross-cutting groups (power/thermal/security/edge_ai),
  same shape but keyed `domain`.
- `players`: `{company, product, connects_to, quarterly_data}` — UNCHANGED.
  - `connects_to`: outgoing edges (objects with `company`, `relationship`, `contracts[]`).
  - `quarterly_data`: node-level signals/figures about the company itself.
- A company MAY appear in more than one layer/sector if it genuinely plays multiple roles
  (e.g. Corning = optical fiber in `interconnect` AND glass-core in `advanced_packaging`). Intentional.

### Standard layers (FIXED — top → bottom; use these slugs, in this order)

```
application          # AI assistants/chatbots, agentic platforms, enterprise SaaS, AI-native vertical apps
ai_models            # foundation models (LLM/multimodal), fine-tuned models, inference serving, agent frameworks
software_infra       # ML frameworks, GPU programming/kernels, distributed training, Kubernetes, inference opt
cloud_infra          # hyperscaler cloud, neocloud (GPU-specialized), edge/distributed cloud, colocation
system_integration   # server OEM/ODM (Foxconn, Quanta, Wistron, Supermicro, Dell, Arista) — OWNER-ADDED (not in source PDF)
compute_hardware     # training/inference GPU, custom AI ASIC, dedicated accelerators, server CPU, networking ASIC
memory               # HBM, HBF, DRAM, NAND flash, LPDDR
interconnect         # Scale-up / Scale-out / Scale-across / Components (NVLink, transceivers, DSP, optics, CPO, OCS)
advanced_packaging   # CoWoS/SoIC, HBM stacking & bonding, FC-BGA substrate, glass-core substrate, TIM
foundry              # leading-edge logic, specialty/legacy, silicon photonics, compound (GaN/SiC/InP), OSAT
equipment            # litho (EUV/DUV), deposition & etch, metrology/inspection, MOCVD
materials            # silicon/SOI/InP/SiC wafers, photoresist, process gases, substrate materials
minerals             # silicon, copper, gallium, indium, germanium, hafnium, tantalum, tungsten, cobalt, lithium, rare earths
```

### Cross-cutting domains (FIXED — sit BESIDE the stack, keyed `domain`)
```
power     # generation (nuclear/gas/SMR), grid (transformer/substation), datacenter power (UPS/PDU/busbar),
          # power semiconductors (GaN/SiC/PMIC/MLCC & passives)
thermal   # air cooling, direct-to-chip liquid, immersion, two-phase, TIM, heat exchanger/CDU
security  # AI model security, AI workload cybersecurity, post-quantum crypto, optical encryption, HW root of trust
edge_ai   # autonomous vehicles, humanoid robotics, drones/UAV, edge inference chips, AR/VR, quantum/parallel compute
```
Power and thermal are real sub-chains that attach to datacenter/compute nodes via their own edges.

---

## How enrichment works (the transcript loop)

The user gives a URL (earnings call, news article, GTC-style event). The system:

1. **Fetches** the transcript → saves to `transcripts/`.
2. **Analyzes** it against a chain with these jobs (ADD-only):
   - add `quarterly_data` to existing nodes (figures about the company).
   - add `contracts` entries to existing edges (deal detail: units, value, date).
   - ADD a new company ONLY IF it passes the litmus test, with empty `contracts`/`quarterly_data`.
   - ADD a new edge ONLY IF the transcript states a real relationship (e.g. "AWS supports
     Anthropic compute") → add/extend that `connects_to` entry.
3. **Saves** the additions as a patch in `patches/`; `apply_patches.py` merges it into the chain
   (never drop existing nodes/edges/data — and never write `chains/` directly, see Workflow 2).

**Caching:** building a skeleton (Opus) is expensive → runs rarely, saved to disk. Loading is free.
Re-build only on explicit "update" command, never automatically.

**Future automation:** later, auto-fetch new transcripts on a schedule (GitHub Actions cron) so it
runs even when the computer is off. Do NOT build the scheduler until the core loop is solid.

---

## Tech stack

- **Language:** Python (beginner — explicit and commented).
- **Editor:** VS Code + Claude extension.
- **LLM:** Claude Code terminal (no API calls). Skeleton building and transcript enrichment are
  done directly by Claude in this editor. Python functions in `main.py` are kept for reference
  but no longer invoked for LLM tasks.
- **US transcripts:** `av.py` pulls the FULL call (prepared remarks + Q&A, speaker turns) from
  Alpha Vantage `EARNINGS_CALL_TRANSCRIPT` into `transcripts/av/*.txt` (needs `ALPHAVANTAGE_API_KEY`
  in `.env`, free key, 25 requests/day). See Workflow 2c. Motley Fool scraping (`main.py`) is the
  fallback for a call Alpha Vantage has not posted yet.
- **Korean filings:** `dart.py` pulls DART (opendart.fss.or.kr) periodic reports + full financial
  statements into `transcripts/dart/*.txt` (needs `DART_API_KEY` in `.env`). See Workflow 2b.
- **Storage:** JSON files (`chains/`, `transcripts/`). Migrates later to a merged nodes+edges graph,
  then a web backend.
- **Web (future):** Streamlit MVP → full frontend. Functions stay reusable so the web layer calls them.
- **Automation (future):** GitHub Actions cron.

---

## Project structure

```
earnings-ai/
├── CLAUDE.md
├── main.py                   # functions for now; split into modules later
├── av.py                     # US companies: Alpha Vantage full call transcripts → transcripts/av/*.txt (Workflow 2c)
├── av/sync_state.json        # GENERATED by `python av.py sync` — last sync + (symbol, quarter) saved + waiting list
├── av/pending.json           # GENERATED — files saved by sync, not yet enriched (`enrich us` queue)
├── investing.py              # Taiwan/Japan/Europe/HK/China: Investing.com call transcripts → transcripts/investing/*.txt (Workflow 2d)
│                             #   + `conferences`: investor-conference fireside chats for EVERY listed name → transcripts/conferences/*.txt (Workflow 2g)
├── investing/sync_state.json # GENERATED by `python investing.py sync` — article URLs already saved
├── investing/conferences_state.json # GENERATED by `python investing.py conferences` — runs[] (when, pages walked, oldest date) + every conference URL seen
├── ir_pull.py                # company IR press releases from each company's own RSS feed → transcripts/ir/*.txt (Workflow 2h, `enrich ir`)
├── ir/feeds.json             # company → IR source: RSS, HTML list page (kind page) or JSON endpoint (kind json); ir/sync_state.json + ir/pending.json GENERATED
├── verify_queue.json         # labels applied but not yet through the Opus verifier; auto-verify at 5+ (enrich skill rule 7)
├── investing/pending.json    # GENERATED — files saved by sync/conferences, not yet enriched (`enrich intl` rows = transcript, `enrich conference` rows = conference)
├── tw.py                     # Taiwan Chinese-call companies: 法說會 video → whisper transcript → transcripts/tw/*.txt (Workflow 2e)
├── tw/sync_state.json        # GENERATED by `python tw.py sync` — conferences seen + media status
├── (audio: ~/tw_audio/)      # call audio lives OUTSIDE OneDrive — see tw.py AUDIO_DIR
├── tw/pending.json           # GENERATED — transcripts written, not yet enriched (`enrich tw` queue)
├── dart.py                   # Korean companies: DART filings → transcripts/dart/*.txt (Workflow 2b)
├── dart/corp_codes.json      # GENERATED by `python dart.py corp` — stock code → DART corp_code
├── dart/sync_state.json      # GENERATED by `python dart.py sync` — last sync date + saved rcept_nos
├── dart/pending.json         # GENERATED — files saved by sync, not yet enriched (`enrich dart` queue)
├── edgar_pull.py             # US companies: SEC 8-K / 10-K / 10-Q saved WHOLE → transcripts/edgar/*.txt (Workflow 2f, completeness contract)
├── edgar/pending.json        # GENERATED by `python edgar_pull.py queue` — the `enrich edgar` queue (done.json = enriched, dropped.json = noise, STATUS.md = table)
├── utils/show_filing.py      # read a saved filing page by page (never the Read tool — exhibits are single huge lines)
├── utils/check_edgar_patch.py# pre-flight check of an edgar patch (numbers in filing, party named, no new node, locator)
├── utils/edgar_batches.py    # split the edgar queue by company for parallel enrich + verify agents
├── supply_contracts/         # Korean 공급계약 공시, one accumulating txt per company (dart.py sync)
├── apply_patches.py          # patches/*.json → chains/ — the ONLY writer of chains/ during enrichment (safe under parallel jobs)
├── patches/                  # enrichment INBOX: one ADD-only patch per transcript; applied/ holds the receipts
├── graph_build.py            # applies patches, then chains/ → graph/merged_graph.json, then calls derive.py (--sync also refreshes web/public)
├── verify_graph.py           # AUDIT (read-only): every quarterly_data/contract re-checked against its source file → graph/verification.json
├── derive.py                 # graph → Timelines / Screener / Capex views (graph/timelines.bundle.json, graph/company_metrics.json, graph/capex_backlog.json)
├── enrich_status.py          # per-PIPELINE dashboard (enrich us/edgar/dart/intl/tw/conference/manual): last sync, source date range,
│                             #   pending queue, saved-but-no-data files → graph/enrich_status.json (Coverage tab, top cards); run by graph_build.py
├── enrich_log.json           # APPEND-ONLY run record written by enrich_status.py (one row per day+pipeline when counts change) — commit it
├── timelines/                # hand-curated BASELINE tables — INPUT to derive.py, never auto-written
├── company_metrics.json      # hand-curated screener BASELINE — input, never auto-written
├── capex_backlog.json        # hand-curated capex BASELINE — input, never auto-written
├── graph/                    # GENERATED on every build (merged graph + the three derived views) — never hand-edit
│   └── hubs.txt              # full hub list; builds print only what CHANGED since the last one — cat this for all of it
├── .env                      # ANTHROPIC_API_KEY, DART_API_KEY, ALPHAVANTAGE_API_KEY (gitignored)
├── .gitignore
├── chains/                   # one JSON per product chain
│   ├── nvidia_vera_rubin.json
│   ├── google_tpu_v6(Trillium).json
│   └── ...
└── transcripts/
    ├── nvda_q1_2027.txt
    ├── av/                   # US calls written by av.py: nvidia_q3_2027.txt (header carries the source label)
    ├── investing/            # non-US calls written by investing.py: alchip_q2_2026.txt (header carries the source label)
    ├── conferences/          # fireside chats written by investing.py conferences: credo_goldmansachsconference_2026-09-10.txt (transcript part only)
    ├── tw/                   # Chinese 法說會 transcripts written by tw.py: foxconn_q2_2026.txt (verbatim whisper STT)
    └── dart/                 # Korean filings written by dart.py: skhynix_q2_2026_dart.txt (정기보고서),
                              #   sanilelectric_prelim_2026-08-07.txt (잠정실적)
```

Functions in `main.py`:
- `fetch_transcript(url, filename)` — scrape Motley Fool URL → save to `transcripts/` → return text.
- `load_transcript(filename)` — read a saved transcript.
- `build_chain_skeleton(company, chain_focus)` — Opus builds the structural skeleton INCLUDING
  `connects_to` edges (with empty `contracts: []`).
- `save_chain(chain_data, filename)` / `load_chain(filename)` — JSON read/write in `chains/`.
- `analyze_with_transcript(chain, transcript, quarter_label)` — ADD quarterly_data + edge contracts
  + new nodes/edges (ADD-only, litmus-test guarded).

Later split into: `supply_chain.py`, `analyzer.py`, `graph.py` (merge chains → nodes+edges), `main.py`.

---

## Roadmap (build order)

1. **[in progress]** Per-chain skeletons for multiple products, each WITH `connects_to` edges from
   the start. Cover many domains (memory, photonics, packaging, substrate, foundry, cloud, ai_lab).
   Human curates/corrects each (especially photonics/optical depth, which AI under-fills).
2. Transcript/article enrichment that ADDS deal detail to edges (units, $, dates) and node figures.
3. Graph build: merge all chains by company name → one nodes+edges graph (cross-file hubs).
4. Web app: clickable multidimensional map + search + drill-down (Streamlit MVP → full frontend).
5. Automation: scheduled auto-fetch (GitHub Actions).

---

## AI Workflows (Claude Code terminal — no API call needed)

These are the exact rules Claude follows when the user asks for a skeleton build or transcript
enrichment. The Python functions in `main.py` still exist for reference but are no longer called —
Claude does this work directly.

The full step-by-step procedures live in `.claude/skills/` and load ON DEMAND, so they cost no
context until the matching trigger fires. **When a trigger below fires, invoke that skill FIRST
and follow it — do not improvise the procedure from this table.**

| The user says | Invoke skill | What it does |
|---|---|---|
| "build chain skeleton for X" / "make a chain for X" | `chain-skeleton` | Workflow 1 — write a new `chains/<product>.json` with layers, sectors, players and `connects_to` edges (empty `contracts`), then `graph_build.py --sync`. |
| a URL / pasted transcript, `Transcript:<company>`, or bare `enrich` | `enrich` | Workflow 2 — the ADD-only patch format, JOB 1–5 (quarterly_data, contracts, new nodes, new edges, topics/slot/capex tags), canonical source labels, `graph_build.py --sync` + `verify_graph.py`. |
| `enrich dart` | `enrich` → `references/dart.md` | Workflow 2b — Korean names via DART (정기보고서 / 잠정실적 / 공급계약), English-only rule, read-every-line rule. |
| `enrich us` | `enrich` → `references/us.md` | Workflow 2c — US names via Alpha Vantage (`av.py sync → pending → done`). |
| `enrich intl` | `enrich` → `references/intl.md` | Workflow 2d — Taiwan/Japan/Europe/HK/China via Investing.com (`investing.py`). |
| `enrich tw` | `enrich` → `references/tw.md` | Workflow 2e — Taiwan Chinese-language 法說會 via video + whisper (`tw.py`). |
| `enrich edgar` | `enrich` → `references/edgar.md` | Workflow 2f — US names via SEC EDGAR (`edgar_pull.py` → queue → done): 8-Ks with every exhibit whole, 10-K/10-Q customer + supplier/backlog paragraphs + XBRL. COMPLETENESS CONTRACT: every filing read once to the last page (`utils/show_filing.py`), enriched files immutable (re-pull → delta only), `utils/check_edgar_patch.py` pre-flight, enricher + independent verifier, settled rulings. |
| `enrich ir` | `enrich` → `references/ir.md` | Workflow 2h — company IR press releases via each company's own RSS feed (`ir_pull.py discover / sync / pending / done`) → `transcripts/ir/`; company-issued only, never articles; facts only, demos ≠ shipping. |
| `enrich conference` | `enrich` → `references/conferences.md` | Workflow 2g — investor-conference fireside chats (all listed names, US too) via `investing.py conferences`; only what the call did not say; multi-agent enrich + verify, `graph_build.py --sync`, verification loop, memory update. |
| `ask 실행` / `ask up` / `ask 종료` / `ask down` | `ask-server` | Workflow 3 — check/restart the local Opus engine behind the live Ask tab (fixed Tailscale address). **Never run `local-ask/up.mjs`** — it overwrites `LOCAL_ASK_URL` on Vercel with a throwaway Cloudflare address. |

Nothing was dropped when these moved out of this file — each skill holds the original text verbatim.

---

## Rules for the AI assistant working in this repo

- Preserve existing nodes, edges, and data. ADD only. Never silently restructure curated chains.
- Enrichment NEVER writes to `chains/` directly — it writes a patch to `patches/` and lets
  `apply_patches.py` (via `graph_build.py`) merge it. Parallel jobs overwrite each other otherwise
  (Workflow 2 explains the lost-update problem). Skeleton builds (Workflow 1) still write `chains/` directly —
  they create a new file, so nothing to collide with.
- Build edges as SPECIFIC directed relationships (`connects_to`), not full layer-to-layer links.
  Same-layer edges allowed when real (e.g. HBM → CoWoS). No-relationship nodes get `connects_to: []`.
- Edges are objects carrying `contracts[]`; skeleton leaves contracts empty, transcripts fill them.
- Follow FIXED layer/domain slugs and the `{company, product, connects_to, quarterly_data}` player shape (nested under layer→sector).
- Apply the litmus test before adding any company.
- Tag every new `quarterly_data` / `contracts` entry with `topics` (plus `slot` / `capex` where relevant) —
  the Timelines, Screener and Capex tabs are derived from these tags (Workflow 2, JOB 5). Never hand-edit `graph/`.
- Keep new Python explicit and commented; explain new concepts to the builder.
- Don't build future phases (scheduler, graph-merge, web) until the current phase is solid.
- Return strict JSON when asked for chain data — no markdown code fences, no prose around it.

