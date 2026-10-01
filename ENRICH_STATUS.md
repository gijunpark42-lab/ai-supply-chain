# Enrichment status board

Generated 2026-10-01 01:58 by `enrich_status.py`. Every `graph_build.py` run rebuilds it, and every enrich run ends by rebuilding it. Refresh by hand (seconds, no model tokens): `python -X utf8 enrich_status.py`

Agents: read this first and trust it. Do not re-scan pipelines or the graph to find out what is done. Full name lists: `graph/enrich_status.json` → `board`. Record what no script can know with `python -X utf8 enrich_status.py mark …` / `note …` (coordinator only, see the end of this page).

## Run next

1. **`Opus verifier over verify_queue.json`** — 140 applied labels are waiting for the independent check (rule: at 5+)
2. **`enrich us`** — 4 overdue for a call: Applied Digital (last 2026-04-09), Simulations Plus (last 2026-04-09), 3M (last 2026-04-21), Texas Instruments (last 2026-04-22); 4 never had a call enriched (fetch with defeatbeta, mark the ones with none): ChipMOS, PDF Solutions, POET Technologies, Shell
3. **`enrich edgar`** — 175 filings queued
4. **`enrich taiwan`** — 1 fetched file(s) waiting to be enriched (1 IR release); Taiwan Chinese-call sync (tw.py) last ran 24 days ago (2026-09-07); 4 overdue for a call: Wiwynn (last 2026-02-26), Inventec (last 2026-05-12), Gigabyte (last 2026-05-15), VPEC (last 2026-05-27)
5. **`enrich japan`** — 2 fetched file(s) waiting to be enriched (1 call, 1 IR release); 1 overdue for a call: Murata (last 2026-04-30)
6. **`enrich europe`** — 3 overdue for a call: Schneider Electric (last 2026-04-30), Legrand (last 2026-05-12), AT&S (last 2026-05-21)
7. **`enrich china`** — 1 fetched file(s) waiting to be enriched (1 call)

Shared collectors (every market command runs them first when due): IR feeds synced 2026-09-30 (342 feeds); conference listing walked 2026-09-30.
Opus verification queue: 140 label(s) waiting (runs at 5+).

## Needs a decision or setup

