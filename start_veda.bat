@echo off
setlocal
cd /d "%~dp0"

echo.
echo  VEDA - Agent-Native Construction Project Intelligence Platform
echo  ==============================================================
echo.

set "VEDA_INSTALL_DEPS=0"
if not exist ".venv\Scripts\python.exe" (
    echo  [setup] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo  [error] Could not create the virtual environment.
        echo          Install Python 3.10+ and make sure "python" is on PATH.
        pause
        exit /b 1
    )
    set "VEDA_INSTALL_DEPS=1"
)

rem v0.1.2 added adaptive OCR. Existing v0.1.1 environments need the new
rem packages too, so do a cheap import probe rather than assuming .venv means
rem requirements.txt is already satisfied.
if "%VEDA_INSTALL_DEPS%"=="0" (
    ".venv\Scripts\python.exe" -c "import pymupdf, rapidocr, onnxruntime" >nul 2>&1
    if errorlevel 1 set "VEDA_INSTALL_DEPS=1"
)

if "%VEDA_INSTALL_DEPS%"=="1" (
    echo  [setup] Installing/updating dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo  [error] Dependency installation failed.
        pause
        exit /b 1
    )
)

where horizun-msproject-mcp >nul 2>&1
if errorlevel 1 (
    echo  [warn] horizun-msproject-mcp was not found on PATH.
    echo         Install it with:  dotnet tool install -g HorizunMsProjectMcp
    echo         VEDA will start, but schedule analysis will be unavailable.
    echo.
)

where claude >nul 2>&1
if errorlevel 1 (
    if "%GEMINI_API_KEY%"=="" (
        echo  [warn] No reasoning provider found.
        echo         Install Claude Code:  npm install -g @anthropic-ai/claude-code
        echo         or set GEMINI_API_KEY to use Antigravity/Gemini.
        echo         VEDA will still run its rule-based analyser.
        echo.
    )
)

if not exist "data" mkdir data

echo  [start] VEDA is starting on http://127.0.0.1:8770
echo  [start] Press Ctrl+C to stop.
echo.

start "" http://127.0.0.1:8770
".venv\Scripts\python.exe" -m veda.main

endlocal
