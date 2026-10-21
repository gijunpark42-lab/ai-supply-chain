"""
dod_contracts.py — U.S. Department of Defense daily contract announcements that name our companies →
transcripts/dod/*.txt, queued for the enrich loop.

Why this exists
---------------
Every business day the Department of Defense (since September 2025 also styled "Department of War") publishes ONE
page listing every contract it awarded that day worth $7.5 million or more, grouped by service (Army, Navy, Air
Force, Defense Logistics Agency, ...). Each award is one paragraph: the contractor's name and location, the amount,
the contract type and number, what it buys, where the work is done, the completion date and the contracting activity.
It is the government's own official record, so it is saved verbatim. Many graph companies win these awards —
Northrop Grumman, L3Harris, SpaceX ("Space Exploration Technologies Corp."), Rocket Lab, Microsoft, Amazon, Google,
Oracle, IBM, Honeywell, Keysight, utilities and power suppliers (DLA Energy) ...

A DoD award is NOT a transcript and NOT a company document: it is the customer's record of an order. Enrich it as a
fact on the winner's node (amount, program, completion date, contracting activity) and record the agency as a
government customer in relations/ (scope "other"; agencies are never nodes) — `.claude/skills/enrich/references/dod.md`.

Commands (python -X utf8 dod_contracts.py …)
--------------------------------------------
    sync [--since YYYY-MM-DD] [--company "<Company>" …]   read every new announcement day, save + queue our awards
    pending [--company "<Company>"] [--market US]       the queue
    done --label "<label>" [--why …]                    one file handled — enriched, or `--why "no material facts"`
    done --all                                          every queued file handled (only when that is true)
    status [--company "<Company>"]                      every file saved and its state, plus the days read
    unmatched                                           big awardees that are not graph companies, and names that
                                                        LOOK like a graph company but are not matched (alias review)

Files
-----
    transcripts/dod/<slug>_<YYYY-MM-DD>.txt   one file per company per announcement day: header + the award
                                              paragraph(s) naming it, verbatim, each under its service heading
    dod/sync_state.json   last sync, runs, every announcement day seen {date, url, title, status = saved / skip:<why> /
                          later:<why>, companies matched, entities skipped}, every file saved with its state, the big
                          unmatched awardees and the near-misses
    dod/pending.json      saved files not yet enriched

How war.gov answers (found 2026-10-21)
--------------------------------------
defense.gov redirects to www.war.gov. The site sits behind Akamai:
  - the contracts RSS feed answers plain requests:
        https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max=200
    (one item per announcement day, newest first; max=200 reaches back ~9 months);
  - the day pages (…/News/Contracts/Contract/Article/<id>/contracts-for-oct-20-2026/) and the list page answer
    403 "Access Denied" to scripts, even with full browser headers. They are read through Jina Reader
    (https://r.jina.ai/<URL>, header X-Return-Format: html), which returns the rendered page — the same HTML a browser
    gets. Each script run first tries war.gov directly once; after a 403 it uses Jina for the rest of the run.
  - If the RSS ever fails, the list page (10 days per page, ?Page=N) is read through Jina instead.
  - The announcement day is the RSS publication day in US Eastern time, not the title: on 2026-09-29 the Sept. 29
    awards went up twice, first titled "Contracts for Sept. 28, 2026". Saved paragraphs are fingerprinted, so a
    re-posted page adds nothing twice.
Day page HTML: <div class="body"> holds <p> paragraphs; a service heading is a centred <p><strong>ARMY</strong></p>;
an award is one <p>; "*" after a name marks a small business (footnote "* Small Business" at the end).
Jina's anonymous limit is about 20 requests a minute: one request every 3.5 s, retries with a growing wait.

Matching contractor names to graph companies (never a guess)
------------------------------------------------------------
Only the CONTRACTOR position of a paragraph is matched — the names before "is awarded / was awarded / have been
awarded" (several awardees are separated by ";"), or after "to" / "for" in a CORRECTION — never a company named in the
description ("for Boeing F/A-18 spares"). Each name is compared at its start with the curated ALIASES table below:
legal entity names ("Northrop Grumman Systems Corp.", "Space Exploration Technologies Corp."), and a few wholly owned
subsidiaries whose ownership is certain (Aerojet Rocketdyne → L3Harris, Constellation NewEnergy → Constellation
Energy, Direct Energy Business → NRG Energy). Names that look like a node but are another company (General Electric Co.
= GE Aerospace, not GE Vernova; Vertex Aerospace ≠ Vertex) sit in NOT_NODES. A name that starts with a graph company's
name but matches no alias is never saved — it is listed by `unmatched` as a near-miss for a human to review.
A joint venture whose name contains a graph company ("Fluor-X JV") is not the company: skipped and recorded.
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from taxonomy import market_of

ROOT = Path(__file__).resolve().parent
META = ROOT / "company_metadata.json"
STATE = ROOT / "dod" / "sync_state.json"
PENDING = ROOT / "dod" / "pending.json"
OUT_DIR = ROOT / "transcripts" / "dod"

RSS = "https://www.war.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max=200"
LIST_PAGE = "https://www.war.gov/News/Contracts/?Page={page}"
JINA = "https://r.jina.ai/"
# One announcement day's page: …/Article/<id>/contracts-for-oct-20-2026/ (a few slugs say "sept", one covered
# "feb-2-2026-through-feb-4-2026").
ARTICLE_URL = re.compile(r"https?://(?:www\.)?(?:war|defense)\.gov/News/Contracts/Contract/Article/(\d+)/"
                         r"(contracts-for-[a-z0-9-]+?)/?(?=[\s<\"')\]]|$)", re.I)
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"), 1)}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
BROWSER_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none",
                   "Upgrade-Insecure-Requests": "1"}

FIRST_DAYS = 120           # the first sync reaches back this many days
RESYNC_OVERLAP = 3         # a later sync re-lists this many days before the last sync (pages already read are skipped)
PAUSE = 3.5                # seconds between two requests (Jina's anonymous limit is ~20 a minute)
RUN_BUDGET_MIN = 45        # stop reading new pages after this many minutes; the next run continues
MAX_TRIES = 3              # a page that keeps failing to parse is given up after this many runs
BIG_AWARD = 100_000_000    # an unmatched awardee at or above this amount is reported by `unmatched`


# ---------------------------------------------------------------- the alias table
# (pattern, graph company, note). The pattern is matched at the START of a contractor name (an optional "The " is
# allowed before it), case-insensitively, and must end on a word boundary. The FIRST matching row wins, so a more
# specific row (Honeywell Aerospace, Siemens Energy) comes before the general one (Honeywell, Siemens).
# A note explains every name that is not simply the company's own name; it is written into the saved file's header.
# Add a row only when the legal entity is certainly that company (its own name, or a wholly owned subsidiary).
ALIASES = [
    # --- defense, space, government services
    (r"Northrop Grumman", "Northrop Grumman", None),
    (r"L3Harris|L3 Harris|L-3 Harris", "L3Harris", None),
    (r"L-?3 (?:Technologies|Communications)", "L3Harris",
     "L3 Technologies (formerly L-3 Communications) merged with Harris Corp. into L3Harris in 2019"),
    (r"Harris Corp(?:oration)?", "L3Harris", "Harris Corp. merged with L3 Technologies into L3Harris in 2019"),
    (r"Aerojet Rocketdyne", "L3Harris", "Aerojet Rocketdyne has been a wholly owned L3Harris subsidiary since July 2023"),
    (r"Space Exploration Technologies|SpaceX", "SpaceX", "Space Exploration Technologies Corp. is SpaceX's legal name"),
    (r"Rocket Lab", "Rocket Lab", None),
    (r"Blue Origin", "Blue Origin", None),
    (r"United Launch Alliance", "United Launch Alliance", None),
    (r"United Launch Services", "United Launch Alliance",
     "United Launch Services LLC is United Launch Alliance's contracting entity"),
    (r"Planet Labs", "Planet Labs", None),
    (r"AST SpaceMobile", "AST SpaceMobile", None),
    (r"AST & Science", "AST SpaceMobile", "AST & Science LLC is AST SpaceMobile's operating subsidiary"),
    (r"Axiom Space", "Axiom Space", None),
    (r"Kepler Communications", "Kepler Communications", None),
    (r"ArianeGroup", "ArianeGroup", None),
    (r"Starcloud", "Starcloud", None),
    (r"Davidson Technologies", "Davidson Technologies", None),
    (r"Thales", "Thales", None),
    (r"Rolls[- ]Royce", "Rolls-Royce", None),
    (r"Honeywell Aerospace", "Honeywell Aerospace", None),
    (r"Honeywell", "Honeywell",
     "Honeywell's aerospace business has been the separate company Honeywell Aerospace since 06-29-2026; this file "
     "follows the name DoD printed (Honeywell International Inc. is the Honeywell parent's legal name) — never re-file "
     "it under Honeywell Aerospace, and name the entity as printed in the entry"),
    (r"Deloitte", "Deloitte", None),
    (r"Unisys", "Unisys", None),
    # --- cloud, software, AI
    (r"Microsoft", "Microsoft", None),
    (r"Amazon Web Services|Amazon\.com", "Amazon", None),
    (r"Google", "Google", None),
    (r"Oracle (?:America|Corp|USA|Federal|National Security|Inc)", "Oracle", None),
    (r"International Business Machines|IBM", "IBM", None),
    (r"Meta Platforms", "Meta", None),
    (r"Apple Inc", "Apple", None),
    (r"Adobe (?:Inc|Systems)", "Adobe", None),
    (r"OpenAI", "OpenAI", None),
    (r"Anthropic", "Anthropic", None),
    (r"Cohere Inc", "Cohere", None),
    (r"Perplexity AI", "Perplexity", None),
    (r"Mistral AI", "Mistral", None),
    (r"CrowdStrike", "CrowdStrike", None),
    (r"Palo Alto Networks", "Palo Alto Networks", None),
    (r"Cloudflare", "Cloudflare", None),
    (r"Akamai", "Akamai Technologies", None),
    (r"Fortanix", "Fortanix", None),
    (r"Utimaco", "Utimaco", None),
    (r"Tesla (?:Inc|Motors)", "Tesla", None),
    (r"Uber Technologies", "Uber", None),
    (r"Mastercard", "Mastercard", None),
    # --- compute, networks, data centers
    (r"Hewlett[- ]Packard Enterprise", "HPE", None),
    (r"Juniper Networks", "HPE", "Juniper Networks has been a wholly owned HPE subsidiary since July 2025"),
    (r"Dell (?:Federal|Marketing|Technologies|Inc|Products|EMC)", "Dell", None),
    (r"Super Micro Computer|Supermicro", "Supermicro", None),
    (r"Cisco", "Cisco", None),
    (r"Arista Networks", "Arista", None),
    (r"NetApp", "NetApp", None),
    (r"Penguin Solutions", "Penguin Solutions", None),
    (r"Penguin Computing", "Penguin Solutions", "Penguin Computing is a wholly owned Penguin Solutions (formerly SMART "
                                               "Global Holdings) subsidiary"),
    (r"Cerebras", "Cerebras", None),
    (r"SambaNova", "SambaNova", None),
    (r"Groq", "Groq", None),
    (r"Lumen Technologies", "Lumen Technologies", None),
    (r"CenturyLink", "Lumen Technologies", "CenturyLink renamed itself Lumen Technologies in 2020"),
    (r"Level 3 (?:Communications|Parent)", "Lumen Technologies", "Level 3 is a wholly owned Lumen Technologies subsidiary"),
    (r"Nokia", "Nokia", None),
    (r"Ciena", "Ciena", None),
    (r"Iron Mountain (?:Inc|Incorporated|Information Management|Data Centers)", "Iron Mountain", None),
    (r"Equinix", "Equinix", None),
    (r"Digital Realty", "Digital Realty", None),
    (r"CoreWeave", "CoreWeave", None),
    (r"Crusoe Energy", "Crusoe", None),
    (r"Applied Digital", "Applied Digital", None),
    (r"IonQ", "IonQ", None),
    (r"Rigetti", "Rigetti Computing", None),
    (r"D-Wave", "D-Wave Quantum", None),
    (r"Quantinuum", "Quantinuum", None),
    (r"PsiQuantum", "PsiQuantum", None),
    (r"Infleqtion", "Infleqtion", None),
    (r"ColdQuanta", "Infleqtion", "ColdQuanta renamed itself Infleqtion in 2022"),
    (r"QuEra", "QuEra Computing", None),
    (r"Xanadu Quantum", "Xanadu", None),
    (r"Quantum Computing Inc", "Quantum Computing Inc", None),
    # --- semiconductors, components, test
    (r"NVIDIA", "NVIDIA", None),
    (r"Intel (?:Corp|Federal)", "Intel", None),
    (r"Advanced Micro Devices", "AMD", None),
    (r"Qualcomm", "Qualcomm", None),
    (r"Micron Technology", "Micron", None),
    (r"GlobalFoundries", "GlobalFoundries", None),
    (r"Analog Devices", "Analog Devices", None),
    (r"Texas Instruments", "Texas Instruments", None),
    (r"Microchip Technology", "Microchip Technology", None),
    (r"Microsemi", "Microchip Technology", "Microsemi has been a wholly owned Microchip Technology subsidiary since 2018"),
    (r"Broadcom", "Broadcom", None),
    (r"Marvell", "Marvell", None),
    (r"Wolfspeed", "Wolfspeed", None),
    (r"Skyworks", "Skyworks Solutions", None),
    (r"MACOM", "MACOM", None),
    (r"Lattice Semiconductor", "Lattice Semiconductor", None),
    (r"ON Semiconductor|onsemi", "onsemi", None),
    (r"Infineon", "Infineon", None),
    (r"STMicroelectronics", "STMicroelectronics", None),
    (r"Coherent (?:Corp|Inc|Aerospace)", "Coherent", None),
    (r"II-VI", "Coherent", "II-VI Inc. renamed itself Coherent Corp. in 2022"),
    (r"Lumentum", "Lumentum", None),
    (r"Corning Inc", "Corning", None),
    (r"Keysight", "Keysight", None),
    (r"Viavi", "Viavi", None),
    (r"Teradyne", "Teradyne", None),
    (r"Applied Materials", "Applied Materials", None),
    (r"Lam Research", "Lam Research", None),
    (r"KLA Corp", "KLA", None),
    (r"MKS Instruments", "MKS Instruments", None),
    (r"Entegris", "Entegris", None),
    (r"Amphenol", "Amphenol", None),
    (r"TE Connectivity", "TE Connectivity", None),
    (r"Bel Fuse", "Bel Fuse", None),
    (r"Littelfuse", "Littelfuse", None),
    (r"Vishay", "Vishay", None),
    (r"Jabil", "Jabil", None),
    (r"Celestica", "Celestica", None),
    (r"Sanmina", "Sanmina", None),
    (r"Flex Ltd|Flextronics", "Flex", None),
    (r"TTM Technologies", "TTM Technologies", None),
    (r"Amkor", "Amkor Technology", None),
    (r"Materion", "Materion", None),
    (r"MP Materials", "MP Materials", None),
    (r"Lynas", "Lynas Rare Earths", None),
    (r"Umicore", "Umicore", None),
    (r"5N Plus", "5N Plus", None),
    (r"Taiwan Semiconductor Manufacturing", "TSMC", None),
    (r"Samsung Electronics", "Samsung", None),
    (r"LG Electronics", "LG Electronics", None),
    (r"Panasonic", "Panasonic Holdings", None),
    (r"Fujitsu", "Fujitsu", None),
    (r"NEC Corp", "NEC", None),
    (r"Kyocera", "Kyocera", None),
    (r"Lenovo", "Lenovo", None),
    (r"Mitsubishi Heavy Industries", "Mitsubishi Heavy Industries", None),
    (r"Mitsubishi Electric", "Mitsubishi Electric", None),
    (r"Sumitomo Electric", "Sumitomo Electric", None),
    (r"Mitsui & Co", "Mitsui & Co.", None),
    (r"Hitachi Energy", "Hitachi Energy", None),
    # --- industrial, power equipment, materials
    (r"GE Vernova", "GE Vernova", None),
    (r"Siemens Energy", "Siemens Energy", None),
    (r"Siemens Healthineers|Siemens Medical Solutions", "Siemens Healthineers", None),
    (r"Siemens", "Siemens", None),
    (r"ABB (?:Inc|Ltd|Motors|Enterprise)", "ABB", None),
    (r"Schneider Electric", "Schneider Electric", None),
    (r"Eaton (?:Corp|Aerospace|Electrical)", "Eaton", None),
    (r"Eaton Mission Systems", "Eaton", "Eaton Mission Systems (formerly Cobham Mission Systems) has been an Eaton "
                                        "business since June 2021"),
    (r"Emerson (?:Electric|Process|Automation)", "Emerson", None),
    (r"Johnson Controls", "Johnson Controls", None),
    (r"Carrier (?:Corp|Global)", "Carrier Global", None),
    (r"Trane (?:U\.S|US|Technologies|Inc)", "Trane Technologies", None),
    (r"Vertiv", "Vertiv", None),
    (r"Hubbell", "Hubbell", None),
    (r"nVent", "nVent", None),
    (r"Legrand", "Legrand", None),
    (r"Regal Rexnord", "Regal Rexnord", None),
    (r"Rockwell Automation", "Rockwell Automation", None),
    (r"Powell Industries", "Powell Industries", None),
    (r"Generac", "Generac", None),
    (r"Cummins", "Cummins", None),
    (r"Caterpillar", "Caterpillar", None),
    (r"W[aä]rtsil[aä]", "Wärtsilä", None),
    (r"Babcock (?:&|and) Wilcox", "Babcock & Wilcox", None),
    (r"Bloom Energy", "Bloom Energy", None),
    (r"FuelCell Energy", "FuelCell Energy", None),
    (r"EnerSys", "EnerSys", None),
    (r"Fluence Energy", "Fluence Energy", None),
    (r"Baker Hughes", "Baker Hughes", None),
    (r"Atlas Copco", "Atlas Copco", None),
    (r"Alfa Laval", "Alfa Laval", None),
    (r"Modine", "Modine", None),
    (r"Munters", "Munters", None),
    (r"AAON", "AAON", None),
    (r"SPX Technologies", "SPX Technologies", None),
    (r"Dover Corp", "Dover", None),
    (r"Gates (?:Corp|Industrial)", "Gates Industrial", None),
    (r"Nordson", "Nordson", None),
    (r"3M (?:Co|Company)", "3M", None),
    (r"Linde (?:Inc|Gas|LLC|plc)", "Linde", None),
    (r"Air Products", "Air Products", None),
    (r"(?:American )?Air Liquide", "Air Liquide", None),
    (r"Solstice Advanced Materials", "Solstice Advanced Materials", None),
    # --- engineering, construction (rule B: data-center / grid contractors)
    (r"Fluor", "Fluor", None),
    (r"Jacobs Engineering Group|Jacobs Solutions", "Jacobs Solutions", None),
    (r"EMCOR", "EMCOR", None),
    (r"Comfort Systems", "Comfort Systems USA", None),
    (r"Quanta Services", "Quanta Services", None),
    (r"MasTec", "MasTec", None),
    (r"Primoris", "Primoris Services", None),
    (r"Sterling Infrastructure", "Sterling Infrastructure", None),
    (r"Dycom", "Dycom", None),
    (r"IES Holdings", "IES Holdings", None),
    (r"MYR Group", "MYR Group", None),
    (r"Argan", "Argan", None),
    # --- energy suppliers and utilities (DLA Energy supply contracts, utility privatization)
    (r"Constellation Energy", "Constellation Energy", None),
    (r"Constellation NewEnergy", "Constellation Energy",
     "Constellation NewEnergy is Constellation Energy's retail power and gas supply subsidiary"),
    (r"NRG (?:Energy|Business)", "NRG Energy", None),
    (r"Direct Energy (?:Business|Services)", "NRG Energy",
     "Direct Energy has been a wholly owned NRG Energy subsidiary since January 2021"),
    (r"Vistra", "Vistra", None),
    (r"Talen Energy", "Talen Energy", None),
    (r"NextEra Energy", "NextEra Energy", None),
    (r"Florida Power (?:&|and) Light", "NextEra Energy", "Florida Power & Light is NextEra Energy's utility subsidiary"),
    (r"Duke Energy", "Duke Energy", None),
    (r"Dominion Energy", "Dominion Energy", None),
    (r"Virginia Electric (?:&|and) Power", "Dominion Energy",
     "Virginia Electric and Power Co. (Dominion Energy Virginia) is Dominion Energy's utility subsidiary"),
    (r"Southern Company|Southern Co\b(?!\.? (?:Inc|LLC))", "Southern Company", None),
    (r"Georgia Power|Alabama Power|Mississippi Power", "Southern Company",
     "Georgia Power, Alabama Power and Mississippi Power are Southern Company's utility subsidiaries"),
    (r"American Electric Power", "American Electric Power", None),
    (r"Appalachian Power|Indiana Michigan Power|Southwestern Electric Power|Public Service Co(?:mpany|\.)? of Oklahoma|"
     r"AEP Texas", "American Electric Power",
     "Appalachian Power, Indiana Michigan Power, SWEPCO, PSO and AEP Texas are AEP's utility subsidiaries"),
    (r"Xcel Energy", "Xcel Energy", None),
    (r"Public Service Co(?:mpany|\.)? of Colorado|Northern States Power|Southwestern Public Service", "Xcel Energy",
     "Public Service Co. of Colorado, Northern States Power and Southwestern Public Service are Xcel Energy's utility "
     "subsidiaries"),
    (r"Entergy", "Entergy", None),
    (r"Exelon", "Exelon", None),
    (r"Baltimore Gas (?:&|and) Electric|Potomac Electric Power|PECO Energy|Commonwealth Edison|Delmarva Power|"
     r"Atlantic City Electric", "Exelon", "BGE, Pepco, PECO, ComEd, Delmarva Power and Atlantic City Electric are Exelon's "
                                         "utility subsidiaries"),
    (r"Eversource", "Eversource", None),
    (r"NSTAR|Connecticut Light (?:&|and) Power|Public Service Co(?:mpany|\.)? of New Hampshire", "Eversource",
     "NSTAR Electric, Connecticut Light and Power and Public Service Co. of New Hampshire are Eversource's utility "
     "subsidiaries"),
    (r"NiSource|Northern Indiana Public Service", "NiSource", None),
    (r"WEC Energy|Wisconsin Electric Power|We Energies", "WEC Energy Group", None),
    (r"Puget Sound Energy", "Puget Sound Energy", None),
    (r"Shell (?:Energy|Trading|Oil|Aviation|Marine|Offshore|USA|International)", "Shell", None),
    (r"Saudi Arabian Oil|Saudi Aramco", "Saudi Aramco", None),
    (r"Motiva Enterprises", "Saudi Aramco", "Motiva Enterprises has been wholly owned by Saudi Aramco since 2017"),
    (r"Oklo", "Oklo", None),
    (r"NuScale", "NuScale Power", None),
    (r"X-?Energy", "X-Energy", None),
    (r"TerraPower", "TerraPower", None),
    (r"Brookfield Renewable", "Brookfield Renewable", None),
    # --- pharma / biotech (DLA Troop Support medical buys)
    (r"Pfizer", "Pfizer", None),
    (r"Merck Sharp (?:&|and) Dohme|Merck (?:&|and) Co", "Merck & Co.", None),
    (r"EMD (?:Millipore|Serono|Electronics)|MilliporeSigma|Merck KGaA", "Merck KGaA",
     "EMD / MilliporeSigma is the name Merck KGaA uses in the United States"),
    (r"Eli Lilly", "Eli Lilly", None),
    (r"AstraZeneca", "AstraZeneca", None),
    (r"Bristol[- ]Myers Squibb", "Bristol Myers Squibb", None),
    (r"Sanofi", "Sanofi", None),
    (r"Amgen", "Amgen", None),
    (r"Novo Nordisk", "Novo Nordisk", None),
    (r"Genentech", "Roche-Genentech", None),
    (r"Moderna", "Moderna", None),
    (r"Bayer", "Bayer", None),
    (r"Illumina", "Illumina", None),
    (r"Ginkgo Bioworks", "Ginkgo Bioworks", None),
    (r"Twist Bioscience", "Twist Bioscience", None),
    (r"Pacific Biosciences", "Pacific Biosciences", None),
    (r"Tempus (?:AI|Labs)", "Tempus AI", None),
    (r"Medpace", "Medpace", None),
]

# Names that look like a graph company but are a different company — never matched, never a near-miss.
NOT_NODES = [
    (r"General Electric", "GE Aerospace (its legal name is General Electric Co.) — not GE Vernova"),
    (r"GE (?:Aerospace|Aviation)", "GE Aerospace — not a graph company, not GE Vernova"),
    (r"Vertex (?:Aerospace|Modernization)", "V2X's aircraft-maintenance units — not Vertex (Vertex Pharmaceuticals)"),
    (r"Tesla Industries", "a ground-power-unit maker in Delaware — not Tesla"),
    (r"Iron Mountain Solutions", "a Huntsville, Alabama engineering-services firm — not Iron Mountain"),
    (r"Arista Aviation", "an aviation-services firm — not Arista (Arista Networks)"),
    (r"Coherent Technical", "Coherent Technical Services, a federal IT contractor — not Coherent"),
    (r"Emerson Construction", "a construction firm — not Emerson (Emerson Electric)"),
    (r"Nova Group", "a Napa, California construction firm — not Nova"),
    (r"Cadence Aerospace", "an aerostructures supplier — not Cadence (Cadence Design Systems)"),
    (r"Rockwell Collins", "Collins Aerospace (RTX) — not Rockwell Automation"),
    (r"BWX Technologies|BWXT", "BWX Technologies — not Babcock & Wilcox"),
    (r"Wesco Aircraft", "Incora — not Wesco"),
    (r"Jacobs Technology", "part of Amentum since the September 2024 spin-off — not Jacobs Solutions"),
    (r"Fermi Research Alliance", "the Fermilab operator — not Fermi"),
]

# Names that need a human look before they get an alias (listed by `unmatched` as near-misses with this note).
REVIEW = [
    (r"Jacobs\b", "Jacobs Solutions",
     "Jacobs-named entity: Jacobs Technology / Jacobs Government Services went to Amentum in September 2024 — check "
     "the entity before adding an alias"),
    (r"Quanta Government Solutions", "Quanta Services",
     "possibly a Quanta Services subsidiary (microgrid / power construction) — confirm the ownership before adding an "
     "alias; certainly not Quanta (Quanta Computer)"),
]


def _compile(pattern):
    """A table pattern → a regex anchored at the start of a name (optional "The "), ending on a word boundary."""
    return re.compile(r"(?:the\s+)?(?:%s)(?![A-Za-z0-9])" % pattern, re.I)


ALIAS_RES = [(_compile(p), node, note) for p, node, note in ALIASES]
NOT_NODE_RES = [(_compile(p), why) for p, why in NOT_NODES]
REVIEW_RES = [(_compile(p), node, note) for p, node, note in REVIEW]


# ---------------------------------------------------------------- small helpers

def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def new_state():
    return {"last_sync": None, "runs": [], "seen": {}, "files": {}, "para_keys": {}, "unmatched": {}, "near_miss": {}}


def para_key(company, para):
    """A short fingerprint of one award paragraph for one company. Letters, digits and "$" only, so a re-posted
    page whose copy differs by an invisible character (a non-breaking space or hyphen) gives the same key."""
    norm = re.sub(r"[^a-z0-9$]", "", para.lower())
    return hashlib.sha1(f"{company}|{norm}".encode("utf-8")).hexdigest()[:16]


def check_aliases(meta):
    """Every alias must point at a graph company, spelled exactly as in company_metadata.json — the label prefix
    must be the node name (enrich skill §5)."""
    bad = sorted({node for _p, node, _n in ALIASES if node not in meta})
    if bad:
        sys.exit(f"ALIASES name companies that are not in company_metadata.json: {bad} — fix the table first")


_session = requests.Session()
_last = [0.0]
_direct_blocked = [False]          # war.gov answered 403 once in this run → use Jina for every later page


def _polite():
    wait = PAUSE - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def fetch(url, headers=None, timeout=90):
    """GET politely; retry network errors, 429 (rate limit) and 5xx with a growing wait. Returns the response
    (any status) or None when every try failed on the network."""
    r = None
    for attempt in range(MAX_TRIES):
        _polite()
        try:
            r = _session.get(url, headers=headers or BROWSER_HEADERS, timeout=timeout)
            if r.status_code != 429 and r.status_code < 500:
                return r
        except requests.RequestException as e:
            print(f"  network error ({type(e).__name__}) on {url[:90]}")
        time.sleep(15 * (attempt + 1) ** 2)        # 15 s, 60 s, 135 s
    return r


def blocked(text):
    """True for Akamai's 'Access Denied' page (or an empty answer)."""
    return not text or "Access Denied" in text[:3000] or "errors.edgesuite.net" in text[:3000]