- **Question for the user — UMC:** UMC's Q2 FY2026 call reports its own silicon photonics (12-inch photonics IC in mass production, TFLN modulators, CPO parts) and advanced packaging (interposers, hybrid bonding, DTC; 10+ customers). UMC sits only in foundry.json. Add placements in optical_networking.json (interconnect/Components, like GlobalFoundries) and packaging_substrate.json? All facts are on the foundry node meanwhile. — source: UMC Q2 FY2026 (07-29-2026) (asked 2026-09-29; answer, then `enrich_status.py resolve "UMC" --answer "…"`)
- **Question for the user — TSMC:** TSMC-Sony Kumamoto JV release (08-11-2026, smartphone image-sensor fab, volume production 2029): the Opus verifier DELETED the entry under the out-of-chain-segment rule (2026-09-27). Keep it deleted, or should a TSMC fab/capex commitment count even when the product is outside the AI chain? — source: TSMC press release: Sony Semiconductor Solutions and TSMC Agreed to Establish (08-11-2026) (asked 2026-09-29; answer, then `enrich_status.py resolve "TSMC" --answer "…"`)
- **Question for the user — TTM Technologies:** TTM Epiq release (08-17-2026): the Opus verifier REMOVED the A&D capex (>$130M Syracuse, >$400M US plants through 2029) under the out-of-chain rule and kept only the $50M Eau Claire center (serves commercial + defense). Should out-of-chain-segment capex be dropped like orders, and does Eau Claire count? — source: TTM Technologies press release: TTM Technologies, Inc. Continues Global Growth Strategy (08-17-2026) (asked 2026-09-29; answer, then `enrich_status.py resolve "TTM Technologies" --answer "…"`)
- **Question for the user — Vultr:** HPE's 09-30 release names Vultr (private, 'largest privately-held cloud infrastructure company') as buyer of HPE's first AMD Helios order ($1.2B, US data centers). Add Vultr as a neocloud node (neocloud.json, cloud_infra / Neocloud (GPU-specialized)) like the private Fluidstack / Lambda nodes, plus an HPE -> Vultr edge? Meanwhile the order sits on HPE's Helios node with counterparty Vultr. — source: HPE press release: HPE secures its first AMD Helios order in $1.2 billion deal (09-30-2026) (asked 2026-09-30; answer, then `enrich_status.py resolve "Vultr" --answer "…"`)
- **Question for the user — Cognition:** CoreWeave's 09-30 release names Cognition (private, maker of Devin) as the first production customer of CoreWeave's Vera Rubin NVL72; it already appears as a customer in earlier entries. Add as a node (ai_models), or keep as counterparty only? Same question for Blackfuel (private inference platform, Digital Realty BCN1, 09-30 release). — source: CoreWeave press release: CoreWeave Delivers NVIDIA Vera Rubin NVL72 Performance at (09-30-2026) (asked 2026-09-30; answer, then `enrich_status.py resolve "Cognition" --answer "…"`)
- **Question for the user — Toppan:** Broadcom's 09-29 release (AST JV, Singapore FC-BGA substrate plant) says Broadcom is TOPPAN Holdings' largest FC-BGA substrate customer. Toppan sits only in foundry.json (materials / Photomask), and its product text describes the photomask business now spun out as Tekscend. Add a Toppan placement in packaging_substrate.json (advanced_packaging / FC-BGA Substrate) with a Toppan -> Broadcom edge? And should the photomask node be renamed/split to Tekscend? Meanwhile the fact is on Broadcom's node with counterparty TOPPAN Holdings. — source: Broadcom press release: AST Completes Singapore's First High-End FC-BGA Substrate (09-29-2026) (asked 2026-09-30; answer, then `enrich_status.py resolve "Toppan" --answer "…"`)
- **Question for the user — Pharma decision dates:** ai_bio pharma rule captures only FDA/EC approvals and CHMP positive opinions. Should a stated FDA decision date (PDUFA, e.g. Roche giredestrant 30 Nov / 18 Dec 2026; Novo CagriSema decision expected Q4 2026) or a commercial launch (Novo Wegovy pill launched in US/UAE/UK/Germany) count as next_catalyst on pharma nodes? Tonight they yielded nothing. — source: Roche-Genentech press release: Roche's giredestrant combination significantly improved (10-01-2026) (asked 2026-09-30; answer, then `enrich_status.py resolve "Pharma decision dates" --answer "…"`)
- **Question for the user — 10x Genomics:** 10x Genomics' Sentira release (09-29) says it is 'collaborating with NVIDIA': NVIDIA accelerated computing runs Atera on-instrument processing and Sentira analysis, rapids-singlecell integrated. Make it an NVIDIA -> 10x Genomics edge in ai_bio (like NVIDIA -> Simulations Plus), or keep it as a counterparty entry on 10x (current)? — source: 10x Genomics press release: 10x Genomics Announces Sentira, a New Computational (09-29-2026) (asked 2026-09-30; answer, then `enrich_status.py resolve "10x Genomics" --answer "…"`)
- **Question for the user — NetApp:** NetApp INSIGHT releases (09-29): (1) Novus' first, orderable release runs on 'qualified Supermicro servers' — collaboration wording, both are players in nand_flash.json: add a Supermicro -> NetApp edge? (2) Oracle OCI NetApp Storage Service — Oracle is not a player in nand_flash.json, so no NetApp -> Oracle edge (NetApp has edges to Amazon/Microsoft/Google for the same service type). Add Oracle there? Both facts are on NetApp's node with counterparty keys meanwhile. — source: NetApp press release: NetApp and Supermicro Collaborate to Power AI at Any Scale (09-29-2026) (asked 2026-10-01; answer, then `enrich_status.py resolve "NetApp" --answer "…"`)
- **Question for the user — Trane Technologies:** Trane's 09-30 release: lab proof-of-concept of an 800-volt DC chiller with Eaton and Danfoss — skipped under 'demos never count'. It is a direct 800 V DC data-center transition signal. Record such power/thermal proof-of-concepts as attributed 'demonstration' entries with no slot, or keep excluding them? — source: Trane Technologies press release: Trane Technologies Demonstrates Industry-First 800-Volt (09-30-2026) (asked 2026-10-01; answer, then `enrich_status.py resolve "Trane Technologies" --answer "…"`)
- **Question for the user — Synopsys:** Synopsys investor day (09-30): new Synopsys -> Amazon ($1B+ multi-year IP deal, Amazon = lead application-optimized IP customer) and Synopsys -> OpenAI (EDA licence) edges were placed in nvidia_vera_rubin.json, Synopsys' company-wide placement. Should Synopsys get a placement in aws_trainium3 / cpu_datacenter so the Amazon custom-silicon IP edge sits nearer Trainium/Graviton? — source: Synopsys press release: Synopsys and Amazon Announce Strategic, Multi-year IP (09-30-2026) (asked 2026-10-01; answer, then `enrich_status.py resolve "Synopsys" --answer "…"`)
- **Question for the user — Private customers as nodes (2026-10-01 run):** Several releases name private/unlisted companies in a stated supply or customer role; all are kept as counterparty keys on the filer's node for now. Add any as nodes? Mobilint and HyperAccel (Korean AI chip startups, SemiFive design customers), UTAC (private OSAT, Hanmi equipment buyer), FPT Corp (HOSE: FPT, AI factory on ASUS servers - listed), Shinwa Controls (Wiwynn liquid-cooling partner), SolarEdge (NASDAQ, Infineon SiC SSCB/SST collaboration - listed). (asked 2026-10-01; answer, then `enrich_status.py resolve "Private customers as nodes (2026-10-01 run)" --answer "…"`)
- **Question for the user — HDD media placement:** Resonac (hard-disk media capacity in Singapore 160M -> 230M disks/yr from 2029) and JX Advanced Metals (HDD magnetic sputtering targets 1.5x by mid-2029) only have foundry/packaging nodes, so both HDD releases yielded nothing. Give them a materials placement under nand_flash.json 'Nearline HDD'? (asked 2026-10-01; answer, then `enrich_status.py resolve "HDD media placement" --answer "…"`)
- **Question for the user — Granopt Faraday rotators:** Granopt (Sumitomo Metal Mining 51% / Mitsubishi Gas Chemical 49%) triples Faraday-rotator capacity for optical communications by FY2027. The Opus verifier deleted it from SMM's mlcc node as out of segment, so it is now not in the graph. Give SMM (or Granopt) an optical_networking placement so it can be recorded? (asked 2026-10-01; answer, then `enrich_status.py resolve "Granopt Faraday rotators" --answer "…"`)
- **Question for the user — Wiwynn -> Amazon edge:** Wiwynn 09-10 release: it manufactures and integrates server systems and racks for Amazon (Annapurna custom hardware). New edge placed in nvda_b200.json where Amazon is a player. Keep there, or add Wiwynn to an aws_trainium chain and move it? (asked 2026-10-01; answer, then `enrich_status.py resolve "Wiwynn -> Amazon edge" --answer "…"`)
- **Question for the user — Operating facts inside award releases:** Award releases sometimes restate operating facts: Schneider WEF Lighthouse (El Paso on-time delivery 61% -> 97%, USD 43M backorders cleared amid data-center demand); Lenovo TIME/Fast Company (AI revenue 33-35% of group). Rule says awards yield nothing. Keep operating facts from award releases the way they are kept from financing releases? (asked 2026-10-01; answer, then `enrich_status.py resolve "Operating facts inside award releases" --answer "…"`)
- Korean earnings calls: only Samsung publishes an official call script (kind.py fetches it). SK Hynix's calls exist only at third-party transcript services, SEMCO / SK Telecom have an audio replay, NAVER a gated replay, LG Innotek none; most KOSDAQ names hold no public call (their decks come through kind.py). The last calls in the graph are SK Hynix 2026-04-23, Samsung Electro-Mechanics 2026-04-30, Samsung 2026-07-30; 81 Korean companies never had one. A call pasted by the user (Transcript:<company>) is enriched as usual.

