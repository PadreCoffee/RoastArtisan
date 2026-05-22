@echo off
setlocal

set "ROOT=%~dp0"
set "SRC=%ROOT%src"
set "VENV=%ROOT%.venv-run"

if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
  if errorlevel 1 exit /b 1
)

set "PATH=%VENV%\Scripts;%PATH%"

"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

"%VENV%\Scripts\python.exe" -m pip install -r "%SRC%\requirements.txt"
if errorlevel 1 exit /b 1

cd /d "%SRC%"
"%VENV%\Scripts\python.exe" artisan.py
