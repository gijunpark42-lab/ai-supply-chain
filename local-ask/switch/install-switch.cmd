@echo off
rem install-switch.cmd - put the Ask Switch on this PC (run once per PC, e.g. after cloning the repo on a new PC).
rem   1. copies "Ask Switch.cmd" to the Desktop
rem   2. registers the scheduled task "local-ask runner" (starts node server.mjs at every logon)
rem   3. prints what still has to be done by hand (Tailscale login, funnel, .env secret)
rem Full checklist: local-ask\NEW-PC.md
setlocal
cd /d "%~dp0"
set "LOCAL_ASK=%~dp0.."
for %%i in ("%LOCAL_ASK%") do set "LOCAL_ASK=%%~fi"

echo.
echo  1. Desktop switch
copy /y "%~dp0Ask Switch.cmd" "%USERPROFILE%\Desktop\Ask Switch.cmd" >nul && echo     copied to Desktop

echo  2. Autostart task
for /f "delims=" %%i in ('where node 2^>nul') do set "NODE=%%i"
if "%NODE%"=="" (
  echo     node.exe not found - install Node.js 20+ first, then run this again.
) else (
  rem schtasks.exe fails oddly on some PCs; the PowerShell cmdlets are reliable.
  powershell -NoProfile -Command "Unregister-ScheduledTask -TaskName 'local-ask runner' -Confirm:$false -ErrorAction SilentlyContinue; $a = New-ScheduledTaskAction -Execute '%NODE%' -Argument 'server.mjs' -WorkingDirectory '%LOCAL_ASK%'; $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -Hidden; Register-ScheduledTask -TaskName 'local-ask runner' -Action $a -Trigger $t -Settings $s -Force | Out-Null" && echo     task "local-ask runner" registered ^(%NODE%^)
)

echo  3. Still to do by hand (once):
if not exist "%LOCAL_ASK%\.env" (
  echo     - create local-ask\.env from .env.example; ASK_SHARED_SECRET must equal the value on Vercel
) else (
  echo     - local-ask\.env exists  [ok]
)
if exist "C:\Program Files\Tailscale\tailscale.exe" (
  echo     - Tailscale installed  [ok]  ^(check: tailscale status / tailscale funnel status^)
) else (
  echo     - install Tailscale:  winget install --id Tailscale.Tailscale
)
echo     - tailscale up --hostname gijun-pc --unattended   ^(log in in the browser; remove the OLD gijun-pc device in the
echo                                              Tailscale admin console first so the name and address stay the same^)
echo     - tailscale funnel --bg 8787
echo     - claude --version   ^(the Claude Code CLI must be installed and logged in^)
echo.
echo  Then double-click "Ask Switch" on the Desktop.
pause
endlocal
