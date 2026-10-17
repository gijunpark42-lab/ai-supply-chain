<#
Daily market-data routine (user, 2026-10-17: the daily market-data collection must not be skipped when the
previous enrich session is still running; a failure must reach the phone instead of staying silent).

Windows Task Scheduler starts this script every day at 22:00, one hour before routine/nightly.ps1. It runs scripts
only (no Claude session, no model tokens), so it runs even when last night's enrich session is still working - the
case where nightly.ps1 skips its whole night. First it logs which branch and commit will run the collectors, and on
main (with no "nightly enrich*" session working in the checkout) it pulls, so a collector fix merged on GitHub is
used the same day. Then these steps, in this order, each one time-boxed:
    a) market/selftest.py           offline regression tests that pin known parsing results
                                    (writes market/selftest_result.json)                                  10 min
    b) market/run_all.py            every market-data collector, one line each in market/run_log.jsonl    45 min
    c) utils/transcript_quality.py  writes graph/transcript_quality.json for the enrich session            10 min
    d) market/health.py             reads market/run_log.jsonl and the selftest result, sends the phone
                                    alert (a collector failed 2 nights in a row, or the tests failed)      5 min
    e) publish                      routine/nightly.ps1 -PublishOnly -MarketOnly: the market-data files only
                                    (branch, PR, merge into main), when the checkout is on main, no
                                    "nightly enrich*" session is working and the collectors added market
                                    history rows                                                          15 min
A step whose script does not exist yet is skipped and logged. One line per event goes to
.claude/market_data_task.log (gitignored); each step's full output goes to .claude/<step>.log and .claude/<step>.err.log.

nightly.ps1 at 23:00 then skips its own market-data steps when market/run_log.jsonl already has today's line for
every collector, and runs them itself only when this task did not run today (fallback). The two scripts never
collect at the same time: both take the same lock (a named Windows mutex) around their market-data steps, and the
one that comes second waits. This script waits at most 30 minutes for the lock: if nightly.ps1 holds it that long,
nightly.ps1 is collecting today's data itself, so b), c) and e) are skipped. a) and d) run either way, so the tests
and the phone-alert check never depend on the lock. Pulling and publishing also take nightly.ps1's git lock, so they
never overlap a switch, pull or publish of nightly.ps1. Worst case, all steps together:
2 + 10 + 30 + 45 + 10 + 5 + 15 = 117 min, inside the task's 2-hour limit.

Test it in another checkout (a git worktree), without publishing and without a phone alert:
    powershell -NoProfile -ExecutionPolicy Bypass -File routine\market_data.ps1 -RepoRoot C:\Users\calif\Desktop\earnings-ai-market -NoPublish -NoAlert
(The collectors really run there and change that checkout's market/history, market/run_log.jsonl and graph files.)
Register once (current user, runs while logged on, wakes the laptop, catches up after a missed day):
    $a = New-ScheduledTaskAction -Execute powershell.exe -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\calif\Desktop\earnings-ai\routine\market_data.ps1"'
    $t = New-ScheduledTaskTrigger -Daily -At 10pm
    $s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName "earnings-ai market data" -Action $a -Trigger $t -Settings $s
Run today's job now:  Start-ScheduledTask -TaskName "earnings-ai market data"
Stop the routine:     Unregister-ScheduledTask -TaskName "earnings-ai market data" -Confirm:$false
#>
param(
    [string]$RepoRoot = "",   # the checkout to run in; empty = the folder above routine\ (this script's own checkout)
    [switch]$NoPublish,       # -NoPublish: run every step except e) publish (for tests)
    [switch]$NoAlert          # -NoAlert: run d) as `health.py --dry-run` (prints the alerts, writes and sends nothing)
)

$scriptStart = Get-Date
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$repo = (Resolve-Path $RepoRoot).Path
Set-Location $repo
New-Item -ItemType Directory -Force -Path (Join-Path $repo ".claude") | Out-Null    # .claude is gitignored
$log = Join-Path $repo ".claude\market_data_task.log"
function Write-Log($text) {
    Add-Content -Path $log -Encoding UTF8 -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), $text)
}
Write-Log ("start in {0}" -f $repo)

# The project's Python (the same one nightly.ps1 and the enrich session use), else whatever is on PATH.
$python = Join-Path $env:LOCALAPPDATA "Python\bin\python.exe"
if (-not (Test-Path $python)) { $found = Get-Command python -ErrorAction SilentlyContinue; if ($found) { $python = $found.Source } }

