@echo off
py -3 "%~dp0setup_access.py" --gui
if errorlevel 1 pause
