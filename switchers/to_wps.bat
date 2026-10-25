@echo off
setlocal enabledelayedexpansion
title aidaka account-line to WPS table JSON
cd /d "%~dp0"

REM ============================================================
REM  aidaka - AI daily check-in
REM  Convert account lines (separated by #) into the JSON that
REM  column B of the Kingsoft (WPS) sheet expects.
REM  Double-click for the Chinese menu, or pass an argument:
REM      to_wps.bat qoder
REM  All real logic and the menu live in to_wps.py, which also
REM  prints every Chinese message. This .bat stays pure ASCII,
REM  otherwise the console shows mojibake under chcp 936.
REM ============================================================

set "SCRIPT=%~dp0to_wps.py"
if not exist "%SCRIPT%" (
    echo [ERROR] to_wps.py not found in this folder.
    echo         Keep this .bat and to_wps.py together.
    pause
    exit /b 1
)

REM ---- locate Python ----
set "PY="
where py     >nul 2>nul && set "PY=py"
if not defined PY ( where python  >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.8+ and add it to PATH,
    echo         or edit this file and set PY to the full path of python.exe.
    pause
    exit /b 1
)

REM ---- an argument means: convert directly, skip the menu ----
if not "%~1"=="" (
    "%PY%" "%SCRIPT%" %*
    exit /b !ERRORLEVEL!
)

REM ---- double-click: show the menu ----
"%PY%" "%SCRIPT%" --menu
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
    echo.
    echo [ERROR] exited with code !RC! - see the messages above.
    pause
)
exit /b !RC!
