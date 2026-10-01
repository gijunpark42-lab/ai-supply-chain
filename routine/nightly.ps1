<#
Nightly enrich routine (user, 2026-09-26: run it every night at 23:00 on THIS computer — no API, no cloud).

Windows Task Scheduler starts this script every night at 23:00. It starts ONE background Claude Code session
in this repo, on the user's own Claude login (subscription usage, never the pay-per-use API):
    Monday-Saturday : enrich us   (the daily US command: every source except SEC filings)
    Sunday          : enrich      (the status board's whole Run next list: every market that is due, EDGAR included)
The session shows up in `claude agents` like any background job. Attach in the morning to read its report,
answer its questions, or say "커밋해 푸시해" — it never commits or pushes by itself.

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
param([switch]$Test)   # -Test: start a tiny plumbing-check session instead of an enrich run

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$log = Join-Path $repo ".claude\nightly.log"
function Write-Log($text) {
    Add-Content -Path $log -Encoding UTF8 -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), $text)
}

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

# 2. Tonight's command and the prompt that carries the unattended rules.
if ($Test) { $command = "test" }
elseif ((Get-Date).DayOfWeek -eq "Sunday") { $command = "enrich" }
else { $command = "enrich us" }

if ($Test) {
    $prompt = 'Routine plumbing test started by routine/nightly.ps1. Use the Write tool to create .claude/nightly_test.txt containing the word OK (this checks that the routine can write in place), then reply with one line: OK plus the first item of the Run next list in ENRICH_STATUS.md. Touch nothing else and run nothing else.'
} else {
    $prompt = 'Nightly routine started by routine/nightly.ps1 while nobody is watching. Run `' + $command + '` exactly as the enrich skill says: status board first and last, parallel enricher agents, check_patch, graph_build.py --sync, verification. Unattended rules: never stop to wait for an answer - record a judgment the rules do not settle with enrich_status.py ask and carry on; do not commit, push or merge (the user reviews in the morning); leave alone any uncommitted edits you did not make. Run Python scripts by the literal path, e.g. `/c/Users/calif/AppData/Local/Python/bin/python.exe -X utf8 apply_corrections.py --check` - never through a shell variable such as P=...; $P, because the permission allow rules match the literal command. End with a short report in Korean: what was enriched, new companies, open questions, and the board Run next block. Its last line is `result:` plus a one-line summary - board questions are not a reason to wait. Write `needs input:` instead only when a step could not run (permission denied, usage limit, a source down that the rules cannot work around), naming the step.'
}

# 3. Start the background session. `claude --bg` prints the session id and returns at once.
$name = "nightly $command " + (Get-Date -Format "MM-dd")
$out = & $claude --bg --permission-mode auto -n $name $prompt 2>&1 | Out-String
$match = [regex]::Match($out, "\b[0-9a-f]{8}\b")
if (-not $match.Success) {
    Write-Log ("FAILED to start {0}: {1}" -f $command, $out.Trim())
    exit 1
}
$id = $match.Value
Write-Log ("started {0} as {1}" -f $command, $id)

# 4. Keep the laptop from idle-sleeping until the session stops working (at most 8 hours).
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);'
[Win32.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null   # 0x80000001 = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
$deadline = (Get-Date).AddHours(8)
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
