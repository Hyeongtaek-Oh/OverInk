@echo off
rem OverInk launcher for Windows (opens drawing mode right away).
rem   run.bat            start in drawing mode (or bring up the running instance)
rem   run.bat --debug    run with a console window to see error messages
setlocal
set "DIR=%~dp0"

if not exist "%DIR%.venv\Scripts\pythonw.exe" (
    echo OverInk is not installed yet. Run install.bat first.
    pause
    exit /b 1
)

if /i "%~1"=="--debug" (
    "%DIR%.venv\Scripts\python.exe" "%DIR%overink.py" --show
    pause
    exit /b
)

rem pythonw = no console window
start "" "%DIR%.venv\Scripts\pythonw.exe" "%DIR%overink.py" --show %*
