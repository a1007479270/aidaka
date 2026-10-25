@echo off
setlocal
REM Keep Python on the native Windows console path. A stale PYTHONIOENCODING
REM makes Chinese output unreadable (GBK console vs UTF-8 bytes).
set "PYTHONIOENCODING="
REM ============================================================
REM  TraeWork login-state switcher (Windows launcher) - aidaka
REM  Double-click this .bat, or run:  switch_auth.bat [list|backup|show]
REM  It only launches switch_auth.py (Python); all user-facing messages are
REM  Chinese and printed there, because this .bat must stay pure ASCII.
REM
REM  TraeWork login state is AES-128-CBC encrypted, so switch_auth.py
REM  needs the cryptography package (installed automatically below).
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

REM This platform's parser needs the cryptography package. Prefer an
REM interpreter that already has it, so no network access is needed.
set "PYCR="
for %%C in (py python python3) do (
    if not defined PYCR (
        where %%C >nul 2>nul && %%C -c "import cryptography" >nul 2>nul && set "PYCR=%%C"
    )
)
if defined PYCR (
    set "PY=%PYCR%"
    goto :havepy
)
echo [SETUP] Installing the "cryptography" package, one time only...
"%PY%" -m pip install --quiet --disable-pip-version-check cryptography
"%PY%" -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Could not install "cryptography". Run manually:
    echo             "%PY%" -m pip install cryptography
    pause
    exit /b 1
)
:havepy

"%PY%" "%SCRIPT%" %*
pause
