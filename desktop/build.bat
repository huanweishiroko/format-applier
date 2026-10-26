@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ===========================================================================
rem  Taofu - Windows packaging script, PyInstaller onedir
rem
rem  Usage - run it yourself in a normal terminal:
rem      cd <the folder this file is in>
rem      .\build.bat
rem
rem  Output: desktop\dist\<AppName>\<AppName>.exe
rem
rem  KEEP THIS FILE PURE ASCII, CRLF, NO BOM.
rem  cmd.exe decodes .bat bytes with the active code page, so a non-ASCII
rem  literal here - above all inside python -c "..." - gets mangled. The app
rem  name is CJK, therefore this script never spells it out and never touches
rem  the CJK output path itself: build_finish.py does all of that, discovering
rem  the folder by scanning dist\. See the header of that file.
rem
rem  dist\ is never wiped - it may hold release archives.
rem ===========================================================================

for %%I in ("%~dp0..") do set "PROJ=%%~fI"
set "PYTHON=%PROJ%\.venv\Scripts\python.exe"
set "TEMP=%PROJ%\.venv\pip-tmp"
set "TMP=%TEMP%"
cd /d "%~dp0"
if not exist "%TEMP%" mkdir "%TEMP%" >nul 2>&1

if not exist "%PYTHON%" (
    echo [ERROR] Interpreter not found: %PYTHON%
    echo         Check .venv, or edit the PYTHON variable in this script.
    pause
    exit /b 1
)

echo [0/4] Environment
echo        PYTHON = %PYTHON%
echo        TEMP   = %TEMP%
echo        CWD    = %CD%
echo.

echo [1/4] Checking PyInstaller ...
"%PYTHON%" -m PyInstaller --version
if errorlevel 1 (
    echo        Not installed. Installing with pip into %TEMP% - first run pulls a few MB ...
    "%PYTHON%" -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] pip install pyinstaller failed. Send the output above to whoever debugs this.
        pause
        exit /b 1
    )
    "%PYTHON%" -m PyInstaller --version
)
echo.

echo [2/4] Building - onedir + windowed, first run takes 1 to 3 minutes ...
"%PYTHON%" -m PyInstaller --noconfirm --clean Taofu.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller failed. Read the last 30 lines above.
    echo         Common causes: pyinstaller too old / _internal locked / antivirus blocking writes.
    pause
    exit /b 1
)
echo.

echo [3/4] Finishing: relocate presets, copy .env, locate the exe ...
"%PYTHON%" "%~dp0build_finish.py"
if errorlevel 1 (
    echo [ERROR] build_finish.py failed - see the output above.
    pause
    exit /b 1
)
if exist "build" rmdir /S /Q "build" >nul 2>&1
echo.

echo [4/4] Done
echo.
echo Next steps:
echo   1^) Double-click the exe printed above.
echo   2^) User data - config.json / presets / usage.json - goes to %%APPDATA%%\Taofu\,
echo      falling back to %%LOCALAPPDATA%%\Taofu, ~\.taofu, then %%TEMP%%\taofu.
echo      It never writes next to the exe and never needs administrator rights.
echo   3^) AI parsing needs an API key: fill it in Settings - API settings - Save.
echo   4^) To override built-in presets, drop a presets\ folder next to the exe.
echo.
echo NOTE: never ship a .env that holds a real API key - build_finish copies only the template.
echo.
pause
endlocal
