---
name: ask-server
description: Check or restart the local Opus engine behind the live Ask tab. Use when the user says "ask 실행", "ask up", "ask 종료" or "ask down". NEVER runs local-ask/up.mjs (it would overwrite the fixed Tailscale address on Vercel).
---

### Workflow 3 — `ask 실행` (make sure the local Opus engine is behind the live site)

**Do NOT run `node local-ask/up.mjs`** (or `down.mjs`). Since 2026-09-13 the runner is reached through a FIXED Tailscale Funnel address (`https://gijun-pc.tail362ef7.ts.net`) that is already set as `LOCAL_ASK_URL` on Vercel; `up.mjs` would overwrite it with a throwaway trycloudflare address and break Ask. The runner autostarts at logon (scheduled task "local-ask runner"); the desktop `Ask Switch.cmd` (repo copy: `local-ask/switch/`) shows ON/OFF and flips the runner.

**Trigger: the user says `ask 실행` or `ask up`.** Run these three checks (Git Bash) and report each line:

```bash
# 1. runner on this PC (starts it through the scheduled task if it is down)
curl -s -m 3 -o /dev/null http://127.0.0.1:8787/health || (schtasks /run /tn "local-ask runner" && sleep 5)
curl -s -m 3 http://127.0.0.1:8787/health          # 401 without the secret = up; connection refused = down (see local-ask/logs/runner.out)
# 2. Tailscale Funnel (fixed public address)
"C:/Program Files/Tailscale/tailscale.exe" funnel status   # must show https://gijun-pc.tail362ef7.ts.net -> proxy http://127.0.0.1:8787
# 3. the public address reaches the runner
curl -s -m 20 -o /dev/null -w "%{http_code}\n" https://gijun-pc.tail362ef7.ts.net/health   # 401 or 200 = reachable
```

If step 2 shows no funnel config, re-enable it once: `"C:/Program Files/Tailscale/tailscale.exe" funnel --bg 8787`.
If Tailscale is logged out or `tailscale status --json` shows `BackendState: NoState`, run
`"C:/Program Files/Tailscale/tailscale.exe" up --hostname gijun-pc --unattended` (the user logs in in the browser if
asked). `--unattended` is required: without it the connection drops as soon as no Tailscale client is attached.
Nothing on Vercel needs to change — `LOCAL_ASK_URL` is permanent. Optionally verify live: POST one
question to `https://gijun42.com/api/ask` and check the `done` line says `"engine":"local"`.

The runner is `local-ask/server.mjs` (the Claude Code CLI: Opus, max effort, no tools — the user's subscription,
no API key). The website has NO API fallback by design (Gemini and the Anthropic API were removed on 2026-09-11):
when the runner is unreachable the site says "Ask is busy".

**`ask 종료` / `ask down`** → stop the runner only (the site then shows "Ask is busy"; the next logon starts it again):

```powershell
Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -match 'server\.mjs' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Never print or paste `ASK_SHARED_SECRET` — it lives in `local-ask/.env` (git-ignored) and on Vercel. Details in
`local-ask/README.md`.
