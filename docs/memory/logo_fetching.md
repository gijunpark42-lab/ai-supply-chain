---
name: logo-fetching
description: How to fetch brand logos for missing graph nodes (static/logos/ + manifest.json)
metadata: 
  node_type: memory
  type: reference
  originSessionId: c3733e73-6cbf-48d6-b600-96298fe661e5
---

Node badges read `static/logos/manifest.json` ( `"<node id>": {"file","bg"}` ), key MUST equal the merged_graph node id; app.py URL-quotes the filename so spaces/parens are fine. SVG preferred (vector → satisfies "1080+" automatically). bg = "light" for dark/colored logos, "dark" for white logos.

Find missing: compare `graph/merged_graph.json` node ids vs manifest keys.

Fetch method that worked (2026-06-14, batch of 30), in order of reliability:
1. **Wikidata P154** (best): Wikipedia title → wikibase_item (Q id) via en.wikipedia `prop=pageprops&ppprop=wikibase_item`; Q id → P154 logo file via wikidata `wbgetentities&props=claims`; file → URL via commons `prop=imageinfo`. Returns official SVG for most big firms.
2. Commons file search (`generator=search&gsrnamespace=6`) for `"<company> logo"` when no P154.
3. Company homepage scrape for `.svg` (header/footer logo); white variants → bg=dark.

Pitfalls: Wikipedia `pageimages` returns the page's lead photo (building), NOT the logo — don't use it. Clearbit logo API is dead. Brandfetch 403s WebFetch. seeklogo/worldvectorlogo block direct download + have name collisions (e.g. "JSR" → jsr.io / JSR MUSIK, not JSR Corp; "disco" → red circle, not DISCO semiconductor). Verify rasters by Reading them as images. Use real SSL (don't disable TLS verify — it's blocked).

Manifest edit: load with OrderedDict, append new entries (file-then-bg key order), `json.dumps(indent=1, ensure_ascii=False)` NO trailing newline → byte-identical to original, clean diff. Do NOT use sort_keys (reorders inner keys → huge churn).

