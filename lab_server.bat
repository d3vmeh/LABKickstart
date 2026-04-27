@echo off
setlocal enabledelayedexpansion

:: Move to the directory where the script is located
cd /d "%~dp0"

:: Set default variables if not already set
if "%VENV%"=="" set "VENV=.venv"
if "%HOST%"=="" set "HOST=0.0.0.0"
if "%PORT%"=="" set "PORT=8000"

:: Path to uvicorn in a Windows virtual environment
set "UVICORN_PATH=%VENV%\Scripts\uvicorn.exe"

:: Check if uvicorn exists
if not exist "%UVICORN_PATH%" (
    echo error: %UVICORN_PATH% not found.
    echo Create the venv first:
    echo python -m venv %VENV%
    echo %VENV%\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: Set PYTHONPATH to include the src directory
set "PYTHONPATH=%CD%\src"

:: Run uvicorn
echo Starting server on %HOST%:%PORT%...
"%UVICORN_PATH%" labkickstart.app:app --host %HOST% --port %PORT% --reload %*

pause