@echo off
setlocal
echo Checking Python commands...
echo.
echo [py -3 --version]
py -3 --version 2>&1
echo.
echo [python --version]
python --version 2>&1
echo.
echo [python3 --version]
python3 --version 2>&1
echo.
echo A usable installation must report Python 3.11 or later.
echo If none do, install Python from https://www.python.org/downloads/windows/
echo and select Add python.exe to PATH.
pause
