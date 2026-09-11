@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Print Bridge - printer quality settings
cd /d "%~dp0"

echo.
echo   Print quality, resolution and toner saving live in the printer's own
echo   Windows driver - not in the bridge, and not on your phone. Whatever you
echo   set here applies to every job that arrives over WiFi, because this PC
echo   is the machine doing the rendering.
echo.

rem  the default printer, from the registry - no PowerShell 3 needed
set "PRN="
set "DEV="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows NT\CurrentVersion\Windows" /v Device 2^>nul ^| findstr /i "REG_SZ"') do set "DEV=%%B"
if defined DEV (
  for /f "tokens=1 delims=," %%C in ("!DEV!") do set "PRN=%%C"
)

if "%~1" NEQ "" set "PRN=%~1"

if not defined PRN (
  echo   No default printer found. Install the printer's Windows driver first,
  echo   or pass the printer name:   "Printer Quality Settings.bat" "HP LaserJet..."
  goto :done
)

echo   Opening printing defaults for:  !PRN!
echo.
rundll32 printui.dll,PrintUIEntry /e /n "!PRN!"

:done
echo.
pause
endlocal