def get_html(url):
    """(html, via) for one war.gov page: straight from war.gov when it answers, else the rendered page through
    Jina Reader. (None, why) when neither works."""
    if not _direct_blocked[0]:
        r = fetch(url)
        if r is not None and r.status_code == 200 and not blocked(r.text):
            return r.text, "direct"
        _direct_blocked[0] = True
        print(f"  war.gov answered {r.status_code if r is not None else 'nothing'} to a direct request — "
              f"reading pages through Jina Reader for the rest of this run")
    r = fetch(JINA + url, headers={"User-Agent": UA, "X-Return-Format": "html"}, timeout=120)
    if r is not None and r.status_code == 200 and not blocked(r.text):
        return r.text, "jina"
    why = f"HTTP {r.status_code}" if r is not None else "network error"
    if r is not None and r.status_code == 200:
        why = "Jina returned war.gov's Access Denied page (Jina blocked too)"
    return None, why


# ---------------------------------------------------------------- the list of announcement days

def day_of(slug_month, day, year):
    """('oct', '20', '2026') → date(2026, 10, 20); None when the month word is not a month."""
    m = MONTHS.get(slug_month[:3].lower())
    try:
        return date(int(year), m, int(day)) if m else None
    except ValueError:
        return None


def last_date_in(text, pattern):
    """The LAST date written in a title ("Contracts for Feb. 2, 2026, Through Feb. 4, 2026" → Feb. 4) or a slug
    ("contracts-for-feb-2-2026-through-feb-4-2026"), or None."""
    found = [day_of(*m) for m in re.findall(pattern, text or "")]
    found = [d for d in found if d]
    return found[-1] if found else None


