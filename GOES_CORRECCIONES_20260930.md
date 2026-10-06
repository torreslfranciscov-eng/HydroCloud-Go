# Correcciones DatosGOES — 30/09/2026

Se auditaron 741 registros activos GOES contra hasta doce mensajes LRGS almacenados por DCP, últimos siete días. Se aplicaron 16 cambios de decoder y tres de canal primario en 19 registros. Verificados desde una nueva conexión.

| Clave | Estación | Decoder anterior → nuevo | Canal anterior → nuevo |
|---|---|---|---|
| BOMBA07016 | BOMBANA | OTTBinario → GS300 | Sin cambio |
| SITAL07000 | SITALA | OTTBinario → GS300 | Sin cambio |
| FARGO07012 | FINCA ARGOVIA | OTTBinario → GS300 | Sin cambio |
| HUIXT07077 | HUIXTLA | OTTBinario → GS300 | Sin cambio |
| AGRAN07000 | ARROYO GRANDE | OTTBinario → GS300 | Sin cambio |
| LFLOR07102 | LAS FLORES | OTTBinario → GS300 | Sin cambio |
| HUIMA27XXX | HUIMANGUILLO (INIFAP) | OTTBinario → GS300 | Sin cambio |
| GONZTAM001 | GONZALEZ TAM | OTTBinario → GS300 | Sin cambio |
| 000000LG13 | MARKAZUZA | GS300 → OTTBinario | Sin cambio |
| 0000000G03 | PLATANAR | OTTBinario → GS300 | Sin cambio |
| 0000000G08 | BOCA DEL CERRO | OTTBinario → GS300 | Sin cambio |
| CHACCHIA05 | CHACAMAX | OTTBinario → GS300 | Sin cambio |
| CHENCHIA06 | CHALCHIHUITÁN | Sin cambio | 55 → 145 |
| CUXTCHIA09 | CUXTEPEQUES | Sin cambio | 55 → 95 |
| STODCHIA22 | SANTO DOMINGO | Sin cambio | 55 → 95 |
| MOTOZ07119 | MOTOZINTLA | OTTBinario → GS300 | Sin cambio |
| LENCR07XXX | LA ENCRUCIJADA | OTTBinario → GS300 | Sin cambio |
| LOMAPUE004 | PUENTE PALOMAS (H1) | OTTBinario → GS300 | Sin cambio |
| GFLAGUNA04 | ESTACION LAGUNA | OTTBinario → GS300 | Sin cambio |

No se modificaron sensores, orden, unidades, escalas, horarios, velocidad, satélite ni canales de alarma.

El decoder identifica el formato de la trama: no certifica que las posiciones del catálogo de sensores coincidan. Las discrepancias de cantidad siguen bloqueando la ingesta para evitar mediciones falsas. No se reprocesó histórico en esta operación.

Se conservaron variantes textuales compatibles; mensajes ambiguos, DCP duplicados o evidencia insuficiente no provocaron modificaciones. Respaldo privado local: `goes-lrgs-backup-applied-20260930.json`; excluido de Git.

## Revisión adicional de ingesta

