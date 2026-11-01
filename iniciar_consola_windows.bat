@echo off
chcp 65001 > nul
title HydroCloud GOES Ingestion Service (Consola en Vivo)
echo ================================================================
echo    HYDROCLOUD GOES COLLECTOR - MODO CONSOLA EN VIVO
echo ================================================================
echo.

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo [.venv activado]
)

:: Si no está configurada en config.ini ni en el sistema, solicitarla o usar variable de entorno
if "%PG_PASSWORD%"=="" (
    echo [INFO] Usando configuracion de config.ini...
)

python -u mycloud_all_timescale.py
pause
