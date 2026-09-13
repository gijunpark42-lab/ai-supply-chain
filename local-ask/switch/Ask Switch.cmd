@echo off
rem Ask Switch - shows whether gijun42.com Ask is being answered by THIS PC, and flips it.
rem ON  = the Claude Opus runner (local-ask/server.mjs) is running on port 8787.
rem OFF = runner stopped; the site shows "Ask is busy" until ON again (or the next logon).
rem Installed on the Desktop by install-switch.cmd; the repo copy lives in local-ask/switch/.
setlocal
title Ask Switch
set "TS=C:\Program Files\Tailscale\tailscale.exe"
set "DIR=%~dp0"
if exist "%DIR%..\server.mjs" (set "LOCAL_ASK=%DIR%..") else (set "LOCAL_ASK=%USERPROFILE%\Desktop\earnings-ai\local-ask")

:status
cls
echo.
echo  ===================== ASK SWITCH =====================
curl -s -m 3 -o nul http://127.0.0.1:8787/health
if errorlevel 1 (set STATE=OFF) else (set STATE=ON)
echo.
echo    Runner on this PC :  %STATE%
"%TS%" status >nul 2>&1 && (echo    Tailscale         :  connected) || (echo    Tailscale         :  NOT connected  ^(run: tailscale up^))
for /f %%i in ('curl -s -m 15 -o nul -w "%%{http_code}" https://gijun-pc.tail362ef7.ts.net/health') do set CODE=%%i
if "%CODE%"=="401" (echo    Public address    :  reachable) else if "%CODE%"=="200" (echo    Public address    :  reachable) else (echo    Public address    :  not reachable ^(HTTP %CODE%^))
echo.
echo  ======================================================
echo.
if "%STATE%"=="ON" (
  choice /c YN /n /m "  Turn OFF? [Y/N] "
  if errorlevel 2 goto end
  powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -match 'server\.mjs' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
  timeout /t 2 /nobreak >nul
  goto status
) else (
  choice /c YN /n /m "  Turn ON? [Y/N] "
  if errorlevel 2 goto end
  schtasks /run /tn "local-ask runner" >nul 2>&1 || start "" /b /d "%LOCAL_ASK%" node server.mjs
  timeout /t 6 /nobreak >nul
  goto status
)

:end
endlocal
