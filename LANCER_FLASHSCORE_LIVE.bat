@echo off
chcp 65001 >nul
title Flashscore Live & Combines M1/M2 (Local)
echo ========================================================
echo   FLASHSCORE LIVE STREAM & COMBINES (LOCAL PORT 8090)
echo ========================================================
echo.
echo Demarrage du serveur live local sur http://localhost:8090 ...
cd /d "%~dp0"

start "" http://localhost:8090

python scripts\unibet_live_stream.py
pause
