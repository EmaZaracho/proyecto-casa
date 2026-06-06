@echo off
cd /d "%~dp0"
echo Configurando entorno...
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Listo. Ejecutar iniciar_gui.bat para iniciar.
pause
