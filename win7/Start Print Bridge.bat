@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Print Bridge
rem  The package lives one folder up; this launcher only differs in how it
rem  installs Python, so it runs everything from the repository root.
cd /d "%~dp0.."

rem ---------------------------------------------------------------------
rem  1. administrator rights - needed for the firewall rules and for
rem     installing Python and SumatraPDF without prompting
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
echo   Print Bridge - Windows 7 edition
echo   ---------------------------------------------------------------
echo.

set "ARCH=64"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "ARCH=32"

if "%ARCH%"=="64" (
  set "PYFILE=python-3.8.10-amd64.exe"
  set "SUMFILE=SumatraPDF-3.6.1-64-install.exe"
) else (
  set "PYFILE=python-3.8.10.exe"
  set "SUMFILE=SumatraPDF-3.6.1-install.exe"
)
set "PYURL=https://www.python.org/ftp/python/3.8.10/!PYFILE!"
set "SUMURL=https://www.sumatrapdfreader.org/dl/rel/3.6.1/!SUMFILE!"

rem ---------------------------------------------------------------------
rem  2. Python - 3.8.10 is the last one that runs on Windows 7
rem ---------------------------------------------------------------------
call :findpython
if not defined PY (
  echo   Python is not installed on this PC, and Print Bridge needs it.
  echo   Windows 7 needs 3.8.10 - newer ones refuse to run here.
  echo.
  call :fetch "!PYFILE!" "!PYURL!"
  if defined GOT (
    echo   Installing Python 3.8.10 - this takes a minute, no windows will open.
    "!GOT!" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    call :findpython
  )
)
if not defined PY (
  echo.
  echo   Could not install Python automatically.
  echo.
  echo   Download it on any PC, put the file in a "setup" folder next to this
  echo   one, and run this again - it will pick it up and install it silently:
  echo.
  echo       !PYURL!
  echo.
  echo   ^(Or install it by hand and tick "Add Python 3.8 to PATH".^)
  goto :halt
)
!PY! -c "import sys;print('  Python:     '+sys.version.split()[0])"

rem ---------------------------------------------------------------------
rem  3. the one library it needs, for announcing the printer over WiFi
rem ---------------------------------------------------------------------
!PY! -c "import zeroconf" >nul 2>&1
if errorlevel 1 (
  echo   Installing the network-discovery library, one moment...
  !PY! -m pip install --quiet --disable-pip-version-check zeroconf
  !PY! -c "import zeroconf" >nul 2>&1
  if errorlevel 1 (
    echo   ! Could not install "zeroconf". Print Bridge will still run and the
    echo     web page will work, but phones will not find the printer on their
    echo     own. Try this, then start Print Bridge again:
    echo         !PY! -m pip install --upgrade pip
  )
)
echo   Discovery:  ready

rem ---------------------------------------------------------------------
rem  3b. the PDF engine - this is what lets Print Bridge print by itself
rem ---------------------------------------------------------------------
!PY! -c "import pypdfium2" >nul 2>&1
if errorlevel 1 (
  echo   Installing the PDF engine, one moment...
  !PY! -m pip install --quiet --disable-pip-version-check pypdfium2
)
!PY! -c "import pypdfium2" >nul 2>&1
if errorlevel 1 (
  echo   ! No PDF engine. Falling back to SumatraPDF.
  echo     On a PC with internet:  pip download pypdfium2 -d setup
  echo     then copy the .whl into the setup folder here and run:
  echo         pip install setup\pypdfium2-*.whl
) else (
  echo   PDF engine: ready - no other program needed
  set "HAVE_PDFIUM=1"
)

rem ---------------------------------------------------------------------
rem  4. silent printing helper - only needed without the PDF engine above
rem ---------------------------------------------------------------------
if defined HAVE_PDFIUM goto :skipsumatra
call :findsumatra
if not defined HAVE_SUMATRA (
  echo.
  echo   SumatraPDF is not installed. It is what prints a PDF with no dialog
  echo   and no rescaling - without it, jobs open in your default PDF app and
  echo   exact paper sizing is not guaranteed.
  echo.
  call :fetch "!SUMFILE!" "!SUMURL!"
  if defined GOT (
    echo   Installing SumatraPDF...
    "!GOT!" -s
    call :findsumatra
  )
)
if defined HAVE_SUMATRA (
  echo   SumatraPDF: found
) else (
  echo   ! SumatraPDF is still missing. Download it on any PC and put it in a
  echo     "setup" folder next to this one, or just drop SumatraPDF.exe into
  echo     this folder - the bridge looks here first:
  echo         !SUMURL!
  echo.
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
!PY! -m printbridge %*

:halt
echo.
pause
endlocal
exit /b

rem =====================================================================
rem  helpers
rem =====================================================================

:findpython
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
if not defined PY if exist "%WINDIR%\py.exe" set "PY="%WINDIR%\py.exe" -3"
if not defined PY if exist "%ProgramFiles%\Python38\python.exe" set "PY="%ProgramFiles%\Python38\python.exe""
if not defined PY if exist "%ProgramFiles(x86)%\Python38-32\python.exe" set "PY="%ProgramFiles(x86)%\Python38-32\python.exe""
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python38\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python38\python.exe""
goto :eof

:findsumatra
set "HAVE_SUMATRA="
if exist "%~dp0..\SumatraPDF.exe" set "HAVE_SUMATRA=1"
if exist "%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe" set "HAVE_SUMATRA=1"
if exist "%ProgramFiles%\SumatraPDF\SumatraPDF.exe" set "HAVE_SUMATRA=1"
if exist "%ProgramFiles(x86)%\SumatraPDF\SumatraPDF.exe" set "HAVE_SUMATRA=1"
goto :eof

rem  %1 = file name, %2 = where to get it. Sets GOT to a local copy, or
rem  leaves it empty. A file already sitting in setup\ always wins.
:fetch
set "GOT="
if exist "%~dp0setup\%~1" (
  echo   Using setup\%~1
  set "GOT=%~dp0setup\%~1"
  goto :eof
)
set "DEST=%TEMP%\%~1"
echo   Downloading %~1 ...
del "!DEST!" >nul 2>&1
certutil -urlcache -split -f "%~2" "!DEST!" >nul 2>&1
call :gotit
if defined GOT goto :eof
bitsadmin /transfer pbfetch /download /priority normal "%~2" "!DEST!" >nul 2>&1
call :gotit
if defined GOT goto :eof
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]3072;(New-Object Net.WebClient).DownloadFile('%~2','!DEST!')" >nul 2>&1
call :gotit
if not defined GOT echo   ! The download did not work.
goto :eof

:gotit
if not exist "!DEST!" goto :eof
for %%S in ("!DEST!") do if %%~zS GTR 1000000 set "GOT=!DEST!"
if not defined GOT del "!DEST!" >nul 2>&1
goto :eof
