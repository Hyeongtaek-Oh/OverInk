@echo off
rem OverInk installer for Windows: adds a Start menu shortcut.
rem   install.bat              add to the Start menu (search "OverInk", pin to taskbar)
rem   install.bat --autostart  also start in the background at sign-in (Ctrl+Alt+P to draw)
rem   install.bat --uninstall  remove shortcuts (project folder and settings are kept)
setlocal
set "DIR=%~dp0"
set "PROGRAMS=%APPDATA%\Microsoft\Windows\Start Menu\Programs"
set "STARTUP=%PROGRAMS%\Startup"
set "PYW=%DIR%.venv\Scripts\pythonw.exe"
set "ICON=%DIR%overink.ico"

if /i "%~1"=="--uninstall" (
    del /q "%PROGRAMS%\OverInk.lnk" 2>nul
    del /q "%STARTUP%\OverInk.lnk" 2>nul
    del /q "%ICON%" 2>nul
    echo OverInk shortcuts removed.
    goto :end
)

rem ---- Python virtual environment + dependencies ----
rem (no parenthesized block here: %PYTHON% would be expanded before it is set)
if exist "%DIR%.venv\Scripts\python.exe" goto :deps
call :find_python || goto :fail
echo Creating virtual environment...
%PYTHON% -m venv "%DIR%.venv" || goto :fail
:deps
echo Installing dependencies...
"%DIR%.venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r "%DIR%requirements.txt" || goto :fail

rem ---- icon + shortcuts ----
"%DIR%.venv\Scripts\python.exe" "%DIR%overink.py" --export-icon "%ICON%" || goto :fail

call :shortcut "%PROGRAMS%\OverInk.lnk" "--show" || goto :fail
echo Added to Start menu: press Win, type "OverInk" (can be pinned to taskbar).

if /i "%~1"=="--autostart" (
    call :shortcut "%STARTUP%\OverInk.lnk" "" || goto :fail
    echo Autostart added: waits in the background after sign-in ^(Ctrl+Alt+P^).
)
goto :end

rem ---- helpers ----
:find_python
rem prefer the py launcher; skip the Microsoft Store "python" stub
where py >nul 2>nul && (py -3 --version >nul 2>nul) && (set "PYTHON=py -3" & exit /b 0)
python --version >nul 2>nul && (set "PYTHON=python" & exit /b 0)
echo Python 3 was not found. Install it from https://www.python.org/downloads/
echo ^(tick "Add python.exe to PATH"^), then run install.bat again.
exit /b 1

:shortcut
rem %1 = .lnk path, %2 = extra argument. Values go through env vars to avoid quoting issues.
set "OI_LNK=%~1"
set "OI_ARGS=%~2"
set "OI_DIR=%DIR%"
set "OI_PYW=%PYW%"
set "OI_ICON=%ICON%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:OI_LNK);" ^
  "$s.TargetPath = $env:OI_PYW;" ^
  "$s.Arguments = ([char]34 + $env:OI_DIR + 'overink.py' + [char]34 + ' ' + $env:OI_ARGS).Trim();" ^
  "$s.WorkingDirectory = $env:OI_DIR.TrimEnd('\');" ^
  "$s.IconLocation = $env:OI_ICON;" ^
  "$s.Description = 'Draw on top of the screen';" ^
  "$s.Save()"
exit /b %errorlevel%

:fail
echo.
echo Installation failed. See the messages above.
pause
exit /b 1

:end
endlocal
