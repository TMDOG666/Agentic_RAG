@echo off
setlocal

cd /d "%~dp0"

echo ========================================
echo Agentic_RAG dev launcher
echo Project dir: %CD%
echo ========================================

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found in PATH.
    pause
    exit /b 1
)

if not exist "webui\package.json" (
    echo [ERROR] webui\package.json not found.
    pause
    exit /b 1
)

echo [1/2] Starting backend...
start "Agentic_RAG Backend" cmd /k "conda activate langchain && cd /d %CD% && uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload"

echo [2/2] Starting frontend...
start "Agentic_RAG WebUI" cmd /k "cd /d %CD%\webui && npm run dev"

echo.
echo Backend docs: http://127.0.0.1:8080/docs
echo Frontend url: usually http://127.0.0.1:5173
echo.
echo If frontend fails on first run, execute: cd webui && npm install
echo If backend dependencies are missing, activate langchain and run: pip install -r requirements.txt
echo.
pause