TITLE_DATE = r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s+(\d{4})"
SLUG_DATE = r"([a-z]{3,9})-(\d{1,2})-(\d{4})"


def list_days(start):
    """Every announcement day on or after `start`: [{id, date, url, title}], oldest first. The RSS feed first;
    the list page through Jina when the feed fails.

    The announcement day is the RSS publication time in US Eastern time (the pages go up ~5 pm ET). The title and
    the slug are only the fallback: on 2026-09-29 DoD posted the Sept. 29 awards under the title and slug "Contracts
    for Sept. 28, 2026" (article 4614322), then again correctly titled (4614270)."""
    days = {}

    def add(match, title=None, when=None):
        art_id, slug_ = match.group(1), match.group(2)
        when = when or last_date_in(title, TITLE_DATE) or last_date_in(slug_, SLUG_DATE)
        if when and art_id not in days:
            days[art_id] = {"id": art_id, "date": when.isoformat(),
                            "url": f"https://www.war.gov/News/Contracts/Contract/Article/{art_id}/{slug_}/",
                            "title": title or f"Contracts for {when.strftime('%b. %d, %Y')}"}

    r = fetch(RSS, headers={"User-Agent": UA})
    if r is not None and r.status_code == 200 and "<item>" in r.text:
        for item in re.findall(r"<item>(.*?)</item>", r.text, re.S):
            link = ARTICLE_URL.search(item)
            if not link:
                continue
            title = re.search(r"<title>\s*(.*?)\s*</title>", item, re.S)
            pub = re.search(r"<pubDate>\s*(.*?)\s*</pubDate>", item, re.S)
            try:                                              # GMT → US Eastern (standard time is close enough
                pub_day = (parsedate_to_datetime(pub.group(1)) - timedelta(hours=5)).date() if pub else None
            except (TypeError, ValueError):                   # for pages posted in the afternoon)
                pub_day = None
            add(link, title.group(1).strip() if title else None, pub_day)
        source = "RSS feed"
    else:
        print(f"RSS feed answered {r.status_code if r is not None else 'nothing'} — reading the list page through Jina")
        source = "list page via Jina"
        for page in range(1, 40):                            # 10 days per page; 40 pages = more than a year
            r = fetch(JINA + LIST_PAGE.format(page=page), headers={"User-Agent": UA}, timeout=120)
            if r is None or r.status_code != 200:
                break
            found = list(ARTICLE_URL.finditer(r.text))
            for m in found:
                add(m)
            dates = [d for d in (last_date_in(m.group(2), SLUG_DATE) for m in found) if d]
            if not dates or min(dates) < start:
                break
    rows = sorted((d for d in days.values() if d["date"] >= start.isoformat()), key=lambda d: (d["date"], d["id"]))
    oldest = min((d["date"] for d in days.values()), default=None)
    return rows, source, oldest


