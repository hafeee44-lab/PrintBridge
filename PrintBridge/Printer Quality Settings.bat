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

set "PRN="
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "(Get-CimInstance Win32_Printer | Where-Object {$_.Default} | Select-Object -First 1).Name"`) do set "PRN=%%P"

if "%~1" NEQ "" set "PRN=%~1"

if not defined PRN (
  echo   No printer found. Install the printer's Windows driver first.
  goto :done
)

echo   Opening printing defaults for:  !PRN!
echo.
rundll32 printui.dll,PrintUIEntry /e /n "!PRN!"

:done
echo.
pause
endlocal
