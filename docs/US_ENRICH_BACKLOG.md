# US earnings-call enrich backlog (2026 calls)

Downloaded 2026-09-16. **Progress:** 2026-09-16 run 3 enriched + verified the 40 newest rows (Status column) plus Cerebras Q1/Q2 FY2026 (newly listed, CBRS — not in this table); run 4 (same day) enriched + verified the next 50 newest rows; run 5 (same day, one workflow: 111 enrichers + 111 verifiers) enriched + verified the last 112. **Backlog complete — 0 rows pending.** Every US-listed graph node (NYSE/NASDAQ ticker in
`company_metadata.json`) was checked against every call it reported in calendar 2026; these are the
calls the graph had no label for. All are FULL transcripts (prepared remarks + analyst Q&A).

- **202 queue rows, 145 companies.** Machine queue: `av/pending.json` (gitignored, this PC only) —
  `enrich us` / `python av.py pending` picks them up; `python av.py done` clears the queue after enrichment.
- Source: defeatbeta US transcripts parquet (`data/US/stock_earning_call_transcripts.parquet`), except
  Applied Materials Q1 FY2026 (Motley Fool — Alpha Vantage and defeatbeta hold only a 10.7k-char templated stub)
  and Oracle Q3 FY2026 (Motley Fool file already on disk).
