@echo off
title HydroCloud GOES Ingestion Service (Consola en Vivo)
echo ================================================================
echo    HYDROCLOUD GOES COLLECTOR - CONSOLA EN VIVO
echo ================================================================
echo.

if exist .venv\Scriptsctivate.bat (
    call .venv\Scriptsctivate.bat
)

python -u mycloud_all_timescale.py
pause
