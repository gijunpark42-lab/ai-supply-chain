<#
Nightly enrich routine (user, 2026-09-26: run it every night at 23:00 on THIS computer — no API, no cloud).

Windows Task Scheduler starts this script every night at 23:00. It starts ONE background Claude Code session
in this repo, on the user's own Claude login (subscription usage, never the pay-per-use API), that runs
`enrich all` every night: every market (US, Korea, Taiwan, Japan, Europe, China, other) and every source, EDGAR,
conferences, IR, the waitlist, news interviews, the relations backfill and the gap fill, due or not (user, 2026-10-19:
"모든나라 그냥 다 한번에 시켜야해 매일 11시마다"; before that bare `enrich` since 10-14, `enrich us` Mon-Sat before that).
The session sizes its worker pool from the free memory (utils/agent_budget.py) and reuses the same workers all night,
recording their progress in utils/work_ledger.py's ledger (user, 2026-10-19); it decides open judgments itself.
If the session stops blocked at graph_build.py (killed for low memory inside Claude Code), this script runs
graph_build.py --sync once more outside the session and publishes when that build succeeds.
The session shows up in `claude agents` like any background job. Attach in the morning to read its report.

Publishing (user, 2026-10-14: "푸시및머지까지 하게시키자"): when the session finishes as done, THIS SCRIPT (not the
session) commits the run's data files only (the $publishPaths list below: transcripts, patches, chains, graph,
web/public, collector state, status board) on a branch nightly-enrich-<date>, pushes it, opens a PR and merges it into
main, then returns the checkout to an up-to-date main. Code, docs and anything else changed stay uncommitted for the
user to review (logged). A run that ends blocked is not published; the next night's run rebuilds and publishes it.
Only the listed paths are committed: a file the user staged by hand stays staged and out of the PR. Nothing is
published from a branch other than main (that branch's unmerged commits would be merged too).
Publish the current data by hand:  powershell -NoProfile -ExecutionPolicy Bypass -File routine\nightly.ps1 -PublishOnly
Publish only the daily market data (what routine/market_data.ps1 runs at 22:00; never switches branches):
    powershell -NoProfile -ExecutionPolicy Bypass -File routine\nightly.ps1 -PublishOnly -MarketOnly

If the computer is off or asleep at 23:00, the task runs as soon as the computer is on again.
While the session works, this script keeps the laptop from idle-sleeping, and it writes one line per event
to .claude/nightly.log (gitignored). If last night's session is still working, tonight is skipped, so two
runs never enrich the same queue. The daily market data does not depend on this: routine/market_data.ps1 collects it
at 22:00 (its own task), and this script runs those steps only when that task did not run today.

Test the plumbing (a tiny session that only writes .claude/nightly_test.txt, no enrich):
    powershell -NoProfile -ExecutionPolicy Bypass -File routine\nightly.ps1 -Test
Register once (current user, runs while logged on, wakes the laptop, catches up after a missed night):
    $a = New-ScheduledTaskAction -Execute powershell.exe -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\calif\Desktop\earnings-ai\routine\nightly.ps1"'
    $t = New-ScheduledTaskTrigger -Daily -At 11pm
    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 12)
    Register-ScheduledTask -TaskName "earnings-ai nightly enrich" -Action $a -Trigger $t -Settings $s
Run tonight's job now:  Start-ScheduledTask -TaskName "earnings-ai nightly enrich"
Stop the routine:       Unregister-ScheduledTask -TaskName "earnings-ai nightly enrich" -Confirm:$false
#>
param(
    [switch]$Test,          # -Test: start a tiny plumbing-check session instead of an enrich run
    [switch]$PublishOnly,   # -PublishOnly: commit + push + PR + merge the current enrich data, start no session
    [switch]$MarketOnly     # -MarketOnly: like -PublishOnly, but only the $marketPaths below (routine/market_data.ps1)
)
if ($MarketOnly) { $PublishOnly = $true }    # -MarketOnly alone must never start an enrich session

$scriptStart = Get-Date     # the 8-hour session limit below counts from here, data steps included
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$log = Join-Path $repo ".claude\nightly.log"
function Write-Log($text) {
    Add-Content -Path $log -Encoding UTF8 -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), $text)
}