## Markets

| Market | Companies | Call current | Overdue | Never had a call | No own data | Waiting | IR feeds | Collector last ran |
|---|---|---|---|---|---|---|---|---|
| US — United States | 193 | 182 | 4 | 4 | 2 | 0 | 183 | us 2026-09-30 |
| KR — Korea | 84 | 1 | 2 | 81 | 0 | 0 | 20 | dart 2026-10-01, kind 2026-10-01 |
| TW — Taiwan | 75 | 22 | 4 | 49 | 40 | 1 | 46 | intl 2026-10-01, tw 2026-09-07 |
| JP — Japan | 66 | 10 | 1 | 55 | 32 | 2 | 59 | intl 2026-10-01 |
| EU — Europe | 28 | 16 | 3 | 9 | 6 | 0 | 21 | intl 2026-10-01 |
| CN — China / Hong Kong | 15 | 1 | 0 | 14 | 10 | 1 | 11 | intl 2026-10-01 |
| other — Other listed | 5 | 1 | 0 | 4 | 4 | 0 | 2 | intl 2026-10-01 |

`Call current` = the latest own earnings call is within the company's usual gap + 3 weeks. `No own data` = not one entry from the company's own documents yet (new nodes land here). Marked companies (no source exists) are left out of Overdue / Never.

