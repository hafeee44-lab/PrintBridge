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

rem  The default printer. The registry holds it on every version of Windows and
rem  needs no PowerShell, so it works on 7 as well; CIM is only the fallback.
set "PRN="
set "DEV="
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows NT\CurrentVersion\Windows" /v Device 2^>nul ^| findstr /i "REG_SZ"') do set "DEV=%%B"
if defined DEV for /f "tokens=1 delims=," %%C in ("!DEV!") do set "PRN=%%C"
if not defined PRN call :askwindows

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
exit /b

:askwindows
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "(Get-CimInstance Win32_Printer | Where-Object {$_.Default} | Select-Object -First 1).Name"`) do set "PRN=%%P"
goto :eof
