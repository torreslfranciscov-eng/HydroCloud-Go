# Decoders: despliegue controlado

## Archivos

Desplegar juntos `mycloud_all_timescale.py`, `gs300_catalog.py` y
`telemetry_decoders.py`; no basta con reemplazar el script principal.
Ejecutar antes `python -m unittest test_gs300_config test_telemetry_decoders -v`.

## Configuración necesaria

- Configurar `ORACLE_CATALOG_USER`, `ORACLE_CATALOG_PASSWORD` y
  `ORACLE_CATALOG_DSN` mediante secretos del servicio (véase GS300_CORRECCION.md).
- Configurar `DECODER_PROFILES_PATH` apuntando a JSON local revisado por estación,
  indexado por IdAsignado. No desplegar el ejemplo como configuración real.
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

No se inició la ingesta ni se reprocesó el histórico durante la preparación.
El arranque actual del programa ejecuta sincronización/revalidación: no importar
el módulo principal para pruebas de solo lectura. No hacer recuperación masiva
hasta validar perfiles y respaldar las series afectadas. Conservar la versión
previa como referencia, pero no restaurar su decodificación heurística para
solucionar un rechazo de configuración.