# ---------------------------------------------------------------- reading one day page

def paragraphs(html):
    """The day page's award paragraphs: [(service heading, paragraph text)], in page order. The text is the page's
    words exactly; only runs of white space are folded into one space (HTML line breaks)."""
    soup = BeautifulSoup(html, "html.parser")
    bodies = [d for d in soup.find_all("div", class_="body") if "contract" in d.get_text().lower()]
    if not bodies:
        return [], None
    body = max(bodies, key=lambda d: len(d.get_text()))
    for br in body.find_all("br"):
        br.replace_with("<<BR>>")
    h1 = soup.find("h1")
    title = re.sub(r"\s+", " ", h1.get_text()).strip() if h1 else None
    out, service = [], ""
    for p in body.find_all("p"):
        text = re.sub(r"\s+", " ", p.get_text()).strip()
        for chunk in text.split("<<BR>>"):
            chunk = chunk.strip()
            if not chunk or re.fullmatch(r"\*\s*Small Business\.?", chunk, re.I):
                continue                                      # the page footnote, not an award
            letters = re.sub(r"[^A-Za-z]", "", chunk)
            if len(chunk) <= 80 and letters and letters.isupper() and "$" not in chunk:
                service = chunk.strip("* ").upper()          # a service heading: ARMY, NAVY, DEFENSE LOGISTICS AGENCY
                continue
            out.append((service, chunk))
    return out, title


