# HydroCloud Administración

Aplicación web ASP.NET Core MVC / .NET 8, interfaz en español, Oracle ODP.NET Core.
La portada ahora ofrece [consulta pública de siete días, consulta histórica autenticada, mapa, gráficas, tablas, CSV y métricas de visitas](CONSULTAS.md). La administración sigue en `/Stations` y requiere rol Administrator.
Implementada contra la estructura real de `HYDROCLOUD.ESTACION`, sus catálogos y siete módulos relacionados, verificados mediante consultas de solo lectura. Ver [análisis del esquema](SCHEMA-REVIEW.md).

## Funcionalidad

- Acceso de administrador por cookie, contraseña almacenada como hash PBKDF2 de ASP.NET Identity, límite de intentos y protección antifalsificación en formularios.
- Búsqueda por nombre/clave, filtros activas/inactivas y paginación de 25 estaciones.
- Altas con UUID, edición de ubicación, clasificación, canales, comentarios y disponibilidad.
- Validación de coordenadas, pertenencia municipio/entidad y subcuenca/cuenca, y detección de claves existentes.
- Edición con comprobación de versión y bloqueo de fila durante la transacción; impide sobrescribir cambios simultáneos del formulario.
- Baja lógica confirmada por clave: `ACTIVO=0`, `VISIBLE=0`. Reactivación desde Editar. Sin eliminación física de estaciones, sensores o históricos.
- Autor y fecha UTC en las columnas existentes de registro/modificación; logs de aplicación por identificador. No es una bitácora inmutable de cambios.

- Ficha técnica por estación: alta y edición de GOES, GPRS, radio, sensores, cotas, componentes e inventario físico de sensores.
- Formularios según tipos, longitudes, precisión y nulabilidad reales de Oracle. Catálogos de tipo/unidad, límites mínimo/máximo, muestreo positivo, horarios GOES y pertenencia del sensor validados en servidor.
- Contadores de transmisión y auditoría de solo lectura. Sin traslado de configuraciones entre estaciones. Tokens firmados vinculados a estación, módulo, registro y versión.
- Baja lógica de sensor; finalización de cota; eliminación de configuración GOES/GPRS/radio con confirmación de clave. Crear/eliminar configuraciones sincroniza el indicador del canal dentro de la misma transacción.
- Los inventarios se crean y editan; no se ofrece borrado hasta definir su política de conservación. No hay carga de imágenes: solo referencia textual existente.

No crea tablas ni ejecuta migraciones al iniciar. No modifica la configuración del colector Python ni garantiza su recarga inmediata. Marcar un indicador de canal en Datos generales no crea su configuración. La consulta de mediciones y productos almacenados en `MYCLOUD_TS` está disponible en la portada. Administración de alertas por cliente/usuario, bitácoras, curvas gasto/elevación y catálogos globales quedan pendientes.

## Configuración y ejecución local

Desde la raíz del repositorio:

```sh
dotnet build HydroCloud.Admin/HydroCloud.Admin.csproj
dotnet user-secrets set --project HydroCloud.Admin 'ConnectionStrings:HydroCloud' 'User Id=HYDROCLOUD;Password=CONTRASENA;Data Source=(description=(address=(protocol=tcps)(host=adb.mx-queretaro-1.oraclecloud.com)(port=1521))(connect_data=(service_name=ga4e34d25e10323_hydroclouddb_low.adb.oraclecloud.com))(security=(ssl_server_dn_match=yes)));Pooling=true;Min Pool Size=0;Max Pool Size=6;Connection Timeout=15;'
dotnet user-secrets set --project HydroCloud.Admin 'Admin:Username' 'administrador'
```

Genera un hash de una contraseña propia del portal, distinta de la de Oracle. El comando lee una línea de entrada estándar y devuelve el hash; usa una entrada que no exponga la contraseña en el historial del shell:

