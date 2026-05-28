RoastArtisan Windows x64 build
==============================

This source tree includes the Kuban S7 byte command patch:

setDBbyte(dbnumber,start,value)

Fast test without building an installer
---------------------------------------
1. Install 64-bit Python 3.11 or newer.
2. Run RUN-FROM-SOURCE-WINDOWS.bat.
3. Configure Artisan buttons as S7 Command actions using docs/kuban_s7_byte_commands.md.

Build portable Windows client
-----------------------------
1. Install 64-bit Python 3.11 or newer.
2. Run build-windows-x64-local.bat.
3. The portable executable will be created at:

src\dist\RoastArtisan\RoastArtisan.exe

The script skips derived UI/help/translation regeneration by default because generated files are already included.
To force regeneration, run it as:

set RUN_DERIVED=1
build-windows-x64-local.bat

Optional installer
------------------
Install NSIS before running build-windows-x64-local.bat.
If NSIS is found, the script will also try to build the installer.

Pressure service
----------------
Keep the current Kuban pressure service as-is.
The Artisan patch only adds direct byte writes for start/stop/reset buttons.

Button commands
---------------
See:

docs\kuban_s7_byte_commands.md
