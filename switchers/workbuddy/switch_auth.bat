@echo off
setlocal
chcp 65001 >nul
REM ============================================================
REM  WorkBuddy login-state switcher (Windows launcher) - aidaka
REM  Double-click this .bat, or run:  switch_auth.bat [list|backup|show]
REM  It just delegates to switch_auth.py (Python).
REM ============================================================
set "SCRIPT=%~dp0switch_auth.py"
if not exist "%SCRIPT%" (
    echo [ERROR] Cannot find switch_auth.py beside this .bat file.
    pause
    exit /b 1
)

REM Find a python interpreter (try py, python, python3)
set "PY="
where py     >nul 2>nul && set "PY=py"
if not defined PY ( where python  >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
    echo [ERROR] Python not found. Install Python 3.8+ and add it to PATH,
    echo         or edit this .bat and set PY to your python.exe full path.
    pause
    exit /b 1
)

"%PY%" "%SCRIPT%" %*
pause
