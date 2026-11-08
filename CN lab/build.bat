@echo off
REM ==============================================================================
REM Build script to generate standalone executables for Windows.
REM Uses PyInstaller as a build-time packager.
REM ==============================================================================

echo ==========================================================
echo  Building LAN Collaborative Whiteboard Executables (Windows)
echo ==========================================================

REM 1. Verify PyInstaller is installed
where pyinstaller >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Error: PyInstaller command not found in PATH.
    echo Install it using: pip install pyinstaller
    pause
    exit /b 1
)

REM 2. Build Server Executable (Console application)
echo.
echo [1/3] Building whiteboard-server.exe...
pyinstaller --clean --noconfirm --onefile ^
    --name whiteboard-server ^
    whiteboard\server.py
if %ERRORLEVEL% NEQ 0 (
    echo Error: Server build failed.
    pause
    exit /b 1
)

REM 3. Build Client Executable (Windowed GUI application)
echo.
echo [2/3] Building whiteboard-client.exe...
pyinstaller --clean --noconfirm --onefile --windowed ^
    --name whiteboard-client ^
    whiteboard\client.py
if %ERRORLEVEL% NEQ 0 (
    echo Error: Client build failed.
    pause
    exit /b 1
)

REM 4. Verify dist folder
echo.
echo [3/3] Checking dist folder...
if not exist "dist" mkdir dist

echo ==========================================================
echo  Build Succeeded! Executables generated in dist\:
echo    - dist\whiteboard-server.exe
echo    - dist\whiteboard-client.exe
echo    - dist\README.txt
echo ==========================================================
pause

