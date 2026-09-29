# Decoders: despliegue controlado

## Archivos

Desplegar juntos `mycloud_all_timescale.py`, `gs300_catalog.py`,
`telemetry_decoders.py` y `decoder_profiles.json`; no basta con reemplazar el script principal.
Ejecutar antes `python -m unittest test_gs300_config test_telemetry_decoders -v`.

## Configuración necesaria

- Configurar `ORACLE_CATALOG_USER`, `ORACLE_CATALOG_PASSWORD` y
  `ORACLE_CATALOG_DSN` mediante secretos del servicio (véase GS300_CORRECCION.md).
- `decoder_profiles.json` incluye SO06: 12 columnas textuales, batería 0011 y
  panel 0012, sin reescalar decimales. Para otros perfiles configurar
  `DECODER_PROFILES_PATH`, indexado por IdAsignado. El archivo externo prevalece
  sobre el incorporado para las estaciones que define. No activar el ejemplo.
- `ott_order`: lista de NumeroSensor por orden de bloque OTT. La cantidad,
  intervalo y cobertura deben coincidir con el catálogo. No se eligen sensores
  por plausibilidad de valores. Sin perfil, OTT se rechaza sin escribir lecturas.
- `tables`: tabla textual → lista ordenada de NumeroSensor. Una fila sin número
  de tabla usa `default`. SMN, SMN_ver2 y Vaisala requieren correspondencia
  explícita; no se adivina el grupo por cantidad de columnas.
- `channels`: alias de código textual → NumeroSensor para GASIR/CILA. Sin alias
  se usa el código rellenado con ceros a cuatro caracteres; si no existe en el
  catálogo se rechaza el mensaje completo.

## Cambios y límites

Se conserva el decimal de texto, se preservan columnas vacías como faltantes,
se reconocen canales alfanuméricos, se rechaza OTT truncado y se separa
SMN_ver2 de GS300. El código DOMSAT se guarda desde `type`. El calendario usa
primera transmisión e intervalo, no rango. La alineación general soporta
periodos mayores de una hora y fraccionarios.

El parser OTT acepta únicamente el envoltorio OTA observado. Otros envoltorios,
el catálogo OTT con mensajes bB, SMM y tipos desconocidos requieren revisión;
no se envían a GS300 automáticamente. GS300 conserva su prefijo temporal
pendiente de validación; no se promete corregir fechas históricas.

SHEF/CILA conserva el instante calculado con el desplazamiento y el intervalo
del bloque, sin volver a redondearlo al periodo del catálogo. GASIR conserva
su alineación a intervalo, pendiente de contrastar contra el programa de la
estación cuando exista un desplazamiento no expresado en el mensaje.

Antes de activar una estación, reproducir mensajes conocidos, verificar canal,
unidad, tiempo y total de muestras. Los casos OTT con nueve bloques/diez
sensores o dos horas de muestras/rango de una hora no quedan habilitados por
este cambio: requieren corregir/confirmar el perfil o catálogo primero.

En la reproducción real E8903378 también hay dos bytes posteriores a los nueve
bloques. El código anterior los ignoraba. No se da por hecho que sean relleno
ni se certifica su checksum: el parser estricto rechaza esa cola hasta validar
su especificación. Por ello esta rama NO habilita todavía esa estación OTT.

## Operación

### Corrección SMN_ver2 del 29/09/2026

MX03 (SMN) también incluye perfil explícito: tabla 2 → 0001–0009 cada
10 minutos; tabla 4 → 0010–0011 cada hora. Los decimales de ingeniería se
conservan incluso cuando PUNTODECIMAL=0 en el catálogo. `repair_mx03.py`
reconstruye los once sensores de los últimos siete días desde mensajes crudos,
con simulación predeterminada, respaldo exclusivo y `--apply` explícito.
No se ejecuta automáticamente en Render. Prueba: `test_repair_mx03`.

Perfiles incorporados: SO06, HI03, NY02, NY03 (12 columnas); MC38 (tabla 2:
11 sensores; tabla 4: batería 0012 y panel 0013). QR15 se habilita solo para
batería 0010, columna 11; `null` conserva sin asignar las columnas no verificadas.
CS05 y MC09 no tienen tramas disponibles para certificar su perfil y siguen
requiriendo configuración explícita. No copiar el perfil SO06 a todas.

Los registros textuales mantienen sus valores y fechas, sin escala adicional,
y actualizan `ULTIMAS_MEDICIONES`. Las firmas incompatibles se rechazan antes
de entrar al decodificador. Incluir `decoder_profiles.json` en el despliegue;
si existe `DECODER_PROFILES_PATH`, sus entradas prevalecen por estación.

Reparación manual de voltajes: `python repair_so06_voltages.py --station HI03
--backup /ruta/nueva/HI03-voltage-backup-fecha.json` simula; `--apply` escribe.
El nombre del script se conserva por compatibilidad; acepta los seis perfiles
verificados. No se ejecuta al arrancar Render. Solo cubre últimos siete días,
con respaldo previo, coincidencia temporal exacta y rechazo de contradicciones.
No modifica voltajes positivos diferentes del original ni interpola faltantes.
Los respaldos no se incluyen en Git. QR15 no repara los dos paneles ambiguos.

Pruebas: `python -m unittest test_gs300_config test_telemetry_decoders test_repair_so06 -v`.

### Notas de la preparación inicial (28/09/2026)

No se inició la ingesta ni se reprocesó el histórico durante la preparación.
El arranque actual del programa ejecuta sincronización/revalidación: no importar
el módulo principal para pruebas de solo lectura. No hacer recuperación masiva
hasta validar perfiles y respaldar las series afectadas. Conservar la versión
previa como referencia, pero no restaurar su decodificación heurística para
solucionar un rechazo de configuración.
