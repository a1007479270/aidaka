@echo off
setlocal enabledelayedexpansion
title to_wps - account line to table JSON
cd /d "%~dp0"

REM ============================================================
REM  Convert a switcher account line (#-separated) into the JSON
REM  that the kdocs / WPS sheet needs in column B.
REM
REM  Double-click this file to use the menu, or pass arguments:
REM      to_wps.bat qoder
REM      to_wps.bat all --tsv --clip
REM  The real work is done by to_wps.py (same folder).
REM ============================================================

set "SCRIPT=%~dp0to_wps.py"
if not exist "%SCRIPT%" (
    echo [ERROR] to_wps.py not found next to this .bat file.
    pause
    exit /b 1
)

REM ---- locate a python interpreter ----
set "PY="
where py     >nul 2>nul && set "PY=py"
if not defined PY ( where python  >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.8+ and add it to PATH,
    echo         or open this file in Notepad and set PY to your python.exe.
    pause
    exit /b 1
)

REM ---- args given: pass through, no menu, no pause ----
if not "%~1"=="" (
    "%PY%" "%SCRIPT%" %*
    exit /b !ERRORLEVEL!
)

REM ---- no args: interactive menu ----
:MENU
cls
echo ============================================================
echo    Account line   ==^>   JSON for sheet column B
echo ============================================================
echo   Step 1: get the line from switchers\^<platform^>\switch_auth.bat  [2]
echo   Step 2: convert it here - the JSON lands in your clipboard
echo ------------------------------------------------------------
echo    [1] ima
echo    [2] workbuddy    (new client encrypts login state - see README)
echo    [3] qoder
echo    [4] traework
echo    [5] all four platforms  (TSV: paste once at column A)
echo    [6] paste an account line manually
echo    [0] exit
echo ------------------------------------------------------------
set "CH="
set /p "CH=Select: "
set "CH=!CH:~0,1!"

set "PLAT="
if "!CH!"=="1" set "PLAT=ima"
if "!CH!"=="2" set "PLAT=workbuddy"
if "!CH!"=="3" set "PLAT=qoder"
if "!CH!"=="4" set "PLAT=traework"
if defined PLAT goto :DOONE
if "!CH!"=="5" goto :DOALL
if "!CH!"=="6" goto :DOPASTE
if "!CH!"=="0" exit /b 0
goto MENU

:DOONE
echo.
echo ---------------- !PLAT! ----------------
"%PY%" "%SCRIPT%" !PLAT! --clip
echo.
echo Paste that JSON line into column B of the sheet (already copied).
pause
goto MENU

:DOALL
echo.
echo ---------------- all platforms (TSV) ----------------
"%PY%" "%SCRIPT%" all --tsv --clip
echo.
echo Click the first empty cell of column A, then Ctrl+V - it fills A and B.
pause
goto MENU

:DOPASTE
echo.
set "PLAT="
set /p "PLAT=Platform (ima/workbuddy/qoder/traework): "
if "!PLAT!"=="" ( echo Cancelled.& pause& goto MENU )
echo Paste the account line (a#b#c#d), then press Enter:
set "ACC="
set /p "ACC=Line: "
if "!ACC!"=="" ( echo Cancelled.& pause& goto MENU )
echo.
"%PY%" "%SCRIPT%" !PLAT! "!ACC!" --clip
echo.
pause
goto MENU
