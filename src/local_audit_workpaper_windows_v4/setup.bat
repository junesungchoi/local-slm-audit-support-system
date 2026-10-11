@echo off
setlocal
call :find_python

if not defined PYTHON (
  echo Python 3 was not found.
  echo Install Python 3.11 or later from https://www.python.org/downloads/windows/
  echo During installation, select Add python.exe to PATH.
  pause
  exit /b 1
)

%PYTHON% -m pip install --upgrade pip
%PYTHON% -m pip install -r requirements.txt
echo.
echo Setup complete. Start the application with run.bat.
pause
exit /b 0

:find_python
set "PYTHON="
py -3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"
if defined PYTHON exit /b 0
python -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
if not errorlevel 1 set "PYTHON=python"
if defined PYTHON exit /b 0
python3 -c "import sys; assert sys.version_info >= (3, 11)" >nul 2>nul
if not errorlevel 1 set "PYTHON=python3"
exit /b 0
