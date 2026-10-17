@echo off
setlocal
chcp 65001 >nul
REM ============================================================
REM  ima credential manager (Windows launcher) - daily-checkin
REM  Double-click this .bat, or run:  switch_auth.bat [list|backup|show|extract]
REM  It delegates to switch_auth.py (Python).
REM  ima 凭证提取需要 cryptography 库，缺失时会自动安装。
REM ============================================================
set "SCRIPT=%~dp0switch_auth.py"
if not exist "%SCRIPT%" (
    echo [ERROR] Cannot find switch_auth.py beside this .bat file.
    pause
    exit /b 1
)

REM Find a python interpreter that can import cryptography.
set "PY="
set "FALLBACK="
for %%C in (py python python3) do (
    if not defined PY (
        where %%C >nul 2>nul && %%C -c "import cryptography" >nul 2>nul && set "PY=%%C"
    )
)
for %%C in (py python python3) do (
    if not defined FALLBACK (
        where %%C >nul 2>nul && %%C -c "import sys" >nul 2>nul && set "FALLBACK=%%C"
    )
)

if defined PY goto :run
if not defined FALLBACK (
    echo [ERROR] Python not found. Install Python 3.8+ and add it to PATH, or use the py launcher.
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [SETUP] cryptography is missing, installing it once ...
%FALLBACK% -m pip install --quiet --disable-pip-version-check cryptography
%FALLBACK% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Could not install cryptography automatically. Run this manually, then retry:
    echo             %FALLBACK% -m pip install cryptography
    pause
    exit /b 1
)
set "PY=%FALLBACK%"

:run
"%PY%" "%SCRIPT%" %*
pause
