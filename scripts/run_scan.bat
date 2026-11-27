@echo off
rem Runs one scan. Windows Task Scheduler calls this every hour (see README).
cd /d "%~dp0.."
if not exist data mkdir data
".venv\Scripts\python.exe" -m wowflip scan >> data\task.log 2>&1
