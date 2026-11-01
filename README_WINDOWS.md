# Despliegue de HydroCloud Collector en Windows Server

Esta guía permite instalar el colector satelital GOES como un **Servicio de Windows (24/7 nativo)** que arranca automáticamente con el servidor, no depende de sesiones de usuario abiertas y se recupera solo ante fallas o reinicios.

---

## 1. Requisitos en el Servidor Windows

1. **Python 3.10, 3.11 o 3.12** de 64 bits.
   * Descargar desde: [python.org/downloads/windows](https://www.python.org/downloads/windows/)
   * ⚠️ **MUY IMPORTANTE**: En la primera pantalla del instalador de Python, marcar la casilla:
     `☑ Add python.exe to PATH`.
2. Acceso a internet hacia:
   * Servidores LRGS NOAA: `lrgseddn1.cr.usgs.gov`, `lrgseddn2`, `lrgseddn3` (puertos 16003 / HTTP).
   * PostgreSQL Aiven Cloud: `pg-1ab7e72d-torreslfranciscov-58fb.g.aivencloud.com:19960`.
   * SQL Server remoto: `atlas16.ddns.net:1433`.

---

## 2. Preparar los Archivos

1. Copia o clona la carpeta `HydroCloud-Go` en tu servidor Windows (por ejemplo en `C:\HydroCloud-Go`).
2. Configura la contraseña de PostgreSQL:
   * **Opción A (Recomendada en el archivo):** Abre `config.ini` con el Bloc de notas y coloca en `[timescaledb]`:
     ```ini
     password = TU_PASSWORD_AIVEN
     ```
   * **Opción B (Variable de Entorno de Sistema):**  
     Abre PowerShell como Administrador y ejecuta:
     ```powershell
     [System.Environment]::SetEnvironmentVariable('PG_PASSWORD', 'TU_PASSWORD_AIVEN', [System.EnvironmentVariableTarget]::Machine)
     ```

---

## 3. Probar Primero en Consola (Opcional)

Si deseas ver la descarga satelital en vivo en una ventana de comandos antes de instalar el servicio:

1. Haz doble clic en:
   ```cmd
   iniciar_consola_windows.bat
   ```
2. Verás la conexión a la base de datos, el catálogo de 740 estaciones y las descargas minuto a minuto.
3. Para salir presiona `Ctrl + C`.

---

## 4. Instalar como Servicio de Windows (24/7)

Para que corra en segundo plano de por vida sin necesidad de tener abierta ninguna sesión de usuario:

1. Haz **clic derecho** sobre:
   ```cmd
   instalar_servicio_windows.bat
   ```
   y selecciona **"Ejecutar como administrador"**.
2. El script automáticamente:
   * Instalará las dependencias necesarias (`requirements_windows.txt` incluyendo `pywin32`).
   * Registrará el servicio en el Administrador de Servicios de Windows con inicio automático (`--startup auto`).
   * Iniciará el servicio `MyCloudTimescale`.

---

## 5. Monitoreo y Administración

* **Monitor Web Local:** Abre tu navegador en el servidor en:
  `http://localhost:5555`
  Podrás ver el estado del colector, estaciones descargadas, tasa de fallos y forzar recuperaciones manuales.
* **Desde `services.msc`:**
  * Presiona `Win + R`, escribe `services.msc` y presiona Enter.
  * Busca el servicio: **MyCloud GOES TimescaleDB** (`MyCloudTimescale`).
  * Puedes iniciarlo, detenerlo o reiniciarlo desde allí.
* **Logs del Servicio:**
  * En el **Visor de Eventos de Windows** (`eventvwr.msc`) ➔ *Registros de Windows* ➔ *Aplicación*.

---

## 6. Desinstalación (Si fuera necesario)

Para detener y retirar el servicio de Windows:
1. Haz clic derecho sobre `desinstalar_servicio_windows.bat` y selecciona **"Ejecutar como administrador"**.
