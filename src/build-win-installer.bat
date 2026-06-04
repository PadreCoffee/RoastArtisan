@echo off
:: ABOUT
:: Local (non-CI) Windows build: produces the RoastArtisan app folder AND the
:: NSIS installer .exe. Run this ON A WINDOWS MACHINE from the "src" folder.
::
:: Prerequisites (install once):
::   - Python 3.12/3.13 (64-bit) on PATH
::   - pip install -r requirements.txt
::   - pip install pyinstaller==6.19.0 pyinstaller-versionfile==3.0.1
::   - Qt 6.x with lrelease.exe  (set QT_PATH, e.g. C:\Qt\6.10\msvc2019_64)
::   - NSIS  (https://nsis.sourceforge.io/)  -> makensis.exe
::   - 7-Zip (7z.exe on PATH)
::
:: Usage:
::   set QT_PATH=C:\Qt\6.10.2\msvc2019_64
::   build-win-installer.bat
:: ----------------------------------------------------------------------

@echo on
setlocal enabledelayedexpansion

if not defined QT_PATH (
    echo QT_PATH not set. Example: set QT_PATH=C:\Qt\6.10.2\msvc2019_64
    exit /b 1
)
if not defined PYTHON_PATH (
    for /f "usebackq delims=" %%p in (`python -c "import sysconfig;print(sysconfig.get_paths()['purelib'])"`) do set PYTHON_PATH=%%p
)

python -V

:: 1) Generate derived files: help (.xlsx->.py), ui (.ui->.py),
::    translations (pylupdate refresh + lrelease compile to .qm)
echo ************* build derived files **************
call build-derived-win.bat
if ERRORLEVEL 1 (echo ** Failed in build-derived-win.bat & exit /b 1)

:: 2) Version info file for the .exe metadata
for /f "usebackq delims==" %%a in (`python -c "import artisanlib; print(artisanlib.__version__)"`) do set ARTISAN_VERSION=%%~a
for /f "usebackq delims==" %%a in (`python -c "import artisanlib; print(artisanlib.__build__)"`) do set ARTISAN_BUILD=%%~a
create-version-file version-metadata.yml --outfile version_info-win.txt --version %ARTISAN_VERSION%.%ARTISAN_BUILD%

:: 3) Bundle the app with PyInstaller
echo ************* pyinstaller **************
pyinstaller --noconfirm --log-level=WARN artisan-win-local.spec
if ERRORLEVEL 1 (echo ** Failed in pyinstaller & exit /b 1)

:: 4) Build the installer .exe with NSIS
echo ************* NSIS installer **************
set NSIS_EXE=
if exist "%ProgramFiles%\NSIS\makensis.exe"      set NSIS_EXE="%ProgramFiles%\NSIS\makensis.exe"
if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set NSIS_EXE="%ProgramFiles(x86)%\NSIS\makensis.exe"
if not defined NSIS_EXE (echo makensis.exe not found - install NSIS & exit /b 1)

%NSIS_EXE% /DPRODUCT_VERSION=%ARTISAN_VERSION% /DPRODUCT_BUILD=%ARTISAN_BUILD% setup-install3-pi.nsi
if ERRORLEVEL 1 (echo ** Failed in NSIS & exit /b 1)

echo.
echo ** DONE. Installer: RoastArtisan-win-x64-%ARTISAN_VERSION%-setup.exe
endlocal
