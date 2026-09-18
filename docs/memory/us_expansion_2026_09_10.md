---
name: us-expansion-2026-09-10
description: "2026-09-10 US coverage widening — 38 new US-listed nodes (chillers/HVAC, power gen, grid, colocation, HPC hosts, systems/storage, equipment/materials) added by 6 parallel agents via patches; utils/defeatbeta_fetch.py is the quota-free transcript fetcher for new US names"
metadata: 
  node_type: memory
  type: project
  originSessionId: 51d22f81-c322-4a97-b8f6-a369ddf7a7ea
  modified: 2026-09-10T23:35:53.760Z
---

On 2026-09-10 the user asked to widen the US-listed coverage ("칠러기업들추가하는거도좋을듯", multi-agent, no conflicts,
keep the layer/domain structure, new sector only when a node truly needs one). 38 nodes were added (351 nodes / 1,325 edges
after build), each with 7–10 quarterly_data from its own latest full call. UNCOMMITTED at the time of writing.

**Tooling that now exists:** `utils/defeatbeta_fetch.py "<Canonical Name>" <TICKER>` pulls the latest call from defeatbeta
(no quota) into `transcripts/av/` in av.py's exact header format and prints `LABEL:` / `FILE:`. It writes no shared state,
so parallel agents can each call it. Companies must first be in `company_metadata.json` (done serially by the coordinator).

**Conflict recipe that worked:** coordinator adds metadata entries → 6 agents with disjoint company sets, each writing only
`patches/<slug>_q<N>_<fy>.json` + its transcript → coordinator drops weak edges, runs `graph_build.py --sync` once, reads
verify. Rule for edges: counterparty must be NAMED by management on the call AND already be a node in that chain file
(analyst-named counterparties and "collaboration" partnerships were dropped: Air Products→Samsung, NVIDIA→Equinix).

**Skipped:** IES Holdings (holds no earnings calls), POET Technologies (not on defeatbeta) — removed from metadata again.
**New sector created:** `system_integration > Storage Systems` in nand_flash.json (Pure Storage, NetApp).
**Known verify false alarms:** numbers spelled in words ("two and a half gigawatts" → 2.5; "more than half" → >50%).
**Still open:** logos for the 38 new nodes (see [[logo-fetching]]); Carrier could also sit in Heat Exchanger / CDU (curated edit).
Related: [[project-state]], [[feedback-transcript-sourcing]], [[concurrent-job-race]].

**Follow-up 2026-09-17 (+3 US-listed names):** NXP Semiconductors (NXPI), Microchip Technology (MCHP)
and Skyworks Solutions (SWKS) were added from their latest full calls via three patches. NXP was placed in
`optical_networking` / Networking ASIC; Microchip and Skyworks in both optical Components and Power
Semiconductors. The batch added 21 quarterly-data rows and two management-named Microchip customer edges
to existing power-chain nodes Delta and Lite-On. All three labels verified with 0 fails; graph 355 / 1,402.
Alpha Vantage supplied NXP; Microchip and Skyworks used full-call fallback pages after AV had no transcript.
