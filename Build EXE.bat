@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Print Bridge - build a single .exe
cd /d "%~dp0"

echo.
echo   Print Bridge - building one executable
echo   ---------------------------------------------------------------
echo.

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY ( python -c "import sys" >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo   Python is not installed. Run "Start Print Bridge.bat" once first.
  goto :halt
)
echo   Python:     found

%PY% -m pip install --quiet --disable-pip-version-check pyinstaller zeroconf pypdfium2
if errorlevel 1 (
  echo   ! Could not install the build tools. Check the internet connection.
  goto :halt
)
echo   Tools:      ready

%PY% build\make_icon.py
if errorlevel 1 ( echo   ! Could not build the icon. & goto :halt )

echo   Building - this takes a minute...
%PY% -m PyInstaller --noconfirm --clean --distpath dist --workpath build\work build\printbridge.spec
if errorlevel 1 (
  echo.
  echo   ! The build failed. The messages above say why.
  goto :halt
)

echo.
echo   Done.  dist\Print Bridge.exe
echo.
echo   That one file is everything: Python, the PDF engine, the web page.
echo   Copy it anywhere and double-click it - it starts in the tray, next
echo   to the clock. Nothing else needs installing.
echo.

:halt
echo.
pause
endlocal