- Auditoría ampliada a todas las tramas disponibles de las últimas 24 horas. Detalle por estación: `INGESTA_AUDITORIA_20260930.md`. Compatibilidad de formato y cantidad no certifica calibración física ni igualdad de todas las lecturas almacenadas.
- ZAPALUTA (`ZAPAL07099`): etiqueta OTTBinario → GS300 por evidencia B1 consistente. Respaldo `goes-lrgs-backup-applied-final-20260930.json`. No se cambiaron sensores: aún debe resolverse la discrepancia de cantidad.
- Validación de voltajes negativos unificada para SMN/VAISALA y GS/CILA: valor numérico inválido pasa a NULL, VALIDO=0; el valor recibido se conserva en descripción y trama. No se transforma a positivo ni se cambia escala de valores textuales.
- GS/CILA: los canales con identificador explícito en Sensor pueden guardarse independientemente de canales extra no configurados. Se reportan mensajes parciales; no se asignan sensores por posición ni plausibilidad. Se verifica periodo transportado incluso con una sola muestra. Se actualiza ULTIMAS_MEDICIONES en la misma transacción con las lecturas válidas.
- Histórico de panel solar de CH26, CH29, PU03, SO07 y SO09: 48 filas contrastadas con catálogo y trama marcadas inválidas, comprobadas desde nueva conexión. Cinco resúmenes negativos sustituidos por la última lectura válida disponible. Respaldo privado `smn-panel-voltage-backup-applied-20260930.json`.
- Otros 475 negativos antiguos de esas cinco estaciones no se modificaron: no hubo coincidencia unívoca con las tramas revisadas. No se reconstruyeron agregados históricos.
- No se ha demostrado que todas las estaciones estén correctas. Se mantienen pendientes las discrepancias de sensores/canales, formatos no identificados, relojes internos y mensajes incompletos; no se inventaron parámetros para superar validaciones.

## Reparación de baterías SMN — 01/10/2026

- Se cruzaron siete días de `DCP_HEADERS` y `DCP_DATOS` por DCP, timestamp y primera columna de la tabla 4. Para certificar el canal se exigió una sola serie de batería y al menos tres coincidencias recientes ya guardadas correctamente; no se asignaron sensores por plausibilidad.
- En 114 estaciones certificadas se confirmaron 10,450 actualizaciones y 2,603 inserciones (13,053 muestras). Todas se verificaron desde una conexión nueva: cero faltantes, duplicados o diferencias. Respaldo privado `smn-battery-backup-applied3-20261001.json`.
- GR55, ZAP3DISI04 y ZC02 quedaron fuera por no tener tres coincidencias recientes. GR07 quedó fuera porque la supuesta primera columna alcanzó 1,208 y corresponde a un orden/canal que requiere revisión, no a batería. PU09 quedó fuera por DCP inválido (`c`).
- Se conservaron 191 negativos de 19 estaciones certificadas porque no tienen correspondencia unívoca con las tramas disponibles; no se interpolaron ni se transformaron a positivo.
- Tres resúmenes legados (`Voltaje de batería`) se corrigieron usando la fila válida de `DCP_DATOS` del mismo DCP, sensor y timestamp: MX43, -6266.5 → 12.7 V; BC06, -2145.6 → 12.9 V; MO02, -7060.8 → 13.2 V. Respaldos privados `mx43-legacy-battery-summary-backup-applied-20261001.json` y `smn-battery-summary-backup-applied2-20261001.json`.
- Dos intentos previos no persistieron cambios: uno fue revertido por interbloqueo de Oracle y otro se interrumpió durante espera de bloqueos; ambos se comprobaron con cero filas confirmadas antes del intento final.

## Reconciliación del catálogo GS300 — 01/10/2026

