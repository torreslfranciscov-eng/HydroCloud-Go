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
