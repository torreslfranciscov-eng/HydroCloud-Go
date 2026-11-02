@echo off
setlocal
echo ================================================================
echo    INSTALADOR DE SERVICIO WINDOWS - HYDROCLOUD GOES COLLECTOR
echo ================================================================
echo.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Este script debe ejecutarse como Administrador.
    echo Clic derecho en el archivo y 'Ejecutar como administrador'.
    echo.
    pause
    exit /b 1
)

python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python no se encuentra en el PATH.
    echo Instala Python y marca 'Add python.exe to PATH'.
    echo.
    pause
    exit /b 1
)

echo [1/4] Verificando entorno...
if exist .venv\Scriptsctivate.bat (
    call .venv\Scriptsctivate.bat
    echo Entorno .venv activado.
)

echo [2/4] Instalando dependencias (incluyendo pywin32)...
python -m pip install -r requirements_windows.txt
if %errorLevel% neq 0 (
    echo [ERROR] Fallo la instalacion de paquetes.
    pause
    exit /b 1
)

echo [3/4] Instalando Servicio de Windows con inicio automatico...
python mycloud_all_timescale.py --startup auto install

echo [4/4] Iniciando Servicio de Windows...
python mycloud_all_timescale.py start
if %errorLevel% neq 0 (
    net start MyCloudTimescale
)

echo.
echo ================================================================
echo  SERVICIO INSTALADO Y EN EJECUCION
echo  Nombre del servicio: MyCloudTimescale
echo  Monitor web:         http://localhost:5555
echo ================================================================
echo.
pause
