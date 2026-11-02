# PowerShell Installer para HydroCloud Windows Service
# Requiere permisos de Administrador

Write-Host '================================================================' -ForegroundColor Cyan
Write-Host '   INSTALADOR DE SERVICIO WINDOWS - HYDROCLOUD GOES COLLECTOR' -ForegroundColor Cyan
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host ''

 = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not ) {
    Write-Host '[ERROR] Debes ejecutar PowerShell como Administrador.' -ForegroundColor Red
    Write-Host 'Abre PowerShell con clic derecho -> "Ejecutar como administrador".'
    exit 1
}

Write-Host '[1/4] Verificando Python...' -ForegroundColor Yellow
python --version
if ( -ne 0) {
    Write-Host '[ERROR] Python no esta en el PATH.' -ForegroundColor Red
    exit 1
}

if (Test-Path '.venv\Scripts\Activate.ps1') {
    Write-Host 'Activando .venv...' -ForegroundColor Green
    . .venv\Scripts\Activate.ps1
}

Write-Host '[2/4] Instalando dependencias (pywin32)...' -ForegroundColor Yellow
python -m pip install -r requirements_windows.txt

Write-Host '[3/4] Instalando Servicio de Windows...' -ForegroundColor Yellow
python mycloud_all_timescale.py --startup auto install

Write-Host '[4/4] Iniciando Servicio de Windows...' -ForegroundColor Yellow
python mycloud_all_timescale.py start
if ( -ne 0) {
    Start-Service -Name 'MyCloudTimescale' -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host '================================================================' -ForegroundColor Green
Write-Host '  SERVICIO INSTALADO Y EN EJECUCION' -ForegroundColor Green
Write-Host '  Nombre del servicio: MyCloudTimescale' -ForegroundColor Green
Write-Host '  Monitor web:         http://localhost:5555' -ForegroundColor Green
Write-Host '================================================================' -ForegroundColor Green
