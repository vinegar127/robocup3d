@echo off
REM ===========================================================================
REM  RoboCup3D Demo 一键运行（Windows）
REM ===========================================================================
REM  用法：直接双击本文件。
REM  为什么要有这个文件？因为零基础同学第一次面对命令行会紧张，
REM  双击一个 .bat 比让他们敲命令容易得多。
REM ===========================================================================

chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo  RoboCup3D 新手 Demo
echo ============================================================
echo.

REM --- 找 Python ---
where python >nul 2>nul
if %errorlevel%==0 (
    set PY=python
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set PY=py
    ) else (
        echo [错误] 找不到 Python。
        echo.
        echo 请先安装 Python： https://www.python.org/downloads/windows/
        echo 安装时务必勾选 "Add python.exe to PATH"
        echo.
        echo 详见 docs\01-环境安装.md
        echo.
        pause
        exit /b 1
    )
)

REM --- 优先使用虚拟环境里的 Python ---
if exist ".venv\Scripts\python.exe" (
    set PY=.venv\Scripts\python.exe
    echo [信息] 使用虚拟环境： .venv
) else (
    echo [提示] 没有找到 .venv 虚拟环境，将使用系统 Python。
    echo        建议先执行： python -m venv .venv
)

echo [信息] Python 版本：
%PY% --version
echo.

REM --- 菜单 ---
echo 请选择要运行的内容：
echo.
echo   [1] 闭环仿真（默认，30 秒比赛）
echo   [2] 闭环仿真 + ASCII 动画
echo   [3] 基准测试（跑 20 场，得到分数基线）
echo   [4] 环境体检
echo   [5] 打开 3D 步态可视化（浏览器）
echo   [6] 退出
echo.

set /p CHOICE=请输入序号并回车（直接回车 = 1）:

if "%CHOICE%"=="" set CHOICE=1

if "%CHOICE%"=="1" goto demo
if "%CHOICE%"=="2" goto render
if "%CHOICE%"=="3" goto bench
if "%CHOICE%"=="4" goto check
if "%CHOICE%"=="5" goto viz
if "%CHOICE%"=="6" exit /b 0
echo 无效的选择，默认运行闭环仿真。
goto demo

:demo
echo.
echo --- 运行闭环仿真 ---
%PY% code\demo_sim.py --cycles 1500
goto done

:render
echo.
echo --- 运行闭环仿真（带 ASCII 动画）---
%PY% code\demo_sim.py --cycles 400 --render
goto done

:bench
echo.
echo --- 基准测试：20 场 ---
%PY% code\demo_sim.py --bench 20
goto done

:check
echo.
%PY% scripts\setup_check.py
goto done

:viz
echo.
echo 正在用默认浏览器打开 3D 可视化...
start "" "tools\walkviz\index.html"
goto done

:done
echo.
echo ============================================================
echo  完成。按任意键关闭窗口。
echo ============================================================
pause >nul
endlocal
