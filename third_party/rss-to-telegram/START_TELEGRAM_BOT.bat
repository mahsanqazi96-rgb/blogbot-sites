@echo off
title BlogBot — RSS to Telegram Bot
echo Starting RSS-to-Telegram bot...
echo.

REM Make sure config.ini exists
if not exist "config.ini" (
    echo ERROR: config.ini not found!
    echo Copy config.ini.example to config.ini and fill in your values.
    pause
    exit /b 1
)

REM Check if the repo is cloned
if not exist "rss-to-telegram-bot" (
    echo Cloning RSS-to-Telegram-Bot...
    git clone https://github.com/BoKKeR/RSS-to-Telegram-Bot rss-to-telegram-bot
)

REM Copy config into the tool folder
copy /y config.ini rss-to-telegram-bot\config.ini

REM Run the bot
cd rss-to-telegram-bot
pip install -r requirements.txt --quiet
python bot.py

pause
