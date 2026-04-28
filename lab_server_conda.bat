@echo off
:: Move to the directory where the script is located
cd /d "%~dp0"

:: Set default variables
if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=8000"

:: Set PYTHONPATH so Python can find the 'src' folder
set "PYTHONPATH=%CD%\src"

echo Checking for uvicorn...
where uvicorn >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] uvicorn not found in your current Conda environment.
    echo Please run: conda install -c conda-forge uvicorn
    pause
    exit /b 1
)

echo Starting LABKickstart on %HOST%:%PORT%...
:: The %* allows you to pass extra flags to the command
uvicorn labkickstart.app:app --host %HOST% --port %PORT% %*

pause