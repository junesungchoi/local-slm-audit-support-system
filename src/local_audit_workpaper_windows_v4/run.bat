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

%PYTHON% app.py
if errorlevel 1 (
  echo.
  echo The application did not start. Read the error message above.
  echo If the message says that openpyxl or pypdf is missing, run setup.bat once.
  pause
)
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