```sh
dotnet HydroCloud.Admin/bin/Debug/net8.0/HydroCloud.Admin.dll --hash-password
dotnet user-secrets set --project HydroCloud.Admin 'Admin:PasswordHash' 'HASH_GENERADO'
ASPNETCORE_ENVIRONMENT=Development dotnet run --project HydroCloud.Admin --no-launch-profile --urls http://127.0.0.1:5080
```

Abre http://127.0.0.1:5080. Se requiere permitir la IP de salida en la ACL de Oracle. No hay contraseña predeterminada ni credenciales de Oracle en los archivos del proyecto. User Secrets se guarda fuera del repositorio y no cifra los secretos en disco.

## Producción

Publicar con `dotnet publish HydroCloud.Admin -c Release`. Configurar por gestor de secretos o variables de entorno `ConnectionStrings__HydroCloud`, `Admin__Username`, `Admin__PasswordHash` y `AllowedHosts` (dominio real).

Servir con HTTPS. Si se aloja detrás de proxy, configurar encabezados reenviados y proxies confiables según el proveedor antes de habilitar la redirección HTTPS. Persistir y proteger el llavero de ASP.NET Data Protection en despliegues con contenedores y compartirlo si hay varias réplicas. El Dockerfile es una base de empaquetado, no configura terminación TLS ni proxy.

Es preferible usar un usuario de aplicación con SELECT/INSERT/UPDATE sobre `HYDROCLOUD.ESTACION`, `SENSOR`, `COTASENSOR`, `COMPONENTE_ESTACION`, `COMP_SENSORINVENTARIO`; SELECT/INSERT/UPDATE/DELETE sobre `DATOSGOES`, `DATOSGPRS`, `DATOSRADIO`; y SELECT en `CUENCA`, `SUBCUENCA`, `ENTIDADFEDERATIVA`, `MUNICIPIO`, `ORGANISMO`, `ESTATUSESTACIONBITACORA`, `TIPOSENSOR`, `UNIDADMEDIDA`. Necesita visibilidad de sus columnas en ALL_TAB_COLUMNS y uso de las identidades al insertar. No necesita ADMIN ni DDL. El esquema y la lista permitida de tablas están explícitos en el código.

La comprobación de clave repetida es de aplicación: el esquema existente no tiene una restricción UNIQUE sobre IDASIGNADO. Para unicidad estricta entre altas concurrentes de distintos clientes se necesita revisar duplicados existentes y acordar esa restricción en Oracle.

## Verificación

```sh
dotnet run --project HydroCloud.Admin.Tests
```

Las pruebas de controlador verifican alta, edición, conflictos, token manipulado, relación de catálogos y baja lógica con repositorio en memoria. No escriben en producción. Probar la persistencia de altas/ediciones/bajas contra una copia de la base antes de habilitar el portal a operadores.

La prueba HTTP opcional `python3 HydroCloud.Admin.Tests/smoke_readonly.py` usa la variable `ConnectionStrings__HydroCloud`: inicia temporalmente el portal en localhost:5089 con credenciales efímeras, comprueba autenticación, antiforgery, listado, formularios y validación de campos vacíos, y lo apaga al terminar. Solamente consulta Oracle; no envía altas válidas ni modificaciones/bajas.

Las pruebas incluyen los controladores de estaciones/equipos y reglas de validación. El smoke HTTP puede recibir `EQUIPMENT_SMOKE_STATIONS` como objeto JSON de módulo a ID de estación para recorrer registros representativos de los siete módulos. Los flujos de escritura se prueban en memoria, no contra producción; falta validar persistencia sobre una copia aislada antes de uso operativo. No se ha desplegado un servicio público ni se han creado cuentas operativas del portal.

Referencias: [ODP.NET Core oficial](https://www.nuget.org/packages/Oracle.ManagedDataAccess.Core/23.26.301), [antiforgery de ASP.NET Core](https://learn.microsoft.com/aspnet/core/security/anti-request-forgery?view=aspnetcore-8.0).
