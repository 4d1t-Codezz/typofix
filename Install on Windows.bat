@echo off
rem Double-click this file to install Typofix on Windows.
rem It adds Typofix to the Start menu and desktop, then opens it.
rem Keep this folder where it is afterwards: the shortcuts run the app from here.
cd /d "%~dp0"

echo Installing Typofix...
echo.

python -c "import sys, tkinter; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6" >nul 2>nul
if errorlevel 1 (
    echo Typofix needs Python 3.10 or newer, and it isn't installed yet.
    echo.
    echo 1. The Python download page will open. Download and run the installer.
    echo 2. On its first screen, tick "Add python.exe to PATH", then click Install Now.
    echo 3. Double-click "Install on Windows" again.
    echo.
    start "" https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\make-windows-shortcuts.ps1"
if errorlevel 1 (
    echo.
    echo Install failed ^(see the message above^).
    pause
    exit /b 1
)

start "" pythonw -m typofix
echo.
echo Done! Typofix is on your desktop and in the Start menu, and it's opening now.
echo It also opens by itself when you log in (you can turn that off in its window).
echo.
pause
