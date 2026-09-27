# Enrichment status board

Generated 2026-09-26 22:29 by `enrich_status.py`. Every `graph_build.py` run rebuilds it, and every enrich run ends by rebuilding it. Refresh by hand (seconds, no model tokens): `python -X utf8 enrich_status.py`

Agents: read this first and trust it. Do not re-scan pipelines or the graph to find out what is done. Full name lists: `graph/enrich_status.json` → `board`. Record what no script can know with `python -X utf8 enrich_status.py mark …` / `note …` (coordinator only, see the end of this page).

## Run next

1. **`enrich us`** — 18 fetched file(s) waiting to be enriched (11 conference, 7 IR release); US call sync (av.py) last ran 22 days ago (2026-09-04); 4 overdue for a call: Applied Digital (last 2026-04-09), Simulations Plus (last 2026-04-09), 3M (last 2026-04-21), Texas Instruments (last 2026-04-22); 15 never had a call enriched (fetch with defeatbeta, mark the ones with none): Adeia, Alpha and Omega Semiconductor, Arteris, Bel Fuse, CEVA, ChipMOS … +9 more
2. **`enrich korea`** — 48 fetched file(s) waiting to be enriched (47 IR deck, 1 call); DART sync (dart.py) last ran 16 days ago (2026-09-10); 50 have no DART filing enriched (backfill with `dart.py fetch`): Auros Technology, Chemtronics, Cheryong Electric, DB HiTek, DI Corporation, Daewon Cable … +44 more
3. **`enrich edgar`** — last pulled 16 days ago, 2026-09-10 (weekly)
4. **`enrich taiwan`** — Investing.com call sync (investing.py) last ran 8 days ago (2026-09-18) — one sync serves Taiwan, Japan, Europe and China; Taiwan Chinese-call sync (tw.py) last ran 19 days ago (2026-09-07); 4 overdue for a call: Wiwynn (last 2026-02-26), Inventec (last 2026-05-12), Gigabyte (last 2026-05-15), VPEC (last 2026-05-27)
5. **`enrich japan`** — 1 overdue for a call: Murata (last 2026-04-30)
6. **`enrich europe`** — 3 overdue for a call: Schneider Electric (last 2026-04-30), Legrand (last 2026-05-12), AT&S (last 2026-05-21)

Shared collectors (every market command runs them first when due): IR feeds synced 2026-09-25 (342 feeds); conference listing walked 2026-09-22.
Opus verification queue: 0 label(s) waiting (runs at 5+).

## Needs a decision or setup

- Korean earnings calls: only Samsung publishes an official call script (kind.py fetches it). SK Hynix's calls exist only at third-party transcript services, SEMCO / SK Telecom have an audio replay, NAVER a gated replay, LG Innotek none; most KOSDAQ names hold no public call (their decks come through kind.py). The last calls in the graph are SK Hynix 2026-04-23, Samsung 2026-04-30, Samsung Electro-Mechanics 2026-04-30; 81 Korean companies never had one. A call pasted by the user (Transcript:<company>) is enriched as usual.

## Markets

| Market | Companies | Call current | Overdue | Never had a call | No own data | Waiting | IR feeds | Collector last ran |
|---|---|---|---|---|---|---|---|---|
| US — United States | 193 | 171 | 4 | 15 | 17 | 18 | 183 | us 2026-09-04 |
| KR — Korea | 84 | 0 | 3 | 81 | 50 | 48 | 20 | dart 2026-09-10, kind 2026-09-26 |
| TW — Taiwan | 75 | 17 | 4 | 54 | 50 | 0 | 46 | intl 2026-09-18, tw 2026-09-07 |
| JP — Japan | 65 | 10 | 1 | 54 | 39 | 0 | 59 | intl 2026-09-18 |
| EU — Europe | 28 | 12 | 3 | 13 | 11 | 0 | 21 | intl 2026-09-18 |
| CN — China / Hong Kong | 15 | 1 | 0 | 14 | 13 | 0 | 11 | intl 2026-09-18 |
| other — Other listed | 5 | 0 | 0 | 5 | 4 | 0 | 2 | intl 2026-09-18 |

`Call current` = the latest own earnings call is within the company's usual gap + 3 weeks. `No own data` = not one entry from the company's own documents yet (new nodes land here). Marked companies (no source exists) are left out of Overdue / Never.

## Details by market

### US — United States (`enrich us`)
- Overdue for a call: Applied Digital (last 2026-04-09), Simulations Plus (last 2026-04-09), 3M (last 2026-04-21), Texas Instruments (last 2026-04-22)
- Never had a call enriched: Adeia, Alpha and Omega Semiconductor, Arteris, Bel Fuse, CEVA, ChipMOS, Diodes, Lattice Semiconductor, Lightwave Logic, Littelfuse, MP Materials, PDF Solutions … +3 more
- Waiting to enrich: 11 conference, 7 IR release
- Known gaps, do not re-search: Bayer (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25), Relay Therapeutics (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25), Roche-Genentech (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25)