# Run one step as its own process, stop it when it runs longer than $minutes, and log its exit code and the last
# line it printed. (Copied from routine/nightly.ps1, plus $program so the publish step can run powershell.exe.)
function Invoke-DataStep($step, [string[]]$arguments, [int]$minutes, [string]$program = $python) {
    $out = Join-Path $repo (".claude\" + $step + ".log")
    $err = Join-Path $repo (".claude\" + $step + ".err.log")     # Start-Process needs a separate file for stderr
    try {
        $p = Start-Process -FilePath $program -ArgumentList $arguments -WorkingDirectory $repo -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
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

# A Python step runs only when its script exists (selftest.py and health.py are newer than this routine).
function Invoke-PythonStep($step, $script, [int]$minutes, [string[]]$extra = @()) {
    if (-not (Test-Path (Join-Path $repo $script))) {
        Write-Log ("{0} skipped: {1} does not exist yet" -f $step, $script)
        return
    }
    Invoke-DataStep $step (@("-X", "utf8", $script) + $extra) $minutes
}

# Is a "nightly enrich*" Claude session working in this checkout? `claude agents --json` lists the background
# sessions (the same check as nightly.ps1). Returns @{checked; running}: checked = the list could be read (when it
# cannot, a session might be working), running = the working session or $null.
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue     # never the pay-per-use API
$claude = Join-Path $env:USERPROFILE ".local\bin\claude.exe"
if (-not (Test-Path $claude)) { $found = Get-Command claude -ErrorAction SilentlyContinue; if ($found) { $claude = $found.Source } else { $claude = $null } }
function Get-EnrichSession {
    $result = @{ checked = $false; running = $null }
    if ($claude) {
        try {
            $sessions = (& $claude agents --json | Out-String) | ConvertFrom-Json -ErrorAction Stop
            $result.running = @($sessions | Where-Object { $_.name -like "nightly enrich*" -and $_.state -eq "working" })[0]
            $result.checked = $true
        } catch { }
    }
    return $result
}

# Which code runs the collectors. On main with no enrich session working, pull first (a working session edits files
# in this checkout, so nothing is pulled under it). On another branch, that branch's code runs and nothing is
# published (nightly.ps1's Publish-Run only publishes from main).
$branch = git rev-parse --abbrev-ref HEAD
$commit = git rev-parse --short HEAD
Write-Log ("checkout: {0} at {1}" -f $branch, $commit)
if ($branch -ne "main") {
    Write-Log ("WARNING: the checkout is on {0}, not main: its code runs the collectors, nothing is pulled or published" -f $branch)
} else {
    $enrich = Get-EnrichSession
    if (-not $enrich.checked) {
        Write-Log "pull skipped: could not read claude agents --json (an enrich session might be working)"
    } elseif ($enrich.running) {
        Write-Log ("pull skipped: {0} ({1}) is working in this checkout" -f $enrich.running.id, $enrich.running.name)
    } else {
        # nightly.ps1's git lock: never pull while nightly.ps1 switches, pulls or publishes.
        $gitLock = New-Object System.Threading.Mutex($false, "Global\earnings-ai-git")
        try { $haveGitLock = $gitLock.WaitOne([TimeSpan]::FromMinutes(2)) }
        catch { $haveGitLock = $true }      # the last holder died without releasing it; it is ours now
        if (-not $haveGitLock) {
            Write-Log "pull skipped: nightly.ps1 still held the git lock after 2 min (a publish is running)"
        } else {
            $pulled = git pull --ff-only -q 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) { Write-Log ("pull FAILED, the collectors run {0}: {1}" -f $commit, $pulled.Trim()) }
            else { Write-Log ("pulled main, now at {0}" -f (git rev-parse --short HEAD)) }
            $gitLock.ReleaseMutex()
        }
    }
}

# a) The tests, before the lock: they read only tests/market/fixtures, so they run even when the lock is busy.
Invoke-PythonStep "selftest" "market/selftest.py" 10

# The market-data lock, shared with routine/nightly.ps1. A named mutex has one holder at a time across processes,
# and Windows frees it when its holder dies, so a killed run never leaves it stuck.
$lock = New-Object System.Threading.Mutex($false, "Global\earnings-ai-market-data")
try { $haveLock = $lock.WaitOne([TimeSpan]::FromMinutes(30)) }
catch { $haveLock = $true }      # the only error here: the last holder died without releasing it; it is ours now
if (-not $haveLock) {
    Write-Log "collect and publish skipped: another market-data run (nightly.ps1 fallback or a manual run) still held the lock after 30 min"
} else {
    # b) - c)
    Invoke-PythonStep "market_data" "market/run_all.py" 45
    Invoke-PythonStep "transcript_quality" "utils/transcript_quality.py" 10
}

# d) The phone-alert check runs even when the lock was busy (health.py pushes each alert at most once a day).
if ($NoAlert) { $healthArgs = @("--dry-run") } else { $healthArgs = @() }
Invoke-PythonStep "market_health" "market/health.py" 5 $healthArgs

# e) Publish the market-data files only, still holding the lock (nightly.ps1's fallback must not write them while
#    they are committed). A working enrich session is editing files in this checkout (nightly.ps1 publishes when it
#    ends), so nothing is published while one works. nightly.ps1 -PublishOnly -MarketOnly checks that again itself,
#    takes the git lock, pulls main, and publishes nothing from another branch. It starts no session, runs no data
#    steps, and commits none of what an enrich session writes (transcripts, patches, chains, the rest of graph).
if ($haveLock) {
    if ($NoPublish) {
        Write-Log "publish skipped: -NoPublish"
    } elseif ($branch -ne "main") {
        Write-Log ("publish skipped: the checkout is on {0}, not main" -f $branch)
    } else {
        $changed = @(git status --porcelain -- market/history market/ai_lab_deals.json)
        if ($changed.Count -eq 0) {
            Write-Log "publish skipped: the collectors added no market history rows"
        } else {
            $enrich = Get-EnrichSession
            if (-not $enrich.checked) {
                Write-Log "publish skipped: could not read claude agents --json (an enrich session might be working)"
            } elseif ($enrich.running) {
                Write-Log ("publish skipped: {0} ({1}) is still working; nightly.ps1 publishes when it finishes" -f $enrich.running.id, $enrich.running.name)
            } else {
                $nightly = Join-Path $repo "routine\nightly.ps1"
                Invoke-DataStep "market_publish" @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $nightly + '"'), "-PublishOnly", "-MarketOnly") 15 "powershell.exe"
                $last = Get-Content (Join-Path $repo ".claude\nightly.log") -Tail 1 -Encoding UTF8 -ErrorAction SilentlyContinue
                if (-not $last) { $last = "(no line)" }
                Write-Log ("publish ({0} market history files changed), nightly.log says: {1}" -f $changed.Count, $last)
            }
        }
    }
    $lock.ReleaseMutex()
}
Write-Log ("done in {0} min" -f [math]::Round(((Get-Date) - $scriptStart).TotalMinutes, 1))