- Se compararon todas las tramas B1 de las últimas 24 horas con `HYDROCLOUD.DATOSGOES` y `HYDROCLOUD.SENSOR`. Se exigieron al menos tres tramas estables, coincidencia exacta de longitud y correspondencia física inequívoca antes de modificar Oracle.
- Se corrigieron 15 catálogos GS300: MMDETAB015, MOJOTAB012, ZACATAB006, SALCUA061Q, ZANAP27117, TAMUSLP024, TLAHUA033Q, CARTER021Q, MADETAM034, PALMAS048Q, ARCOCHIA11, CHAPTAB001, QUIOCHIA19, MACUTAB017 y PLATANAR (`0000000G03`).
- Los cambios incluyeron rangos de transmisión, períodos, orden, desactivación de canales ausentes y la inserción comprobada del sensor `2001` de batería en PALMAS048Q. Cada tanda se prevalidó, respaldó y confirmó desde una conexión nueva.
- MMDETAB015 quedó con rango de 120 minutos, batería `0901` cada 10 minutos y temperatura `0905` inactiva. La verificación final da 72 palabras recibidas y 72 exigidas, sin conflictos.
- El decoder GS300 ya conserva los sensores calculados, pero no les asigna posiciones físicas. Esto eliminó rechazos falsos sin desactivar esos sensores en Oracle. Las nueve pruebas de configuración pasan.
- La auditoría llegó de 365 a 395 estaciones transmisoras con al menos una trama compatible. El denominador varía con la ventana móvil de 24 horas; el detalle vigente y los GS300 pendientes están en `GS300_CATALOGO_REVISION_20261001.md`. No se aplicaron configuraciones ambiguas ni se inventaron sensores.
- No se reprocesó histórico en esta operación.
- YC05 (DZILAM, DCP `15CC1620`) se corrigió de `GS300` a `SMN`: 20 tramas recientes son registros de texto y ninguna contiene firma B1. El decoder ya coincide; queda pendiente catalogar la segunda columna de presión porque el wire transporta 12 columnas y `SENSOR` contiene 11.
- PLATANAR (DCP `15B27202`) quedó con rango de 120 minutos y cinco sensores activos en el orden real del wire: `0001` nivel (12 muestras/10 min), `0002` precipitación (12/10), `0900` batería (2/60), `0901` estado RLS (12/10) y `0902` señal RLS (12/10, un decimal). Se desactivaron y ocultaron `0017` y `0018`. Las 18 tramas de 50 palabras produjeron 300 comparaciones solapadas sin discrepancias y, tras el cambio, 18/18 validan contra el catálogo.
- EMILIANO ZAPATA CHABLÉ (`0000000G07`, DCP `15B2C18C`) quedó con rango de 120 minutos. `0020` Nivel Recipiente y `0021` Estado del pluvio cambiaron de período 60 a 10 minutos; los demás parámetros ya coincidían. Las 18 transmisiones únicas de 62 palabras produjeron 372 comparaciones solapadas sin discrepancias y, tras el cambio, 18/18 validan contra el catálogo.
- Se reconciliaron siete catálogos GS300 adicionales, cada uno con respaldo y verificación posterior: GONZALEZ (`000000GR02`, 52 palabras), GUACAMAYAS (`GUACAXXXXX`, 146), SITALA (`SITAL07000`, 122), EL ESCALON (`EESCA07186`, 122), CHACAMAX (`CHACCHIA05`, 86), TONALA (`TONAL07168`, 50) y SILTEPEC (`SILTCHIA23`, 98). Se corrigieron únicamente rangos, períodos, órdenes o estados activos demostrados por la longitud, la escala física y entre 175 y 730 valores solapados sin discrepancias por estación.
- BOCA DEL CERRO (`0000000G08`, DCP `15B2D2FA`) se reconcilió con la configuración física proporcionada por el usuario: `0001`, `0002`, `0003`, `0004`, `0005`, `0009`, `0010`, `0011`, `0012` y `0905` Estado RLS nivel. Se activó `0001`, se corrigieron cuatro períodos a 10 minutos y se desactivaron/ocultaron `0016`, `0906` y `0907`. Las 18 tramas de 90 palabras produjeron 540 solapamientos sin discrepancias y validan 18/18 después del cambio.
- EL PORTILLO (`0000000G21`, DCP `15C8131A`) quedó con rango de 120 minutos y sólo los tres sensores confirmados por la captura: nivel, batería y precipitación. Sus 38 palabras se dividen en 26 mediciones y un sufijo de 12 estados auxiliares `0/1`; el decoder ignora ese sufijo exclusivamente para esta clave y rechaza otros valores o longitudes. La auditoría posterior valida 17/17 tramas.
- CORRALES (`000000LG16`, DCP `15C7C3E0`) conserva sus nueve sensores confirmados por la captura y sus 19 palabras de medición. Las dos palabras finales son diagnósticos internos (estado `0` y temperatura interna cruda `291–336`); el decoder las ignora únicamente para esta clave y dentro de rangos estrictos. La auditoría posterior desde una conexión nueva a Oracle valida 18/18 tramas.
