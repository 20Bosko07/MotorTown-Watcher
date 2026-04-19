@echo off
title Motor Town Watcher Launcher
color 0B

echo ===================================================
echo             MOTOR TOWN WATCHER SETUP
echo ===================================================
echo.

:: --- Update Check from GitHub Releases ---
echo Checking for updates from GitHub...
if exist "version.txt" (
    set /p CURRENT_VERSION=<version.txt
) else (
    set CURRENT_VERSION=v1.0.0
)

FOR /F "tokens=*" %%g IN ('powershell -Command "$ErrorActionPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/20Bosko07/MotorTown-Watcher/releases/latest'; if($release) { $release.tag_name }"') do (SET LATEST_TAG=%%g)

if not "%LATEST_TAG%"=="" (
    if not "%LATEST_TAG%"=="%CURRENT_VERSION%" (
        echo [UPDATE AVAILABLE] A new version %%LATEST_TAG%% is available! You are running %CURRENT_VERSION%.
        echo Your browser will now open the download page. Please download the newest zip!
        timeout /t 5 >nul
        start "" "https://github.com/20Bosko07/MotorTown-Watcher/releases/latest"
        echo Please extract the new files over your current folder and run start.bat again.
        echo Exiting...
        pause
        exit /b
    ) else (
        echo [INFO] You are running the latest version ^(%CURRENT_VERSION%^).
    )
) else (
    echo [INFO] Could not check for updates right now. Skipping...
)
echo ===================================================
echo.

:: Check if 'py' (Windows Python Launcher) or 'python' exists
set PYTHON_CMD=python
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python was not found!
        echo Please download Python: https://www.python.org/downloads/
        echo IMPORTANT: Make sure to check the box "Add Python to PATH" during installation!
        echo.
        pause
        exit /b
    ) else (
        set PYTHON_CMD=py
    )
)

echo [OK] Python found. Checking and installing missing packages automatically...
%PYTHON_CMD% -m pip install -r requirements.txt

echo.
echo ===================================================
echo             MOTOR TOWN WATCHER RUNNING
echo ===================================================
echo.
echo The web interface will open automatically in your browser...
echo To close the program, simply close this black window!
echo.

:: Open the browser in the background
start "" "http://localhost:5000"

:: Start the Backend App script
%PYTHON_CMD% app.py

echo.
echo The program was terminated or an error occurred.
pause
