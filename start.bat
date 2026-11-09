@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0backend\.venv\Scripts\python.exe"

where node >nul 2>&1
if errorlevel 1 (
    echo Install Node.js LTS first: https://nodejs.org/
    goto failed
)

if /i "%~1"=="setup" (
    if not exist "%PYTHON%" python -m venv backend\.venv
    if errorlevel 1 goto failed
    "%PYTHON%" -m pip install -r backend\requirements.txt
    if errorlevel 1 goto failed
    pushd backend\whatsapp
    call npm ci
    if errorlevel 1 (
        popd
        goto failed
    )
    popd
)

if not exist "%PYTHON%" goto needs_setup
if not exist "backend\whatsapp\node_modules" goto needs_setup
if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul
"%PYTHON%" backend\manage.py migrate --noinput
if errorlevel 1 (
    echo Check that MySQL is running in XAMPP and backend\.env names the correct database.
    echo On a new computer, import database\setup.sql using phpMyAdmin first.
    goto failed
)
if /i "%~1"=="setup" (
    echo Setup complete. Run start.bat to open Nexora.
    exit /b 0
)

start "Nexora WhatsApp" /D "%~dp0backend\whatsapp" cmd /k "node index.js"
start "Nexora Backend" cmd /k ""%PYTHON%" "%~dp0backend\manage.py" runserver 127.0.0.1:8000"
echo Website: http://127.0.0.1:8000/
echo Close both server windows to stop Nexora.
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8000/"
exit /b 0

:needs_setup
echo Run "start.bat setup" once to install the project dependencies.
:failed
echo Startup stopped. Read the error above.
pause
exit /b 1
