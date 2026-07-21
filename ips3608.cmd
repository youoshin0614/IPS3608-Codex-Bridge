@echo off
setlocal
set "PROJECT_DIR=%~dp0"
set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo Error: environment not installed. Run install.ps1 first. 1>&2
  exit /b 2
)

"%PYTHON_EXE%" -m ips3608_bridge %*
exit /b %ERRORLEVEL%

