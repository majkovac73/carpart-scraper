@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo TrackDeals Website unter http://localhost:8000  (Strg+C zum Beenden)
python website.py --host 0.0.0.0 --port 8000