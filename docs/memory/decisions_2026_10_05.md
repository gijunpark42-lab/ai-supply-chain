---
name: decisions-2026-10-05
description: "User rulings of 2026-10-05 — customer lists ARE edges (with judgment, not blanket), empty edges dropped, Kenmec deleted, HGTECH equipment placement, Zhongtian copper foil kept, tw.py no-VAD"
metadata:
  node_type: memory
  type: project
  originSessionId: abe4be0c-9cd7-404a-a320-256a4ab9eef6
  modified: 2026-10-05T08:57:37.223Z
---

User answers to the board questions, 2026-10-05:
1. A company's own customer list counts as an edge (SKILL.md JOB 4 updated) — but "don't just add all ~400,
   use judgment": only when the filer itself names X as its customer, the sale is in that chain's product,
   direction supplier -> customer, and no Filer -> X edge exists in any chain. A graph-wide scan of 410 candidates
   gave ~40 edges; partners / suppliers / competitors / event name-drops / analyst words were skipped.
2. Empty edges left by deletes are removed (Grace Fabric -> Nan Ya Plastics; 南亚 there = Nanya New Material).
3. Kenmec deleted (product rested on a third-party blog) — node, metadata, logo, local name; waitlist row dropped.
4. HGTECH got an equipment placement (hbm_memory, Advanced Packaging Equipment: 12-inch wafer laser tools).
5. Zhongtian's PCB copper-foil facts stay on its node.

**Why:** the user owns structure; these were the open board questions.
**How to apply:** customer-list edges follow the strict test above; empty edges created by a delete are removed,
skeleton edges are not. tw.py now transcribes without VAD (vad_filter=True dropped ~40% of a call). Open with the
user: re-transcribe the 17 older tw calls; Micron's prepared-remarks PDF (split call); condensed BESI transcript;
Marvell "5 hyperscalers" names inferred onto Amazon/Google/Oracle. Related: [[feedback-full-transcript-only]],
[[enrich-rules-2026-09-26]].
