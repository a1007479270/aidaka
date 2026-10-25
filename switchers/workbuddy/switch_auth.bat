@echo off
setlocal
REM Keep Python on the native Windows console path. A stale PYTHONIOENCODING
REM makes Chinese output unreadable (GBK console vs UTF-8 bytes).
set "PYTHONIOENCODING="
REM ============================================================
REM  WorkBuddy login-state switcher (Windows launcher) - aidaka
REM  Double-click this .bat, or run:  switch_auth.bat [list|backup|show]
REM  It only launches switch_auth.py (Python); all user-facing messages are
REM  Chinese and printed there, because this .bat must stay pure ASCII.
REM
REM  WorkBuddy tokens are encrypted on disk; switch_auth.py decrypts
REM  them with a pure-stdlib AES-256-GCM implementation.
REM ============================================================
set "SCRIPT=%~dp0switch_auth.py"
if not exist "%SCRIPT%" (
    echo [ERROR] switch_auth.py not found in this folder.
    echo         Keep this .bat and switch_auth.py together.
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
    echo         or edit this file and set PY to the full path of python.exe.
    pause
    exit /b 1
)

REM Double-click runs the interactive menu, so keep the window open;
REM with arguments (list/backup/show) return immediately for scripting.
"%PY%" "%SCRIPT%" %*
if "%~1"=="" pause
