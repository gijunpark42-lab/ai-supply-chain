# News interviews of company executives (added 2026-10-17)

`media_pull.py` reads the YouTube channels of five news outlets every day and saves the transcript of each
interview in which a named executive of a graph company speaks on camera (`transcripts/media/`). The transcripts
are **enrich inputs only**: the enrich session turns the executive's own first-person statements about their
company into graph signals (enrich skill §11), and nothing else of the video or the transcript reaches the site.

## The user's rules (2026-10-17)

> "찌라시면 시그널이면 안 돼. 무조건 뉴스여야 함. 회사 관계자가 직접 얘기한 거여야 해"
> (A rumor must never be a signal. It must be news, and a company official must have said it directly.)

1. **News outlets only.** Only videos from the official channels in the allowlist `media/channels.json`:
   CNBC Television, CNBC International TV, Bloomberg Television, Yahoo Finance and Fox Business. Each channel id
   is checked against the channel itself when the list is made; a video from any other channel is never read.
2. **A company official speaking directly, on camera.** CEO, CFO, President, COO, CTO, founder, division head or
   head of investor relations. The person must be named in the video's title or description and must be on that
   company's roster in `media/executives.json`. A former executive who is no longer on the roster does not count.
3. **Never a signal:** rumors, reports, "reportedly", "sources say", and anything an anchor, reporter, host, analyst
   or strategist says. Analysts (for example Dan Ives) are left out of this pipeline entirely, and so are "here's
   why the stock moved" explainers.
