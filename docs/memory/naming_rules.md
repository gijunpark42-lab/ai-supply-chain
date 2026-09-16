---
name: naming-rules
description: Company name conventions — must be identical across all chain files for graph merge to create shared hub nodes
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 4df4e4a9-c6f7-4bd9-99ed-01c351552f92
---

Company names MUST be spelled identically across all chain files. Different spellings create separate nodes in the merged graph instead of a shared hub — this breaks the entire cross-chain connectivity.

**Why:** graph_build.py merges nodes by exact company name string match. "AWS" ≠ "Amazon Web Services" = two separate nodes.

**How to apply:** After every Opus skeleton build, scan for these known problem patterns and fix with replace_all before running graph_build.py.

## Canonical names (use these, not variants)

| Use this | NOT this |
|----------|----------|
| `Amazon` (since 2026-08-27; was `Amazon Web Services` — renamed repo-wide 2026-08-27 on user request "change aws to amazon, name and brand logo": 101 literal replacements over chains/company_metadata/company_metrics/quant/capex_backlog/reports + source labels `Amazon Web Services Q1 FY2026 (...)`→`Amazon Q1 FY2026 (...)`; utils/fix_names.py's map was updated to point at the new name, not used to do it) | `AWS`, `AWS Annapurna`, `Amazon Web Services` |
| `Everpure` (since 2026-09-10; was `Pure Storage`: the company renamed itself Everpure, Inc., NYSE ticker PSTG -> P; its own calls already open with "Welcome to Everpure") | `Pure Storage`, `Pure` |
| `Cipher Digital` (since 2026-09-10; was `Cipher Mining`: renamed Cipher Digital Inc., Nasdaq CIFR unchanged) | `Cipher Mining` |
| `Microsoft` | `Microsoft Azure`, `Azure` |
| `Google` | `Google Cloud`, `Google LLC` |
| `Meta` | `Meta AI`, `Meta Platforms` |
| `Samsung` | `Samsung Electronics`, `Samsung Memory`, `Samsung SSD` |
| `Dell` | `Dell Technologies`, `Dell EMC` |
| `Arista` | `Arista Networks` |
| `Ajinomoto Fine-Techno` | `Ajinomoto`, `Sumitomo Bakelite / Ajinomoto` |
| `Amkor Technology` | `Amkor` |
| `Resonac (Showa Denko)` | `Resonac`, `Showa Denko` |

## Rules for ai_lab tier

Only real AI model companies. NOT product names or divisions:
- ✅ `Meta` (not `Meta AI` — that's a product)
- ✅ `Google DeepMind` (separate entity from Google)
- ✅ `xAI`, `OpenAI`, `Anthropic`

## Rules for sub-brands and divisions

Vertically integrated companies (Samsung, SK Hynix, Micron, NVIDIA, Intel) appear in multiple tiers — that is correct and intentional per CLAUDE.md. Do NOT create fake sub-entities like "Samsung Memory SSD" or "Intel Assembly/Test (ATM)". Collapse to parent company.

## Corporate spin-offs to know

- **Sandisk** (SNDK, NASDAQ) — WD spun off its NAND/flash business in early 2025. WD kept HDDs. Use "Sandisk" in NAND chain, NOT "Western Digital".
- **Intel Foundry** — Intel's foundry services arm (separate from Intel the CPU brand but same ticker INTC). Both "Intel" and "Intel Foundry" are valid as separate nodes when they play different roles.
- **Samsung Foundry** — MERGED INTO `Samsung` on 2026-09-12 (user request; both are 005930.KS). Do NOT create a "Samsung Foundry" node again — foundry-role players and edge targets are `Samsung`. Source labels like "Samsung Foundry Q2 FY2026 (…)" may still exist on the Samsung node; leave them (verify_graph maps them to the shared filing). Tool: `utils/merge_company.py --from X --into Y`.
- **xAI** — MERGED INTO `SpaceX` on 2026-09-16 (user: "xai는 spacex 산하임" — xAI is a SpaceX subsidiary; SpaceX already sits in `ai_models / Foundation Models`). Do NOT create an "xAI" node — customer/lab-role players and edge targets are `SpaceX` (e.g. Credo→SpaceX for the Memphis AEC cluster). Mention "xAI" inside signal text only when the speaker said it.

## How to rename a node in this repo (done 2026-09-10 for Everpure and Cipher Digital; verified)

A rename is a structural edit, so it is a direct write, not a patch. Touch ALL of these or something breaks:
1. `chains/*.json`: the player's `"company"` field AND every source label prefix (`"Old Q4 FY2026 (...)"` ->
   `"New Q4 FY2026 (...)"`). derive.py only treats a label as the company's own when it starts with
   `<node id> + " "`, and av.py/investing.py re-pull a company whose label prefix differs from its node name.
   Audit: HEAD text with the same replacements applied must equal the working copy byte-for-byte.
2. `company_metadata.json`: rename the key in place (keep position) and fix ticker/exchange.
3. `transcripts/<source>/<slug>_q<N>_<year>.txt`: change ONLY the `# source label:` header line and rename the
   file to the new slug (verify_graph resolves a label by that header first, then by filename; the call text
   stays verbatim). Only derived files (graph/evidence.json) reference transcript filenames.
4. Other companies' `reports/*.json` that name the company (competitor entries / sentences).
5. `static/logos/manifest.json` key + file name, rename the file, and DELETE the old file from
   `web/public/logos` afterwards: sync-data.mjs copies but never prunes.
6. `utils/fix_names.py` RENAMES map gets `"Old": "New"` (manual tool, nothing imports it).
7. EDGAR pipeline files, if the company has filings: each `transcripts/edgar/<TICKER>_*.txt` header
   (`# Old (TICKER) ...` and `# source label: Old 8-K (...)`) plus the rows in `edgar/pending.json`,
   `edgar/dropped.json`, `edgar/STATUS.md`. Edit company + label of those rows only. Do NOT rerun
   `edgar_pull.py queue`: it re-judges every filing's relevance against the NEW graph names and can move rows.
   These files are written with Path.write_text, so they are CRLF: compare/write with that line ending.
   Check that edgar_pull.py is not running first.
8. `python3 graph_build.py --sync`, then `verify_graph.py --label "<new label>"` must give the same verdicts
   as `--label "<old label>"` did before the rename (with --label it does not overwrite graph/verification.json).
No patch in `patches/` (the inbox) may still carry the old name, or apply_patches.py (exact-name matching,
no aliases) will recreate the old node.

What actually happened on 2026-09-10: right after the graph rebuild, the EDGAR pipeline rebuilt its own
queue (`edgar_pull.py queue`, 18:29), which recomputed each row's company from the NEW graph, so the
Cipher rows became `Cipher Digital` by themselves (no split-node risk). Their labels come from the filing
headers, so the 6 CIFR headers and queue labels still read `Cipher Mining 8-K (...)`. They were left
alone because another session was working that queue. Header label == queue label keeps verify passing;
change both together (then rebuild the queue) only when the pipeline is idle, and afterwards run the
label-prefix scan from common_fixes. Never change only the headers: the queue label would stop resolving.