AWARD_VERB = re.compile(r"\b(?:awarded|modified|received|selected|added as|will compete|compete for)\b", re.I)
SEGMENT_SPLIT = re.compile(r";|\)\s*,|:\s")
LEAD = re.compile(r"^(?:(?:and|&)\s+|(?:UPDATE|CORRECTIONS?)\s*:?\s*|the following\b[^:]*:\s*)+", re.I)
# "Name, City, State" — what a contractor entry looks like ("Name,* City" for a small business)
ENTITY = re.compile(r"^(?P<name>[^,;()]{2,150}?)\s*,\*?\s+(?P<place>[A-Z][^,;()]{1,60}?),\*?\s+"
                    r"(?P<region>[A-Z][A-Za-z .'-]{1,40}?)\s*(?:[,;(]|$)")
AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)(?:\s*(million|billion))?", re.I)
JV = re.compile(r"\bJ\.?V\b|joint venture", re.I)


def usd(text):
    """The first dollar amount in a text as a number ($1.2 billion → 1.2e9), or None."""
    m = AMOUNT.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", "") or 0)
    return value * {"million": 1e6, "billion": 1e9}.get((m.group(2) or "").lower(), 1)


def contractor_entries(para):
    """The contractor entries of one award paragraph: [(name, segment text)]. Only the contractor position counts:
    the text before the award verb (several awardees are separated by ";"), or — in a CORRECTION / UPDATE, and when
    the list follows the verb ("The following companies are awarded …: A, City, State; B, …") — every segment that
    has the shape "Name, City, State"."""
    correction = bool(re.match(r"\s*(CORRECTION|UPDATE)", para, re.I))
    verb = AWARD_VERB.search(para)
    zone = para if correction or not verb else para[:verb.start()]
    pieces = SEGMENT_SPLIT.split(zone)
    if correction:                                            # "… announced on Sept. 29, 2026, to <Name>, City, State"
        pieces = [x for piece in pieces for x in re.split(r"\b(?:to|for)\s+(?=[A-Z0-9])", piece)]
    entries = []
    for piece in pieces:
        piece = LEAD.sub("", piece.strip())
        m = ENTITY.match(piece)
        if m:
            entries.append((m.group("name").strip(" *"), piece))
    if not entries and zone is not para:                      # the list comes after the verb
        return contractor_entries_whole(para)
    return entries


