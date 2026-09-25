---
name: feedback-transcript-only-purism
description: User rejected and fully reverted the knowledge-edge + news-pipeline + source-filter program — chain data stays earnings-transcript-grounded only
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fc55431c-0d9a-48a4-b3fa-864f65a36aec
---

On 2026-06-11 the user approved, watched me build, then ORDERED A FULL REVERT of the entire
"map improvement" program: earnings-only UI toggle, source_registry.json, AI-knowledge structural
edges (`origin:"knowledge"`), filing-based enrichment of qd=0 nodes (Tower/Fujikura), and the
/news-sweep pipeline (skill + watchlist + inbox queue + CLAUDE.md Workflow 3). Final words:
"원래 트랜스크립트만 있던 걸로 모든 걸 되돌리자 ... 이거 아닌듯."

**Why:** Seeing it built clarified what the project is NOT. The map's value is that every data
point is grounded in a full transcript/filing the user controls. AI-knowledge edges and
news-derived data — even gated, graded, and toggleable — felt like dilution, not enrichment.
The user prefers a smaller, fully-trusted map over a denser, mixed-provenance one.

**How to apply:**
- Do NOT re-propose knowledge-based edges, news sweeps/pipelines, or source-quality toggles
  unless the user raises them first.
- Enrichment stays: user-driven, one source at a time, full transcripts (or user-provided
  official docs/DART route) only — the existing Workflow 2.
- "Approved plan" ≠ settled preference: for changes to the data's NATURE (not just volume),
  expect the user may revert after seeing it live; keep such work cleanly revertable
  (no commits until explicitly ordered — this saved the day here).
- Related: [[project-state]]

**EXCEPTION granted by the user, 2026-09-22 (ECOC 2026):** "if only a summary exists, add conference content
fact-based — but it must be an accurate source; the company's own IR release is fine." So for a conference with no
full transcript, OFFICIAL COMPANY-ISSUED documents (IR press releases on the company's own site / Business Wire)
may be used. Rules applied: fetch from the official URL, save verbatim to transcripts/non_transcript_sources/ with a
NOT-a-transcript NOTE and a `# source label:` header; label names the document type
("Marvell ECOC 2026 press release (09-21-2026)") so it never mixes with transcript labels; facts only (specs,
availability, counts), marketing adjectives dropped, demos never written as shipping products, hedges kept, no
edges/contracts from joint demos. Third-party articles, newsletters and exhibitor boilerplate are still NOT sources.
This does not reopen the reverted news-pipeline program; it is per-request.

**NARROWED 2026-09-24:** the exception above is now a standing rule limited to company-issued documents (IR releases, SEC/DART filings); articles are pointers only. Full rule: [[feedback-source-hierarchy]].
