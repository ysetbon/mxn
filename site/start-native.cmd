@echo off
cd /d "%~dp0"
python serve_native.py
if errorlevel 1 pause
