---
name: ai-bio-chain
description: "chains/applications/ai_bio.json — the AI-drug-discovery chain, its layer placement, what is enriched, and which nodes have no free transcript source"
metadata: 
  node_type: memory
  type: project
  originSessionId: 04e18dca-b3a7-48ad-9506-b4dab78c625f
  modified: 2026-09-18T10:30:59.433Z
---

`chains/applications/ai_bio.json` — AI-enabled drug discovery / precision medicine / autonomous labs.
Built half-way by an earlier session on 2026-09-18, finished and pushed the same day (29 players,
108 quarterly_data, 27 edges, 20 contracts; graph 380 nodes / 1,429 edges).

**Layer placement** (the user's guess that "most names are application layer" is right):
- `application` — Biopharma End Customers (9: BMS, Lilly, Sanofi, Roche-Genentech, Vertex, Jazz,
  AstraZeneca, Bayer, Novo Nordisk), Omics Data & Biological Measurement (Illumina, Twist, 10x,
  PacBio, Nautilus), Precision Medicine & Clinical AI (Tempus AI, SOPHiA GENETICS)
- `ai_models` — AI-Native Drug Discovery (Recursion, Schrödinger, Absci, Relay, Evaxion, AbCellera),
  Model-Informed Drug Development (Certara, Simulations Plus), **Frontier AI Models (Anthropic)**
- `software_infra` Ginkgo Bioworks · `cloud_infra` Google, Amazon · `compute_hardware` NVIDIA

**Edge direction is supplier → customer.** The 9 biopharma names are terminal consumers and correctly
carry `connects_to: []`; deal detail lives on the incoming edges from the discovery platforms.

**No free transcript exists** for Relay Therapeutics (RLAY), Roche-Genentech (RHHBY) and Bayer (BAYRY) —
absent from BOTH defeatbeta and Alpha Vantage (checked 2026Q1 and 2026Q2). Those three sit at
quarterly_data 0. Roche and Bayer are European, so the route is `investing.py` (Workflow 2d), not `av.py`.

**Q2 2026 finding worth remembering:** Eli Lilly, Vertex, AstraZeneca, Novo Nordisk and Sanofi calls
contain ZERO mentions of AI/ML/computational discovery. Only Bristol Myers Squibb (named Anthropic AND
NVIDIA as AI partners) and Jazz (AbCellera T-cell engager collaboration) discuss it. Do not expect pharma
customer calls to corroborate the supplier side — the AI detail comes from the platform companies' calls.

**Proposed but NOT added** (structure is the user's call): BioNTech, Merck, GSK, Daiichi Sankyo, Incyte,
LevelSet Bio, Personalis, Simcere (2096.HK), IQVIA, Crinetics. All were named only as counterparties.

See [[project_state]], [[naming_rules]], [[generation_separation]].

**UI registration gotcha (cost a second round trip):** a new chain is invisible in the web app until its
slug is added to `CHAIN_COLORS` in `web/src/lib/taxonomy.ts` — `Sidebar.tsx` derives the whole chain filter
list from `Object.keys(CHAIN_COLORS)` and `page.tsx` seeds the default-checked set from it, so nodes
belonging only to the unregistered chain get filtered out (the header read "355 / 380 companies,
20 / 21 active chains"). `ai_bio` is `#d946ef`; a keyword rule was also added to the Ask router in
`web/src/lib/retrieval.ts`. Now documented as the last step of the chain-skeleton skill.

**Capture rule (user, 2026-09-18):** on an earnings call, **if MANAGEMENT said it and it is material to
the company, capture it; ANALYST statements are not wanted.** A number an analyst raises counts only once
management repeats or confirms it, and then it is attributed to the manager. Do NOT filter by chain theme:
my earlier prompt said "prioritise AI/ML content", and because these pharma calls contain almost none the
agents captured only a few headline financials (AstraZeneca 40%, Novo 45%, BMS 59% of management figures).
A 7-agent re-read fixed it: +141 entries, coverage now 89-100%, chain at 249 quarterly_data.
Split management from analysts by reading how questioners are introduced - usually the Operator, but on the
AstraZeneca call the CEO introduces each analyst by name and firm, and calls carry substitute analysts who
are not on any roster. Measure coverage with: management-spoken figures present in the graph / total.
