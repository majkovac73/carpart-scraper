@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo === Scrape neue Deals ===
python main.py --min-discount 15 %*
if errorlevel 1 goto :eof
echo.
echo === Telegram-Verteilung ===
python telegram_distribute.py