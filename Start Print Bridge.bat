@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Print Bridge
cd /d "%~dp0"

rem ---------------------------------------------------------------------
rem  1. administrator rights - needed once, for the firewall rules
rem ---------------------------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
  echo Asking for administrator rights ^(needed to open the printing ports^)...
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs" >nul 2>&1
  )
  exit /b
)

echo.
echo   Print Bridge - starting up
echo   ---------------------------------------------------------------
echo.

rem ---------------------------------------------------------------------
rem  2. find Python
rem ---------------------------------------------------------------------
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
if not defined PY ( python3 -c "import sys" >nul 2>&1 && set "PY=python3" )

if not defined PY (
  echo   Python is not installed on this PC, and Print Bridge needs it.
  echo.
  echo   Install it with one command:
  echo.
  echo       winget install --id Python.Python.3.12
  echo.
  set /p GO=  Run that now? [Y/n]
  if /I "!GO!"=="n" goto :halt
  winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  echo.
  echo   Python installed. Close this window and double-click
  echo   "Start Print Bridge.bat" again.
  goto :halt
)
echo   Python:     found

rem ---------------------------------------------------------------------
rem  3. the one library it needs, for announcing the printer over WiFi
rem ---------------------------------------------------------------------
%PY% -c "import zeroconf" >nul 2>&1
if errorlevel 1 (
  echo   Installing the network-discovery library, one moment...
  %PY% -m pip install --quiet --disable-pip-version-check zeroconf
  %PY% -c "import zeroconf" >nul 2>&1
  if errorlevel 1 (
    echo   ! Could not install "zeroconf". Print Bridge will still run and the
    echo     web page will work, but phones will not find the printer on their
    echo     own. Check this PC's internet connection and try again.
  )
)
echo   Discovery:  ready

rem ---------------------------------------------------------------------
rem  3b. the PDF engine - this is what lets Print Bridge print by itself
rem ---------------------------------------------------------------------
%PY% -c "import pypdfium2" >nul 2>&1
if errorlevel 1 (
  echo   Installing the PDF engine, one moment...
  %PY% -m pip install --quiet --disable-pip-version-check pypdfium2
)
%PY% -c "import pypdfium2" >nul 2>&1
if errorlevel 1 (
  echo   ! Could not install "pypdfium2". Print Bridge will fall back to
  echo     SumatraPDF if it is present. Check this PC's internet connection.
) else (
  echo   PDF engine: ready - no other program needed
  set "HAVE_PDFIUM=1"
)

rem ---------------------------------------------------------------------
rem  4. silent printing helper - only needed without the PDF engine above
rem ---------------------------------------------------------------------
if defined HAVE_PDFIUM goto :skipsumatra
set "HAVE_SUMATRA="
if exist "%~dp0SumatraPDF.exe" set "HAVE_SUMATRA=1"
if exist "%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe" set "HAVE_SUMATRA=1"
if exist "%ProgramFiles%\SumatraPDF\SumatraPDF.exe" set "HAVE_SUMATRA=1"
if exist "%ProgramFiles(x86)%\SumatraPDF\SumatraPDF.exe" set "HAVE_SUMATRA=1"
if not defined HAVE_SUMATRA (
  echo.
  echo   SumatraPDF is not installed. It is what prints a PDF with no dialog
  echo   and no rescaling - without it, jobs open in your default PDF app and
  echo   exact paper sizing is not guaranteed.
  echo.
  set /p GO2=  Install it now? [Y/n]
  if /I not "!GO2!"=="n" (
    winget install --id SumatraPDF.SumatraPDF --accept-source-agreements --accept-package-agreements
  )
) else (
  echo   SumatraPDF: found
)

:skipsumatra

rem ---------------------------------------------------------------------
rem  5. firewall: IPP on 631 and Bonjour on 5353
rem ---------------------------------------------------------------------
netsh advfirewall firewall delete rule name="Print Bridge (IPP printing)" >nul 2>&1
netsh advfirewall firewall delete rule name="Print Bridge (Bonjour discovery)" >nul 2>&1
netsh advfirewall firewall add rule name="Print Bridge (IPP printing)" dir=in action=allow protocol=TCP localport=631 profile=private,domain >nul 2>&1
netsh advfirewall firewall add rule name="Print Bridge (Bonjour discovery)" dir=in action=allow protocol=UDP localport=5353 profile=private,domain >nul 2>&1
echo   Firewall:   ports opened for private networks

echo.
echo   Tip: "Install Autostart.bat" makes this start with Windows, with no
echo        window at all. "Printer Quality Settings.bat" opens the driver
echo        settings that decide resolution and toner use.
echo.
%PY% -m printbridge %*

:halt
echo.
pause
endlocal
