# Decoders: despliegue controlado

## Archivos

Desplegar juntos `mycloud_all_timescale.py`, `gs300_catalog.py`,
`telemetry_decoders.py` y `decoder_profiles.json`; no basta con reemplazar el script principal.
Ejecutar antes `python -m unittest test_gs300_config test_telemetry_decoders -v`.

## Configuración necesaria

### SMN: configuración desde Sensor (29/09/2026)

Para estaciones cuyo DatosGOES.Decodificador es SMN, la fuente de asignación
es Sensor → Estacion/TipoSensor/UnidadMedida. Se cargan Orden, PeriodoMuestra,
unidad y EsCalculada, antes omitidos. La tabla 2 usa canales no calculados de
10 minutos; tabla 4 usa batería y panel de 60 minutos, en V. Ambos grupos se
ordenan por Sensor.Orden, no por NumeroSensor ni por plausibilidad del valor.
Se exige cantidad exacta, órdenes únicos y unidades presentes. No se necesita
agregar JSON por estación para esas tablas; el JSON no prevalece sobre Sensor
en SMN. Tablas adicionales o discrepancias se rechazan, sin truncar columnas.

SMN_ver2, Vaisala y OTT conservan las excepciones explícitas existentes: no se
extrapola la estructura de tablas SMN a protocolos diferentes. El texto no se
escala nuevamente por PuntoDecimal. Cada mensaje textual completo y su resumen
se guardan en una transacción; una excepción revierte todas sus filas.

Esta corrección de ingesta no reescribe automáticamente datos históricos.

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

### GS300: orden y calidad de voltajes (29/09/2026)

Para GS300 se usa Sensor.Orden, único y obligatorio, para construir posiciones;
NumeroSensor identifica el canal, no su posición en la trama. Se mantienen
RangoTransmision/PeriodoMuestra para calcular cuántas muestras lleva cada canal.
Radiocomunicación: batería 2001 en posición 12, temperatura 2002 en 13
(índices desde cero); antes se leía la batería en 84.

El parser estricto reconoce `///` como faltante sin desplazar palabras; no
convierte automáticamente `\u0060@@` (-131072) en faltante universal. Los voltajes de
batería/panel negativos o fuera del rango configurado se guardan NULL, inválidos,
con el valor rechazado en DESCRIPCION y el mensaje original en DCP_HEADERS.
No se convierten a cero. Otras variables conservan valores negativos legítimos.
Referencia: https://www.ott.com/download/sutron-x-link-manual/ (sección 16.3).

ULTIMAS_MEDICIONES conserva su estructura histórica por variable, no por sensor:
ahora solo acepta valores válidos y no nulos. Es un resumen de último dato válido,
no un diagnóstico del estado actual. DCP_DATOS sigue distinguiendo SENSOR_ID.
No se incluye un cambio de esquema ni del portal en esta publicación.

`repair_gs300_voltages.py` permite simulación y reparación manual con respaldo
de los canales de voltaje comprobados de RADIOCO019 y RIOFTAM005. No se ejecuta
al arrancar el servicio y no altera canales/estaciones no incluidos en su lista.

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
# OTT: corrección basada en IGS LRGS C# (30/09/2026)

Referencia aportada: `LRGS_VS15_24062017_mod.rar`,
`igs.lrgs/Igs.Lrgs/DcpMessageParser.cs` y `NativeDcpMessage.cs`.
No se incluye el archivo RAR en el despliegue.

- Fecha interna: Int32 little-endian, segundos desde 2000-01-01; no se sustituye por recepción.
- Bloques: intervalo y cantidad Int16; muestras Int16 en orden antiguo a reciente.
- Intervalo cero: cada valor lleva fecha Int32 propia.
- Banderas inferiores a -32700: NULL, inválidas, con código original en descripción.
- Canales del catálogo: sensores no calculados por Sensor.Orden; cantidad y periodo deben coincidir.
- Voltajes negativos/fuera de límites: NULL e inválidos; no alimentan últimas mediciones.
- Cabeceras OTA con prefijo comilla, acento grave, b o espacio.
- Reloj interno fuera de recepción -7 días / +5 minutos: rechazar sin inventar fechas.
- Mensajes truncados o colas desconocidas: rechazar íntegros; no copiar la aceptación parcial del C#.

Validación real sin escrituras: Acueducto Chapala–Guadalajara, sensor 0011,
14.08 V a 2026-09-30 16:00 UTC. El Arenal: bandera -32758 y reloj en 2007,
rechazado. Agua Salada: cola no interpretada, pendiente. No se certifican todas
las variantes OTT. La tabla Sensor actual no contiene las dos ecuaciones lineales
opcionales del C#; no se inventan calibraciones. No se reparó histórico ni se desplegó
como parte de esta validación local.

Publicación posterior: corrección enviada a `main` en `b7fe16a`.
Reparación autorizada posterior: `repair_ott_voltage.py` reconstruyó la batería
0011 de Acueducto (15B94430), ventana de siete días: 85 actualizaciones y 49
inserciones; 134 muestras verificadas desde otra conexión. Dos filas antiguas
sin evidencia se conservaron. Respaldo local privado:
`LG44-voltage-backup-ott-applied-20260930.json` (ignorado por Git).
No se repararon otros sensores, otras estaciones ni agregados históricos.
El envío a GitLab no certifica por sí mismo que Render haya arrancado esa versión.

Ampliación del 30/09: La Purísima (126), Barberena (142), Gómez Farías (142),
Puente Tonalá (142) y Soto la Marina (143): 695 muestras verificadas desde una
conexión nueva, 495 actualizaciones y 200 inserciones. En estas cinco estaciones
no quedaron filas antiguas sin correspondencia dentro de las ventanas revisadas.
Los respaldos individuales `*-voltage-backup-ott-applied-20260930.json` permanecen
locales y fuera de Git. Total con Acueducto: 829 muestras de batería reconstruidas.
Antes de estas reparaciones adicionales se verificaron lecturas nuevas guardadas
por la ingesta que coincidían con las tramas: La Purísima 14.39 V (19 UTC),
Barberena 13.39 V (18 UTC), Gómez Farías 13.60 V (18 UTC), Puente Tonalá 13.46 V
(18 UTC) y Soto la Marina 13.60 V (19 UTC). No se obtuvo el estado del panel Render.
