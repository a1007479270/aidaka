@echo off
setlocal enabledelayedexpansion
title aidaka 账号行转表格JSON
cd /d "%~dp0"

REM ============================================================
REM  aidaka · AI 打卡机
REM  把账号行（# 分隔）转成金山文档表格 B 列要的 JSON
REM  双击运行进中文菜单；也可命令行传参： to_wps.bat qoder
REM  真正的转换逻辑和菜单都在 to_wps.py
REM ============================================================

set "SCRIPT=%~dp0to_wps.py"
if not exist "%SCRIPT%" (
    echo [错误] 本目录下找不到 to_wps.py，请确保本文件和它在同一个目录。
    pause
    exit /b 1
)

REM ---- 找 Python ----
set "PY="
where py     >nul 2>nul && set "PY=py"
if not defined PY ( where python  >nul 2>nul && set "PY=python" )
if not defined PY ( where python3 >nul 2>nul && set "PY=python3" )
if not defined PY (
    echo [错误] 没有找到 Python。请安装 Python 3.8 以上版本，并加入 PATH。
    echo        或者用记事本打开本文件，把 PY 改成 python.exe 的完整路径。
    pause
    exit /b 1
)

REM ---- 带了参数就直接转，不进菜单 ----
if not "%~1"=="" (
    "%PY%" "%SCRIPT%" %*
    exit /b !ERRORLEVEL!
)

REM ---- 双击：进中文菜单 ----
"%PY%" "%SCRIPT%" --menu
set "RC=!ERRORLEVEL!"
if not "!RC!"=="0" (
    echo.
    echo 运行出错，错误码 !RC!。请把上面的报错信息截图反馈。
    pause
)
exit /b !RC!
