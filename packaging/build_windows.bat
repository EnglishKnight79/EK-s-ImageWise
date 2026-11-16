@echo off
rem Builds the Windows installer. Double-click this file (or run it from a terminal).
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 - 3.12 is needed. Install it from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)

if not exist .venv-build python -m venv .venv-build
call .venv-build\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r packaging\requirements-build.txt
if errorlevel 1 goto fail

rem --models puts the background-removal models inside the installer so it works offline
python packaging\build.py --models %*
if errorlevel 1 goto fail

echo.
echo Done. Your installer is in the dist\installer folder.
pause
exit /b 0

:fail
echo.
echo The build failed - see the messages above.
pause
exit /b 1
