---
name: agent-concurrency-limits
description: "How many parallel enricher agents this laptop can run, and when it is safe to run graph_build (RAM, OneDrive lock, battery)"
metadata:
  node_type: memory
  type: project
  originSessionId: abe4be0c-9cd7-404a-a320-256a4ab9eef6
  modified: 2026-10-05T06:04:14.649Z
---

Measured on 2026-10-04 (16 GB laptop, repo under OneDrive Desktop):
- Each `utils/check_patch.py` / `verify_graph.py` process loads every document (~800 MB). With ~15 agents
  running, several pre-flight checks at once left 1.7–2 GB free. Keep it to about **10–12 concurrent enricher
  agents**; refill as they finish rather than launching 20 at once.
- `graph_build.py` writes chains/ only in its first step (apply_patches, ~1 min). Don't run it while enricher
  agents may still be writing/revising patches — hold their in-flight patch files out first, or wait.
  (A held file's agent will just rewrite it; delete the stale held copy afterwards.)
- OneDrive can briefly lock a file ("[Errno 22] Invalid argument" on open-for-write). apply_patches.save_chain
  now retries; enrich_status.record can hit it too — just retry.
- On battery: the user once ran a multi-hour session unplugged with the lid closed (power settings: lid = do
  nothing, sleep = never). Never start the chains-writing step below ~25% battery; tell the user to plug in.

- Measured 2026-10-05: 26 verifier agents at once worked when the prompt forbade `verify_graph.py` (they read
  graph/verification.json instead); Claude Code caps concurrent subagents at 25 (the 26th errors — launch it when one
  finishes). Parallel agents share /tmp: two overwrote each other's /tmp/dump.py — tell agents to keep helper scripts in
  the job tmp dir (`C:\Users\calif\.claude\jobs\<job>\tmp\<agent-name>\`).
- The account can hit the weekly Opus limit mid-run (2026-10-04): new enricher agents then fail immediately; keep the
  unverified labels in verify_queue.json pending and resume after the reset or when the user lifts it.

Related: [[concurrent-job-race]], [[enrich-rules-2026-09-26]].
