@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller stock.spec
echo Ejecutable generado en dist\SistemaDeStock.exe
pause