- Intel Foundry Q4 FY2025 shares Intel's call file — enrich only the foundry segment under the Intel Foundry label.
- Mostly older than the calls already in the graph (131 are Q4-2025 calls reported Jan–Feb 2026): enrich for
  history/timelines; do not let them overwrite newer screener slots (no `slot` on entries older than the
  company's latest call).

| Company | Label | File | Status |
|---|---|---|---|
| 3M | 3M Q4 FY2025 (01-20-2026) | `transcripts/av/3m_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| AAON | AAON Q4 FY2025 (03-02-2026) | `transcripts/av/aaon_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| AAON | AAON Q1 FY2026 (05-07-2026) | `transcripts/av/aaon_q1_2026.txt` | enriched 2026-09-16 |
| ACM Research | ACM Research Q4 FY2025 (02-26-2026) | `transcripts/av/acmresearch_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| ACM Research | ACM Research Q1 FY2026 (05-07-2026) | `transcripts/av/acmresearch_q1_2026.txt` | enriched 2026-09-16 |
| AMD | AMD Q4 FY2025 (02-03-2026) | `transcripts/av/amd_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| ASE Group | ASE Group Q4 FY2025 (02-05-2026) | `transcripts/av/asegroup_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| ASML | ASML Q4 FY2025 (01-28-2026) | `transcripts/av/asml_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| AXT | AXT Q4 FY2025 (02-20-2026) | `transcripts/av/axt_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Adobe | Adobe Q1 FY2026 (03-12-2026) | `transcripts/av/adobe_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Adobe | Adobe Q3 FY2026 (09-10-2026) | `transcripts/av/adobe_q3_2026.txt` | enriched 2026-09-16 |
| Advanced Energy | Advanced Energy Q4 FY2025 (02-10-2026) | `transcripts/av/advancedenergy_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Advanced Energy | Advanced Energy Q1 FY2026 (05-04-2026) | `transcripts/av/advancedenergy_q1_2026.txt` | enriched 2026-09-16 |
| Aehr Test Systems | Aehr Test Systems Q2 FY2026 (01-08-2026) | `transcripts/av/aehrtestsystems_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Aehr Test Systems | Aehr Test Systems Q3 FY2026 (04-07-2026) | `transcripts/av/aehrtestsystems_q3_2026.txt` | enriched 2026-09-16 (run 4) |
| Air Products | Air Products Q1 FY2026 (01-30-2026) | `transcripts/av/airproducts_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Air Products | Air Products Q2 FY2026 (04-30-2026) | `transcripts/av/airproducts_q2_2026.txt` | enriched 2026-09-16 |
| Amazon | Amazon Q4 FY2025 (02-05-2026) | `transcripts/av/amazon_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| American Electric Power | American Electric Power Q4 FY2025 (02-12-2026) | `transcripts/av/americanelectricpower_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| American Electric Power | American Electric Power Q1 FY2026 (05-05-2026) | `transcripts/av/americanelectricpower_q1_2026.txt` | enriched 2026-09-16 |
| Amkor Technology | Amkor Technology Q4 FY2025 (02-09-2026) | `transcripts/av/amkortechnology_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Amphenol | Amphenol Q4 FY2025 (01-28-2026) | `transcripts/av/amphenol_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Analog Devices | Analog Devices Q1 FY2026 (02-18-2026) | `transcripts/av/analogdevices_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Apple | Apple Q1 FY2026 (01-29-2026) | `transcripts/av/apple_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Applied Digital | Applied Digital Q2 FY2026 (01-07-2026) | `transcripts/av/applieddigital_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Applied Materials | Applied Materials Q1 FY2026 (02-12-2026) | `transcripts/av/appliedmaterials_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Applied Optoelectronics | Applied Optoelectronics Q4 FY2025 (02-26-2026) | `transcripts/av/appliedoptoelectronics_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Argan | Argan Q4 FY2026 (03-26-2026) | `transcripts/av/argan_q4_2026.txt` | enriched 2026-09-16 (run 4) |
| Argan | Argan Q1 FY2027 (06-04-2026) | `transcripts/av/argan_q1_2027.txt` | enriched 2026-09-16 |
| Arista | Arista Q4 FY2025 (02-12-2026) | `transcripts/av/arista_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Arm Holdings | Arm Holdings Q3 FY2026 (02-04-2026) | `transcripts/av/armholdings_q3_2026.txt` | enriched 2026-09-16 (run 5) |
| Astera Labs | Astera Labs Q4 FY2025 (02-10-2026) | `transcripts/av/asteralabs_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Axcelis | Axcelis Q4 FY2025 (02-17-2026) | `transcripts/av/axcelis_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Axcelis | Axcelis Q1 FY2026 (05-07-2026) | `transcripts/av/axcelis_q1_2026.txt` | enriched 2026-09-16 |
| Baker Hughes | Baker Hughes Q4 FY2025 (01-26-2026) | `transcripts/av/bakerhughes_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Baker Hughes | Baker Hughes Q1 FY2026 (04-24-2026) | `transcripts/av/bakerhughes_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Bloom Energy | Bloom Energy Q4 FY2025 (02-05-2026) | `transcripts/av/bloomenergy_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Broadcom | Broadcom Q1 FY2026 (03-04-2026) | `transcripts/av/broadcom_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Cadence | Cadence Q4 FY2025 (02-17-2026) | `transcripts/av/cadence_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Camtek | Camtek Q4 FY2025 (02-18-2026) | `transcripts/av/camtek_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Carrier Global | Carrier Global Q4 FY2025 (02-05-2026) | `transcripts/av/carrierglobal_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Carrier Global | Carrier Global Q1 FY2026 (04-30-2026) | `transcripts/av/carrierglobal_q1_2026.txt` | enriched 2026-09-16 |
| Caterpillar | Caterpillar Q4 FY2025 (01-29-2026) | `transcripts/av/caterpillar_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Caterpillar | Caterpillar Q1 FY2026 (04-30-2026) | `transcripts/av/caterpillar_q1_2026.txt` | enriched 2026-09-16 |
| Celestica | Celestica Q4 FY2025 (01-29-2026) | `transcripts/av/celestica_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Ciena | Ciena Q1 FY2026 (03-05-2026) | `transcripts/av/ciena_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Cipher Digital | Cipher Digital Q4 FY2025 (02-24-2026) | `transcripts/av/cipherdigital_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Cipher Digital | Cipher Digital Q1 FY2026 (05-05-2026) | `transcripts/av/cipherdigital_q1_2026.txt` | enriched 2026-09-16 |
| Cisco | Cisco Q2 FY2026 (02-11-2026) | `transcripts/av/cisco_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Coherent | Coherent Q2 FY2026 (02-04-2026) | `transcripts/av/coherent_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Cohu | Cohu Q4 FY2025 (02-12-2026) | `transcripts/av/cohu_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Cohu | Cohu Q1 FY2026 (04-30-2026) | `transcripts/av/cohu_q1_2026.txt` | enriched 2026-09-16 |
| Comfort Systems USA | Comfort Systems USA Q4 FY2025 (02-20-2026) | `transcripts/av/comfortsystemsusa_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Comfort Systems USA | Comfort Systems USA Q1 FY2026 (04-24-2026) | `transcripts/av/comfortsystemsusa_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Core Scientific | Core Scientific Q4 FY2025 (03-03-2026) | `transcripts/av/corescientific_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| CoreWeave | CoreWeave Q4 FY2025 (02-26-2026) | `transcripts/av/coreweave_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Corning | Corning Q4 FY2025 (01-28-2026) | `transcripts/av/corning_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Credo | Credo Q3 FY2026 (03-03-2026) | `transcripts/av/credo_q3_2026.txt` | enriched 2026-09-16 (run 4) |
| Cummins | Cummins Q4 FY2025 (02-05-2026) | `transcripts/av/cummins_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Cummins | Cummins Q1 FY2026 (05-05-2026) | `transcripts/av/cummins_q1_2026.txt` | enriched 2026-09-16 |
| Dell | Dell Q4 FY2026 (02-26-2026) | `transcripts/av/dell_q4_2026.txt` | enriched 2026-09-16 (run 4) |
| Digital Realty | Digital Realty Q4 FY2025 (02-05-2026) | `transcripts/av/digitalrealty_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Digital Realty | Digital Realty Q1 FY2026 (04-23-2026) | `transcripts/av/digitalrealty_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Dominion Energy | Dominion Energy Q4 FY2025 (02-23-2026) | `transcripts/av/dominionenergy_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Dominion Energy | Dominion Energy Q1 FY2026 (05-01-2026) | `transcripts/av/dominionenergy_q1_2026.txt` | enriched 2026-09-16 |
| Dycom | Dycom Q4 FY2026 (03-04-2026) | `transcripts/av/dycom_q4_2026.txt` | enriched 2026-09-16 (run 4) |
| Dycom | Dycom Q1 FY2027 (05-27-2026) | `transcripts/av/dycom_q1_2027.txt` | enriched 2026-09-16 |
| EMCOR | EMCOR Q4 FY2025 (02-26-2026) | `transcripts/av/emcor_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| EMCOR | EMCOR Q1 FY2026 (04-29-2026) | `transcripts/av/emcor_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Eaton | Eaton Q4 FY2025 (02-03-2026) | `transcripts/av/eaton_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Element Solutions | Element Solutions Q4 FY2025 (02-18-2026) | `transcripts/av/elementsolutions_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Element Solutions | Element Solutions Q1 FY2026 (04-29-2026) | `transcripts/av/elementsolutions_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Entegris | Entegris Q4 FY2025 (02-10-2026) | `transcripts/av/entegris_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Entergy | Entergy Q4 FY2025 (02-12-2026) | `transcripts/av/entergy_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Entergy | Entergy Q1 FY2026 (04-29-2026) | `transcripts/av/entergy_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Equinix | Equinix Q4 FY2025 (02-11-2026) | `transcripts/av/equinix_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Equinix | Equinix Q1 FY2026 (04-29-2026) | `transcripts/av/equinix_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Everpure | Everpure Q1 FY2027 (05-27-2026) | `transcripts/av/everpure_q1_2027.txt` | enriched 2026-09-16 |
| Everpure | Everpure Q2 FY2027 (08-26-2026) | `transcripts/av/everpure_q2_2027.txt` | enriched 2026-09-16 |
| Eversource | Eversource Q4 FY2025 (02-13-2026) | `transcripts/av/eversource_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Eversource | Eversource Q1 FY2026 (05-07-2026) | `transcripts/av/eversource_q1_2026.txt` | enriched 2026-09-16 |
| Exelon | Exelon Q4 FY2025 (02-12-2026) | `transcripts/av/exelon_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Exelon | Exelon Q1 FY2026 (05-06-2026) | `transcripts/av/exelon_q1_2026.txt` | enriched 2026-09-16 |
| Fabrinet | Fabrinet Q2 FY2026 (02-02-2026) | `transcripts/av/fabrinet_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Flex | Flex Q3 FY2026 (02-04-2026) | `transcripts/av/flex_q3_2026.txt` | enriched 2026-09-16 (run 5) |
| Fluence Energy | Fluence Energy Q1 FY2026 (02-05-2026) | `transcripts/av/fluenceenergy_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| FormFactor | FormFactor Q4 FY2025 (02-04-2026) | `transcripts/av/formfactor_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| GE Vernova | GE Vernova Q4 FY2025 (01-28-2026) | `transcripts/av/gevernova_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Galaxy Digital | Galaxy Digital Q4 FY2025 (02-03-2026) | `transcripts/av/galaxydigital_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Galaxy Digital | Galaxy Digital Q1 FY2026 (04-28-2026) | `transcripts/av/galaxydigital_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Generac | Generac Q4 FY2025 (02-11-2026) | `transcripts/av/generac_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Generac | Generac Q1 FY2026 (04-29-2026) | `transcripts/av/generac_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| GlobalFoundries | GlobalFoundries Q4 FY2025 (02-11-2026) | `transcripts/av/globalfoundries_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Google | Google Q4 FY2025 (02-04-2026) | `transcripts/av/google_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| HPE | HPE Q1 FY2026 (03-09-2026) | `transcripts/av/hpe_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Hubbell | Hubbell Q4 FY2025 (02-03-2026) | `transcripts/av/hubbell_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Hubbell | Hubbell Q1 FY2026 (04-30-2026) | `transcripts/av/hubbell_q1_2026.txt` | enriched 2026-09-16 |
| Hut 8 | Hut 8 Q4 FY2025 (02-25-2026) | `transcripts/av/hut8_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Hut 8 | Hut 8 Q1 FY2026 (05-06-2026) | `transcripts/av/hut8_q1_2026.txt` | enriched 2026-09-16 |
| IREN | IREN Q2 FY2026 (02-05-2026) | `transcripts/av/iren_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Ichor | Ichor Q4 FY2025 (02-09-2026) | `transcripts/av/ichor_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Ichor | Ichor Q1 FY2026 (05-04-2026) | `transcripts/av/ichor_q1_2026.txt` | enriched 2026-09-16 |
| Intel | Intel Q4 FY2025 (01-22-2026) | `transcripts/av/intel_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Intel Foundry | Intel Foundry Q4 FY2025 (01-22-2026) | `transcripts/av/intel_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Johnson Controls | Johnson Controls Q1 FY2026 (02-04-2026) | `transcripts/av/johnsoncontrols_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| KLA | KLA Q2 FY2026 (01-29-2026) | `transcripts/av/kla_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Keysight | Keysight Q1 FY2026 (02-23-2026) | `transcripts/av/keysight_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Kulicke & Soffa | Kulicke & Soffa Q1 FY2026 (02-05-2026) | `transcripts/av/kulickesoffa_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Lam Research | Lam Research Q2 FY2026 (01-28-2026) | `transcripts/av/lamresearch_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Linde | Linde Q4 FY2025 (02-05-2026) | `transcripts/av/linde_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Lumen Technologies | Lumen Technologies Q4 FY2025 (02-03-2026) | `transcripts/av/lumentechnologies_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Lumentum | Lumentum Q2 FY2026 (02-03-2026) | `transcripts/av/lumentum_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| MACOM | MACOM Q1 FY2026 (02-05-2026) | `transcripts/av/macom_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| MKS Instruments | MKS Instruments Q4 FY2025 (02-18-2026) | `transcripts/av/mksinstruments_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Marvell | Marvell Q4 FY2026 (03-05-2026) | `transcripts/av/marvell_q4_2026.txt` | enriched 2026-09-16 (run 4) |
| MaxLinear | MaxLinear Q4 FY2025 (01-29-2026) | `transcripts/av/maxlinear_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| MaxLinear | MaxLinear Q1 FY2026 (04-23-2026) | `transcripts/av/maxlinear_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Meta | Meta Q4 FY2025 (01-28-2026) | `transcripts/av/meta_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Microsoft | Microsoft Q2 FY2026 (01-28-2026) | `transcripts/av/microsoft_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Monolithic Power Systems | Monolithic Power Systems Q4 FY2025 (02-05-2026) | `transcripts/av/monolithicpowersystems_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| NRG Energy | NRG Energy Q4 FY2025 (02-24-2026) | `transcripts/av/nrgenergy_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| NRG Energy | NRG Energy Q1 FY2026 (05-11-2026) | `transcripts/av/nrgenergy_q1_2026.txt` | enriched 2026-09-16 |
| NVIDIA | NVIDIA Q4 FY2026 (02-25-2026) | `transcripts/av/nvidia_q4_2026.txt` | enriched 2026-09-16 (run 4) |
| Navitas | Navitas Q4 FY2025 (02-25-2026) | `transcripts/av/navitas_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Nebius | Nebius Q4 FY2025 (02-12-2026) | `transcripts/av/nebius_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| NetApp | NetApp Q3 FY2026 (02-26-2026) | `transcripts/av/netapp_q3_2026.txt` | enriched 2026-09-16 (run 4) |
| NetApp | NetApp Q4 FY2026 (05-28-2026) | `transcripts/av/netapp_q4_2026.txt` | enriched 2026-09-16 |
| NextEra Energy | NextEra Energy Q4 FY2025 (01-27-2026) | `transcripts/av/nexteraenergy_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| NextEra Energy | NextEra Energy Q1 FY2026 (04-23-2026) | `transcripts/av/nexteraenergy_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Nokia | Nokia Q4 FY2025 (01-29-2026) | `transcripts/av/nokia_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Nokia | Nokia Q1 FY2026 (04-23-2026) | `transcripts/av/nokia_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Nova | Nova Q4 FY2025 (02-12-2026) | `transcripts/av/nova_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| NuScale Power | NuScale Power Q4 FY2025 (02-27-2026) | `transcripts/av/nuscalepower_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| NuScale Power | NuScale Power Q1 FY2026 (05-07-2026) | `transcripts/av/nuscalepower_q1_2026.txt` | enriched 2026-09-16 |
| Oklo | Oklo Q4 FY2025 (03-17-2026) | `transcripts/av/oklo_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Oklo | Oklo Q1 FY2026 (05-12-2026) | `transcripts/av/oklo_q1_2026.txt` | enriched 2026-09-16 |
| Onto Innovation | Onto Innovation Q4 FY2025 (02-19-2026) | `transcripts/av/ontoinnovation_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Oracle | Oracle Q3 FY2026 (03-10-2026) | `transcripts/bigtech/oracle_q3_2026.txt` | enriched 2026-09-16 (run 4) |
| Penguin Solutions | Penguin Solutions Q1 FY2026 (01-06-2026) | `transcripts/av/penguinsolutions_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Penguin Solutions | Penguin Solutions Q2 FY2026 (04-01-2026) | `transcripts/av/penguinsolutions_q2_2026.txt` | enriched 2026-09-16 (run 4) |
| Photronics | Photronics Q1 FY2026 (02-27-2026) | `transcripts/av/photronics_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Photronics | Photronics Q2 FY2026 (05-28-2026) | `transcripts/av/photronics_q2_2026.txt` | enriched 2026-09-16 |
| Powell Industries | Powell Industries Q1 FY2026 (02-04-2026) | `transcripts/av/powellindustries_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Powell Industries | Powell Industries Q2 FY2026 (05-05-2026) | `transcripts/av/powellindustries_q2_2026.txt` | enriched 2026-09-16 |
| Power Integrations | Power Integrations Q4 FY2025 (02-05-2026) | `transcripts/av/powerintegrations_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Qnity Electronics | Qnity Electronics Q4 FY2025 (02-26-2026) | `transcripts/av/qnityelectronics_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Qnity Electronics | Qnity Electronics Q1 FY2026 (05-12-2026) | `transcripts/av/qnityelectronics_q1_2026.txt` | enriched 2026-09-16 |
| Qualcomm | Qualcomm Q1 FY2026 (02-04-2026) | `transcripts/av/qualcomm_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Quanta Services | Quanta Services Q4 FY2025 (02-19-2026) | `transcripts/av/quantaservices_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Quanta Services | Quanta Services Q1 FY2026 (04-30-2026) | `transcripts/av/quantaservices_q1_2026.txt` | enriched 2026-09-16 |
| Rambus | Rambus Q4 FY2025 (02-02-2026) | `transcripts/av/rambus_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| SPX Technologies | SPX Technologies Q4 FY2025 (02-24-2026) | `transcripts/av/spxtechnologies_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| SPX Technologies | SPX Technologies Q1 FY2026 (04-30-2026) | `transcripts/av/spxtechnologies_q1_2026.txt` | enriched 2026-09-16 |
| STMicroelectronics | STMicroelectronics Q4 FY2025 (01-29-2026) | `transcripts/av/stmicroelectronics_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Sandisk | Sandisk Q2 FY2026 (01-29-2026) | `transcripts/av/sandisk_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Sanmina | Sanmina Q1 FY2026 (01-26-2026) | `transcripts/av/sanmina_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| Sanmina | Sanmina Q2 FY2026 (04-27-2026) | `transcripts/av/sanmina_q2_2026.txt` | enriched 2026-09-16 (run 4) |
| Seagate | Seagate Q2 FY2026 (01-27-2026) | `transcripts/av/seagate_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Semtech | Semtech Q4 FY2026 (03-16-2026) | `transcripts/av/semtech_q4_2026.txt` | enriched 2026-09-16 (run 4) |
| SiTime | SiTime Q4 FY2025 (02-04-2026) | `transcripts/av/sitime_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| SiTime | SiTime Q1 FY2026 (05-06-2026) | `transcripts/av/sitime_q1_2026.txt` | enriched 2026-09-16 |
| Silicon Motion | Silicon Motion Q4 FY2025 (02-04-2026) | `transcripts/av/siliconmotion_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Solstice Advanced Materials | Solstice Advanced Materials Q4 FY2025 (02-11-2026) | `transcripts/av/solsticeadvancedmaterials_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Solstice Advanced Materials | Solstice Advanced Materials Q1 FY2026 (05-06-2026) | `transcripts/av/solsticeadvancedmaterials_q1_2026.txt` | enriched 2026-09-16 |
| Southern Company | Southern Company Q4 FY2025 (02-19-2026) | `transcripts/av/southerncompany_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Southern Company | Southern Company Q1 FY2026 (04-30-2026) | `transcripts/av/southerncompany_q1_2026.txt` | enriched 2026-09-16 |
| Sterling Infrastructure | Sterling Infrastructure Q4 FY2025 (02-26-2026) | `transcripts/av/sterlinginfrastructure_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Sterling Infrastructure | Sterling Infrastructure Q1 FY2026 (05-05-2026) | `transcripts/av/sterlinginfrastructure_q1_2026.txt` | enriched 2026-09-16 |
| Supermicro | Supermicro Q2 FY2026 (02-03-2026) | `transcripts/av/supermicro_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Synopsys | Synopsys Q1 FY2026 (02-25-2026) | `transcripts/av/synopsys_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| TE Connectivity | TE Connectivity Q1 FY2026 (01-21-2026) | `transcripts/av/teconnectivity_q1_2026.txt` | enriched 2026-09-16 (run 5) |
| TSMC | TSMC Q4 FY2025 (01-15-2026) | `transcripts/av/tsmc_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| TTM Technologies | TTM Technologies Q4 FY2025 (02-04-2026) | `transcripts/av/ttmtechnologies_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Talen Energy | Talen Energy Q4 FY2025 (02-26-2026) | `transcripts/av/talenenergy_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Talen Energy | Talen Energy Q1 FY2026 (05-05-2026) | `transcripts/av/talenenergy_q1_2026.txt` | enriched 2026-09-16 |
| TeraWulf | TeraWulf Q4 FY2025 (02-27-2026) | `transcripts/av/terawulf_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| TeraWulf | TeraWulf Q1 FY2026 (05-08-2026) | `transcripts/av/terawulf_q1_2026.txt` | enriched 2026-09-16 |
| Teradyne | Teradyne Q4 FY2025 (02-03-2026) | `transcripts/av/teradyne_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Tesla | Tesla Q4 FY2025 (01-28-2026) | `transcripts/av/tesla_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Tesla | Tesla Q1 FY2026 (04-22-2026) | `transcripts/av/tesla_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Texas Instruments | Texas Instruments Q4 FY2025 (01-27-2026) | `transcripts/av/texasinstruments_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Tower Semiconductor | Tower Semiconductor Q4 FY2025 (02-11-2026) | `transcripts/av/towersemiconductor_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Tower Semiconductor | Tower Semiconductor Q1 FY2026 (05-13-2026) | `transcripts/av/towersemiconductor_q1_2026.txt` | enriched 2026-09-16 |
| Trane Technologies | Trane Technologies Q4 FY2025 (01-29-2026) | `transcripts/av/tranetechnologies_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Uber | Uber Q4 FY2025 (02-04-2026) | `transcripts/av/uber_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Uber | Uber Q1 FY2026 (05-06-2026) | `transcripts/av/uber_q1_2026.txt` | enriched 2026-09-16 |
| Ultra Clean | Ultra Clean Q4 FY2025 (02-23-2026) | `transcripts/av/ultraclean_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Ultra Clean | Ultra Clean Q1 FY2026 (04-28-2026) | `transcripts/av/ultraclean_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| Veeco | Veeco Q4 FY2025 (02-25-2026) | `transcripts/av/veeco_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Vertiv | Vertiv Q4 FY2025 (02-11-2026) | `transcripts/av/vertiv_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Viavi | Viavi Q2 FY2026 (01-28-2026) | `transcripts/av/viavi_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Vicor | Vicor Q4 FY2025 (02-20-2026) | `transcripts/av/vicor_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Vishay | Vishay Q4 FY2025 (02-04-2026) | `transcripts/av/vishay_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Vistra | Vistra Q4 FY2025 (02-26-2026) | `transcripts/av/vistra_q4_2025.txt` | enriched 2026-09-16 (run 4) |
| Wesco | Wesco Q4 FY2025 (02-10-2026) | `transcripts/av/wesco_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Wesco | Wesco Q1 FY2026 (04-30-2026) | `transcripts/av/wesco_q1_2026.txt` | enriched 2026-09-16 |
| Western Digital | Western Digital Q2 FY2026 (01-29-2026) | `transcripts/av/westerndigital_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Wolfspeed | Wolfspeed Q2 FY2026 (02-04-2026) | `transcripts/av/wolfspeed_q2_2026.txt` | enriched 2026-09-16 (run 5) |
| Xcel Energy | Xcel Energy Q4 FY2025 (02-05-2026) | `transcripts/av/xcelenergy_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| Xcel Energy | Xcel Energy Q1 FY2026 (04-30-2026) | `transcripts/av/xcelenergy_q1_2026.txt` | enriched 2026-09-16 (run 4) |
| nVent | nVent Q4 FY2025 (02-06-2026) | `transcripts/av/nvent_q4_2025.txt` | enriched 2026-09-16 (run 5) |
| onsemi | onsemi Q4 FY2025 (02-09-2026) | `transcripts/av/onsemi_q4_2025.txt` | enriched 2026-09-16 (run 5) |
