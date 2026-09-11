@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Print Bridge - start with Windows
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  echo Asking for administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
  exit /b
)

echo.
echo   Print Bridge - start automatically with Windows
echo   ---------------------------------------------------------------
echo.

rem --- find pythonw.exe, which runs without a console window -----------
set "PYW="
for /f "usebackq delims=" %%P in (`py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul`) do set "PYW=%%P"
if not exist "!PYW!" (
  for /f "usebackq delims=" %%P in (`python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul`) do set "PYW=%%P"
)
if not exist "!PYW!" (
  echo   Could not find Python. Run "Start Print Bridge.bat" once first -
  echo   it will install Python for you - then come back here.
  goto :done
)
echo   Python:   !PYW!

rem --- firewall, in case the bridge has never been started by hand -----
netsh advfirewall firewall delete rule name="Print Bridge (IPP printing)" >nul 2>&1
netsh advfirewall firewall delete rule name="Print Bridge (Bonjour discovery)" >nul 2>&1
netsh advfirewall firewall add rule name="Print Bridge (IPP printing)" dir=in action=allow protocol=TCP localport=631 profile=private,domain >nul 2>&1
netsh advfirewall firewall add rule name="Print Bridge (Bonjour discovery)" dir=in action=allow protocol=UDP localport=5353 profile=private,domain >nul 2>&1
echo   Firewall: ports open

rem --- the scheduled task ---------------------------------------------
schtasks /Delete /TN "Print Bridge" /F >nul 2>&1
schtasks /Create /TN "Print Bridge" /SC ONLOGON /RL HIGHEST /F ^
  /TR "\"!PYW!\" \"%~dp0run_hidden.pyw\"" >nul 2>&1
if errorlevel 1 (
  echo   ! Could not create the scheduled task.
  goto :done
)
echo   Task:     created - it will start at every logon, with no window
echo.
echo   Starting it now...
schtasks /Run /TN "Print Bridge" >nul 2>&1
timeout /t 4 >nul

rem --- tell the user where it is --------------------------------------
rem  Ask the bridge itself, so this shows the same address it advertises.
set "IP="
for /f "usebackq delims=" %%I in (`"!PYW:pythonw.exe=python.exe!" -c "from printbridge.discovery import local_ip;print(local_ip())" 2^>nul`) do set "IP=%%I"
if defined IP set "IP=!IP: =!"
if not defined IP (
  for /f "tokens=2 delims=:" %%I in ('ipconfig ^| findstr /i /c:"IPv4"') do (
    if not defined IP set "IP=%%I"
  )
  if defined IP set "IP=!IP: =!"
)

echo.
echo   Print Bridge is running in the background.
if defined IP (
  echo       Web page:  http://!IP!:631
) else (
  echo       Web page:  port 631 on this PC - run "Start Print Bridge.bat"
  echo                  once to see the exact address.
)
echo       Log file:  %~dp0printbridge.log
echo.
echo   Your phone should list the printer straight from Share ^-^> Print.
echo   To undo this, run "Stop Starting With Windows.bat".

:done
echo.
pause
endlocal
