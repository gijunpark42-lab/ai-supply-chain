# Missing public-company candidates — US / Korea / Japan / Taiwan

Audit date: 2026-09-17  
Baseline: `graph/merged_graph.json` (352 nodes / 1,400 edges) and `company_metadata.json`  
Scope: listed semiconductor, AI data-center power/cooling, packaging, materials, test and infrastructure companies missing from the current graph. This is a candidate list only. No node, metadata, logo, transcript, patch or generated graph file was changed.

## How the list was built

- Compared the current graph against [iShares SOXX holdings](https://www.ishares.com/us/products/239705/ishares-semiconductor-etf/latest-holdings.csv), [Kodex semiconductor and AI-power material](https://www.samsungfund.com/upload/kodex/newsroom/20260427141121713.pdf), [Global X Japan Semiconductor ETF holdings](https://globalxetfs.co.jp/en/funds/2644/index.html), [CTBC 00891 Taiwan semiconductor holdings](https://www.ctbcinvestments.com.tw/CTWEB/Content/ETF/pcd.aspx?ETF_ID=00891), and [VegaShares COOL holdings](https://vegasharesetfs.com/public/COOL).
- `A` means the company directly makes a chip, semiconductor input/equipment, packaging/test product, grid product, rack power product or cooling product. These are the cleanest future add candidates.
- `B` means it needs a stricter company-filing check because its AI exposure is broad, indirect or mixed with non-AI businesses.
- Distributors and holding companies are not promoted to `A`; the project litmus test still applies before any future addition.

## Summary

| Region | A: direct candidates | B: review candidates | Explicit exclusions |
|---|---:|---:|---:|
| US-listed | 0 | 0 | 0 |
| Korea | 32 | 12 | 0 |
| Japan | 9 | 3 | 0 |
| Taiwan | 25 | 2 | 2 |
| **Total remaining** | **66** | **17** | **2** |

## US-listed — completed (3 added on 2026-09-17)

| Company | Ticker | Added to |
|---|---|---|
| NXP Semiconductors | NXPI | Optical networking — Networking ASIC |
| Microchip Technology | MCHP | Optical networking — Components; Power semiconductors |
| Skyworks Solutions | SWKS | Optical networking — Components; Power semiconductors |

All three now have full-call transcripts, transcript-backed patches, metadata and logos. Microchip's
call also supported two named-customer edges to existing power-chain nodes: Delta and Lite-On.

Note: UMC also appears in SOXX through its US ADR, but it is grouped under Taiwan below. Every US equity in the COOL power/cooling basket was already present in the graph.

## Korea — A (32)

### Semiconductor / packaging / equipment / materials

| Company | Ticker | Direct role |
|---|---:|---|
| DB HiTek | 000990 | Specialty foundry |
| HPSP | 403870 | High-pressure semiconductor annealing equipment |
| Hana Micron | 067310 | Semiconductor packaging and test |
| TES | 095610 | Deposition and etch equipment |
| Eugene Technology | 084370 | Semiconductor deposition equipment |
| TCK | 064760 | SiC process consumables |
| TSE | 131290 | Semiconductor test interfaces |
| Doosan Tesna | 131970 | Wafer test and semiconductor test services |
| KC Tech | 281820 | CMP and wet-clean equipment |
| Komico | 183300 | Semiconductor chamber-part cleaning and coatings |
| Park Systems | 140860 | AFM metrology |
| Wonik Materials | 104830 | Semiconductor specialty gases |
| Hana Materials | 166090 | Silicon/SiC process consumables |
| FST | 036810 | Pellicles and semiconductor temperature-control equipment |
| Nextin | 348210 | Semiconductor inspection equipment |
| GST | 083450 | Scrubbers and chillers for fabs |
| YIK | 232140 | Memory semiconductor test equipment |
| S&S Tech | 101490 | Photomask blanks and EUV-pellicle development |
| FADU | 440110 | Data-center SSD controllers |
| SemiFive | 490470 | Custom-silicon design platform |
| HaeSung DS | 195870 | Semiconductor package substrates and leadframes |
| GigaVis | 420770 | PCB/substrate inspection equipment |
| Intekplus | 064290 | Semiconductor and advanced-packaging inspection |
| Nepes | 033640 | OSAT and fan-out packaging |
| Hansol Chemical | 014680 | Semiconductor process chemicals |
| ENF Technology | 102710 | Semiconductor process chemicals |

### AI power / grid

| Company | Ticker | Direct role |
|---|---:|---|
| Iljin Electric | 103590 | Transformers, switchgear and power cable |
| Gaon Cable | 000500 | Power cable |
| Daewon Cable | 006340 | Power cable |
| LS Eco Energy | 229640 | Power cable and grid infrastructure |
| JeRyong Electric | 033100 | Distribution transformers |
| LS Marine Solution | 060370 | Submarine power-cable installation |

## Korea — B (12)

| Company | Ticker | Why it needs review |
|---|---:|---|
| Jeju Semiconductor | 080220 | Fabless memory is direct, but current AI/data-center exposure needs filing proof |
| Taesung | 323280 | PCB equipment; confirm advanced AI-board/substrate exposure |
| Protec | 053610 | Packaging automation; confirm relevance to current chains |
| Hanyang ENG | 045100 | Fab utility systems; may be too contractor-like under the litmus test |
| MiCo | 059090 | Semiconductor ceramic parts mixed with other businesses |
| Koh Young Technology | 098460 | Inspection equipment with broad SMT/medical exposure |
| LS | 006260 | Holding company; operating subsidiaries are the direct beneficiaries |
| KT | 030200 | Cloud/data-center/AI exposure needs a chain-specific filing basis |
| Samsung SDS | 018260 | Enterprise AI and cloud exposure needs a chain-specific filing basis |
| LG CNS | 064400 | Enterprise AI/cloud/data-center exposure needs a chain-specific filing basis |
| Kakao | 035720 | AI model/application exposure is broad and consumer-platform-heavy |
| NHN | 181710 | Cloud/AI exposure needs a chain-specific filing basis |

## Japan — A (9)

| Company | Ticker | Direct role | Audit source |
|---|---:|---|---|
| ROHM | 6963 | Power and analog semiconductors | Global X 2644 / COOL |
| Horiba | 6856 | Semiconductor process measurement and analysis | Global X 2644 |
| Japan Micronics | 6871 | Probe cards and semiconductor test equipment | Global X 2644 |
| Rorze | 6323 | Wafer-handling automation | Global X 2644 |
| ULVAC | 6728 | Vacuum deposition and semiconductor equipment | Global X 2644 |
| Shibaura Mechatronics | 6590 | Semiconductor manufacturing equipment | Global X 2644 |
| Tekscend Photomask | 429A | Semiconductor photomasks | Global X 2644 |
| Japan Material | 6055 | Fab gases, chemicals and facility services | Global X 2644 historical constituent |
| Sanken Electric | 6707 | Power semiconductors | Global X 2644 historical constituent |

## Japan — B (3)

| Company | Ticker | Why it needs review |
|---|---:|---|
| Macnica Holdings | 3132 | Semiconductor distributor; usually fails the direct-benefit test |
| Alps Alpine | 6770 | Broad component supplier; current AI-chain exposure needs proof |
| Shibaura Electronics | 6957 | Temperature sensors; data-center/semiconductor exposure needs proof |

## Taiwan — A (25)

### Semiconductor / foundry / test / materials

| Company | Ticker | Direct role |
|---|---:|---|
| United Microelectronics (UMC) | 2303 / UMC ADR | Specialty foundry |
| Winbond Electronics | 2344 | Specialty DRAM and flash memory |
| Jentech Precision Industrial | 3653 | Server thermal and mechanical components |
| MPI Corporation | 6223 | Probe cards and semiconductor test |
| Realtek Semiconductor | 2379 | Networking and connectivity silicon |
| King Yuan Electronics (KYEC) | 2449 | Semiconductor testing |
| eMemory Technology | 3529 | Embedded-memory IP |
| Vanguard International Semiconductor | 5347 | Specialty foundry |
| WinWay Technology | 6515 | Semiconductor test sockets/interfaces |
| WIN Semiconductors | 3105 | Compound-semiconductor foundry |
| Silergy | 6415 | Power-management ICs |
| ChipMOS Technologies | 6147 | OSAT and semiconductor testing |
| AP Memory Technology | 6531 | Specialty memory |
| Sino-American Silicon Products | 5483 | Semiconductor wafers/materials |
| ASMedia Technology | 5269 | High-speed interface silicon |
| VisEra Technologies | 6789 | CMOS image-sensor foundry and wafer-level processing |
| Formosa Sumco Technology | 3532 | Silicon wafers |

### AI server cooling / rack power

| Company | Ticker | Direct role |
|---|---:|---|
| Asia Vital Components | 3017 | Server thermal management |
| Auras Technology | 3324 | Server cooling modules |
| Sunonwealth Electric Machine | 2421 | Fans and thermal modules |
| Nidec Chaun-Choung Technology | 6230 | Heat pipes and thermal modules |
| Chicony Power Technology | 6412 | Server power supplies |
| TaiSol Electronics | 3338 | Thermal modules and heat pipes |
| FSP Technology | 3015 | Power supplies |
| ADDA Corporation | 3071 | Cooling fans |

## Taiwan — B (2) and exclusions (2)

| Company | Ticker | Disposition | Reason |
|---|---:|---|---|
| Novatek Microelectronics | 3034 | B | Display-driver-heavy; direct AI exposure needs proof |
| Fositek | 6805 | B | Included in a thermal basket, but its disclosed core business is still dominated by hinges/components |
| WPG Holdings | 3702 | Exclude | Distributor rather than a direct product supplier |
| WT Microelectronics | 3036 | Exclude | Distributor rather than a direct product supplier |

## Existing-node note

LandMark Optoelectronics (3081) is already in the graph as `Landmark`; it is not a missing company. Its current metadata is incomplete/misclassified, but this audit intentionally made no metadata edits.

## Resume point

If enrichment resumes later, process the remaining `A` list first: Korea from each company's own DART filing only, and Japan/Taiwan only where a full transcript or existing approved pipeline is immediately available. The US-listed slice is complete.
