# ================================================================
# INSTALADOR DE SERVICIO WINDOWS: HydroCloud Dashboard
# ================================================================
$ErrorActionPreference = "Stop"

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[ERROR] Este script debe ejecutarse como Administrador." -ForegroundColor Red
    Write-Host "Haz clic derecho en PowerShell y selecciona 'Ejecutar como administrador'."
    Exit 1
}

$dashboardDir = $PSScriptRoot
$exePath = Join-Path $dashboardDir "HydroCloud.Admin.exe"
$serviceName = "HydroCloudDashboard"

# Buscar nssm.exe en la carpeta actual o en D:\HydroCloud
$nssmPath = Join-Path $dashboardDir "nssm.exe"
if (-not (Test-Path $nssmPath)) {
    $parentNssm = Join-Path (Split-Path $dashboardDir) "nssm.exe"
    if (Test-Path $parentNssm) {
        $nssmPath = $parentNssm
    } else {
        $rootNssm = "D:\HydroCloud\nssm.exe"
        if (Test-Path $rootNssm) { $nssmPath = $rootNssm }
    }
}

if (-not (Test-Path $nssmPath)) {
    Write-Host "[INFO] nssm.exe no encontrado localmente. Descargando automaticamente..." -ForegroundColor Yellow
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $zipPath = Join-Path $dashboardDir "nssm_temp.zip"
        Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zipPath
        Expand-Archive -Path $zipPath -DestinationPath (Join-Path $dashboardDir "nssm_extracted") -Force
        Copy-Item (Join-Path $dashboardDir "nssm_extracted\nssm-2.24\win64\nssm.exe") $nssmPath -Force
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path $dashboardDir "nssm_extracted") -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "[INFO] nssm.exe listo en la carpeta." -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] No se pudo descargar nssm.exe automaticamente. Asegurate de tener conexion o colocar nssm.exe en esta carpeta." -ForegroundColor Red
        Exit 1
    }
}

Write-Host "=== Instalando $serviceName como Servicio de Windows ===" -ForegroundColor Cyan

# Detener y remover si ya existe
$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] El servicio $serviceName ya existe. Reinstalando..." -ForegroundColor Yellow
    & $nssmPath stop $serviceName | Out-Null
    & $nssmPath remove $serviceName confirm | Out-Null
    Start-Sleep -Seconds 2
}

# Instalar con NSSM
& $nssmPath install $serviceName $exePath
& $nssmPath set $serviceName AppDirectory $dashboardDir
& $nssmPath set $serviceName AppParameters "--urls http://0.0.0.0:5000"
& $nssmPath set $serviceName AppEnvironmentExtra "ASPNETCORE_ENVIRONMENT=Production" "ASPNETCORE_URLS=http://0.0.0.0:5000"
& $nssmPath set $serviceName Description "HydroCloud Web Dashboard - Visualizador Hidrometeorologico 24/7"
& $nssmPath set $serviceName Start SERVICE_AUTO_START
& $nssmPath set $serviceName AppStdout (Join-Path $dashboardDir "dashboard_stdout.log")
& $nssmPath set $serviceName AppStderr (Join-Path $dashboardDir "dashboard_stderr.log")

# Iniciar servicio
Write-Host "Iniciando servicio $serviceName..." -ForegroundColor Cyan
& $nssmPath start $serviceName

Start-Sleep -Seconds 3
$svc = Get-Service -Name $serviceName
Write-Host "============================================================" -ForegroundColor Green
Write-Host " [EXITO] Servicio $serviceName instalado correctamente!" -ForegroundColor Green
Write-Host " Estado: $($svc.Status)" -ForegroundColor Green
Write-Host " Dashboard local en: http://localhost:5000" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green