## Details by market

### US — United States (`enrich us`)
- Overdue for a call: Applied Digital (last 2026-04-09), Simulations Plus (last 2026-04-09), 3M (last 2026-04-21), Texas Instruments (last 2026-04-22)
- Never had a call enriched: ChipMOS, PDF Solutions, POET Technologies, Shell
- Known gaps, do not re-search: Bayer (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25), Relay Therapeutics (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25), Roche-Genentech (call: no free transcript source (AI-bio chain check, recorded 2026-09-18); recheck 2026-12-25)

### KR — Korea (`enrich korea`)
- Overdue for a call: SK Hynix (last 2026-04-23), Samsung Electro-Mechanics (last 2026-04-30)

### TW — Taiwan (`enrich taiwan`)
- Overdue for a call: Wiwynn (last 2026-02-26), Inventec (last 2026-05-12), Gigabyte (last 2026-05-15), VPEC (last 2026-05-27)
- Never had a call enriched: ADDA, AP Memory, ASMedia, ASPEED, AVC (Asia Vital Components), Accton Technology, All Ring Tech, Andes Technology, Auras Technology, C Sun Manufacturing, CHPT (Chunghwa Precision Test), Chenbro … +37 more
- Waiting to enrich: 1 IR release

### JP — Japan (`enrich japan`)
- Overdue for a call: Murata (last 2026-04-30)
- Never had a call enriched: AGC, Accretech (Tokyo Seimitsu), Asahi Kasei, Asetek, Canon, Dai Nippon Printing, Disco Corporation, Ebara, Ferrotec, Fujifilm, Fujikura, Fujimi … +43 more
- Waiting to enrich: 1 call, 1 IR release

### EU — Europe (`enrich europe`)
- Overdue for a call: Schneider Electric (last 2026-04-30), Legrand (last 2026-05-12), AT&S (last 2026-05-21)
- Never had a call enriched: ASM International, Comet Holding, Inficon, LPKF Laser & Electronics, Merck KGaA, Prysmian, SUSS MicroTec, Siemens Energy, VAT Group

### CN — China / Hong Kong (`enrich china`)
- Never had a call enriched: Accelink, Eoptolink, Huatian Technology, Innolight, Innoscience, JCET, Lenovo, Luxshare, Montage Technology, TFC Optical, TFME, Victory Giant Technology … +2 more
- Waiting to enrich: 1 call

### other — Other listed (`enrich intl`)
- Never had a call enriched: AEM Holdings, Indosat, Lynas Rare Earths, UMS Integration

## Pipelines

