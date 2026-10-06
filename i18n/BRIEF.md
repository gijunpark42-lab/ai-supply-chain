# Translation brief (earnings-ai web, 2026-09-27)

You translate one chunk of English strings from an AI / semiconductor supply-chain research site into
**Korean (ko)**, **Simplified Chinese (zh)** and **Japanese (ja)**. Folder:
`i18n/pending/` in the repo (call it BASE; created by `python i18n.py pending`). Python:
`C:\Users\calif\AppData\Local\Python\bin\python.exe`.

## Your chunk
Your chunk is `cNNN` (given in your task). Its part file(s): `BASE/chunks/cNNN_p*.json`,
each `{ "id": "English text", ... }`. For EACH part and EACH language write
`BASE/out/<lang>/cNNN_pK.json` = `{ "id": "translation", ... }` with exactly the same ids (3 files per part).
Work part by part: read a part, write its ko, zh and ja files, then the next part. Write valid JSON
(escape `"` and `\` inside strings; keep `\n` as `\n`). Use the Write tool; create folders if needed.

## Rules
1. Meaning exactly as the English — no additions, no omissions, no summarising. Keep attribution and hedges
   ("CEO: …", "management expects", "may", "about", "targets") — never turn an expectation into a fact.
2. Copy VERBATIM, never translate or convert:
   - every number, percentage, date, range and figure, AND money amounts as a whole, including currency and
     scale word: "KRW 58.8 billion", "US$1.43 billion (NT$45.4 billion)", "$220B", "KRW 45,946M" stay exactly
     like that inside the translated sentence (no 억 / 亿 / 億 conversion, no arithmetic);
   - company, product, model and brand names, tickers (NVIDIA, SK Hynix, TSMC, Vera Rubin, HBM4E, CoWoS-L);
   - technical acronyms and units (EUV, DRAM, NAND, CPO, OSAT, GW, MW, nm, mm, kt, wph), fiscal labels
     (Q2 FY2026, 1H26, FY2025), source labels like "Samsung Q2 FY2026 (07-30-2026)".
3. Translate generic industry words into the standard term used in financial / semiconductor media of that
   market (e.g. backlog → ko 수주잔고 / zh 在手订单 / ja 受注残; utilisation → 가동률 / 产能利用率 / 稼働率;
   guidance → 가이던스 / 业绩指引 / ガイダンス; substrate → 기판 / 基板 / 基板).
4. Style: concise research-note register. ko: 간결한 평서체(~다) 또는 명사형 종결, 존댓말 금지. zh: 简体中文,
   concise business Chinese. ja: 常体(である調)・簡潔. Short labels (sector names, table headers, one-word
   values like "no specific figure", "not stated") → short standard equivalents
   (ko 구체적 수치 없음 / zh 无具体数字 / ja 具体的な数値なし).
5. A string that is only a proper noun / code / acronym → return it unchanged.
6. Never output anything but the JSON files. No notes inside the JSON.
7. Do ALL the work yourself: never spawn sub-agents, forks or tasks (the run is rate-limited). If a part file
   already exists in out/<lang>/ and passes validation, skip it (you may be resuming someone else's work).

## Check before you finish
From the repo root run `...python.exe -X utf8 i18n.py validate i18n/pending cNNN` (your chunk only) and fix every reported problem (numbers/currency tokens
must survive exactly; ko must contain Hangul, zh/ja CJK; no Hangul in zh/ja; no kana in zh) until
`RESULT: clean`.

## Final message
ONE line only: `cNNN: clean` or `cNNN: <n> problems left: <short reason>`.
