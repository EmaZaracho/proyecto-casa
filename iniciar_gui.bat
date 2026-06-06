@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python no encontrado.
    echo Instalar desde https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist stock_gui.py (
    echo ERROR: No se encontro stock_gui.py en %cd%
    pause
    exit /b 1
)

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python stock_gui.py
if %errorlevel% neq 0 (
    echo.
    echo La aplicacion cerro con un error. Revisar stock.log para detalles.
    pause
)
