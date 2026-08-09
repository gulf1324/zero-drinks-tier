@echo off
rem ASCII only. Korean messages are printed by the Python script,
rem because cmd.exe parses .cmd files in the OEM codepage (949) and
rem would mangle UTF-8 Korean written here.
chcp 65001 >nul
cd /d "%~dp0"
python zero_soda_scan.py --mode update
echo.
pause
