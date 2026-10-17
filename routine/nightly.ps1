<#
Nightly enrich routine (user, 2026-09-26: run it every night at 23:00 on THIS computer — no API, no cloud).

Windows Task Scheduler starts this script every night at 23:00. It starts ONE background Claude Code session
in this repo, on the user's own Claude login (subscription usage, never the pay-per-use API), that runs
`enrich` every night: the status board's whole Run next list, every market that is due, EDGAR included
(user, 2026-10-14: "야간 enrich들 앞으로 그냥 모든 enrich로"; before that it was `enrich us` Mon-Sat and `enrich` on Sunday).
The session shows up in `claude agents` like any background job. Attach in the morning to read its report.

Publishing (user, 2026-10-14: "푸시및머지까지 하게시키자"): when the session finishes as done, THIS SCRIPT (not the
session) commits the run's data files only (the $publishPaths list below: transcripts, patches, chains, graph,
web/public, collector state, status board) on a branch nightly-enrich-<date>, pushes it, opens a PR and merges it into
main, then returns the checkout to an up-to-date main. Code, docs and anything else changed stay uncommitted for the
user to review (logged). A run that ends blocked is not published; the next night's run rebuilds and publishes it.
Publish the current data by hand:  powershell -NoProfile -ExecutionPolicy Bypass -File routine\nightly.ps1 -PublishOnly

If the computer is off or asleep at 23:00, the task runs as soon as the computer is on again.
While the session works, this script keeps the laptop from idle-sleeping, and it writes one line per event
to .claude/nightly.log (gitignored). If last night's session is still working, tonight is skipped, so two
runs never enrich the same queue.

Test the plumbing (a tiny session that only writes .claude/nightly_test.txt, no enrich):
    powershell -NoProfile -ExecutionPolicy Bypass -File routine\nightly.ps1 -Test
Register once (current user, runs while logged on, wakes the laptop, catches up after a missed night):
    $a = New-ScheduledTaskAction -Execute powershell.exe -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\calif\Desktop\earnings-ai\routine\nightly.ps1"'
    $t = New-ScheduledTaskTrigger -Daily -At 11pm
    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 9)
    Register-ScheduledTask -TaskName "earnings-ai nightly enrich" -Action $a -Trigger $t -Settings $s
Run tonight's job now:  Start-ScheduledTask -TaskName "earnings-ai nightly enrich"
Stop the routine:       Unregister-ScheduledTask -TaskName "earnings-ai nightly enrich" -Confirm:$false
#>
param(
    [switch]$Test,          # -Test: start a tiny plumbing-check session instead of an enrich run
    [switch]$PublishOnly    # -PublishOnly: commit + push + PR + merge the current enrich data, start no session
)

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
    "ENRICH_STATUS.md", "enrich_log.json", "enrich_marks.json", "verify_queue.json", "company_metadata.json", "enrich_waitlist.json",
    # Daily market data (user, 2026-10-17; market/run_all.py below). Its web files are graph/*.json (covered by
    # "graph") and their copies in web/public/data (covered by "web/public"); market/cache/ is gitignored, never published.
    "market/history", "market/run_log.jsonl", "market/ai_lab_deals.json"
)

# Run git / gh, log the output when it fails, and return $true on success.
function Invoke-Step($what, [scriptblock]$cmd) {
    $output = & $cmd 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { Write-Log ("publish FAILED at {0}: {1}" -f $what, $output.Trim()); return $false }
    return $true
}

