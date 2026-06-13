@echo off
REM Launch Gemel locally. Double-click this file.
cd /d "%~dp0"
echo Starting Gemel at http://localhost:8000  (close this window to stop)
REM open the browser a couple seconds after the server starts
start "" /min cmd /c "timeout /t 2 >nul & start http://localhost:8000"
.venv\Scripts\python.exe -m uvicorn gemel_server:app --port 8000
