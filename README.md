# AI Supply Chain

A living map of the **global AI / semiconductor supply chain** as a connected graph —
every supplier, customer, and deal, extracted from earnings calls and connected.
Click any company and the whole supply web lights up.

**Live app:** [gijun42.com](https://gijun42.com) — Next.js on Vercel (see [`web/`](web/README.md)). **Current graph:**

380 companies · 1,430 directed edges · 21 product chains · 1,149 source documents
(622 earnings calls, 421 SEC filings — 10-K, 10-Q, 8-K — and 96 investor conferences, in English, Korean and Whisper-transcribed Taiwanese).
<img width="1103" height="775" alt="graph3d" src="https://github.com/user-attachments/assets/ca4d792d-44d7-4127-a542-8d390f9d2f03" />
<img width="1156" height="853" alt="nodedossieraehr" src="https://github.com/user-attachments/assets/78a18768-d8df-4aa0-bca0-aa98f827de54" />
<img width="1418" height="1375" alt="generation-transitions" src="https://github.com/user-attachments/assets/8294dacd-8fdd-4b83-a2c4-b3888e87c744" />
<img width="1418" height="1055" alt="chain-2d-view" src="https://github.com/user-attachments/assets/88eb7a7a-2473-4e2a-ae1f-f11425f88d3c" />
<img width="1418" height="1238" alt="company-screener" src="https://github.com/user-attachments/assets/19454c87-797e-49ac-bf74-11fef1aac1e3" />
<img width="1543" height="1625" alt="timelines-cpo" src="https://github.com/user-attachments/assets/e25acb5b-b8e0-4f08-92a0-9309f58affb7" />
<img width="1418" height="1055" alt="chain-2d-ripple" src="https://github.com/user-attachments/assets/64f84e0f-c3fc-4ab6-bea9-68f9bb503e7e" />



## Quant: does "sold out" move stocks? (`quant/`)

An event study on the hand-labeled **"capacity sold out"** signal across 71 US-listed earnings calls: entry at t+1 close, +5/+10/+20-trading-day windows, abnormal returns vs. SOXX/SPY/QQQ, one-sample t-tests and hit rates. Result: flagged names lagged SOXX by a mean 9.4% over the 20 trading days after the call (n=15, p=0.026, hit rate 0.13), so by the time a company says it on a call the news is already in the price relative to its peers. Code and outputs live in [`quant/`](quant/) (`event_study.py`, `results.json`).

---

## What makes it different

1. **A graph, not a layer cake.** Layers exist (memory → packaging → foundry → …),
   but every connection is a *specific directed edge* between two companies —
   AWS → Anthropic, SK Hynix → TSMC — never "layer N connects to layer N+1".
   Companies that appear in many chains merge into shared hubs (TSMC sits in 16
   chains, ASML in 15, Amkor in 14).

2. **Edges carry deals, not just lines.** An edge holds the actual contracts on the
   relationship — units, dollar values, dates — and accumulates new entries every
   quarter. Examples currently in the graph: Anthropic → AMD (up to 2 GW of MI450 in
   Helios racks), Nebius → Meta ($27B over 5 years), Vistra → Meta (nuclear PPAs),
   AXT → Coherent / Lumentum (InP long-term supply agreements).

3. **Generations are separated.** `nvda_b200` and `nvidia_vera_rubin` are different
   chains on purpose — the investment signal is the *transition delta* (HBM3E→HBM4
   content growth, copper→optical, CPO penetration, attach ratios), not a static
   snapshot.

4. **Transcript-grounded only.** Every data point carries a canonical source label
   (`NVIDIA Q1 FY2027 (05-28-2026)`) pointing at the earnings call, official IR
   document, or SEC filing it came from. No news scraping, no invented figures.
   Enrichment is ADD-only: existing nodes, edges, and history are never dropped.

## The web app (`web/`)

| Tab | What it shows |
|---|---|
| **Graph** | 3D force graph of the merged supply web — search, filter by chain/layer/domain, click for the node dossier |
| **Chain 2D** | One product chain at a time, top-down layer flow with de-spaghettied edges |
| **Generations** | The transition engine — B200→Vera Rubin, MI355→MI450, Trainium2→3, TPU v7→v8: who's retained, gained, lost |
| **Timelines** | Hand-curated thematic tables: CPO, HBM, foundry roadmaps, supply tightness, 800 VDC transition, … |
| **Screener** | One row per company: latest revenue/growth, guidance, backlog, supply status, next catalyst |
| **Capex** | Hyperscaler + neocloud money view — capex (the demand signal) and backlog/RPO/contracted revenue, with sourced bar charts |
| **Coverage** | The enrichment queue: each company's earnings calendar joined with data freshness — what to enrich next |
| **Exposure** | "Who benefits" per chain or generation transition: an explainable exposure score, customer-concentration facts, and a basket you can copy into a watchlist (TradingView symbols) |
| **Ask** | Ask the Graph in plain English — answers written only from the stored signals/contracts, every claim cited to its source label |

Every signal in the node dossier has a **source** button that shows the verbatim passage of the transcript
or filing it came from (`evidence.py` -> `graph/evidence.json`).

**Ask the Graph answers with Claude Opus on the owner's own PC by default** (`local-ask/`, see below).
An optional API fallback for when the PC is off is picked from these env vars (Vercel -> Settings ->
Environment Variables, or `web/.env` locally), first match wins:

| Variable | Service | Cost |
|---|---|---|
| `ASK_BASE_URL` + `ASK_API_KEY` | any OpenAI-compatible endpoint (OpenRouter, Mistral, a local Ollama...) | depends |
| `GROQ_API_KEY` | Groq (`llama-3.3-70b-versatile`), key from console.groq.com | free tier, no card (30 requests/min but only ~12K tokens/min, about one question a minute) |

`ASK_MODEL` overrides the default model name for whichever service is picked. Gemini and the Anthropic
API were removed on 2026-09-11 (Gemini key revoked; Claude must not be billed through the API) — Claude
answers come only from the local runner.

How a question is answered (`web/src/app/api/ask/`): a cheap model first rewrites the question into 2–4
queries in the graph's vocabulary plus an intent (`lookup` / `compare` / `rank` / `timeline`), the browser
searches the union of those queries, and the answer engine must synthesize — rank and compare the
numbers it was given, cite each as `[n]`, and say "the graph does not contain …" only when nothing
matched. Both engines share one prompt, `web/src/lib/askPrompt.mjs`.

**The default engine: Claude Code on your own PC.** `local-ask/` is a tiny server that runs
`claude -p` (Opus, max effort, no tools) for each question. Set `LOCAL_ASK_URL` (a Cloudflare Tunnel or
Tailscale Funnel address) and `ASK_SHARED_SECRET` on Vercel and the route tries it first — `/health` in
3 s, then `/answer` for up to 3 minutes — and falls back to the API key above (if any) whenever the PC is
off. The badge under each answer shows which engine replied (`claude-code-local` vs the API model id).
See `local-ask/README.md`.

## How data gets in (the enrichment loop)

`Transcript: <company>` runs a fixed six-step pipeline:

1. **Fetch** the latest full earnings transcript (Motley Fool first for US names;
   official IR / SEC 8-K as fallback) → save under `transcripts/<sector>/` with a
   source header.
2. **Enrich** every chain where the company is a node — add `quarterly_data` to
   nodes and `contracts` to edges. ADD-only; new companies/edges only when the
   transcript states them and they pass the litmus test (*"does this company's
   stock directly benefit from the product being built and sold?"*).
3. **Verify** — JSON validity plus internal consistency (segments sum to totals).
4. **Rebuild** the merged graph: `python graph_build.py` → `graph/merged_graph.json`.
5. **Timelines** — update the relevant thematic tables (replace-with-latest).
6. **Screener** — replace the company's `company_metrics.json` row with the new quarter.

Then `npm run sync` in `web/` copies everything into `web/public/data` and a push to
`main` deploys via Vercel.

## Repository layout

```
chains/               one JSON per product chain, 21 in all (accelerators / applications / components / manufacturing)
graph/                merged_graph.json — built by graph_build.py, never edited by hand
timelines/            hand-curated thematic tables (13)
reports/              per-company equity-research dossiers (44)
transcripts/          source documents, one folder per sector (1,737 files)
company_metrics.json  screener — one latest-quarter row per company
company_metadata.json tickers / exchanges / listing status (380 companies)
capex_backlog.json    hyperscaler + neocloud capex & backlog (feeds the Capex tab)
taxonomy.py           the fixed 13-layer / 4-domain vocabulary (single source of truth)
graph_build.py        merges all chains by company name into the nodes+edges graph
web/                  the Next.js app (see web/README.md; Vercel root directory = web)
```

## Working on it

- **Rebuild the graph** after touching any chain: `python graph_build.py`
- **Run the app**: `cd web && npm install && npm run dev` (the predev hook syncs data)
- **Division of labor**: humans own the chain *structure* (which companies, which
  edges); AI assistants own the repetitive transcript enrichment. Rules for
  assistants live in [`CLAUDE.md`](CLAUDE.md) — read it before changing anything.
