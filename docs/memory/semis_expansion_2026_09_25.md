---
name: semis-expansion-2026-09-25
description: "2026-09-25 semiconductor coverage expansion — 133 new skeleton nodes (knowledge-built at the user's explicit request, then 5 Opus verifiers), YJ Semi renamed Yuanjie, first minerals layer, logos; how it was landed safely beside parallel sessions and how to revert"
metadata:
  node_type: memory
  type: project
  originSessionId: ea96297e-207a-489e-8e6c-43e20fa54cbb
  modified: 2026-09-25T09:41:45.439Z
---

On 2026-09-25 the user asked (Korean) for a list of every missing semiconductor company (e.g. LPKF), with ambiguous
ones split out for approval; then approved: my 76 "clear" + 11 recommended ambiguous + POET, YMTC, Toray + ALL of
group B4 (weak-AI semis) + all minerals (Korea Zinc, Umicore, 5N Plus, MP Materials, Lynas) + Foosung, and said
"build the skeleton from your own knowledge, verify it, multi-agent if it fits, mind the other sessions, attach logos".
It also ordered `YJ Semi` merged into **Yuanjie** (688498.SS; renamed, same node).

**What landed (uncommitted):** graph 379 -> 512 nodes, 1,591 edges. 133 companies / 134 placements across 11 chains,
146 outgoing + 16 incoming edges, all `contracts: []` and `quarterly_data: []` (skeleton only — they still need
enrichment). New sectors: foundry `Specialty / Mature-Node Foundry`, hbm `Sub-fab Equipment (Scrubbers / Chillers)`,
`Solder & Bonding Materials`, packaging `Lids & Thermal Interface (TIM)`, cpu `Server Mechanical Components`, and the
FIRST `minerals` layer (optical: Indium, Germanium; power_cooling: Rare Earths). Canonical names chosen:
UMS Integration (not UMS Holdings, renamed 2024), Nippon Sanso Holdings (4091.T parent), Unisem Co. (Korean 036200,
not Malaysian Unisem), TES (095610; a DIFFERENT company from TSE 131290), Hitachi High-Tech + Carl Zeiss SMT status
`subsidiary`. Yuanjie was NOT added separately (it was the existing `YJ Semi` node).

**Verification:** 5 enricher (Opus) verifiers on disjoint slices wrote JSON verdicts; coordinator folded them with
`build.py` + `overrides.py` (job tmp). 16 draft edges dropped as unevidenced (e.g. FADU->Meta, EV Group->Intel,
Mitsubishi Electric->Innolight, uPI->NVIDIA consumer-only, Chroma->SPIL/KYEC 403-only), 55 evidenced edges added
(filings, TSMC/Intel/Lam supplier awards, IR releases), 25 product fixes, Toray moved to mlcc (MLCC carrier film).
Some kept edges rest on trade press only (Grand Process/Victory Giant/Nepes/Air Liquide/Kinik -> customers, HPSP, UMS).
40 companies have no evidenced edge (connects_to []).

**Tension to remember:** [[feedback-transcript-only-purism]] rejected knowledge-built edges in June. This run was
an explicit user order for a knowledge-built SKELETON (Workflow 1 style, structure only, no data points), so it went
ahead — but if the user reverts it, remove the 133 players + 16 incoming edges by name (patch receipt:
`patches/applied/skeleton_semis_expansion_2026-09-25.json`); chains also carry other sessions' uncommitted work, so
never `git checkout` the chain files to revert.

**Landing recipe that worked beside 3 parallel sessions:** drafts + verdicts only in job tmp; ONE ADD-only patch via
apply_patches (no direct chains/ write); metadata appended after a re-read (byte-identical re-serialization:
indent=2, CRLF, trailing newline); pre/post snapshot of per-chain player/edge/qd/contract counts proved +0 loss;
another session's `ir_*` patches arrived mid-build and were left for its own build. Logos: 4 agents wrote only to
job tmp, coordinator rendered one light/dark contact sheet (headless Chrome) and was sole manifest writer
(indent=1, LF, trailing newline, append-only).

**Batch 2 (same day, user: "yes do it all"):** the 17 semiconductor + 12 power/thermal names left on
docs/MISSING_PUBLIC_COMPANIES_2026-09-17.md were added the same way (job tmp `semis2/`, 3 verifiers + 2 logo agents,
patch `patches/applied/skeleton_semis_expansion2_2026-09-25.json`): 29 companies, 20 + 8 incoming edges, graph 541 nodes /
1,619 edges. Names: `TSE Co.` (131290; NOT the Tokyo exchange, NOT TES), `FST` (036810 pellicles — Formosa Sumco's own logo
also says "FST", different company), `Cheryong Electric` (DART English name; the list said JeRyong), `Komico`
(MiCo 41.85%), `Tekscend Photomask` (Toppan 46.55%), `Sino-American Silicon` (GlobalWafers 46.64% parent),
`Nidec Chaun-Choung`, `VisEra` (TSMC 67%) — listed subsidiaries kept as separate nodes. Yuanjie's product fixed to
"InP laser chips (CW / DFB / EML)...". The shared WebSearch budget (200) ran out mid-run; later evidence came from DART /
MOPS / direct fetches. Surfaced, NOT changed: GlobalWafers metadata should be 6488.TWO / TPEx (is .TW / TWSE); Toppan
node's "merchant photomasks" product now overlaps Tekscend; MiCo's product text names Komico's business.
Still open: Alchip->d-Matrix edge (Alchip not in foundry.json); Doosan Tesna + B-review names from the 09-17 list not added.
Related: [[naming-rules]], [[logo-fetching]], [[concurrent-job-race]], [[graph-cleanup-2026-09-05]].
