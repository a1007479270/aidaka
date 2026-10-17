@echo off
setlocal
REM ============================================================
REM  TraeWork login-state switcher (Windows launcher) - aidaka
REM  Double-click this .bat, or run:  switch_auth.bat [list|backup|show]
REM  It delegates to switch_auth.py (Python).
REM  TraeWork 登录态是加密的(AES-128-CBC)，需要 cryptography，缺失时会自动安装。
REM ============================================================
set "SCRIPT=%~dp0switch_auth.py"
if not exist "%SCRIPT%" (
    echo [错误] 本目录下找不到 switch_auth.py，请确保本文件和它在同一个目录。
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
    echo [错误] 没有找到 Python。请安装 Python 3.8 以上版本并加入 PATH， or use the py launcher.
    echo         下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [准备] 缺少 cryptography 库，正在自动安装（只需装一次）……
%FALLBACK% -m pip install --quiet --disable-pip-version-check cryptography
%FALLBACK% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo [错误] 自动安装 cryptography 失败。请先手动执行下面这条命令，然后重新运行：
    echo             %FALLBACK% -m pip install cryptography
    pause
    exit /b 1
)
set "PY=%FALLBACK%"

:run
"%PY%" "%SCRIPT%" %*
pause
