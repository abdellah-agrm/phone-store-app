@echo off
title PhoneShopManager - Seeder CLI
cd /d "%~dp0"
if exist "penv\Scripts\activate.bat" (
    call penv\Scripts\activate.bat
)
python seeder.py
pause
