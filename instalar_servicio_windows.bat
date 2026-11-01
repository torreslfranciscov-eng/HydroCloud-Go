@echo off
chcp 65001 > nul
echo ================================================================
echo    INSTALADOR DE SERVICIO WINDOWS - HYDROCLOUD GOES COLLECTOR
echo ================================================================
echo.

:: Verificar permisos de Administrador
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Este script debe ejecutarse como Administrador.
    echo Por favor, haz clic derecho en el archivo y selecciona:
    echo "Ejecutar como administrador".
    echo.
    pause
    exit /b 1
)

:: Verificar si Python está instalado
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python no se encuentra en el PATH.
    echo Asegúrate de tener Python 3.10, 3.11 o 3.12 instalado y marcado
    echo "Add python.exe to PATH" en el instalador de Python.
    echo.
    pause
    exit /b 1
)

echo [1/4] Verificando entorno virtual o paquetes Python...
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo Entorno virtual local (.venv) activado.
)

echo [2/4] Instalando dependencias de Windows (incluyendo pywin32)...
python -m pip install --upgrade pip
python -m pip install -r requirements_windows.txt
if %errorLevel% neq 0 (
    echo [ERROR] Falló la instalación de paquetes. Revisa tu conexión a internet.
    pause
    exit /b 1
)

:: Post-instalación de pywin32 para registrar DLLs en Windows
echo Registrando componentes de servicio en Windows...
python -c "import win32serviceutil" >nul 2>&1
if %errorLevel% neq 0 (
    echo Registrando pywin32_postinstall...
    python Scripts\pywin32_postinstall.py -install 2>nul
)

echo.
echo [3/4] Instalando Servicio de Windows con inicio automático...
python mycloud_all_timescale.py --startup auto install

echo.
echo [4/4] Iniciando Servicio de Windows...
python mycloud_all_timescale.py start
if %errorLevel% neq 0 (
    net start MyCloudTimescale
)

echo.
echo ================================================================
echo  ¡SERVICIO INSTALADO Y EN EJECUCIÓN SATISFACTORIAMENTE!
echo  Nombre del servicio: MyCloudTimescale
echo  Monitor web:         http://localhost:5555
echo ================================================================
echo.
pause
