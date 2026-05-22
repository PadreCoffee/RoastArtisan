@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "SRC=%ROOT%src"
set "VENV=%ROOT%.venv-win-x64"

echo.
echo RoastArtisan local Windows x64 build
echo ====================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install 64-bit Python 3.11+ and try again.
  exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv "%VENV%"
  if errorlevel 1 exit /b 1
)

set "PYTHON_PATH=%VENV%"
set "PYQT=6"
set "PYUIC=pyuic6.exe"
set "QT_PATH=%VENV%\Lib\site-packages\PyQt6\Qt6"
set "QT_TRANSL=%VENV%\Lib\site-packages\PyQt6\Qt6\translations"
set "PATH=%VENV%\Scripts;%PATH%"

echo Installing Python dependencies...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

"%VENV%\Scripts\python.exe" -m pip install -r "%SRC%\requirements.txt"
if errorlevel 1 exit /b 1

"%VENV%\Scripts\python.exe" -m pip install pyinstaller==6.19.0 pyinstaller-versionfile==3.0.1 build==1.4.0 pywin32==311 tzdata==2025.3
if errorlevel 1 exit /b 1

if not exist "%ROOT%vc_redist.x64.exe" (
  echo Downloading Microsoft VC++ Redistributable...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile '%ROOT%vc_redist.x64.exe'"
  if errorlevel 1 exit /b 1
)

cd /d "%SRC%"

if /i "%RUN_DERIVED%"=="1" (
  echo Building derived files...
  call build-derived-win.bat
  if errorlevel 1 exit /b 1
) else (
  echo Skipping derived file generation. Set RUN_DERIVED=1 to force it.
)

for /f "usebackq delims==" %%a IN (`python -c "import artisanlib; print(artisanlib.__version__)"`) DO (set ARTISAN_VERSION=%%~a)
for /f "usebackq delims==" %%a IN (`python -c "import artisanlib; print(artisanlib.__build__)"`) DO (set ARTISAN_BUILD=%%~a)

echo Creating version metadata...
create-version-file version-metadata.yml --outfile version_info-win.txt --version %ARTISAN_VERSION%.%ARTISAN_BUILD%
if errorlevel 1 exit /b 1

echo Running PyInstaller...
pyinstaller --noconfirm --log-level=WARN artisan-win-local.spec
if errorlevel 1 exit /b 1

echo.
echo Portable build finished:
echo %SRC%\dist\artisan\artisan.exe
echo.

if exist "%ProgramFiles%\NSIS\makensis.exe" (
  echo NSIS found. Building installer...
  "%ProgramFiles%\NSIS\makensis.exe" /DPRODUCT_VERSION=%ARTISAN_VERSION% /DPRODUCT_BUILD=%ARTISAN_BUILD% setup-install3-pi.nsi
) else if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" (
  echo NSIS found. Building installer...
  "%ProgramFiles(x86)%\NSIS\makensis.exe" /DPRODUCT_VERSION=%ARTISAN_VERSION% /DPRODUCT_BUILD=%ARTISAN_BUILD% setup-install3-pi.nsi
) else (
  echo NSIS not found. Portable build is ready; installer was skipped.
)

echo.
echo Done.
exit /b 0
