### Korean IR presentations from the KRX KIND IR library (`enrich kind`; part of `enrich korea`)

Built 2026-09-27 (user: build a pipeline for the Korean companies' IR materials so an agent does not have to
look each time). Most Korean names hold no English earnings call; they present at 기업설명회 and post the deck to
the Korea Exchange's central IR library (KIND IR자료실). `kind.py` lists that library for every company at once,
keeps only our Korean companies (match on the stock code), saves each new deck's text page by page and queues it.
Coverage: 34 of our 84 Korean companies posted a deck there in the last 12 months — mostly KOSDAQ (ISC, Koh Young,
Leeno, Jusung, Simmtech, Park Systems, PSK, Hana Micron, TES, Dongjin Semichem, FADU, SemiFive …). The KOSPI large
caps (Samsung, SK Hynix, SEMCO, LG Innotek, Naver) post on their own websites, not in KIND.

**The large caps' own IR sites (same `sync`, since 2026-09-27).** KIND holds nothing for the KOSPI large caps,
so `kind.py` also reads six company IR sites for the two latest reported quarters (`SITES` in kind.py):
Samsung — its OFFICIAL earnings-call script (English, prepared remarks + full Q&A) saved as a CALL to
`transcripts/kr_calls/samsung_q<N>_<year>.txt` with the normal call label (`Samsung Q2 FY2026 (07-30-2026)`),
plus its deck; SK Hynix, Samsung Electro-Mechanics, LG Innotek, NAVER, SK Telecom — their results decks, saved to
`transcripts/kind/<slug>_<date>_q<N>_<year>_site.txt` as `<Company> IR presentation: Q<N> <YYYY> results (MM-DD-YYYY)`.
Every site label is dated the company's earnings day = its latest DART 영업(잠정)실적 filing for that quarter.
A call already in the graph under the same label (e.g. pasted by hand) is skipped, not saved twice. None of the other
large caps publishes a call transcript (SK Hynix: third-party services only; SEMCO / SK Telecom: audio replay;
NAVER: gated replay; LG Innotek: none) — a call the user pastes is enriched as usual. In the Samsung script the
Q&A questions are `[Name, Firm] Q. …` (analysts: context only) and the answers `- …` (management).

**Loop**
1. `python -X utf8 kind.py sync` — lists the library from 7 days before the last sync (first run: 120 days back) to
   14 days ahead (decks for events a few days away are posted early), saves every new deck of our companies to
   `transcripts/kind/<slug>_<YYYY-MM-DD>_<irSeq>.txt` and queues it in `kind/pending.json`. Rows are skipped with the
   reason recorded in `kind/sync_state.json`: no PDF attached, the same file already saved under another row (KIND
   attaches one deck to several rows), an image-only deck (no text layer). A KIND web-firewall block stops the run
   (re-run later — rows already handled are remembered).
2. `python -X utf8 kind.py pending [--company "<Company>"]` — the queue.
3. Enrich each deck under the enrich skill's common rules (parallel `enricher` agents, split by company):
   - A deck is a company-issued document, NOT a transcript: facts (revenue, OP, segment mix, capacity, customers
     named by the company, product roadmap dates) and company targets / guidance. Marketing claims are attributed
     ("the company describes itself as the leading …"); nothing is inferred from a chart without printed numbers.
   - The decks are mostly Korean: every entry is written in English (skill §8); KRW stays KRW ("KRW 58.8 billion").
   - Depth rule: add only what the company's node does not already state for that period — the DART preliminary /
     periodic report (`enrich dart`) is the primary source for the quarter's numbers; the deck adds mix, roadmap,
     customers, capacity and targets.
   - Slots (skill slot table, "Company IR presentation"): `guidance`, `next_catalyst`, `backlog_or_b2b`,
     `supply_status` when the deck itself states that fact; never `revenue_growth` (DART holds it).
   - Label: the file's `# source label:` line verbatim — `<Company> IR presentation: KIND <irSeq> (MM-DD-YYYY)`,
     dated the IR event (e.g. `Nepes IR presentation: KIND 19356 (09-18-2026)`).
4. `python -X utf8 utils/check_patch.py <patches>` until clean → one `python graph_build.py --sync`.
5. `python -X utf8 kind.py done --label "<label>"` for every handled deck (`--why "no material facts"` when it gave
   nothing); `status [--company …]` lists every saved deck and its state.
