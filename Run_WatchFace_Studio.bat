@echo off
title Watch Face Studio
cd /d "%~dp0"
python watch_face_studio.py
if errorlevel 1 (
    echo.
    echo An error occurred. Press any key to exit.
    pause >nul
)
