@echo off
setlocal EnableExtensions
title Print Bridge - stop starting with Windows
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
  exit /b
)

echo.
schtasks /Query /TN "Print Bridge" >nul 2>&1
if errorlevel 1 (
  echo   Print Bridge was not set to start with Windows.
) else (
  schtasks /End /TN "Print Bridge" >nul 2>&1
  schtasks /Delete /TN "Print Bridge" /F >nul 2>&1
  echo   Removed. Print Bridge will no longer start on its own.
)

echo   Stopping anything still running...
rem  wmic, not PowerShell: Windows 7 has no Get-CimInstance. The [_] keeps the
rem  pattern from matching this command's own line and killing wmic itself.
wmic process where "commandline like '%%run[_]hidden.pyw%%'" call terminate >nul 2>&1
echo   Done.
echo.
pause
endlocal
