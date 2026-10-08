@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        py -3 src\server.py
        goto :finished
    )
)

where python >nul 2>nul
if not errorlevel 1 (
    python --version >nul 2>nul
    if not errorlevel 1 (
        python src\server.py
        goto :finished
    )
)

echo Python 3 was not found. Install Python 3.10 or newer and try again.
:finished
if errorlevel 1 echo The image studio stopped with an error.
echo.
pause
endlocal