# The data an enrich run writes. Only these are auto-published; code (.py, web/src, skills), docs and the
# hand-curated baselines (timelines/, company_metrics.json, capex_backlog.json) wait for the user.
$publishPaths = @(
    "transcripts", "patches", "chains", "graph", "web/public", "static", "i18n", "supply_contracts",
    "av", "investing", "tw", "dart", "edgar", "ir", "kind", "tdnet", "edinet", "mops", "cninfo", "utility_filings",
    "perplexity", "hkex", "dod", "cnbrief",
    "ENRICH_STATUS.md", "enrich_log.json", "enrich_marks.json", "verify_queue.json", "company_metadata.json", "enrich_waitlist.json",
    # Non-AI relationships (decision C, 2026-10-17; relations.py): the rows the nightly backfill writes and its queue.
    "relations", "relations_backfill.json",
    # Daily market data (user, 2026-10-17; market/run_all.py below). Its web files are graph/*.json (covered by
    # "graph") and their copies in web/public/data (covered by "web/public"); market/cache/ is gitignored, never published.
    "market/history", "market/run_log.jsonl", "market/ai_lab_deals.json",
    # News interviews (user, 2026-10-17; media_pull.py, run by routine/market_data.ps1): media/ holds its state, the
    # executive roster, the channel allowlist and the coordinator's list of the interview files enriched
    # (media/enriched.jsonl). The transcripts themselves (transcripts/media) are gitignored: whole broadcasts never go
    # to the public repo (.gitignore says why), so "transcripts" never picks them up.
    "media"
)
# The daily market data alone (-MarketOnly, the 22:00 publish of routine/market_data.ps1): the collectors' history,
# run log and web files, plus the state, roster and channel allowlist of media_pull.py, which runs in the same task
# (enrich skill section 11; its transcripts are gitignored). It leaves out everything an enrich session writes
# (transcripts, patches, chains, the rest of graph, media/enriched.jsonl), so the 22:00 publish never carries what a
# blocked session left; that waits for a night that finishes as done. web/public/data needs no entry: the site's
# build copies graph/ into it (web/package.json "prebuild").
$marketPaths = @(
    "market/history", "market/run_log.jsonl", "market/ai_lab_deals.json",
    "graph/memory_prices.json", "graph/gpu_prices.json", "graph/insiders_index.json", "graph/insiders",
    "graph/financing_index.json", "graph/financing", "graph/hyperscaler_cash.json", "graph/ai_labs.json",
    "graph/transcript_quality.json", "graph/financials_index.json", "graph/financials",
    "media/sync_state.json", "media/executives.json", "media/channels.json"
)

# One git job at a time in this checkout: switching to main, pulling and publishing must never overlap.
# routine/market_data.ps1 pulls at 22:00 and publishes through `nightly.ps1 -PublishOnly -MarketOnly`, and a late
# night of this script (a catch-up start, a session that ends around 22:00) can switch, pull or publish at the same
# time. A named Windows mutex has one holder at a time across processes, and Windows frees it when its holder dies.
# Returns the mutex when it is ours (give it back with .ReleaseMutex()), or $null after $minutes of waiting.
function Enter-GitLock([int]$minutes) {
    $gitLock = New-Object System.Threading.Mutex($false, "Global\earnings-ai-git")
    try { $mine = $gitLock.WaitOne([TimeSpan]::FromMinutes($minutes)) }
    catch { $mine = $true }      # the only error here: the last holder died without releasing it; it is ours now
    if ($mine) { return $gitLock }
    return $null
}

# Run git / gh, log the output when it fails, and return $true on success.
function Invoke-Step($what, [scriptblock]$cmd) {
    $output = & $cmd 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Log ("publish FAILED at {0}: {1}" -f $what, $output.Trim()); return $false }
    return $true
}

