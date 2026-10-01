### Workflow 2e — Taiwan Chinese-language calls via 法說會 video + whisper (`enrich tw`)

The TWSE/TPEx names Investing.com does NOT carry (their calls are in Chinese): Quanta, Wiwynn,
Foxconn, Wistron, Unimicron, Delta Electronics, GUC, Elite Material, Gold Circuit, Zhen Ding,
Nan Ya PCB, Kinsus, ASPEED, Chenbro, Pegatron, Gigabyte, Yageo, GlobalWafers, Accton, Inventec,
Phison, Faraday, VPEC, TUC, Powertech — the full list is `COMPANIES` in `tw.py`. (Alchip,
MediaTek, Lite-On, Nanya Technology hold English calls and stay on Workflow 2d.)

**This is the confirmed Taiwan pipeline (user decision 2026-08-31):** the primary source is the
法說會 itself — MOPS lists every conference (t100sb02_1), Taiwanese finance channels upload the
full call to YouTube (非凡 "完整公開" etc.), `yt-dlp` pulls the audio, and local `faster-whisper`
produces OUR OWN verbatim Chinese transcript (~30 min CPU per 1-hour call; verified on the
Foxconn Q2 FY2026 call). MOPS decks, material information and monthly revenue are company filings, not transcripts:
since 2026-10-01 `mops.py` collects them (references/mops.md), a separate step of `enrich taiwan`.

**Trigger: the user says `enrich tw`.**
1. `python tw.py sync` — MOPS results-call discovery (this month + last) → YouTube search →
   audio downloads into `tw/audio/`. `no_media` rows (webex/zucast broker calls, e.g. Quanta)
   need a replay URL found by hand: `python tw.py fetch <url> --company "Quanta" --date YYYY-MM-DD`.
2. `python tw.py transcribe` — whisper every waiting audio (SLOW — run in background/overnight).
3. `python tw.py pending` — the queue. Enrich every row (Workflow 2 jobs + JOB 5 tags) with the
   Workflow 2b language rules: the source txt is Chinese; everything written into chains/ is
   ENGLISH (translate as you go, grep the additions for Chinese characters before finishing).
   The transcript has no speaker labels and STT can garble numbers — when a figure looks off,
   cross-check the company's MOPS deck or monthly revenue before writing it. Management-only rule
   without speaker labels: take the prepared remarks and the answers phrased as the company's own
   ("we", "our", "公司", "我們"); skip anything phrased as a question or attributed to a broker or
   analyst; when unsure whether a sentence is management's, leave it out.
4. `python graph_build.py --sync` (verify_graph runs on the labels just applied), then `python tw.py done`.
5. Report per company: label, what was added, verify result.

File format `transcripts/tw/<slug>_q<N>_<year>.txt`: `SOURCE:` (YouTube URL) / `VIDEO TITLE:` /
`CALL DATE:` / `QUARTER:` / `# source label:` header, then timestamped verbatim Chinese lines
(`[MM:SS] text`). Quarter mapping: Jan–Mar call = Q4 of previous FY; Apr–Jun = Q1; Jul–Sep = Q2;
Oct–Dec = Q3 (graph-history +1 wins when they disagree, same as Workflow 2d).

