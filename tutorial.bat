@echo off
rem Abre el programa directamente en el tutorial guiado (usa una base de datos de practica: no toca la suya).
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py --tutorial
) else (
  python main.py --tutorial
)
if errorlevel 1 pause