4. **Only the executive's own words.** Only the named executive's first-person statements about their own company
   become signals, quoted verbatim from the transcript with the `[mm:ss]` timestamp and the video URL. No caption
   kind is human-checked text, so every quote carries a mark: "(broadcast captions)" for `youtube manual captions`
   (the outlet's uploaded track: live captioning or a machine track), "(auto-captions)" for YouTube's
   auto-captions, "(machine transcript)" for faster-whisper. A number counts only when it is clear and the
   company's own call, filing or release states it too (enrich skill §11e).
5. **Nothing of the video or the transcript on the website.** The site shows only the short quote inside a signal,
   with the video URL as its source.

## How a video is chosen

1. Each allowlisted channel's RSS feed (`https://www.youtube.com/feeds/videos.xml?channel_id=...`) lists its latest
   15 uploads. When those do not reach back to the start of the `--days` window (a busy channel posts 40+ videos a
   day), or `--days` is more than 7, the channel's `/videos` tab is also listed with `yt-dlp --flat-playlist`. A video
   listed there without a description is looked up with `yt-dlp -J` when its title names a rostered executive or a
   company that has one (Fox titles often leave the guest's name out).
   A video already in `media/sync_state.json` as "saved" (with its file on disk) or as a hard "skip" (`"hard": true`:
   a rumor, a report, a Short, a long show, no English captions) is not looked at again. Every other skip carries a
   `"stamp"` (the roster's `updated` date | `DECIDE_VERSION` in `media_pull.py`): when the roster is rebuilt or the
   rules change, it is decided again the next time it is in the `--days` window. A "fail" (network error, captions
   not ready yet) is retried on the next runs, 3 times at most.
2. `media_pull.decide(title, description, roster)` returns `(keep, node_id, exec_name, reason)`; `roster` is the
   `companies` block of `media/executives.json`. It keeps a video only when a rostered executive is NAMED in the
   title or the description AND the title shows that person speaking ("<Name> on ...", "<Company> CEO <Name>: ...",
   "..., says <Name>", "Altman on OpenAI's ..." (the family name while the title names the company), "full
   interview", "joins", a keynote or remarks). When the description names the executive too, the speaking word must
   belong to them there as well: they are its subject ("Cohere CEO Aidan Gomez joins ...", "Aaron Jagdfeld, Generac
   chairman, president and CEO, joins ...") or its object ("sits down with Dell CEO Michael Dell"); a reporter as
   the subject ("CNBC's Kif Leswing joins ... with the latest on comments from Nvidia CEO Jensen Huang") or a past
   "said" recap does not count. A title that names only the company is kept when the description's FIRST sentence
   has the fully named executive as the speaking subject ("Synopsys CEO Sassine Ghazi discusses ..."), never for an
   "Exclusive:" headline (a reporter's scoop). It always skips rumors and reports ("reportedly", "sources", "a
   report"), analyst / strategist / anchor commentary (Dan Ives, Bloomberg Intelligence and other analysts never get
   in), reporter segments ("has more", "with the latest on"), remarks made elsewhere ("comments made by", "made the
   remarks", "told reporters", "in an interview with Axios"), "here's why the stock fell" explainers, stock-move
   segments, show compilations, a former executive, and a title that fits two rostered people equally. Every
   decision and its reason is written to `media/sync_state.json`, so a skipped video can be checked later.
   `tests/market/test_media_filter.py` pins the decision on known titles and descriptions (including the cases of
   the 2026-10-17 verification), and `tests/market/test_media_sources.py` pins how the enrich tools treat a media
   source. Both run every night in `market/selftest.py`.
3. For a kept video the transcript is YouTube's manual English captions, else its auto-captions, else (videos under
   30 minutes) the audio transcribed locally with faster-whisper ("small.en", CPU). The `# TRANSCRIPT` header line
   says which. "Manual" only means the outlet uploaded the track: CNBC and Fox upload their live broadcast
   captions, Bloomberg's track reads like machine output, and both mishear words and numbers. A new `[mm:ss]` line
   starts about every 25 seconds, at every `>>` speaker change, and at every upper-case speaker tag inside a caption
   line (Fox: "... LIZ: HOW BIG OF A START ..."), so an anchor's question and the answer never share a line.
   Downloads go to a temporary folder outside the repo that is deleted at the end, so nothing of the video or audio
   is kept.

## Files

| Path | What it holds |
|---|---|
| `media/channels.json` | The allowlist: `{"channels": [{"name", "channel_id", "rss"}]}`. |
| `media/executives.json` | The roster: `{"_about", "updated", "companies": {"<graph node id>": [{"name", "title", "aliases": [], "source"}]}}`. Mined by `media_roster.py`, without any model, from the companies' own documents under `transcripts/` (titled speaker lines of calls and conference talks, 10-K executive-officer tables, quote attributions in company press releases); analysts, moderators and hosts are dropped, and so is anyone whose title names none of the rule-2 roles (a plain VP / SVP, a marketing lead). A person found at two companies stays at the newer one when it is a move (Olivier Leonetti: Eaton -> Equinix); a CEO / CFO named as succeeded in two or more newer documents is left out (Kirsten Spears -> Amie Thuener at Broadcom). `HAND_ADD` in `media_roster.py` adds the officials the mining cannot find (Elon Musk at Tesla and SpaceX, Tesla CFO Vaibhav Taneja, OpenAI CFO Sarah Friar, SK Hynix CEO Kwak Noh-jung, Larry Ellison, Cohere's leadership), each with the company document that states the title. It covers the ~200 graph nodes with the most edges, every hyperscaler and AI-lab node, and every other node with a titled official in `transcripts/` (Generac, for one). |
| `media/sync_state.json` | Every video id looked at, with its decision (saved / skip / fail), its reason, `"hard": true` or the `"stamp"` of a soft skip, plus one line per run. Written by `media_pull.py` only. |
| `media/enriched.jsonl` | The interview files the enrich session has read: one line per file, `{"label", "date", "entries", "why"}` (enrich skill §11). Written by the run's coordinator only; `media_status.py` lists the files not yet in it. |
| `transcripts/media/<node-slug>_<YYYY-MM-DD>_<video id>.txt` | One transcript per kept video. Gitignored: kept in the local checkout only (see the end of this page). |

Each transcript starts with these header lines, then the transcript with a `[mm:ss]` timestamp every 20 to 30
seconds:

```
# source label: NVIDIA CNBC interview (10-16-2026)
# SOURCE: https://www.youtube.com/watch?v=<video id>
# OUTLET: CNBC Television
# SPEAKER: Jensen Huang, Founder, President and CEO, NVIDIA
# PUBLISHED: 2026-10-16
# TRANSCRIPT: youtube manual captions | youtube auto-captions | faster-whisper (machine)
# NOTE: news interview; only the named executive's own first-person words may become signals; anchor/reporter/analyst lines and anything reported second-hand never count
# TITLE: <the video title, for the record; never a signal source>
```

`youtube manual captions` keeps its name (the header contract), but it is not checked text either: the signal marks
its quotes "(broadcast captions)" (enrich skill §11e).

The source label is `[Company] [Outlet] interview (MM-DD-YYYY)`, dated the day the video was published, with the
graph node name as `[Company]` (enrich skill §5). A second video of the same company, outlet and day adds its video
id before the date.

## Schedule

`routine/market_data.ps1` (the `earnings-ai market data` task, every day at 22:00, see `docs/market_data.md`) runs
`python -X utf8 media_pull.py --days 2` as its step c2), right after `market/run_all.py` and
`utils/transcript_quality.py`, inside the same market-data lock:

- time box 20 minutes; the step is skipped (logged) when `media_pull.py` does not exist;
- it starts only when at most 75 minutes of the task have passed, so the task still ends inside its 2-hour limit; a
  skipped day is caught up by the next run, because `--days 2` looks back two days and the state file skips videos
  already seen;
- output: `.claude/media_pull.log` and `.claude/media_pull.err.log`, one line in `.claude/market_data_task.log`;
- `nightly.ps1`'s market-data fallback (when the 22:00 task did not run) does not run it;
- on a timeout the whole process tree is stopped (`taskkill /T`), so no yt-dlp or node process is left running.

Publishing: the transcripts in `transcripts/media/` are gitignored and never published (see below). The 22:00
market-data publish (`nightly.ps1 -PublishOnly -MarketOnly`) commits the puller's files in `media/` (state, roster,
allowlist) along with the market data; they alone never start a publish. The nightly enrich publish covers `media/`
too, `media/enriched.jsonl` included.

The enrich session (nightly or by hand) then reads the new files under the rules of enrich skill §11: the status
board lists them under Run next, and the coordinator gives each to the agent that has that company's sources.

Merge note (2026-10-17): the builders' real run of 2026-10-17 15:55 is in `media/sync_state.json` `runs`, so the
22:00 run of the day the branch is merged stops at the once-a-day guard. That is harmless (the next day's `--days 2`
catches up); run `python -X utf8 media_pull.py --force` to run it anyway.

## Run by hand

From the repo root, with the project's Python:

```
python -X utf8 media_pull.py --days 2              # what the 22:00 task runs (once a day; --force runs it again)
python -X utf8 media_pull.py --days 7 --dry-run    # print the decisions only, save nothing
python -X utf8 media_pull.py --only-video <id>     # one video (it must come from an allowlisted channel)
python -X utf8 -m unittest tests/market/test_media_filter.py tests/market/test_media_sources.py -v
python -X utf8 media_roster.py                     # rebuild media/executives.json (prints who was left out and why)
```

The puller stops itself after `--max-minutes` (default 15, inside the routine's 20-minute time box); the videos it
did not reach are looked at on the next run.

## Terms of service and copyright

- Videos and audio are never republished or kept (temporary download folder, deleted after each video).
- The site shows nothing of a video or its transcript: no player, no transcript page, no excerpt. A signal carries
  a short verbatim quote (one or two sentences) with the video URL, so a reader goes to the outlet's own video.
  `evidence.py` (the site's "source" click-through, `graph/evidence.json` -> `Evidence.tsx`) writes
  `doc` / `excerpt` / `matched` = null for a news-interview entry (`hide_media_source`), and the
  waiting list comes from `media_status.py` (labels only). `enrich_status.py` is not changed yet (the main checkout
  has uncommitted edits to it), so for now it counts these files as manual pastes; give them their own "media"
  pipeline there once those edits are committed (the Status tab that shows the board is hidden on the site).
- The transcripts are enrich inputs only and stay in the local checkout: `transcripts/media/` is in `.gitignore`,
  because the GitHub repository (`gijunpark42-lab/ai-supply-chain`) is **public** and whole broadcasts go far beyond
  the short quote rule 5 allows (decided 2026-10-17 on the verifier's recommendation; the user may reverse it by
  deleting that `.gitignore` line). The enrich session and `verify_graph.py` in this checkout read them; another
  checkout lacks them, and `media_pull.py` fetches a "saved" video again when its file is missing.
