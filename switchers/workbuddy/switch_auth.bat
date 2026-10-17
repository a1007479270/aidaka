@echo off
setlocal
REM ============================================================
REM  WorkBuddy login-state switcher (Windows launcher) - aidaka
REM  Double-click this .bat, or run:  switch_auth.bat [list|backup|show]
REM  It just delegates to switch_auth.py (Python).
REM ============================================================
set "SCRIPT=%~dp0switch_auth.py"
if not exist "%SCRIPT%" (
    echo [错误] 本目录下找不到 switch_auth.py，请确保本文件和它在同一个目录。
    pause
    exit /b 1
)

REM Find a python interpreter (try py, python, python3)
set "PY="
where py     >nul 2>nul && set "PY=py"
if not defined PY ( where python  >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
    echo [错误] 没有找到 Python。请安装 Python 3.8 以上版本并加入 PATH，
    echo         或用记事本打开本文件，把 PY 改成 python.exe 的完整路径。
    pause
    exit /b 1
)

"%PY%" "%SCRIPT%" %*
pause
