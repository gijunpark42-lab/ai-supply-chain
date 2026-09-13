# local-ask — answer "Ask the Graph" questions with Claude Code on your own PC

`server.mjs` is a tiny HTTP server. For every question it runs the Claude Code
CLI in print mode — **Opus at max effort, with no tools** — and returns the
answer written only from the snippets it was given. The website's `/api/ask`
route calls it first and falls back to Gemini when it cannot reach it:

```
browser → Vercel /api/ask ─┬─ GET  {LOCAL_ASK_URL}/health   (3 s: "is the PC on?")
                           ├─ POST {LOCAL_ASK_URL}/answer   (≤ 3 min: Opus is slow)
                           └─ any failure → Gemini (with retry/backoff)
```

So the site keeps working when this PC is off, asleep, or the tunnel is down —
the user just gets the Gemini answer instead of the Opus one. The UI badge
shows which engine answered (`claude-code-local` vs the Gemini model id).

Both engines use the **same prompt** (`web/src/lib/askPrompt.mjs`), which is why
this folder must stay inside the repo: `server.mjs` imports that file.

## What the server runs

```
claude -p --safe-mode --tools "" --no-session-persistence --model opus --effort max \
       --output-format json --max-budget-usd 1 --system-prompt "<system prompt>"
```

with the numbered snippets + question written to the process's stdin (a Windows
command line is capped at ~32k characters). Flag by flag:

| flag | why |
|---|---|
| `-p` | print mode: answer once and exit |
| `--safe-mode` | ignore this PC's CLAUDE.md, hooks, MCP servers, plugins, skills |
| `--tools ""` | no tools at all — the answer can only come from the snippets |
| `--no-session-persistence` | do not write a session file per question |
| `--model opus` / `--effort max` | Opus at the highest effort the CLI offers (`ASK_MODEL` / `ASK_EFFORT` override) |
| `--output-format json` | one JSON object on stdout; the answer is its `result` field |
| `--max-budget-usd 1` | hard spend cap per question (`ASK_MAX_BUDGET_USD`) |
| `--system-prompt` | the shared Ask prompt — no coding-assistant persona |

Effort is a real CLI flag, so no settings file is needed and your global
`~/.claude/settings.json` is never touched.

Guards: at most **2** `claude` processes at once, up to **5** more requests wait
in line, anything beyond that gets **429**; a process running longer than
**200 s** (`ASK_TIMEOUT_MS`) is killed and the request gets **504**; when the
Vercel route hangs up (its own 3-minute limit) the process is killed too.

## How it is exposed since 2026-09-13: Tailscale Funnel (fixed address)

**Do NOT run `node local-ask/up.mjs`** (or `down.mjs`). Since 2026-09-13 the runner is reached through a FIXED Tailscale Funnel address (`https://gijun-pc.tail362ef7.ts.net`) that is already set as `LOCAL_ASK_URL` on Vercel; `up.mjs` would overwrite it with a throwaway trycloudflare address and break Ask. The runner autostarts at logon (scheduled task "local-ask runner"); the desktop `Ask Switch.cmd` (repo copy: `local-ask/switch/`) shows ON/OFF and flips the runner.

- Public address: `https://gijun-pc.tail362ef7.ts.net` → `http://127.0.0.1:8787` (`tailscale funnel status`).
  Tailscale runs as a Windows service and reconnects on any network, including ones that block
  cloudflared's port 7844 (campus Wi-Fi). Free personal plan.
- Runner autostart: Windows scheduled task "local-ask runner" (at logon, `node server.mjs` in this folder).
- Re-enable the funnel if it ever disappears: `"C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8787`.
- "ask 실행" is now the health-check procedure in `.claude/skills/ask-server/SKILL.md`.

## Legacy: `node up.mjs` (Cloudflare quick tunnel — DO NOT RUN unless the Funnel is gone for good)

```bat
cd local-ask
node up.mjs        :: start runner + tunnel, point Vercel at the tunnel, redeploy, verify
node down.mjs      :: stop both; the site falls back to Gemini by itself
```

`up.mjs` starts the runner and a Cloudflare quick tunnel (both detached, logs in
`logs/`), writes the tunnel address into Vercel's `LOCAL_ASK_URL`, redeploys the
current production build (env vars are baked in at deploy time — about a
minute), then asks the live site one question and checks that the answer came
from this PC. Steps already done are skipped, so running it twice is cheap.
Options: `--force` (redo the Vercel part), `--no-vercel` (start only, print the
address). It needs the Vercel CLI logged in once (`vercel login`) and never
touches `ASK_SHARED_SECRET` — set that on Vercel yourself, once.

## Run it by hand

Requirements: Node ≥ 20.12 (this PC has 24), the Claude Code CLI logged in
(`claude --version` works; if you have never run `claude` interactively, do it
once and finish the login).

```bat
cd local-ask
copy .env.example .env
node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"   :: paste into ASK_SHARED_SECRET in .env
node server.mjs                                                            :: or double-click start-local-ask.cmd
```

You should see `local-ask listening on http://127.0.0.1:8787 …`. (Once the
tunnel is set up below, `start-all.cmd` starts the runner and the tunnel
together.) In another terminal:

```bat
cd local-ask
node smoke.mjs
```

which calls `/health`, then `/answer` with a made-up question and prints the
Opus answer (~5–30 s). Every request is appended to `logs/requests.jsonl`
(question, wait time, latency, exit code, cost); both `.env` and `logs/` are
git-ignored.

Environment variables (`.env` or the real environment; the environment wins):

