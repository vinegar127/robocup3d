@echo off
REM ===========================================================================
REM  RoboCup3D Demo - one-click launcher (Windows)
REM ===========================================================================
REM  NOTE FOR CONTRIBUTORS:
REM  This .bat file is deliberately written in pure ASCII (English only).
REM  Reason: cmd.exe parses .bat files using the OEM/ANSI codepage (cp936 on
REM  Chinese Windows). UTF-8 encoded Chinese text inside a .bat file gets
REM  CORRUPTED and cmd tries to execute the garbage as commands:
REM      'xxx' is not recognized as an internal or external command
REM  The Python programs this script launches print plenty of Chinese - that
REM  is fine, because Python handles its own UTF-8 output correctly.
REM
REM  Double-click this file to run. No command line knowledge needed.
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   RoboCup3D Simulation Demo
echo ============================================================
echo.

REM --- 1. Locate Python: prefer the project venv ---------------------------
set "PY="
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    echo [INFO] Using virtual environment: .venv
) else (
    where python >nul 2>nul
    if !errorlevel!==0 (
        set "PY=python"
        echo [INFO] No .venv found. Using system Python.
        echo        Recommended: python -m venv .venv
    ) else (
        where py >nul 2>nul
        if !errorlevel!==0 (
            set "PY=py"
            echo [INFO] Using the Python launcher: py
        )
    )
)

if not defined PY (
    echo.
    echo [ERROR] Python not found.
    echo.
    echo   Please install Python first:
    echo     https://www.python.org/downloads/windows/
    echo   IMPORTANT: tick "Add python.exe to PATH" during installation.
    echo.
    echo   More help: docs\01-huan-jing-an-zhuang.md  (Chinese install guide)
    echo.
    pause
    exit /b 1
)

echo.
echo [INFO] Python version:
"%PY%" --version
echo.

REM --- 2. Menu ------------------------------------------------------------
echo   [1] Closed-loop demo          (default, 30s match)
echo   [2] Demo with ASCII animation
echo   [3] Benchmark                 (20 matches, get your baseline score)
echo   [4] Environment health check
echo   [5] Open 3D gait visualizer in browser
echo   [6] Quit
echo.
set "CHOICE="
set /p "CHOICE=Enter a number and press Enter (default = 1): "

if not defined CHOICE set "CHOICE=1"

if "%CHOICE%"=="2" goto render
if "%CHOICE%"=="3" goto bench
if "%CHOICE%"=="4" goto check
if "%CHOICE%"=="5" goto viz
if "%CHOICE%"=="6" exit /b 0
goto demo

:demo
echo.
echo --- Closed-loop demo ---
"%PY%" code\demo_sim.py --cycles 1500
goto done

:render
echo.
echo --- Closed-loop demo with ASCII animation ---
"%PY%" code\demo_sim.py --cycles 400 --render
goto done

:bench
echo.
echo --- Benchmark: 20 matches ---
"%PY%" code\demo_sim.py --bench 20
goto done

:check
echo.
"%PY%" scripts\setup_check.py
goto done

:viz
echo.
echo Opening the 3D gait visualizer in your default browser...
start "" "tools\walkviz\index.html"
goto done

:done
echo.
echo ============================================================
echo   Done. Press any key to close this window.
echo ============================================================
pause >nul
endlocal