### KR — Korea (`enrich korea`)
- Overdue for a call: SK Hynix (last 2026-04-23), Samsung (last 2026-04-30), Samsung Electro-Mechanics (last 2026-04-30)
- No DART filing enriched: Auros Technology, Chemtronics, Cheryong Electric, DB HiTek, DI Corporation, Daewon Cable, Duksan Hi-Metal, ENF Technology, Eugene Technology, Exicon, FADU, FST … +38 more
- Waiting to enrich: 47 IR deck, 1 call

### TW — Taiwan (`enrich taiwan`)
- Overdue for a call: Wiwynn (last 2026-02-26), Inventec (last 2026-05-12), Gigabyte (last 2026-05-15), VPEC (last 2026-05-27)
- Never had a call enriched: ADDA, AP Memory, ASMedia, ASPEED, ASUS, AVC (Asia Vital Components), Accton Technology, All Ring Tech, Andes Technology, Auras Technology, Bizlink, C Sun Manufacturing … +42 more

### JP — Japan (`enrich japan`)
- Overdue for a call: Murata (last 2026-04-30)
- Never had a call enriched: AGC, Accretech (Tokyo Seimitsu), Asahi Kasei, Asetek, Canon, Dai Nippon Printing, Disco Corporation, Ebara, Ferrotec, Fujifilm, Fujikura, Fujimi … +42 more

### EU — Europe (`enrich europe`)
- Overdue for a call: Schneider Electric (last 2026-04-30), Legrand (last 2026-05-12), AT&S (last 2026-05-21)
- Never had a call enriched: ASM International, Air Liquide, Comet Holding, Inficon, LPKF Laser & Electronics, Merck KGaA, PVA TePla, Prysmian, SUSS MicroTec, Siemens Energy, Technoprobe, Umicore … +1 more

### CN — China / Hong Kong (`enrich china`)
- Never had a call enriched: Accelink, Eoptolink, Huatian Technology, Innolight, Innoscience, JCET, Lenovo, Luxshare, Montage Technology, TFC Optical, TFME, Victory Giant Technology … +2 more

### other — Other listed (`enrich intl`)
- Never had a call enriched: 5N Plus, AEM Holdings, Indosat, Lynas Rare Earths, UMS Integration

## Pipelines

| Pipeline | Command | Last sync | Last enriched | Waiting | Files | In graph |
|---|---|---|---|---|---|---|
| US earnings calls | `enrich us calls` | 2026-09-04 | 2026-09-18 | 0 | 297 | 297 |
| US SEC filings | `enrich edgar` | 2026-09-10 | 2026-09-16 | 0 | 1012 | 432 |
| Korea DART filings | `enrich dart` | 2026-09-10 | 2026-09-09 | 0 | 48 | 49 |
| Taiwan / Japan / Europe calls | `enrich intl` | 2026-09-18 | 2026-09-18 | 0 | 30 | 30 |
| Taiwan Chinese 法說會 | `enrich tw` | 2026-09-07 | 2026-09-07 | 0 | 17 | 17 |
| Investor conferences | `enrich conference` | 2026-09-22 | 2026-09-25 | 11 | 105 | 94 |
| Company IR press releases | `enrich ir` | 2026-09-25 | 2026-09-25 | 7 | 152 | 63 |
| Korea IR decks (KIND) | `enrich korea` | 2026-09-26 | - | 47 | 47 | 0 |
| Korea earnings-call scripts | `enrich korea` | 2026-09-26 | - | 1 | 1 | 0 |
| Pasted transcripts | `Transcript:<company>` | 2026-09-25 | 2026-09-25 | 0 | 248 | 248 |

## Coordinator notes (newest first)

- none yet

## Recording what no script can know (coordinator only)

- A source that does not exist: `python -X utf8 enrich_status.py mark "<Company>" ["<Company>" …] --source call --why "<reason>" [--recheck YYYY-MM-DD]` (sources: call, dart, ir, conference, edgar; default recheck in 90 days).
- Undo: `python -X utf8 enrich_status.py unmark "<Company>" --source call`
- Where a run stopped: `python -X utf8 enrich_status.py note US "AV quota hit after 25 calls; 3 left for tomorrow"`
- A judgment for the user (an ambiguous new company, an unclear placement): `python -X utf8 enrich_status.py ask "<subject>" --question "…" [--label "<source label>"]`; after the answer: `python -X utf8 enrich_status.py resolve "<subject>" --answer "…"`
- Parallel enrich agents never write these; they put it in their report and the coordinator records it.