def awardee_count(para, entries):
    """How many contractors a paragraph names: the ";"-separated list before the award verb (an entry such as
    "J&J Worldwide Services, doing business as CBRE, McLean, Virginia" has no "Name, City, State" shape but is still
    an awardee), or the entries found. A CORRECTION's semicolons are not a list."""
    verb = AWARD_VERB.search(para)
    if re.match(r"\s*(CORRECTION|UPDATE)", para, re.I) or not verb or ";" not in para[:verb.start()]:
        return len(entries)
    listed = [s for s in para[:verb.start()].split(";") if "," in s]
    return max(len(entries), len(listed))


def contractor_entries_whole(para):
    """Fallback for 'The following companies …: A, City, State; …' — every "Name, City, State" segment."""
    out = []
    for piece in SEGMENT_SPLIT.split(para):
        piece = LEAD.sub("", piece.strip())
        m = ENTITY.match(piece)
        if m:
            out.append((m.group("name").strip(" *"), piece))
    return out


def match_name(name, piece):
    """('match', company, note) / ('not_node', why) / ('near', company, note) / ('none',) for one contractor entry."""
    for rx, why in NOT_NODE_RES:
        if rx.match(piece):
            return ("not_node", why)
    for rx, node, note in ALIAS_RES:
        if rx.match(piece):
            return ("match", node, note)
    for rx, node, note in REVIEW_RES:
        if rx.match(piece):
            return ("near", node, note)
    return ("none",)


def near_miss_node(name, nodes):
    """A graph company whose full name the contractor name starts with (e.g. 'Tesla Industries Inc.' → Tesla), for
    the alias review list — never a match."""
    low = name.lower()
    best = None
    for n in nodes:
        if len(n) >= 4 and low.startswith(n.lower()) and (len(low) == len(n) or not low[len(n)].isalnum()):
            best = n if best is None or len(n) > len(best) else best
    return best


# ---------------------------------------------------------------- saving

def label_for(company, day, article_id=None):
    """`<Company> DoD contract award (MM-DD-YYYY)`, dated the announcement day. A second page of the same day with
    NEW paragraphs for the company adds that page's article id before the date (as a second interview video adds
    its video id, enrich skill §5), so every file keeps its own label."""
    extra = f" {article_id}" if article_id else ""
    return f"{company} DoD contract award{extra} ({datetime.strptime(day, '%Y-%m-%d').strftime('%m-%d-%Y')})"


def amount_words(hit):
    """How the header states one paragraph's amount: the company's own entry amount in a multi-award paragraph,
    the paragraph's amount for a single award, or the shared figure marked as shared."""
    if hit["amount"] is None:
        return "no amount stated"
    text = "${:,.0f}".format(hit["amount"])
    if hit["awardees"] > 1:
        text += " (this company's entry)" if hit["own_amount"] else f" (combined / shared by {hit['awardees']} awardees)"
    return text


