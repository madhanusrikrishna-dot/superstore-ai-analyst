@echo off
rem Double-click to start the app and a public demo link.
rem Close both windows (or press Ctrl + C in them) to stop.
cd /d "%~dp0"

echo Checking Ollama...
ollama list >nul 2>&1 || (echo Ollama is not running. Open Ollama from the Start menu, then run this again. & pause & exit /b)

start "Superstore AI Analyst - app" cmd /k python -m streamlit run app.py --server.headless true
echo Starting the app...
timeout /t 10 /nobreak >nul

start "Superstore AI Analyst - public link" cmd /k cloudflared tunnel --url http://localhost:8501
echo.
echo Two windows opened:
echo   1. the app  (local: http://localhost:8501)
echo   2. the public link: look for https://....trycloudflare.com in that window
echo.
echo Close both windows when the demo is over.
pause