| variable | default | meaning |
|---|---|---|
| `ASK_SHARED_SECRET` | — (required, ≥ 16 chars) | must equal the `x-ask-secret` header the route sends |
| `ASK_MODEL` | `opus` | CLI model alias or full name |
| `ASK_EFFORT` | `max` | `low` `medium` `high` `xhigh` `max` |
| `ASK_MAX_BUDGET_USD` | `1` | spend cap per question |
| `ASK_TIMEOUT_MS` | `200000` | kill the process after this (keep it above the route's 3-minute wait) |
| `ASK_CLAUDE_BIN` | `claude` | path to the CLI when it is not on PATH |
| `HOST` / `PORT` | `127.0.0.1` / `8787` | bind address (keep localhost; the tunnel connects locally) |

## Protocol

Every request needs the header `x-ask-secret: <ASK_SHARED_SECRET>`; a missing or
wrong value gets `401 {"error":"unauthorized"}`.

- `GET /health` → `200 {"ok":true,"model":"opus","effort":"max","active":0,"queued":0,"uptime_s":12}`
- `POST /answer` with `{"question":"…","snippets":[…],"intent":"lookup|compare|rank|timeline","lang":"en|ko","history":[{"question":"…","answer":"…"}]}`
  (`lang` = answer language; `history` = the earlier turns of the conversation, for follow-up questions)
  → `200 {"answer":"…","citations":[1,3],"model":"claude-code-local","model_id":"claude-opus-5","cli_model":"opus","effort":"max","latency_ms":18342,"cost_usd":0.12}`
  (`model_id` = the model the CLI really used — shown in the site's badge together with `effort`)
  → `400` bad body · `429` queue full · `504` process timed out · `500` the CLI failed

Snippets have the shape the browser already sends the route:
`{ kind: "signal"|"contract", company, target?, chain, label, date, text, topics? }`
(≤ 60 snippets, ≤ 2,000 chars each, ≤ 20,000 chars in total, question ≤ 500 chars).

## Expose it to Vercel

The server listens on localhost only; a tunnel gives it a public HTTPS address
that the route can reach. Nothing else on this PC is exposed, and every request
still needs the secret.

### Cloudflare Tunnel (preferred)

Installed on this PC on 2026-09-07 via `winget install Cloudflare.cloudflared`
(binary: `C:\Program Files (x86)\cloudflared\cloudflared.exe`; open a new
terminal so PATH picks it up). **Easiest:** double-click `start-all.cmd` in this
folder — it opens the runner and the quick tunnel in two windows.

**Quick tunnel — no account, one command:**

```bat
cloudflared tunnel --url http://127.0.0.1:8787
```

It prints a random `https://<words>.trycloudflare.com` address. That address
changes every time you start it, so it is fine for testing but you must update
`LOCAL_ASK_URL` on Vercel after each restart.

**Named tunnel — a stable hostname (needs a free Cloudflare account and a domain
whose DNS is on Cloudflare, e.g. `ask.gijun42.com`; if gijun42.com's DNS is
still at the registrar or Vercel, move it to Cloudflare first or use a different
domain):**

```bat
cloudflared tunnel login
cloudflared tunnel create local-ask
cloudflared tunnel route dns local-ask ask.gijun42.com
```

then a `config.yml` (Windows: `%USERPROFILE%\.cloudflared\config.yml`):

```yaml
tunnel: local-ask
credentials-file: C:\Users\<you>\.cloudflared\<tunnel-id>.json
ingress:
  - hostname: ask.gijun42.com
    service: http://127.0.0.1:8787
  - service: http_status:404
```

`cloudflared tunnel run local-ask` starts it; `cloudflared service install`
runs it as a Windows service so it comes back after a reboot.

### Tailscale Funnel (alternative)

Not installed on this PC yet: `winget install tailscale.tailscale`, sign in, then

```bat
tailscale funnel 8787
```

gives `https://<pc-name>.<tailnet>.ts.net` — stable, no domain needed.

### Vercel

Project → **Settings → Environment Variables** (Production, and Preview if you
want previews to use it):

| variable | value |
|---|---|
| `LOCAL_ASK_URL` | the tunnel address, e.g. `https://ask.gijun42.com` — no trailing slash, no path |
| `ASK_SHARED_SECRET` | the same string as in `local-ask/.env` |

Then **Deployments → Redeploy** (env vars are baked in at deploy time). Test
through the tunnel from this PC with
`set LOCAL_ASK_URL=https://… && node smoke.mjs`, then ask a question on the site:
the badge under the answer should read `claude-code-local`.

Remove `LOCAL_ASK_URL` (or just turn the PC off) and the site is back to pure
Gemini — nothing else changes.

## Keeping it up

- Windows **Settings → System → Power**: set "Sleep" to Never while plugged in
  (a sleeping PC = the route waits 3 s on `/health`, then answers with Gemini).
- Start at login: put a shortcut to `start-local-ask.cmd` (and to the tunnel
  command) in `shell:startup`, or create two Task Scheduler tasks "At log on".
- Watch `logs/requests.jsonl` for latency and failures.

## Troubleshooting

| symptom | cause / fix |
|---|---|
| `401 unauthorized` | the secret differs between `local-ask/.env` and Vercel (spaces? quotes?) |
| `429 busy` | more than 5 questions waiting — a burst; the route already limits 10/min/IP |
| `504 … was stopped` | Opus ran longer than `ASK_TIMEOUT_MS`; raise it, or lower `ASK_EFFORT` to `high` |
| `500 could not start claude` | the CLI is not on PATH for this process → set `ASK_CLAUDE_BIN` to the full path |
| `500 claude reported …` | run the printed command by hand; usually a login (`claude` once interactively) or budget cap |
| site always shows Gemini | the route could not reach `/health` within 3 s: tunnel down, PC asleep, wrong `LOCAL_ASK_URL` |
| started from inside Claude Code and it fails | the server already strips `CLAUDECODE` from the child env — check `ASK_CLAUDE_BIN` |
