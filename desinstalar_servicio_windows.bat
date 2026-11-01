@echo off
chcp 65001 > nul
echo ================================================================
echo    DESINSTALADOR DE SERVICIO WINDOWS - HYDROCLOUD
echo ================================================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Este script debe ejecutarse como Administrador.
    pause
    exit /b 1
)

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo Deteniendo servicio MyCloudTimescale...
python mycloud_all_timescale.py stop 2>nul
net stop MyCloudTimescale 2>nul

echo Desinstalando servicio...
python mycloud_all_timescale.py remove

echo.
echo ================================================================
echo  Servicio detenido y eliminado del Administrador de Servicios.
echo ================================================================
echo.
pause
