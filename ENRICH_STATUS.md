# Enrichment status board

Generated 2026-09-27 02:39 by `enrich_status.py`. Every `graph_build.py` run rebuilds it, and every enrich run ends by rebuilding it. Refresh by hand (seconds, no model tokens): `python -X utf8 enrich_status.py`

Agents: read this first and trust it. Do not re-scan pipelines or the graph to find out what is done. Full name lists: `graph/enrich_status.json` → `board`. Record what no script can know with `python -X utf8 enrich_status.py mark …` / `note …` (coordinator only, see the end of this page).

## Run next

1. **`enrich us`** — 1 fetched file(s) waiting to be enriched (1 IR release); 5 overdue for a call: Alpha and Omega Semiconductor (last 2026-02-05), Applied Digital (last 2026-04-09), Simulations Plus (last 2026-04-09), 3M (last 2026-04-21), Texas Instruments (last 2026-04-22); 6 never had a call enriched (fetch with defeatbeta, mark the ones with none): ChipMOS, MP Materials, PDF Solutions, POET Technologies, Shell, UMC
2. **`enrich edgar`** — last pulled 17 days ago, 2026-09-10 (weekly)
3. **`enrich taiwan`** — 74 fetched file(s) waiting to be enriched (74 IR release); Investing.com call sync (investing.py) last ran 9 days ago (2026-09-18) — one sync serves Taiwan, Japan, Europe and China; Taiwan Chinese-call sync (tw.py) last ran 20 days ago (2026-09-07); 4 overdue for a call: Wiwynn (last 2026-02-26), Inventec (last 2026-05-12), Gigabyte (last 2026-05-15), VPEC (last 2026-05-27)
4. **`enrich japan`** — 172 fetched file(s) waiting to be enriched (172 IR release); 1 overdue for a call: Murata (last 2026-04-30)
5. **`enrich europe`** — 32 fetched file(s) waiting to be enriched (32 IR release); 3 overdue for a call: Schneider Electric (last 2026-04-30), Legrand (last 2026-05-12), AT&S (last 2026-05-21)
6. **`enrich china`** — 31 fetched file(s) waiting to be enriched (31 IR release)
7. **`enrich intl`** — 5 fetched file(s) waiting to be enriched (5 IR release)

Shared collectors (every market command runs them first when due): IR feeds synced 2026-09-25 (342 feeds); conference listing walked 2026-09-22.
Opus verification queue: 0 label(s) waiting (runs at 5+).

## Needs a decision or setup

- Korean earnings calls: only Samsung publishes an official call script (kind.py fetches it). SK Hynix's calls exist only at third-party transcript services, SEMCO / SK Telecom have an audio replay, NAVER a gated replay, LG Innotek none; most KOSDAQ names hold no public call (their decks come through kind.py). The last calls in the graph are SK Hynix 2026-04-23, Samsung Electro-Mechanics 2026-04-30, Samsung 2026-07-30; 81 Korean companies never had one. A call pasted by the user (Transcript:<company>) is enriched as usual.

## Markets

| Market | Companies | Call current | Overdue | Never had a call | No own data | Waiting | IR feeds | Collector last ran |
|---|---|---|---|---|---|---|---|---|
| US — United States | 193 | 179 | 5 | 6 | 5 | 1 | 183 | us 2026-09-26 |
| KR — Korea | 84 | 1 | 2 | 81 | 0 | 0 | 20 | dart 2026-09-27, kind 2026-09-26 |
| TW — Taiwan | 75 | 17 | 4 | 54 | 50 | 74 | 46 | intl 2026-09-18, tw 2026-09-07 |
| JP — Japan | 66 | 10 | 1 | 55 | 40 | 172 | 59 | intl 2026-09-18 |
| EU — Europe | 28 | 12 | 3 | 13 | 11 | 32 | 21 | intl 2026-09-18 |
| CN — China / Hong Kong | 15 | 1 | 0 | 14 | 13 | 31 | 11 | intl 2026-09-18 |
| other — Other listed | 5 | 0 | 0 | 5 | 4 | 5 | 2 | intl 2026-09-18 |

`Call current` = the latest own earnings call is within the company's usual gap + 3 weeks. `No own data` = not one entry from the company's own documents yet (new nodes land here). Marked companies (no source exists) are left out of Overdue / Never.

## Details by market

### US — United States (`enrich us`)
- Overdue for a call: Alpha and Omega Semiconductor (last 2026-02-05), Applied Digital (last 2026-04-09), Simulations Plus (last 2026-04-09), 3M (last 2026-04-21), Texas Instruments (last 2026-04-22)
- Never had a call enriched: ChipMOS, MP Materials, PDF Solutions, POET Technologies, Shell, UMC
- Waiting to enrich: 1 IR release
- Known gaps, do not re-search: Bayer (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25), Relay Therapeutics (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25), Roche-Genentech (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25)