| Pipeline | Command | Last sync | Last enriched | Waiting | Files | In graph |
|---|---|---|---|---|---|---|
| US earnings calls | `enrich us calls` | 2026-09-30 | 2026-09-30 | 0 | 313 | 310 |
| US SEC filings | `enrich edgar` | 2026-10-01 | 2026-09-16 | 175 | 1280 | 432 |
| Korea DART filings | `enrich dart` | 2026-10-01 | 2026-10-01 | 0 | 109 | 118 |
| Taiwan / Japan / Europe calls | `enrich intl` | 2026-10-01 | 2026-10-01 | 2 | 43 | 41 |
| Taiwan Chinese 法說會 | `enrich tw` | 2026-09-07 | 2026-09-07 | 0 | 17 | 17 |
| Investor conferences | `enrich conference` | 2026-09-30 | 2026-09-30 | 0 | 113 | 112 |
| Company IR press releases | `enrich ir` | 2026-09-30 | 2026-10-01 | 2 | 1204 | 375 |
| Korea IR decks (KIND) | `enrich korea` | 2026-10-01 | 2026-09-27 | 0 | 47 | 37 |
| Korea earnings-call scripts | `enrich korea` | 2026-10-01 | 2026-09-27 | 0 | 1 | 1 |
| Pasted transcripts | `Transcript:<company>` | 2026-09-25 | 2026-09-25 | 0 | 248 | 248 |

## Coordinator notes (newest first)

- 2026-10-01 00:10 US: 09-30 nightly enrich us: 33 labels applied (AOS Q4 call, 7 conferences, 25 IR releases; 40 IR rows no material facts). Opus verifiers DONE over all 33 - 16 corrections in patches/corrections/verify-us-0930-a..f.json NOT APPLIED (permission classifier blocked apply_corrections.py in the unattended session). Next: apply_corrections.py --check -> apply_corrections.py -> graph_build.py --sync -> move the 33 verify_queue labels to verified -> i18n step. defeatbeta still 404; AV waiting Dell/SLP/IMOS/PDFS/POET/RLAY. IR sync: 119 feed failures (all markets).
- 2026-09-29 23:22 US: 09-29 nightly enrich us: AV saved AOS Q3 FY2026, MP Materials Q2, UMC Q2 (enriched). defeatbeta still HTTP 404 (HF parquet gone) for APLD/SLP/MMM/TXN/IMOS/PDFS/POET/SHEL/DELL - source outage, not marked. AV waiting: Dell, Simulations Plus, ChipMOS, PDF Solutions, POET, Relay. AOS Q4 FY2026 (Aug) call not yet on AV. All 116 US IR rows closed (41 patches from the blocked 09-28 run applied + 8 new). Skyworks IR files 07-28/09-01/09-11/09-25 saved nav-only (body check passed them) - ir_pull prose_ok gap. US results releases (Vertiv/Vicor/Xcel Q2) slipped past the results-headline skip.
- 2026-09-27 00:27 US: 09-27 enrich us: AV quota hit after 9 calls; defeatbeta still 404. Carry over: Dell, ChipMOS, Simulations Plus (AV waiting), Applied Digital, 3M, Texas Instruments (overdue), MP Materials, PDF Solutions, POET, Shell, UMC (never). Air Products 09-16 release left pending: page body is JS-rendered navigation only; paste the release text by hand. av.py sync assigns the wrong fiscal quarter to June-FY companies with no prior label (AOS) - check before trusting a first-call label. EMCOR 09-17 conference: CEO turns labelled Moderator by investing.py.

## Recording what no script can know (coordinator only)

- A source that does not exist: `python -X utf8 enrich_status.py mark "<Company>" ["<Company>" …] --source call --why "<reason>" [--recheck YYYY-MM-DD]` (sources: call, dart, ir, conference, edgar; default recheck in 90 days).
- Undo: `python -X utf8 enrich_status.py unmark "<Company>" --source call`
- Where a run stopped: `python -X utf8 enrich_status.py note US "AV quota hit after 25 calls; 3 left for tomorrow"`
- A judgment for the user (an ambiguous new company, an unclear placement): `python -X utf8 enrich_status.py ask "<subject>" --question "…" [--label "<source label>"]`; after the answer: `python -X utf8 enrich_status.py resolve "<subject>" --answer "…"`
- Parallel enrich agents never write these; they put it in their report and the coordinator records it.