# Commit the enrich data on a new branch, push it, open a PR and merge it into main, then come back to main.
function Publish-Run($label) {
    $paths = $publishPaths | Where-Object { Test-Path (Join-Path $repo $_) }
    git add -A -- $paths 2>&1 | Out-Null
    $staged = @(git diff --cached --name-only)
    if ($staged.Count -eq 0) { Write-Log "publish: no enrich data changed, nothing to commit"; return }
    $branch = "nightly-enrich-" + (Get-Date -Format "yyyy-MM-dd-HHmm")
    $title = "Nightly enrich {0} (auto-published, {1} files)" -f $label, $staged.Count
    if (-not (Invoke-Step "switch -c" { git switch -c $branch })) { return }
    if (-not (Invoke-Step "commit" { git commit -q -m $title -m "Data files written by the nightly enrich session; published by routine/nightly.ps1 (user, 2026-10-14: push and merge every night)." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" })) { return }
    if (-not (Invoke-Step "push" { git push -q -u origin $branch })) { return }
    $body = "Auto-published by routine/nightly.ps1 after the nightly enrich session finished as done. Data files only; the session's report is in claude agents and .claude/nightly.log."
    $pr = (gh pr create --base main --head $branch --title $title --body $body 2>&1 | Out-String).Trim()
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

# Start from an up-to-date main (uncommitted data is carried along when nothing conflicts).
if (-not $Test) {
    if ((git branch --show-current) -ne "main") {
        if (-not (Invoke-Step "switch main" { git switch main })) { Write-Log "staying on $(git branch --show-current)" }
    }
    Invoke-Step "pull main" { git pull --ff-only -q } | Out-Null
}
if ($PublishOnly) { Publish-Run ("manual " + $runDate); exit 0 }

# 1b. Daily market data (user, 2026-10-17), BEFORE the enrich session: free sources fetched by scripts only (no model
#     tokens), then the transcript quality scan the session reads (graph/transcript_quality.json). Each step is
#     time-boxed; a failure or timeout is logged and the night goes on to enrich. Full output: .claude\<step>.log.
$python = Join-Path $env:LOCALAPPDATA "Python\bin\python.exe"     # the same Python the session is told to use
if (-not (Test-Path $python)) { $found = Get-Command python -ErrorAction SilentlyContinue; if ($found) { $python = $found.Source } }
function Invoke-DataStep($step, [string[]]$arguments, [int]$minutes) {
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
        try { $p.Kill() } catch { }
        Write-Log ("{0} TIMED OUT after {1} min and was stopped (steps that finished are kept)" -f $step, $minutes)
        return
    }
    $last = Get-Content $out -Tail 1 -Encoding UTF8 -ErrorAction SilentlyContinue
    if (-not $last) { $last = "(no output; see " + $err + ")" }
    Write-Log ("{0} exit {1}: {2}" -f $step, $p.ExitCode, $last)
}
if (-not $Test) {
    Invoke-DataStep "market_data" @("-X", "utf8", "market/run_all.py") 45
    Invoke-DataStep "transcript_quality" @("-X", "utf8", "utils/transcript_quality.py") 10
}

# 2. Tonight's command and the prompt that carries the unattended rules.
if ($Test) { $command = "test" } else { $command = "enrich" }

if ($Test) {
    $prompt = 'Routine plumbing test started by routine/nightly.ps1. Use the Write tool to create .claude/nightly_test.txt containing the word OK (this checks that the routine can write in place), then reply with one line: OK plus the first item of the Run next list in ENRICH_STATUS.md. Touch nothing else and run nothing else.'
} else {
    $prompt = 'Nightly routine started by routine/nightly.ps1 while nobody is watching. Run `' + $command + '` exactly as the enrich skill says: status board first and last, parallel enricher agents, check_patch, graph_build.py --sync, verification. Unattended rules: never stop to wait for an answer - record a judgment the rules do not settle with enrich_status.py ask and carry on; do not commit, push or merge yourself - routine/nightly.ps1 publishes the data (branch, PR, merge into main) after you stop, and only if you finish with result:, so end with needs input: if graph_build.py --sync or verification did not complete; leave alone any uncommitted edits you did not make. Run Python scripts by the literal path, e.g. `/c/Users/calif/AppData/Local/Python/bin/python.exe -X utf8 apply_corrections.py --check` - never through a shell variable such as P=...; $P, because the permission allow rules match the literal command. End with a short report in Korean: what was enriched, new companies, open questions, and the board Run next block. Its last line is `result:` plus a one-line summary - board questions are not a reason to wait. Write `needs input:` instead only when a step could not run (permission denied, usage limit, a source down that the rules cannot work around), naming the step.'
}

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

# 4. Keep the laptop from idle-sleeping until the session stops working (at most 8 hours after this script started:
#    the data steps of 1b can take up to 55 minutes, and Task Scheduler stops the script at 9 hours, so counting from
#    the script start leaves Publish-Run about an hour instead of a few minutes).
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);'
[Win32.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null   # 0x80000001 = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
$deadline = $scriptStart.AddHours(8)
do {
    Start-Sleep -Seconds 60
    $job = Get-Sessions | Where-Object { $_.id -eq $id }
} while ($job -and $job.state -eq "working" -and (Get-Date) -lt $deadline)

if ($job) { $state = $job.state } else { $state = "finished (no longer listed)" }
# The job's own one-line detail says why it stopped (finished, or the step that is blocked).
$stateFile = Join-Path $env:USERPROFILE ".claude\jobs\$id\state.json"
if (Test-Path $stateFile) {
    $detail = (Get-Content $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json).detail
    if ($detail) { $state = "{0} - {1}" -f $state, $detail }
}
Write-Log ("{0} stopped working: {1}" -f $id, $state)

# 5. Publish the run (user, 2026-10-14). Only a run that finished as done; a blocked run is rebuilt and published next night.
if (-not $Test) {
    if ($state -like "done*") { Publish-Run $runDate }
    else { Write-Log "not published: the session did not finish as done" }
}