def save_file(company, page, hits, via, second_page=False):
    """Write one company's award paragraph(s) of one day; queue it. `hits` = one dict per paragraph:
    {service, para, name (as printed), note (alias note), awardees (names in the paragraph), correction (bool),
    amount (USD or None), own_amount (True when the amount is this company's own entry in a multi-award list)}.
    `second_page`: the company already has a file for this day from another page → name and label carry the id."""
    label = label_for(company, page["date"], page["id"] if second_page else None)
    path = OUT_DIR / (f"{slug(company)}_{page['date']}" + (f"_{page['id']}" if second_page else "") + ".txt")
    names = sorted({h["name"] for h in hits})
    notes = sorted({h["note"] for h in hits if h["note"]})
    amounts = [h["amount"] for h in hits if h["amount"] and (h["awardees"] == 1 or h["own_amount"])]
    services = sorted({h["service"] for h in hits if h["service"]})
    header = [
        f"SOURCE: {page['url']}" + ("   (read via r.jina.ai — war.gov answers 403 to scripts)" if via == "jina" else ""),
        f"TITLE: {page['title']}",
        "DOCUMENT TYPE: U.S. Department of Defense (Department of War) daily contract announcement — every award of "
        "$7.5 million or more that day; the paragraph(s) below name this company as a contractor",
        f"DATE: {page['date']}   (announcement day)",
        f"COMPANY: {company} — the announcement names: {'; '.join(names)}",
        *([f"ALIAS NOTE: {n}" for n in notes]),
        f"AWARDS: {len(hits)} paragraph(s); services: {', '.join(services) or 'not stated'}; first amount stated per "
        f"paragraph: {'; '.join(amount_words(h) for h in hits)}",
        "# NOTE: NOT a transcript and NOT a company document — the U.S. government's official contract announcement (the",
        "#       customer's own record), saved verbatim. Facts only: amount, contract type / number, what it buys, place",
        "#       of performance, completion date, contracting activity. The agency is a government customer: a relations/",
        "#       row with scope \"other\", never a node (enrich skill §2). An asterisk after a name = small business.",
        f"# source label: {label}",
        "",
    ]
    body = []
    for h in hits:
        tag = [h["service"] or "service not stated"]
        if h["awardees"] > 1:
            tag.append(f"one of {h['awardees']} awardees named in this paragraph")
        if h["correction"]:
            tag.append("correction / update of an earlier announcement")
        body.append(f"[{' | '.join(tag)}]\n{h['para']}\n")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header) + "\n" + "\n".join(body), encoding="utf-8")
    rel = path.relative_to(ROOT).as_posix()
    pending = load(PENDING, [])
    pending.append({"kind": "award", "company": company, "label": label, "file": rel, "date": page["date"],
                    "id": page["id"], "awards": len(hits), "largest_usd": max(amounts) if amounts else None,
                    "services": services})
    save(PENDING, pending)
    print(f"  saved {label}  ({len(hits)} paragraph(s))")
    return rel, label


def read_page(page, state, nodes, only=None):
    """Fetch one announcement day, match every contractor, save one file per graph company. Returns a status
    string for sync_state (saved / skip:<why> / later:<why>) and counters."""
    html, via = get_html(page["url"])
    if html is None:
        return f"later: {via}", {}, via
    paras, title = paragraphs(html)
    if title:
        page["title"] = title
    if not paras:
        return "later: no award paragraphs found on the page", {}, via
    by_company, skipped = {}, {}
    for service, para in paras:
        entries = contractor_entries(para)
        awardees = awardee_count(para, entries)
        multi = awardees > 1
        para_amount = usd(para)
        correction = bool(re.match(r"\s*(CORRECTION|UPDATE)", para, re.I))
        for name, piece in entries:
            verdict = match_name(name, piece)
            if verdict[0] == "match" and JV.search(name):
                skipped[name] = f"joint venture naming {verdict[1]} — not the company itself"
                continue
            if verdict[0] == "match":
                if only and verdict[1] not in only:
                    continue
                own = usd(piece)                              # "(SPE604-27-D-8001, $38,136,143)" in a multi-award list
                by_company.setdefault(verdict[1], []).append(
                    {"service": service, "para": para, "name": name, "note": verdict[2], "awardees": awardees,
                     "correction": correction, "amount": own if own else para_amount,
                     "own_amount": bool(own) and multi})
                continue
            # not ours: remember big awardees and near-misses for the alias review (`unmatched`). Each name keeps the
            # fingerprints of the paragraphs it was counted from, so a re-posted page or a rescan never counts twice.
            # A multi-award paragraph's amount is usually a shared ceiling, so there only the entry's own amount counts.
            key = para_key(name, para)[:10]
            amount = usd(piece) if multi else (usd(piece) or para_amount)
            if verdict[0] == "none" and amount and amount >= BIG_AWARD:
                u = state["unmatched"].setdefault(name, {"awards": 0, "largest_usd": 0, "last": None, "keys": []})
                if key not in u["keys"]:
                    u["keys"].append(key)
                    u["awards"] = len(u["keys"])
                    u["largest_usd"] = max(u["largest_usd"], amount)
                    u["last"] = max(u["last"] or "", page["date"])
            near = verdict[1] if verdict[0] == "near" else (near_miss_node(name, nodes) if verdict[0] == "none" else None)
            if near:
                n = state["near_miss"].setdefault(name, {"looks_like": near, "awards": 0, "last": None, "keys": [],
                                                         "note": verdict[2] if verdict[0] == "near" else None})
                if key not in n["keys"]:
                    n["keys"].append(key)
                    n["awards"] = len(n["keys"])
                    n["last"] = max(n["last"] or "", page["date"])
    saved, duplicates = {}, 0
    for company, hits in sorted(by_company.items()):
        # A paragraph already saved for this company (a re-posted page, a --company rescan) is not saved again.
        new = [h for h in hits if para_key(company, h["para"]) not in state["para_keys"]]
        duplicates += len(hits) - len(new)
        if not new:
            continue
        second = f"transcripts/dod/{slug(company)}_{page['date']}.txt" in state["files"]
        rel, label = save_file(company, page, new, via, second_page=second)
        state["files"][rel] = {"company": company, "label": label, "date": page["date"], "id": page["id"],
                               "status": "queued"}
        for h in new:
            state["para_keys"][para_key(company, h["para"])] = label
        saved[company] = len(new)
    counts = {"paragraphs": len(paras), "matched": sum(saved.values()), "duplicates": duplicates,
              "companies": saved, "skipped": skipped}
    if saved:
        status = "saved"
    elif duplicates:
        status = f"skip:only paragraphs already saved from another page ({duplicates})"
    else:
        status = "skip:no graph company among the contractors"
    return status, counts, via