# Commit the enrich data on a new branch, push it, open a PR and merge it into main, then come back to main.
# The caller holds the git lock (Enter-GitLock). With -MarketOnly, only $marketPaths are published.
function Publish-Run($label) {
    # Never from another branch: its unmerged commits would go into the PR and be merged into main.
    $current = git branch --show-current
    if ($current -ne "main") { Write-Log ("publish skipped: the checkout is on {0}, not main" -f $current); return }
    if ($MarketOnly) { $kind = "market data"; $list = $marketPaths } else { $kind = "enrich data"; $list = $publishPaths }
    $paths = $list | Where-Object { Test-Path (Join-Path $repo $_) }
    git add -A -- $paths 2>&1 | Out-Null
    # Count and commit ONLY these paths, so a file the user staged by hand stays staged and out of the PR. A path is
    # given to `git commit` only when it has staged changes: git commit stops on a path git does not track at all
    # (the gitignored av/, investing/ and tw/ folders exist on disk).
    $commitPaths = @($paths | Where-Object { @(git diff --cached --name-only -- $_).Count -gt 0 })
    if ($commitPaths.Count -eq 0) { Write-Log ("publish: no {0} changed, nothing to commit" -f $kind); return }
    $staged = @(git diff --cached --name-only -- $commitPaths)
    if ($MarketOnly) {
        $branch = "market-data-" + (Get-Date -Format "yyyy-MM-dd-HHmm")
        $title = "Market data {0} (auto-published, {1} files)" -f $label, $staged.Count
        $why = "Daily market-data files written by routine/market_data.ps1; published by routine/nightly.ps1 -PublishOnly -MarketOnly (user, 2026-10-17)."
        $body = "Auto-published by routine/market_data.ps1 after the daily market-data run. Market data files only; the run's log is .claude/market_data_task.log."
    } else {
        $branch = "nightly-enrich-" + (Get-Date -Format "yyyy-MM-dd-HHmm")
        $title = "Nightly enrich {0} (auto-published, {1} files)" -f $label, $staged.Count
        $why = "Data files written by the nightly enrich session; published by routine/nightly.ps1 (user, 2026-10-14: push and merge every night)."
        $body = "Auto-published by routine/nightly.ps1 after the nightly enrich session finished as done. Data files only; the session's report is in claude agents and .claude/nightly.log."
    }
    if (-not (Invoke-Step "switch -c" { git switch -c $branch })) { return }
    if (-not (Invoke-Step "commit" { git commit -q -m $title -m $why -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- $commitPaths })) { return }
    if (-not (Invoke-Step "push" { git push -q -u origin $branch })) { return }
    $pr =(gh pr create --base main --head $branch --title $title --body $body 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { Write-Log ("publish FAILED at pr create: {0}" -f $pr); return }
    if (-not (Invoke-Step "merge" { gh pr merge $branch --merge --delete-branch })) { Write-Log ("PR left open: {0}" -f $pr); return }
    git switch main 2>&1 | Out-Null
    git pull --ff-only -q 2>&1 | Out-Null
    Write-Log ("published and merged {0} files: {1}" -f $staged.Count, $pr)
    $left = @(git status --porcelain)
    if ($left.Count -gt 0) { Write-Log ("left uncommitted for review ({0}): {1}" -f $left.Count, (($left | Select-Object -First 8) -join "; ")) }
}
$runDate = Get-Date -Format "MM-dd"   # the night the run started; labels the session and its PR

# The Claude Code CLI: the native installer's location, else whatever is on PATH.
$claude = Join-Path $env:USERPROFILE ".local\bin\claude.exe"
if (-not (Test-Path $claude)) { $claude = (Get-Command claude -ErrorAction Stop).Source }

# Never the pay-per-use API: without this variable, claude uses the user's own login.
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue

# `claude agents --json` lists the background sessions: id, name, state (working / blocked / done).
# (Store it in a variable before filtering: Windows PowerShell hands a JSON array over as one object.)
function Get-Sessions {
    $sessions = (& $claude agents --json | Out-String) | ConvertFrom-Json
    return $sessions
}

# 1. Skip tonight if last night's session is still working.
$running = Get-Sessions | Where-Object { $_.name -like "nightly enrich*" -and $_.state -eq "working" }
if ($running -and -not $Test) {
    Write-Log ("skipped: {0} ({1}) is still working" -f $running[0].id, $running[0].name)
    exit 0
}

# Start from an up-to-date main (uncommitted data is carried along when nothing conflicts), holding the git lock.
# With -MarketOnly (the 22:00 publish of routine/market_data.ps1) the branch is never switched: on another branch
# nothing is pulled, and Publish-Run stops.
if (-not $Test) {
    if ($PublishOnly) { $waitMinutes = 5 } else { $waitMinutes = 20 }
    $gitLock = Enter-GitLock $waitMinutes
    if (-not $gitLock) {
        # The checkout may be on the other job's publish branch right now: no session and no publish on top of it.
        Write-Log ("skipped: another git job (a publish) still held the git lock after {0} min" -f $waitMinutes)
        exit 0
    }
    $onMain = (git branch --show-current) -eq "main"
    if (-not $onMain -and -not $MarketOnly) {
        if (-not (Invoke-Step "switch main" { git switch main })) { Write-Log "staying on $(git branch --show-current)" }
    }
    if ($onMain -or -not $MarketOnly) { Invoke-Step "pull main" { git pull --ff-only -q } | Out-Null }
    if ($PublishOnly) {
        if ($MarketOnly) { Publish-Run $runDate } else { Publish-Run ("manual " + $runDate) }
    }
    $gitLock.ReleaseMutex()
}
if ($PublishOnly) { exit 0 }

# 1b. Daily market data (user, 2026-10-17), BEFORE the enrich session: free sources fetched by scripts only (no model
#     tokens), then the transcript quality scan the session reads (graph/transcript_quality.json). Each step is
#     time-boxed; a failure or timeout is logged and the night goes on to enrich. Full output: .claude\<step>.log.
#     Normally skipped: the 22:00 task routine/market_data.ps1 already ran them (see below).
$python = Join-Path $env:LOCALAPPDATA "Python\bin\python.exe"     # the same Python the session is told to use
if (-not (Test-Path $python)) { $found = Get-Command python -ErrorAction SilentlyContinue; if ($found) { $python = $found.Source } }
function Invoke-DataStep($step, [string[]]$arguments, [int]$minutes) {
    $script:stepExit = -1                                        # the step's exit code once it ends (-1 = failed / timed out)
    $out = Join-Path $repo (".claude\" + $step + ".log")
    $err = Join-Path $repo (".claude\" + $step + ".err.log")     # Start-Process needs a separate file for stderr
    try {
        $p = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repo -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    } catch {
        Write-Log ("{0} FAILED to start: {1}" -f $step, $_.Exception.Message)
        return
    }
    $null = $p.Handle                                            # keeps ExitCode readable after the process ends
    if (-not $p.WaitForExit($minutes * 60 * 1000)) {
        # Stop the whole process tree, as routine/market_data.ps1 does: media_pull.py runs yt-dlp, which runs node.
        & taskkill.exe /T /F /PID $p.Id 2>&1 | Out-Null
        if (-not $p.HasExited) { try { $p.Kill() } catch { } }
        Write-Log ("{0} TIMED OUT after {1} min and was stopped (steps that finished are kept)" -f $step, $minutes)
        return
    }
    $last = Get-Content $out -Tail 1 -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $last) { $last = "(no output; see " + $err + ")" }
    $script:stepExit = $p.ExitCode
    Write-Log ("{0} exit {1}: {2}" -f $step, $p.ExitCode, $last)
}
# Since 2026-10-17 the 22:00 task (routine/market_data.ps1) runs these steps an hour earlier, even on a night this
# script skips. So they run here only as a fallback: when market/run_log.jsonl lacks today's line for some collector
# (the 22:00 task did not run today). The Python check below prints the missing collector names (empty = all ran);
# it uses run_all.py's own collector list and Pacific date, so it never drifts from the log. The fallback runs the
# 22:00 task's steps a) to d): the tests, the missing collectors, the transcript scan and the phone-alert check.
$runLogCheck = @'
import json
from market.run_all import NAMES, RUN_LOG
from market.common import today
seen = set()
if RUN_LOG.exists():
    for line in RUN_LOG.read_text(encoding='utf-8').splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get('date') == today():
            seen.add(entry.get('collector'))
print(' '.join(name for name in NAMES if name not in seen))
'@
if (-not $Test) {
    # Both scripts take this lock (a named Windows mutex: one holder at a time, freed by Windows when its holder dies)
    # around their market-data steps, so they never collect at the same time. The 22:00 task stops itself within 2 hours.
    $lock = New-Object System.Threading.Mutex($false, "Global\earnings-ai-market-data")
    try { $haveLock = $lock.WaitOne([TimeSpan]::FromMinutes(125)) }
    catch { $haveLock = $true }      # the only error here: the last holder died without releasing it; it is ours now
    if (-not $haveLock) {
        Write-Log "market data skipped: the 22:00 market-data task still held its lock after 125 min"
    } else {
        $missing = (& $python -X utf8 -c $runLogCheck | Out-String).Trim()     # stdout only: a warning on stderr is not a name
        if ($LASTEXITCODE -ne 0) { $missing = "unknown, the run_log check failed" }
        if (-not $missing) {
            Write-Log "market data: the 22:00 task already ran every collector today, data steps skipped"
        } else {
            Write-Log ("market data fallback, today's run_log lacks: {0}" -f $missing)
            # Only the missing collectors (run_all.py keeps its fixed order); all of them when the check itself failed.
            $runAll = @("-X", "utf8", "market/run_all.py")
            if ($missing -notlike "unknown*") { $runAll += @("--only", ($missing -replace ' ', ',')) }
            Invoke-DataStep "selftest" @("-X", "utf8", "market/selftest.py") 10
            Invoke-DataStep "market_data" $runAll 45
            Invoke-DataStep "transcript_quality" @("-X", "utf8", "utils/transcript_quality.py") 10
            # Without this, a night on which the 22:00 task did not run would stay silent. health.py pushes each
            # alert at most once a day, so running it here too is harmless.
            Invoke-DataStep "market_health" @("-X", "utf8", "market/health.py") 5
        }
        # News interviews (user, 2026-10-17: "유튜브도 매일 enrich에 포함"): media_pull.py normally runs in the 22:00 task
        # (its step c2). It keeps to one run a day by itself (media/sync_state.json), so calling it here is a no-op after
        # the 22:00 run and a catch-up when that task did not run or skipped it for time. Either way the session below
        # reads today's interviews (enrich skill section 11).
        if (Test-Path (Join-Path $repo "media_pull.py")) {
            Invoke-DataStep "media_roster" @("-X", "utf8", "media_roster.py") 3      # executives found in today's documents
            Invoke-DataStep "media_pull" @("-X", "utf8", "media_pull.py", "--days", "3") 20
        }
        # Perplexity Finance calls for every market (user, 2026-10-21: "4번" + "안 막히게"): real Chrome + the site's own
        # JSON, paced and capped, one run a day by itself (perplexity/sync_state.json). Before the session, so the
        # session finds the new calls in perplexity/pending.json (enrich skill references/pplx.md).
        if (Test-Path (Join-Path $repo "pplx.py")) {
            Invoke-DataStep "pplx" @("-X", "utf8", "pplx.py", "sync") 45
        }
        $lock.ReleaseMutex()
    }
}

# 2. Tonight's command and the prompt that carries the unattended rules.
if ($Test) { $command = "test" } else { $command = "enrich all" }

if ($Test) {
    $prompt = 'Routine plumbing test started by routine/nightly.ps1. Use the Write tool to create .claude/nightly_test.txt containing the word OK (this checks that the routine can write in place), then reply with one line: OK plus the first item of the Run next list in ENRICH_STATUS.md. Touch nothing else and run nothing else.'
} else {
    $prompt = 'Nightly routine started by routine/nightly.ps1 while nobody is watching. Run `' + $command + '` exactly as the enrich skill says (section 1): every market and every source tonight, due or not - US, Korea, Taiwan, Japan, Europe, China, other, EDGAR, conferences, IR, the waitlist - then the Perplexity Finance call queue (pplx.py pending, references/pplx.md; pplx.py sync already ran), the news interviews (media_status.py, section 11), the relations backfill (relations.py next 15, relations/ rows, utils/check_relations.py until clean, relations.py done), the gap fill batch on the board (section 12: fill or mark every gap), graph_build.py --sync, verification and translation; run every build as `/c/Users/calif/AppData/Local/Python/bin/python.exe -X utf8 utils/build_outside.py` (section 7.2: it runs graph_build.py --sync outside Claude Code, whose low-memory guard killed the in-session build on 10-18, 10-19 and 10-20; while it prints still running, call it again with --wait); status board first and last - refresh it with `/c/Users/calif/AppData/Local/Python/bin/python.exe -X utf8 utils/build_outside.py --board`, never enrich_status.py with no command inside the session (it takes ~1.8 GB; the last refresh of the 10-21 morning run was killed). Worker pool (section 7.4): run utils/agent_budget.py first and never have more agents alive than its agents: number (re-run it before graph_build.py); spawn the pool once and give every next batch to the same idle worker with SendMessage instead of spawning new agents; run utils/work_ledger.py start first and hand out its carried-over items first, and record every batch with work_ledger.py assign and done. Before every graph_build.py: stop every pool worker (TaskStop; each idle worker keeps a process of ~350 MB alive - the 10-20 build was killed with 21 claude processes holding 4 GB), make sure no tool process of yours is still running, and re-run utils/agent_budget.py; restart workers from the ledger only if work remains after the build. Record notes, marks and decisions with enrich_status.py (it no longer rebuilds the board; never pass --board during the run). Unattended rules: never stop to wait for an answer - a judgment the rules do not settle is decided by an independent Opus verifier from the rules and the user earlier answers (enrich_marks.json answered), applied, and recorded with enrich_status.py decide --no-board (section 0.3); do not commit, push or merge yourself - routine/nightly.ps1 publishes the data (branch, PR, merge into main) after you stop, and only if you finish with result:, so end with needs input: if graph_build.py --sync or verification did not complete; leave alone any uncommitted edits you did not make. Run Python scripts by the literal path, e.g. `/c/Users/calif/AppData/Local/Python/bin/python.exe -X utf8 apply_corrections.py --check` - never through a shell variable such as P=...; $P, because the permission allow rules match the literal command. End with a short report in Korean: what was enriched per market, the gap fill (filled / marked), new companies, the decisions you made, and the board Run next block. Its last line is `result:` plus a one-line summary. Low memory is handled, never a stop (user, 2026-10-21): when Claude Code stops one of your commands, monitors or workers for low memory, do not end the run - re-run utils/agent_budget.py until it allows an agent, shrink the pool to its number, rerun the stopped step (heavy scripts through utils/build_outside.py) and go on; write needs input: memory only after the same step was stopped three times. A source that needs a login, an account or a paid subscription is deferred, never a stop (user, 2026-10-21: login-gated sources wait): skip it, mark the gap with enrich_status.py mark --no-board (--why naming the login wall) and go on; never sign in or create an account. Write `needs input:` instead only when a step could not run (permission denied, usage limit, a source down that the rules cannot work around), naming the step; when the build failed (build_outside.py exit 1 with a memory error, or its process gone), name graph_build in that line and do not restart it more than once - the script reruns it outside the session.'
}

# Free memory first (2026-10-21: the 10-20 build was killed with 21 claude processes holding 4 GB): stop the automated
# background sessions that are done or waiting (fintweet day sessions, earlier nightlies). `claude stop` keeps each
# conversation (`claude attach <id>` reopens it); the user's own sessions are left alone.
if (-not $Test) {
    $idle = @((Get-Sessions) | Where-Object { $_.kind -eq "background" -and $_.state -ne "working" -and ($_.name -like "fintweet *" -or $_.name -like "nightly *") })
    foreach ($s in $idle) { & $claude stop $s.id 2>&1 | Out-Null }
    if ($idle.Count -gt 0) { Write-Log ("stopped {0} finished automated session(s): {1}" -f $idle.Count, (($idle | ForEach-Object { $_.name }) -join ", ")) }
}

# The memory the session starts with and the agent ceiling it will get from utils/agent_budget.py (user, 2026-10-19).
if (-not $Test) { Write-Log ("memory at start: " + (& $python -X utf8 (Join-Path $repo "utils\agent_budget.py") | Out-String).Trim()) }

# 3. Start the background session. `claude --bg` prints the session id and returns at once.
$name = "nightly $command " + $runDate
$out = & $claude --bg --permission-mode auto -n $name $prompt 2>&1 | Out-String
$match = [regex]::Match($out, "\b[0-9a-f]{8}\b")
if (-not $match.Success) {
    Write-Log ("FAILED to start {0}: {1}" -f $command, $out.Trim())
    exit 1
}
$id = $match.Value
Write-Log ("started {0} as {1}" -f $command, $id)

# 4. Keep the laptop from idle-sleeping until the session stops working (at most 10.5 hours after this script started:
#    `enrich all` covers every market every night, Task Scheduler stops the script at 12 hours (2026-10-19; it was 9),
#    and counting from the script start leaves the rebuild of 4b and Publish-Run about 90 minutes).
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);'
[Win32.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null   # 0x80000001 = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
$deadline = $scriptStart.AddHours(10.5)
# 4a. A stop for low memory is noticed and handled here (user, 2026-10-21: "메모리 때문에 중단되면 니가 알 수 있게 한 담에
#     니가 알아서 처리해야지"): when the session stops without finishing and its detail names memory, this script logs it
#     ("memory stop"), frees memory (stops the other finished automated sessions and the stopped one; `claude stop` keeps
#     every conversation), waits until 3.5 GB is free (30 min at most) and resumes the same conversation with
#     `claude --bg --resume`, which carries its whole history and ledger. At most 3 resumes, and none in the last
#     45 minutes before the deadline; after that the safety net of 4b and the next night take over.
$resumes = 0
while ($true) {
    do {
        Start-Sleep -Seconds 60
        $job = Get-Sessions | Where-Object { $_.id -eq $id }
    } while ($job -and $job.state -eq "working" -and (Get-Date) -lt $deadline)

    if ($job) { $state = $job.state } else { $state = "finished (no longer listed)" }
    # The job's own one-line detail says why it stopped (finished, or the step that is blocked).
    $stateFile = Join-Path $env:USERPROFILE ".claude\jobs\$id\state.json"
    $sessionId = $null
    if (Test-Path $stateFile) {
        $jobState = Get-Content $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        $sessionId = $jobState.sessionId
        if ($jobState.detail) { $state = "{0} - {1}" -f $state, $jobState.detail }
    }
    Write-Log ("{0} stopped working: {1}" -f $id, $state)

    # The session reports in Korean, so its detail may say memory in Korean. This file has no BOM, so the word is built
    # from its code points (Hangul typed into the code would be misread by Windows PowerShell).
    $koMemory = -join [char[]](0xBA54, 0xBAA8, 0xB9AC)      # the Korean word for memory, built from its code points
    $memoryStop = ($state -notlike "done*") -and ($state -match ("memory|" + $koMemory + "|OOM"))
    if ($Test -or -not $memoryStop) { break }
    if ($resumes -ge 3 -or -not $sessionId -or (Get-Date) -gt $deadline.AddMinutes(-45)) {
        Write-Log ("memory stop: not resumed (resumes so far {0}, session id {1}); the safety net and the next night take over" -f $resumes, $sessionId)
        break
    }
    $resumes++
    $others = @((Get-Sessions) | Where-Object { $_.kind -eq "background" -and $_.state -ne "working" -and ($_.name -like "fintweet *" -or $_.name -like "nightly *") })
    foreach ($s in $others) { & $claude stop $s.id 2>&1 | Out-Null }
    $waitUntil = (Get-Date).AddMinutes(30)
    do {
        $free = [double]((& $python -X utf8 (Join-Path $repo "utils\agent_budget.py") --json | Out-String) | ConvertFrom-Json).free_gb
        if ($free -ge 3.5) { break }
        Start-Sleep -Seconds 60
    } while ((Get-Date) -lt $waitUntil)
    Write-Log ("memory stop {0} of 3: stopped {1} finished session(s), {2} GB free; resuming the conversation" -f $resumes, $others.Count, $free)
    $resumePrompt = 'routine/nightly.ps1 resumed you after a stop for low memory (resume ' + $resumes + ' of 3; user, 2026-10-21: a memory stop is handled, never left). Continue the same enrich all run from where it stopped: run utils/agent_budget.py and keep the pool within its number, read utils/work_ledger.py show for what is left, rerun the step that was stopped (heavy scripts through utils/build_outside.py), then finish the night exactly as your first instructions say, ending with result: or needs input: as before.'
    $out = & $claude --bg --resume $sessionId --permission-mode auto -n $name $resumePrompt 2>&1 | Out-String
    $hint = [regex]::Matches($out, "claude logs ([0-9a-f]{8})")
    if ($hint.Count -gt 0) { $newId = $hint[$hint.Count - 1].Groups[1].Value }
    else { $m = [regex]::Match($out, "\b[0-9a-f]{8}\b"); if ($m.Success) { $newId = $m.Value } else { $newId = $null } }
    if (-not $newId) { Write-Log ("memory stop: resume FAILED: {0}" -f $out.Trim()); break }
    $id = $newId
    Write-Log ("memory stop: resumed as {0}" -f $id)
}

# 4b. Safety net (user, 2026-10-19): inside Claude Code a big graph_build.py can be killed for low memory, and the session
#     then stops blocked naming graph_build. Run the build once more here, outside the session (no such guard), and treat
#     the night as done when it exits 0 and every label applied tonight passes verify_graph (utils/verify_since.py: the
#     rebuild itself has nothing left to apply, so it verifies nothing). A run blocked anywhere else is never published
#     (its unapplied patches may not have been verified yet).
if (-not $Test -and $state -notlike "done*" -and $state -match "graph_build") {
    Write-Log "rebuilding outside the session: graph_build.py --sync"
    Invoke-DataStep "graph_build" @("-X", "utf8", "graph_build.py", "--sync") 60
    $built = $script:stepExit
    if ($built -eq 0) { Invoke-DataStep "verify_since" @("-X", "utf8", "utils/verify_since.py", ('"{0}"' -f $scriptStart.ToString("yyyy-MM-dd HH:mm"))) 40 }   # quoted: Start-Process joins arguments with spaces
    if ($built -eq 0 -and $script:stepExit -eq 0) { $state = "done - graph_build.py --sync rerun by nightly.ps1 after: " + $state }
    else { Write-Log ("rebuild did not settle it (build exit {0}, verify exit {1}); the next night rebuilds" -f $built, $script:stepExit) }
}

# 5. Publish the run (user, 2026-10-14). Only a run that finished as done; a blocked run is rebuilt and published next night.
if (-not $Test) {
    if ($state -like "done*") {
        # The board as the run left it (marks, notes and decisions recorded after the last build), refreshed here,
        # outside the session, so the published ENRICH_STATUS.md is current (2026-10-21: the in-session refresh was
        # killed for low memory).
        Invoke-DataStep "board" @("-X", "utf8", "enrich_status.py") 30
        $gitLock = Enter-GitLock 20                   # the 22:00 market-data publish may be running right now
        if ($gitLock) { Publish-Run $runDate; $gitLock.ReleaseMutex() }
        else { Write-Log "not published: another git job (a publish) still held the git lock after 20 min; the next done night publishes this data" }
        # The map over MCP (user, 2026-10-20): nodus42_mcp.py and the site's /api/mcp read the built data, so the
        # publish updates them; this waits for the site's deploy and logs whether the remote MCP serves the new map.
        if (Test-Path (Join-Path $repo "utils\mcp_check.py")) {
            Invoke-DataStep "mcp_check" @("-X", "utf8", "utils/mcp_check.py", "--minutes", "15") 20
        }
    }
    else { Write-Log "not published: the session did not finish as done" }
    # Free the session's memory right away (2026-10-21: the morning run's finished session stayed loaded until the next
    # night, ~350 MB, while the fintweet slots and the next run ran short). `claude stop` keeps the conversation:
    # `claude attach <id>` reopens it for the report.
    if ($job -or (Get-Sessions | Where-Object { $_.id -eq $id })) { & $claude stop $id 2>&1 | Out-Null; Write-Log ("stopped {0} to free its memory (claude attach {0} reopens it)" -f $id) }
}