Progress: 2026-06-14 batch 1 +30, batch 2 +30, batch 3 +30, batch 4 +10 → manifest 202 entries, ~58 nodes still missing. Batch 4 hit the wall: tail is obscure KR/JP/TW small-caps with NO Wikidata P154 and sites that block scraping (Korean corp sites throw SSL URLError; can't disable TLS verify — soft-blocked). Commons name-token search returns PHOTOS for rasters (Black Forest Labs→forest aerial, ASADA→person, ASPEED→die shot, Yageo→campus) — ALWAYS visually Read raster search hits; trust only SVG from search. Got 10/batch (Fujimi, Landmark, Lasertec, Legrand, Chenbro, Toho Titanium, Leeno[white], Hanmi/HD Hyundai Electric/Submer as ≥1080 PNG). Sub-1080 clean PNGs available if bar relaxed: iPronics 945, Sumitomo Bakelite 809(white), Soulbrain 183, Simmtech 237. Remaining tail likely needs manual logo links from user or Brandfetch (403s WebFetch). KR pass (ko.wikipedia by Korean name → Wikidata P154 + infobox, strict name-token filter; + sites via `requests`): only Hyosung Heavy Industries + LS Electric had ≥1080 (group SVG on Commons) → added, manifest 204. Other 17 KR small-caps have NO ≥1080 logo: ko-wiki infobox grabs generic icons (Commons/Wikidata logo SVGs — MUST require company-name token in filename), KR corp sites SSLError/timeout even via requests-certifi, the few reachable serve tiny header PNGs only (ISC 288, Soulbrain 183, Doosan 830 best). Use `sys.stdout.reconfigure(encoding="utf-8")` for Korean/Japanese prints on this Windows console. JP pass (ja.wikipedia by Japanese name + sites via requests): only Accretech(Tokyo Seimitsu) + Shinko Electric had usable SVG (from official accretech.com / shinko.co.jp headers) → added, manifest 206. ja-wiki infobox returns BUILDING PHOTOS for these (ASADA/Sakai/Shinko/SCREEN "headquarters/office" jpegs — exclude filename tokens headquarters/office/building/factory). Commons SVG search: zero for all JP small-caps. JP sites more reachable than KR but logos mostly tiny PNG (<1080). Still missing & no ≥1080 source: Disco Corporation (CSS-bg logo, the perennial holdout), SCREEN Holdings, TOWA, Via Mechanics, ASADA, Nippon Chemical Industrial, Sakai/Shoei Chemical, Sumitomo Bakelite + JSR Corporation. TW/CN pass (zh.wikipedia 繁體 + sites + web search): zh-wiki/Commons dry (Faraday only a 783px jpeg), TW sites SSLError/ConnectionError (guc-asic, gccgroup, kinsus, wusgroup, zdtco, tfcfiber), worldvectorlogo only collision-risk acronym slugs (emc=likely Dell EMC, tfc=ambiguous — REJECTED per "only certain"). WIN: companieslogo.com is ticker-keyed + reliable + ≥1080 transparent PNG + has SVG too — got Yageo (2327.TW) + GlobalWafers (6488.TWO), verified by Reading the PNG. But companieslogo lacks the smaller TW/CN names (Zhen Ding/Kinsus/Nan Ya PCB/GUC/Faraday/ASPEED/Accelink). No SVG rasterizer on this box (no magick/rsvg/inkscape/cairo) → can't visually verify SVGs; only trust SVG from official-site/Wikidata-P154/companieslogo, and Read rasters to verify. manifest now 208, ~50 nodes still logoless (remaining: small TW/CN PCB+optical+ASIC, JP Disco/SCREEN/etc, JSR, misc KR). For verifiable ≥1080: companieslogo.com first (ticker pages), Read the PNG. KR round-2 via companieslogo: covers KOSPI (.KS) not KOSDAQ (.KQ) — added Doosan Enerbility(034020.KS,1526px), Isu Petasys(007660.KS,1546px), Daeduck Electronics(353200.KS,1552px), all Read-verified → manifest 211. KOSDAQ small-caps 404 on companieslogo (Soulbrain/Wonik IPS/Dongjin/Simmtech/Techwing...). Naver is NOT reachable by my tools: WebFetch errors "unable to fetch from search.naver.com", WebSearch is US-only. companieslogo slug = lowercase-hyphenated name (/doosan-enerbility/logo/); image at /img/orig/<TICKER>_BIG-<hash>.png (hash unguessable → must WebFetch the page). JP round-2 via companieslogo: added SCREEN Holdings (7735.T, 1556px, Read-verified) → manifest 212. Disco Corp IS on companieslogo (/disco-corp/, 6146.T confirmed = the real semiconductor dicing co, verified blue/orange mark+DISCO wordmark) but only 840x840 PNG — UNDER the 1080 bar (all other Disco sources also <900px: findlogovector 900x500, logowik 866, seeklogo 600); pending user decision on whether to accept 840 as the one exception. Yahoo Japan: WebFetch CAN reach search.yahoo.co.jp (unlike Naver) but image search is a JS SPA → returns placeholder text, no extractable image URLs (same dead-end as Naver image). JP companies NOT on companieslogo & no ≥1080: Sumitomo Bakelite (809px white site png), TOWA, Nippon Chemical (792px), Sakai Chemical, ASADA, Via Mechanics (456px), Shoei Chemical. ~46 nodes still logoless (KOSDAQ small-caps, TW/CN PCB/optical/ASIC small-caps, the JP chemicals above, JSR Corporation). Batch 3 leaned on official-site SVG scraping (Wikidata well drying up for small-caps): Camtek, K&S, Trane, nVent, Asetek, Accton, Toppan, Nanya, Wiwynn, IREN, Inventec, Delta. Tip: ALWAYS check a scraped SVG has real drawable content — `<path>/<polygon>/<rect>` count >0 (ASPEED's site SVG was 589B empty, would've rendered blank). Remaining tail is obscure KR/JP/TW small-caps (Soulbrain, Techwing, EO Technics, Jusung, Wonik IPS, Sakai/Shoei/Nippon Chemical, Nan Ya PCB, Kinsus, Zhen Ding, photonics: Ranovus/TFC/Sivers/Accelink, cooling: Submer) — mostly need official-site scrape or stay deferred. Batch 2 lesson: nearly all remaining nodes tie at 1 chain, so don't limit the candidate pool to top-N-by-chain — run Wikidata P154 over ALL missing ids; big global names (Nokia, ABB, Schneider, Siemens Energy, Renesas, STMicro, Panasonic, HOYA, TDK, Kioxia…) sort late but resolve cleanly. Avoid JPEG logos (white box, no transparency); SVG default-fill renders black (fine on light bg). Still deferred: JSR Corporation, Disco Corporation (no free ≥1080/SVG). See [[project_state]].

WRONG-LOGO AUDIT (2026-06-19, user: "check the logos, NVTS looks wrong"): found & fixed FOUR mis-sourced logos. (1) **Navitas** — had Navitas Ltd (Australian EDUCATION co, yellow #FFCB04 swoosh) instead of Navitas Semiconductor NVTS (navy+blue emblem). Name-collision. → companieslogo NVTS_BIG png 1539x336. (2) **Landmark** — had a wrong crimson #C40D3C logo (generic "Landmark") instead of LandMark Optoelectronics (TW 3081, optical epi-wafer): real logo = blue/yellow oval emblem "LandMark Optoelectronics". → lmoc.com.tw header logo.svg (hybrid: 1896x1341 embedded emblem PNG + vector blue #1A50A2 text → scales ≥1080). (3) **GMI** — had the **Pika** logo (aria-label/id="pika-logo")! gmicloud.ai renders a CUSTOMER-logo carousel as inline SVGs (Pika/Cartesia/Singtel…) and the scrape grabbed Pika by mistake; GMI's OWN nav logo is a separate inline `<svg viewBox="0 0 718 233">` with clip-path id `gmi-cloud-logo` (white bracket-mark + "GMI", lime accent). → extracted that, bg light→**dark** (white logo). (4) **Tokyo Ohka Kogyo** — had the **IBM** logo (`<title>Logo International Business Machines Corporation</title>`, IBM blue #1f70c1 8-bar)! → companieslogo 4186.T png 1552x573 (orange "tok", hexagon-o). TWO DETECTION METHODS that worked: (a) **embedded-brand scan** — grep every SVG's aria-label/`<title>`/id+class tokens (strip generic editor noise: base/metadata/namedview/clipPath/Ebene[de]/Warstwa[pl]/Capa[es]/Swatch/Layer) and flag any real company name ≠ node id; caught GMI=Pika and TOK=IBM instantly (HPE's `<title>"Hewlett Packard Enterprise logo"` correctly MATCHES). (b) **brand-color + graph-context** for no-text logos — look up the node's tier/chain in merged_graph to know WHICH company it is, then check the logo's hex palette vs the real brand (Navitas teal/navy not yellow; LandMark blue not crimson). Verified-correct spot-checks (collision-prone generic names): Nova(=Nova Ltd NVMI, navy+magenta gradient ✓), Mistral(orange-gradient AI lab ✓), Lambda(byte-identical to lambda.ai logo-white.svg, NOT AWS Lambda ✓), Alchip/Credo/Quanta(=Quanta Computer blue+red, not Quanta Services ✓)/Innolight(byte-identical to innolight.com logo-w-01.svg ✓)/Flex/Fujimi/Shell/Groq/Uber. ALL 22 raster logos verified correct via a single Pillow contact-sheet montage (mid-gray #969696 bg so white AND dark logos show, label strip per cell) → Read once; far cheaper than Reading each. Minor (not wrong, deferred): Thinking Machines Lab.png has a baked-in WHITE background (not transparent) → shows as a white box. **OneDrive caveat**: this repo is under OneDrive — a file overwrite (Landmark.svg) got transiently REVERTED to the old version by a background OneDrive sync once; re-copying made it stick. After overwriting a logo, re-verify the bytes a few seconds later. UPDATE (2026-06-19, same day): re-verifying "a few seconds later" was NOT enough — across the session/compaction boundary OneDrive REVERTED 3 of the 4 fixes (Landmark→crimson, GMI→Pika, TOK→IBM) back to the wrong versions, while only Navitas (which had reached a commit) survived. The ONLY durable fix in this OneDrive repo is to `git add` the corrected file IMMEDIATELY and `git commit` — git history (`git show HEAD:<file>`, working tree clean) becomes the source of truth, and `git checkout -- <file>` restores it if OneDrive reverts the working copy again. Re-applied + committed all 3 in commit 2543142 (manifest: GMI bg light→dark, TOK file svg→png; wrong TOK .svg `git rm`'d). NOTE: `git commit` in this repo prints noise like `error: failed to delete '.git/worktrees/<name>': Permission denied` (~20 lines) — these are OneDrive-locked stale worktree admin dirs from past sessions; HARMLESS, the commit still completes (check the `[main <sha>]` line).

BATCH 2026-08-27 (+20, manifest 212→232, coverage 230/266 = 86%). Two method fixes that broke the
old wall:
1. **Wikidata ticker lives as a QUALIFIER `P249` on the `P414` (stock exchange) statement, NOT as a
   top-level claim** — I first read top-level P249, got 0/55 and wrongly concluded "no data".
   Reading the qualifier gives a *proof of identity* that kills the name-collision problem for good.
   Necessary because a plain en-wiki search + name-token guard produced garbage at scale: Black
   Forest Labs→Planet Labs, Disco Corp→**Disco Elysium (a video game)**, Via Mechanics→Popular
   Mechanics, Vistra→a different "Vistra (services company)", PSK Holdings→BAWAG PSK (Austrian
   bank), Mirae Industry→Mirae Asset, ISC→(ISC)² , Elite Material→All Elite Wrestling. NEVER accept
   a wiki/Commons hit on name tokens alone.
2. **companieslogo.com has a full sitemap** (`/sitemap.xml`, 3.8 MB, robots.txt allows all) listing
   **12,527 real slugs**. Guessing slugs from the company name misses (`/disco-corp/` is not
   derivable from "Disco Corporation"); instead token-match the node name against the sitemap slug
   list, fetch the top few, and PROVE identity from the ticker embedded in the image filename
   (`/img/orig/<TICKER>[_BIG]-<hash>.png`). This is what finally cracked **Disco Corporation at
   1530x1697** (the perennial holdout, previously stuck at 840px) and Sumitomo Bakelite (1533x1164),
   both listed as "no ≥1080 source exists" above — that conclusion was wrong, re-test old holdouts
   with the sitemap method.
Got via companieslogo (all ticker-proven, all ≥1080, all Read-verified on ONE Pillow contact sheet):
Aehr Test Systems, Cohu, Disco Corporation, EMCOR, Eoptolink, GUC (Global Unichip), IQE, Munters,
Nan Ya PCB, Sanil Electric, Solstice Advanced Materials, Sumitomo Bakelite, TFC Optical, TOWA,
Tower Semiconductor (PNG 1567x495 — better than the Wikidata JPG), Vistra. Via ticker-proven
Wikidata P154 SVG: Exelon, SoftBank (Q201653 / 9984; logo is single #b7bbbe silver → **bg must be
"dark"**, `bg==="dark"` adds the `.dk` class = dark chip backing, see web/src/components/Graph3D.tsx).
Via official-site SVG (company name present on page + drawable-content check): Cohere (cohere.com/
logo.svg), Faraday Technology (faraday-tech.com). REJECTED as unverifiable: SACMI's site "logo" was
a 170x170 square with 58 `<g>` (an icon sprite, not a wordmark) — no rasterizer on this box, so
structure+brand-colors is the only SVG check; when it looks like a sprite, drop it.
Wikimedia API rate-limits: 6 parallel workers → **HTTP 429 on every call** (which silently looked
like "no results"); go sequential with ~0.35 s sleep + backoff and a contact-email User-Agent.
Still missing 36, and companieslogo's sitemap has NO entry for any of them (diagnostic run confirms
the near-misses are all different companies): AD Technology, ASADA, ASPEED, Accelink, Black Forest
Labs, CoolIT Systems, Dongjin Semichem, EO Technics, Elite Material, FläktGroup, Gaonchips, Gold
Circuit, ISC, JSR Corporation (highest value — 13 chains; jsr.co.jp/jsr_e/ serves ZERO .svg refs),
Jusung Engineering, Kinsus, Mirae Industry, Nippon Chemical Industrial, PSK Holdings, Ranovus,
Raytec Semiconductor, Robotechnik, Sacmi, Sakai Chemical Industry, Shoei Chemical, Simmtech, Sivers
Semiconductors, Soulbrain, Techwing, VPEC, Via Mechanics, WUS Printed Circuit, Wonik IPS, YJ Semi,
Zhen Ding, iPronics. These now realistically need user-supplied links or Brandfetch.

BATCH 2026-09-07 (+77 in one 6-agent parallel run; manifest 233 -> 310, coverage 308/312 = 99%).
The graph had grown to 312 nodes (parallel enrichment added the utilities/PCB/materials names), so
81 were logoless. Six agents ran on DISJOINT slices; the no-conflict design that worked: agents may
write ONLY `static/logos/<their own node id>.<ext>` + their own result JSON, and the PARENT is the
sole writer of manifest.json (same single-writer principle as apply_patches.py). Zero collisions,
zero out-of-slice claims. Pre-match the companieslogo sitemap ONCE centrally and hand slices out;
six agents each downloading 3.8 MB is waste + rate-limit risk.

NEW SOURCES that broke walls previous sessions called exhausted:
- **companieslogo has a SEARCH API**: `POST https://companieslogo.com/search` with
  `query=<q>&isLoggedIn=false` -> JSON {name,url,iconUrl}. Far better than grepping the sitemap.
- **TWSE/TPEx `openapi` listed-company tables** + **cninfo topSearch**: ticker -> official company
  name + official homepage, straight from the exchange. This is regulator-grade identity proof and
  it cracked the whole TW/CN slice (companieslogo and Wikidata are BOTH empty for those 17 names).
- **DART's `company.json`** returns each Korean filer's homepage keyed by corp_code, so
  `stock_code == node ticker` proves the domain. It corrected three wrong domains: Wonik IPS is
  **ips.co.kr** (not wonik-ips.com), PSK Holdings **pskholding.com** vs PSK Inc. **pskinc.com**,
  AD Technology **adtek.co.kr**.
- **TLS certificate `O=` field** as identity proof — Zhen Ding and Raytek were confirmed this way.
  (Both sites ship an incomplete chain; fetch the AIA caIssuers intermediate rather than disabling
  verification, which stays forbidden.)
- Korean site tricks: the **`/m/` mobile skin** often carries a 2-3x bigger logo than desktop
  (EO Technics 410px vs 157px); the **`/company/ci` page** carries the full-res CI asset (ISC 842px
  vs 288px); **CSS `url()` mining** finds logos never present in `<img>` (Wonik QnC). Official
  **CI-kit .zip files** contain source `.ai` that renders huge (SK Siltron 1897x881).
- **JSR Corporation is DELISTED** (taken private, ex-TSE 4185) — that is why companieslogo has no
  entry. Got it from the corporate site's og:image. Highest-value node, 13 chains.

RASTERIZER: the "no rasterizer on this box" rule is DEAD — **headless Chrome and Edge are both
installed** (`chrome.exe --headless --screenshot=out.png --window-size=W,H file:///page.html`).
Build ONE html grid of every logo as data: URIs and screenshot it: one invocation renders SVG
faithfully and gives a contact sheet to Read. This is now the correct way to verify logos.

TWO BUG CLASSES the old structural check could not see, both found this run and both FIXED:
1. **XML well-formedness.** `Reflection.svg` carried valueless Vue attrs (`data-v-9f264b4c`), legal
   in HTML but ILLEGAL in XML — and the app loads logos as `img.src`, which parses as XML. It had
   been a broken image in the live app since commit f1ce494 while passing every structural check.
   Run `xml.etree.ElementTree.parse()` over every .svg. (Also: `viewbox` must be `viewBox` —
   attribute names are case-sensitive in XML; Credo.svg has the same lowercase typo but renders
   because it also sets width/height.)
2. **Wrong `bg`.** Chip colours are `#fff` (light) and `#14171c` (dark), from globals.css
   `.nlogo`/`.logochip`. Render every logo on BOTH and compare CONTRAST — not "is any ink visible",
   which passes navy-on-black. Even the contrast metric misses a logo whose accent is bright but
   whose wordmark is dark (SoftBank's bars are silver, its wordmark is black), so LOOK at the
   bg:"dark" set. Found + fixed 4 invisible ones: **Ayar Labs, SoftBank, Camtek, Thinking Machines
   Lab** were all bg:"dark" and unreadable on a dark chip -> flipped to "light". Note this REVERSES
   last session's note that SoftBank must be bg:"dark".
   Still low-contrast but visible, left alone: Sumitomo Bakelite (pale green on white), X-Fab.

SIZE BAR: the old >=1080 rule was rejecting correct logos for no user-visible benefit — chips render
~26-56px tall. Bar used this run: prefer SVG, else >=300px, and take a smaller official asset with
`low_res: true` rather than shipping an empty chip. Installed at 119-270px: AD Technology 222x38,
Simmtech 237x47, Soulbrain 183x35, Techwing 124x31, Mirae Industry 119x32 — all legible, checked on
both chips. A white-boxed (no-alpha) logo is FINE on the light chip because that chip is white;
only key white->transparent when the mark has no white knockout inside it (safe for Techwing; NOT
safe for JSR/Dongjin/Sakai/WUS, whose marks carry white text inside a coloured box).

STILL MISSING (4, all genuinely unresolvable, do not retry blindly): **KOACC** (SPC incorporated
2026-06-10, no web presence at all), **SK Trichem** (sktrichem.com is a parked domain-for-sale
page), **YJ Semi** (no company brands itself that way; likely Yuanjie 源杰 688498.SH but that is
name-token inference — and 扬杰科技 really does market as "YJ" while making power discretes, so the
trap is live), **ASADA** (two real ASADAs and neither matches the node's "isostatic lamination
press" description — the NODE may be mis-specified).

DATA ISSUES surfaced (reported, NOT changed - user owns curation): node `Raytec Semiconductor` vs
the company's actual spelling **Raytek**; `Robotechnik` is metadata'd DE/private but is really
ChiNext **300757** (Suzhou; German arm ficonTEC). VPEC's ticker was wrong (6729.TW) and the other
session corrected it to **2455.TW** independently, matching what the TWSE registry gave us.

BATCH 2026-09-10 (+38 = every new US-listed node from commit ee2a20f; manifest 310 -> 348;
coverage 347/351 = 98.9%; 0 merge rejections, 0 misses). Repo now lives at
C:/Users/calif/Desktop/earnings-ai; the old OneDrive path is an EMPTY folder and the Bash tool's cwd
resets there after every call, so cd in every command and give agents absolute paths.
- Recipe that worked: 4 agents on disjoint sector slices (exact-cover assert), protocol file in the
  job tmp dir, agents write ONLY static/logos/<node id>.<ext> + their own results JSON; parent is the
  single writer of manifest.json through a merge script with guards (slice ownership, filename base ==
  node id, SVG must parse as XML). Review each agent as it lands (merge --dry + a light/dark chip
  contact sheet) so a bad file can still be fixed while the others run.
- Python trap: in Git Bash `python` is 3.11 WITHOUT Pillow. `python3` / `py` are 3.14.3 with Pillow,
  requests, curl_cffi, certifi. Tell parallel agents up front and forbid pip install (shared interpreter).
- Ticker proof must be ticker AND name. Recycled tickers: `Q` was Quintiles before Qnity Electronics;
  `ESI` was ITT Educational / ITT Tech before Element Solutions. Renames found live on the company sites:
  Pure Storage is now **Everpure, Inc., NYSE: P** (purestorage.com -> everpuredata.com, Sept 2026);
  Cipher Mining is now **Cipher Digital Inc.** (still CIFR; ciphermining.com -> cipherdigital.com);
  Penguin Solutions was SGH; Hut 8's current mark is in its brand-assets ZIP; Entergy has a new 2024 "e".
- Wikidata P154 is often a RETIRED logo for US names (Generac, Hubbell, AAON, Sanmina-SCI, Platform
  Specialty for Element Solutions, old SPX Corp, BHGE for Baker Hughes). Confirm against the site header.
- companieslogo lags renames: Sterling Infrastructure sits under slug `sterling-construction`; Galaxy
  Digital only has Frankfurt 7LX.F; `hut-8-mining` is the pre-merger company. qnity.com is an unrelated
  salon consultancy (Qnity Electronics = qnityelectronics.com).
- New defect class: an SVG with heavy built-in padding draws a third the size of its neighbours
  (Cipher's IR file). Chrome getBBox was fooled by an invisible full-size element, so the fix was the
  site's tight header SVG. Look at relative ink size on the contact sheet, not just correctness.
- White-only official assets are common on US IR sites (Talen, Oklo, Advanced Energy, Comfort Systems,
  Powell, Cipher) -> bg "dark" is right; do not substitute unconfirmed recolours.
- Make intrinsic size explicit on new SVGs: added viewBox to Comfort Systems USA (had only width/height)
  and width/height to Cipher (had only viewBox). 41 older SVGs lack a viewBox but render fine in Chrome;
  left alone.
- Wikimedia Commons file host returned 429 for most of the run with 4 agents; companieslogo + company
  sites were enough. Do not put the user's email in request headers (the 09-07 protocol did; v2 removed it).
- Surfaced, NOT changed (user owns naming/metadata): node + metadata still say Pure Storage / PSTG and
  Cipher Mining; Powell exchange (Wikidata Nasdaq vs metadata NYSE); Talen and Baker Hughes (Wikidata
  NYSE vs metadata NASDAQ, unverified); stale manifest key xAI (node removed from the graph).
  Pre-existing low contrast still flagged: Sumitomo Bakelite (pale green on white), X-Fab.
- RESOLVED 2026-09-10 (user: resolve them yourself): nodes renamed `Everpure` (metadata ticker P) and
  `Cipher Digital`; logo manifest keys and files renamed. Exchanges checked on the Nasdaq quote API
  and stockanalysis.com (they agree): Powell Industries is NASDAQ, so its metadata was fixed; Talen
  Energy and Baker Hughes were already NASDAQ in metadata (Wikidata is stale). See [[naming-rules]].

2026-09-16: +SK Telecom (new node) — companieslogo search API → slug `sk-telecom`, ticker SKM (NYSE ADR of 017670.KS) proves identity; `SKM_BIG-eccab257.svg` (SK butterfly + 'telecom' wordmark), XML-valid, readable on both chips, bg light. Manifest 349.