### KR — Korea (`enrich korea`)
- Overdue for a call: SK Hynix (last 2026-04-23), Samsung Electro-Mechanics (last 2026-04-30)

### TW — Taiwan (`enrich taiwan`)
- Overdue for a call: Wiwynn (last 2026-02-26), Inventec (last 2026-05-12), Gigabyte (last 2026-05-15), VPEC (last 2026-05-27)
- Never had a call enriched: ADDA, AP Memory, ASMedia, ASPEED, ASUS, AVC (Asia Vital Components), Accton Technology, All Ring Tech, Andes Technology, Auras Technology, Bizlink, C Sun Manufacturing … +42 more
- Waiting to enrich: 74 IR release

### JP — Japan (`enrich japan`)
- Overdue for a call: Murata (last 2026-04-30)
- Never had a call enriched: AGC, Accretech (Tokyo Seimitsu), Asahi Kasei, Asetek, Canon, Dai Nippon Printing, Disco Corporation, Ebara, Ferrotec, Fujifilm, Fujikura, Fujimi … +43 more
- Waiting to enrich: 172 IR release

### EU — Europe (`enrich europe`)
- Overdue for a call: Schneider Electric (last 2026-04-30), Legrand (last 2026-05-12), AT&S (last 2026-05-21)
- Never had a call enriched: ASM International, Air Liquide, Comet Holding, Inficon, LPKF Laser & Electronics, Merck KGaA, PVA TePla, Prysmian, SUSS MicroTec, Siemens Energy, Technoprobe, Umicore … +1 more
- Waiting to enrich: 32 IR release

### CN — China / Hong Kong (`enrich china`)
- Never had a call enriched: Accelink, Eoptolink, Huatian Technology, Innolight, Innoscience, JCET, Lenovo, Luxshare, Montage Technology, TFC Optical, TFME, Victory Giant Technology … +2 more
- Waiting to enrich: 31 IR release

### other — Other listed (`enrich intl`)
- Never had a call enriched: 5N Plus, AEM Holdings, Indosat, Lynas Rare Earths, UMS Integration
- Waiting to enrich: 5 IR release

## Pipelines

| Pipeline | Command | Last sync | Last enriched | Waiting | Files | In graph |
|---|---|---|---|---|---|---|
| US earnings calls | `enrich us calls` | 2026-09-26 | 2026-09-27 | 0 | 306 | 306 |
| US SEC filings | `enrich edgar` | 2026-09-10 | 2026-09-16 | 0 | 1012 | 432 |
| Korea DART filings | `enrich dart` | 2026-09-27 | 2026-09-27 | 0 | 104 | 106 |
| Taiwan / Japan / Europe calls | `enrich intl` | 2026-09-18 | 2026-09-18 | 0 | 30 | 30 |
| Taiwan Chinese 法說會 | `enrich tw` | 2026-09-07 | 2026-09-07 | 0 | 17 | 17 |
| Investor conferences | `enrich conference` | 2026-09-22 | 2026-09-27 | 0 | 105 | 105 |
| Company IR press releases | `enrich ir` | 2026-09-25 | 2026-09-27 | 315 | 843 | 196 |
| Korea IR decks (KIND) | `enrich korea` | 2026-09-26 | 2026-09-27 | 0 | 47 | 37 |
| Korea earnings-call scripts | `enrich korea` | 2026-09-26 | 2026-09-27 | 0 | 1 | 1 |
| Pasted transcripts | `Transcript:<company>` | 2026-09-25 | 2026-09-25 | 0 | 248 | 248 |

## Coordinator notes (newest first)

- 2026-09-27 00:27 US: 09-27 enrich us: AV quota hit after 9 calls; defeatbeta still 404. Carry over: Dell, ChipMOS, Simulations Plus (AV waiting), Applied Digital, 3M, Texas Instruments (overdue), MP Materials, PDF Solutions, POET, Shell, UMC (never). Air Products 09-16 release left pending: page body is JS-rendered navigation only; paste the release text by hand. av.py sync assigns the wrong fiscal quarter to June-FY companies with no prior label (AOS) - check before trusting a first-call label. EMCOR 09-17 conference: CEO turns labelled Moderator by investing.py.

## Recording what no script can know (coordinator only)

- A source that does not exist: `python -X utf8 enrich_status.py mark "<Company>" ["<Company>" …] --source call --why "<reason>" [--recheck YYYY-MM-DD]` (sources: call, dart, ir, conference, edgar; default recheck in 90 days).
- Undo: `python -X utf8 enrich_status.py unmark "<Company>" --source call`
- Where a run stopped: `python -X utf8 enrich_status.py note US "AV quota hit after 25 calls; 3 left for tomorrow"`
- A judgment for the user (an ambiguous new company, an unclear placement): `python -X utf8 enrich_status.py ask "<subject>" --question "…" [--label "<source label>"]`; after the answer: `python -X utf8 enrich_status.py resolve "<subject>" --answer "…"`
- Parallel enrich agents never write these; they put it in their report and the coordinator records it.
