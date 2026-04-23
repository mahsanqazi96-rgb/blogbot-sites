@echo off
title BlogBot — Skywrite (RSS to Bluesky)
echo Starting Skywrite RSS-to-Bluesky poster...
echo.

REM Check for config
if not exist "config.toml" (
    echo ERROR: config.toml not found!
    echo Copy config.toml.example to config.toml and fill in your Bluesky credentials.
    pause
    exit /b 1
)

REM Check if skywrite is installed (cargo/rust required)
where skywrite >nul 2>&1
if errorlevel 1 (
    echo Skywrite not found. Trying to install via cargo...
    where cargo >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Rust/Cargo not installed.
        echo Install from https://rustup.rs then re-run this script.
        pause
        exit /b 1
    )
    cargo install skywrite
)

skywrite --config config.toml
pause