def sync(since=None, companies=None):
    started = time.time()
    meta = load(META, {})
    check_aliases(meta)
    nodes = list(meta)
    if companies:
        missing = set(companies) - {node for _p, node, _n in ALIASES}
        if missing:
            sys.exit(f"{sorted(missing)} have no row in dod_contracts.py ALIASES — add the company's DoD legal name first")
    state = load(STATE, new_state())
    for k, v in new_state().items():
        state.setdefault(k, v)
    today = date.today()
    if since:
        start = since
    elif state["last_sync"]:
        start = date.fromisoformat(state["last_sync"]) - timedelta(days=RESYNC_OVERLAP)
    else:
        start = today - timedelta(days=FIRST_DAYS)
    rows, source, oldest = list_days(start)
    if oldest and oldest > start.isoformat():
        print(f"note: the {source} reaches back only to {oldest}; nothing older is listed")
    print(f"{len(rows)} announcement days on or after {start} ({source})")
    run = {"at": datetime.now().strftime("%Y-%m-%d %H:%M"), "since": start.isoformat(), "listed": len(rows),
           "companies_only": companies, "read": 0, "paragraphs": 0, "saved_paragraphs": 0, "duplicates": 0,
           "files": 0, "later": 0, "via": None, "stopped": None}
    before_files = len(state["files"])
    covered = set()
    for page in rows:
        prev = state["seen"].get(page["id"], {})
        status_prev = str(prev.get("status", ""))
        if status_prev and not status_prev.startswith("later") and not companies:
            continue                                          # read on an earlier run
        if (time.time() - started) / 60 > RUN_BUDGET_MIN:
            run["stopped"] = f"run budget of {RUN_BUDGET_MIN} min reached; the next sync continues"
            print(run["stopped"])
            break
        print(f"{page['date']}  {page['url']}")
        status, counts, via = read_page(page, state, nodes, set(companies) if companies else None)
        run["via"] = via if via in ("direct", "jina") else run["via"]
        run["read"] += 1
        run["paragraphs"] += counts.get("paragraphs", 0)
        run["saved_paragraphs"] += counts.get("matched", 0)
        run["duplicates"] += counts.get("duplicates", 0)
        covered |= set(counts.get("companies", {}))
        tries = prev.get("tries", 0) + 1 if status.startswith("later") else prev.get("tries", 0)
        if status.startswith("later"):
            run["later"] += 1
            if tries >= MAX_TRIES:
                status = "skip:" + status[len("later: "):] + f" (gave up after {tries} runs)"
            print(f"  {status}")
        if companies and status_prev and not status_prev.startswith("later"):
            # a --company rescan of a page already read: keep its first verdict, add the companies found now
            prev.setdefault("companies", {}).update(counts.get("companies", {}))
            if counts.get("companies"):
                prev["status"] = "saved"
            state["seen"][page["id"]] = prev
        else:
            state["seen"][page["id"]] = {"date": page["date"], "url": page["url"], "title": page["title"],
                                         "status": status, "paragraphs": counts.get("paragraphs", 0),
                                         "companies": counts.get("companies", {}),
                                         "skipped": counts.get("skipped", {}), "tries": tries}
        save(STATE, state)                                    # after every page, so an interrupted run resumes
    run["files"] = len(state["files"]) - before_files
    run["companies"] = sorted(covered)
    finished = run["stopped"] is None
    if finished and not companies:
        state["last_sync"] = today.isoformat()
    state["runs"].append(run)
    save(STATE, state)
    print(f"DoD contracts since {start}: {run['read']} day pages read, {run['paragraphs']} award paragraphs, "
          f"{run['saved_paragraphs']} saved for graph companies → {run['files']} files for {len(covered)} companies"
          + (f" ({run['duplicates']} paragraphs already saved from another page)" if run["duplicates"] else "")
          + (f", {run['later']} pages to retry" if run["later"] else ""))
    print(f"queue now {len(load(PENDING, []))} (`python -X utf8 dod_contracts.py pending`); "
          f"big unmatched awardees and near-misses: `python -X utf8 dod_contracts.py unmatched`")


# ---------------------------------------------------------------- queue and report commands

def mark_done(rows, why=None):
    state = load(STATE, new_state())
    stamp = f"enriched:{date.today().isoformat()}" + (f" ({why})" if why else "")
    for r in rows:
        state.setdefault("files", {}).setdefault(r["file"], {"company": r["company"], "label": r["label"],
                                                             "date": r["date"]})["status"] = stamp
    save(STATE, state)


def status(company=None):
    state = load(STATE, new_state())
    rows = sorted((f["date"], f["company"], f["status"], f["label"]) for f in state["files"].values()
                  if not company or f["company"] == company)
    for d, co, st, lab in rows:
        print(f"{d}  {co:26s} {st[:34]:34s} {lab}")
    seen = state["seen"].values()
    later = sum(1 for s in seen if str(s.get("status", "")).startswith("later"))
    print(f"{len(rows)} files; {len(state['seen'])} announcement days read ({later} to retry); "
          f"last sync {state.get('last_sync') or 'never'}")


def unmatched():
    state = load(STATE, new_state())
    print("BIG AWARDEES that are not graph companies (single award ≥ $%s; a multi-award ceiling counts only when the "
          "entry states its own amount):" % f"{BIG_AWARD:,}")
    rows = sorted(state["unmatched"].items(), key=lambda x: -x[1]["largest_usd"])
    for name, u in rows:
        print(f"  ${u['largest_usd']:>16,.0f}  {u['awards']:3d} award(s)  last {u['last']}  {name}")
    print(f"{len(rows)} names\n")
    print("NEAR-MISSES — contractor names that start like a graph company but matched no alias (never saved; add an "
          "ALIASES row only when the entity is certainly that company, a NOT_NODES row when it is not):")
    for name, n in sorted(state["near_miss"].items(), key=lambda x: x[1]["looks_like"]):
        print(f"  {n['looks_like']:24s} ← {name}  ({n['awards']} award(s), last {n['last']})"
              + (f"  — {n['note']}" if n.get("note") else ""))
    print(f"{len(state['near_miss'])} names")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--since", help="YYYY-MM-DD; default: 3 days before the last sync, or %d days on the first" % FIRST_DAYS)
    s.add_argument("--company", action="append",
                   help="repeatable: re-read the days in the window for these companies only (a new node, a new alias)")
    p = sub.add_parser("pending")
    p.add_argument("--company")
    p.add_argument("--market", help="US / EU / JP …: only companies of that home market")
    d = sub.add_parser("done")
    d.add_argument("--label")
    d.add_argument("--all", action="store_true")
    d.add_argument("--why", help="e.g. 'no material facts' when a file yielded nothing")
    st = sub.add_parser("status")
    st.add_argument("--company")
    sub.add_parser("unmatched")
    args = ap.parse_args()

    if args.cmd == "sync":
        sync(datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else None, args.company)
    elif args.cmd == "pending":
        meta = load(META, {})
        rows = [r for r in load(PENDING, []) if (not args.company or r["company"] == args.company)
                and (not args.market or market_of(meta.get(r["company"], {}).get("exchange")) == args.market)]
        for r in rows:
            amount = f"${r['largest_usd']:,.0f}" if r.get("largest_usd") else "-"
            print(f"{r['date']}  {r['company']:26s} {amount:>16s}  {r['label']:60s} {r['file']}")
        print(f"{len(rows)} pending")
    elif args.cmd == "done":
        rows = load(PENDING, [])
        if args.all:
            hit = rows
        elif args.label:
            hit = [r for r in rows if r["label"] == args.label]
            if not hit:
                sys.exit(f"no queued file has the label {args.label!r}")
        else:
            sys.exit('give --label "<label>" (one file) or --all')
        mark_done(hit, args.why)
        save(PENDING, [r for r in rows if r not in hit])
        print(f"queue: {len(hit)} marked handled and removed, {len(rows) - len(hit)} kept")
    elif args.cmd == "status":
        status(args.company)
    elif args.cmd == "unmatched":
        unmatched()


if __name__ == "__main__":
    main()
