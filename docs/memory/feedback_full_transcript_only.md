---
name: feedback-full-transcript-only
description: Earnings calls are enriched ONLY from a full verbatim transcript (prepared remarks + Q&A); Q&A summaries / scripts / partial records never count
metadata:
  node_type: memory
  type: feedback
  originSessionId: abe4be0c-9cd7-404a-a320-256a4ab9eef6
  modified: 2026-10-05T07:19:16.483Z
---

Earnings-call enrichment uses a FULL transcript only — the complete verbatim call (prepared remarks + Q&A).
A company-published Q&A summary, a presentation script alone, a partial record, or an article about the call does
not count; if only those exist, the call is "not found" (`enrich_status.py mark ... --why "summary only, no full
transcript"`), nothing is enriched from it.

**Why:** the user, 2026-10-05: "어닝 transcript은 무조건 full transcript원칙이다" — said right after a hunt prompt of
mine allowed company Q&A summaries (Murata) as a source.

**How to apply:** every transcript-hunting / enrich prompt states full-transcript-only; Taiwan 法說會 whisper output
of the whole call video counts as full. Company decks / releases / filings stay valid as their own source kinds
(labelled as such), never as a stand-in for the call. Related: [[feedback-source-hierarchy]], [[feedback-transcript-sourcing]].
