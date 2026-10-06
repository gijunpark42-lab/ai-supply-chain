---
name: feedback-youtube-captions
description: "YouTube as a source (conference talks / investor days) — English videos only, captions only (uploader or auto subs via yt-dlp), never whisper/CPU transcription"
metadata:
  node_type: memory
  type: feedback
  originSessionId: abe4be0c-9cd7-404a-a320-256a4ab9eef6
  modified: 2026-10-05T00:54:26.073Z
---

YouTube talks may be used as a source, but only English-language videos, and only their captions
(uploader-provided first, auto-generated English second, via `yt-dlp --write-subs --write-auto-subs --skip-download`).
No whisper / local CPU transcription for this source. (User, 2026-10-04.) **Only highly credible videos**: the company's own official channel or an official event replay (investor / analyst day, official call replay) — never third-party uploads, commentary or news clips (user, 2026-10-04).

**Why:** the user does not want to spend CPU on transcription; English auto-captions are good enough, while
Chinese/Korean auto-captions are poor. Captions are still ASR — no speaker labels, numbers can be misheard — so
numbers are cross-checked against the company's deck/filing and only management statements are taken.

**How to apply:** any new YouTube collector (investor days, conference replays) skips non-English videos and
videos without captions. Preferred targets (my 2026-10-04 recommendation, user agreed to the direction):
official investor/analyst-day replays and official replays of calls that have no transcript. The existing
tw.py (Chinese 法說會 → whisper) is a separate, earlier decision — see [[feedback-transcript-sourcing]].
