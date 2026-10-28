# Revisión del catálogo y decoder GS300 — 2026-10-01

Fuente: Oracle `HYDROCLOUD.SENSOR`/`DATOSGOES` y todas las tramas de las últimas 24 horas.
Sólo se aplicaron cambios respaldados por al menos tres tramas estables y una correspondencia física inequívoca.

## Resultado

- Estaciones o decoders reconciliados: 33.
- Estaciones con al menos una trama compatible después de la corrección: 410 de 472 transmisoras.
- GS300 pendientes descritas abajo: 26.
- Los sensores calculados ya no consumen posiciones físicas del wire.

## Corregidas

`MMDETAB015`, `MOJOTAB012`, `ZACATAB006`, `SALCUA061Q`, `ZANAP27117`, `TAMUSLP024`, `TLAHUA033Q`, `CARTER021Q`, `MADETAM034`, `PALMAS048Q`, `ARCOCHIA11`, `CHAPTAB001`, `QUIOCHIA19`, `MACUTAB017`, `0000000G03`, `0000000G07`, `0000000G08`, `0000000G21`, `000000LG16`, `000000GR02`, `GUACAXXXXX`, `SITAL07000`, `EESCA07186`, `CHACCHIA05`, `TONAL07168`, `SILTCHIA23`, `YC05`, `00000CFE05`, `00000CFE06`, `AGRAN07000`, `BOMBA07016`, `CAZLVER018`, `CFE0000043`.

## PLATANAR — catálogo reconciliado

- Clave: `0000000G03`; DCP: `15B27202`; decoder: `GS300`.
- Las 18 tramas revisadas tienen firma `bB1` y 50 palabras; el decoder coincide.
- Rango corregido de 60 a 120 minutos.
- Distribución comprobada por 300 valores solapados entre transmisiones, sin discrepancias: nivel 12 × 10 min, precipitación 12 × 10 min, batería 2 × 60 min, estado RLS 12 × 10 min y señal RLS 12 × 10 min.
- Sensores activos finales, en orden: `0001`, `0002`, `0900`, `0901`, `0902`. Los antiguos `0017` y `0018`, ausentes de la trama, quedaron inactivos y ocultos.
- Verificación posterior en Oracle: 18/18 tramas compatibles; catálogo esperado 50 palabras y wire observado 50.

## EMILIANO ZAPATA CHABLÉ — catálogo reconciliado

- Clave: `0000000G07`; DCP: `15B2C18C`; decoder: `GS300`.
- Las 18 transmisiones únicas revisadas tienen firma `bB1` y 62 palabras; el decoder coincide.
- Rango corregido de 60 a 120 minutos; `0020` Nivel Recipiente y `0021` Estado del pluvio se corrigieron de 60 a 10 minutos.
- Distribución comprobada: nivel 12 × 10 min; siete sensores 2 × 60 min cada uno; precipitación, nivel de recipiente y estado del pluvio 12 × 10 min cada uno.
- Las 372 comparaciones solapadas entre transmisiones coinciden, sin discrepancias.
- Verificación posterior en Oracle: 18/18 tramas compatibles; catálogo esperado 62 palabras y wire observado 62.

## BOCA DEL CERRO — catálogo reconciliado

- Clave: `0000000G08`; DCP: `15B2D2FA`; decoder: `GS300`.
- La captura de configuración confirmó diez canales físicos: `0001`, `0002`, `0003`, `0004`, `0005`, `0009`, `0010`, `0011`, `0012` y `0905` Estado RLS nivel.
- Se activó y mostró `0001`; `0004`, `0005`, `0009` y `0010` cambiaron de 60 a 10 minutos; `0016`, `0906` y `0907` quedaron inactivos y ocultos.
- Las 18 tramas tienen 90 palabras; las 540 comparaciones solapadas coinciden sin discrepancias.
- Verificación posterior en Oracle: 18/18 tramas compatibles; catálogo esperado 90 palabras y wire observado 90.

## EL PORTILLO — catálogo y sufijo auxiliar reconciliados

- Clave: `0000000G21`; DCP: `15C8131A`; decoder: `GS300`.
- La captura confirmó únicamente `0001` Nivel, `0002` Batería y `0007` Precipitación.
- Rango corregido de 60 a 120 minutos: 12 palabras de nivel, 2 de batería y 12 de precipitación.
- El programa de la estación agrega 12 estados auxiliares constantes `0/1`; el decoder los ignora sólo para esta clave y rechaza cualquier otra longitud o valor.
- Verificación posterior: 17/17 tramas compatibles; 26 palabras de sensores más 12 auxiliares.

## CORRALES — diagnósticos auxiliares identificados

- Clave: `000000LG16`; DCP: `15C7C3E0`; decoder: `GS300`.
- La captura confirmó que los nueve sensores configurados en Oracle son los correctos; ocupan 19 palabras.
- La captura operativa del 2026-10-02 14:57 confirma 24/24 transmisiones estables y los sensores `0010`, `0005`, `0011`, `0001`, `0002`, `0003`, `0009`, `0004` y `0012`.
- Los nueve sensores aparecen funcionando; `0001` Nivel de agua es el único marcado con datos inválidos, lo cual es una condición de medición y no una falla del decoder.
- El transmisor agrega dos diagnósticos no visibles: estado `0` y temperatura interna cruda `291–336`.
- El decoder ignora esas dos palabras sólo para esta clave y sólo dentro de rangos restringidos; cualquier otra longitud o valor se rechaza.
- Verificación posterior desde una conexión nueva a Oracle: 18/18 tramas compatibles.

## EMILIANO ZAPATA CFE — canales ausentes como indefinidos

- Clave: `00000CFE05`; DCP: `E890B56C`; decoder: `GS300`.
- Las capturas confirman los doce sensores: `0001`/`0002` cada 10 minutos y `0003`–`0012` cada 60 minutos.
- El wire trae 38 palabras frente a 44 del catálogo; faltan las seis posiciones finales correspondientes a dos muestras de `0010`, `0011` y `0012`.
- El decoder conserva esos sensores y completa exclusivamente esas posiciones con valor indefinido (`None`/NULL); no inventa ni repite mediciones.
- La excepción sólo aplica a esta clave y exige exactamente 38 palabras; cualquier otra longitud continúa rechazada.
- No se modificó Oracle: el catálogo confirmado permanece intacto.

## PRESA PEÑITAS (PROVISIONAL) — configuración de Presa Peñitas

- Clave: `00000CFE06`; DCP: `E890C3FC`; decoder: `GS300`.
- Se copió en Oracle la configuración activa de los 16 sensores de Presa Peñitas `CFE0000025`, conservando tipos, períodos, orden, decimales, unidades y límites.
- La plantilla completa ocupa 82 palabras: tres bloques iniciales de 12, once canales horarios de dos palabras y dos bloques finales de 12.
- Las tramas de esta estación son estables en 38 palabras y terminan después del primer canal horario (`0004`).
- El decoder conserva las primeras 38 posiciones y agrega las 44 finales como indefinidas (`None`/NULL), sin fabricar ceros ni repetir valores.
- La excepción sólo aplica a esta clave y exige exactamente 38 palabras.

## Correcciones adicionales de esta ronda

| Clave | Estación | Corrección comprobada | Resultado |
|---|---|---|---|
| `AGRAN07000` | ARROYO GRANDE | Rango 60 → 120 min; se intercambió el orden de dirección/velocidad del viento y `0011` quedó inactivo. | 126/126 palabras; diez bloques de 12 y tres canales horarios de 2. |
| `BOMBA07016` | BOMBANA | Rango 60 → 120 min; `0004`, `0005`, `0011`, `0014` y `0015` quedaron inactivos, siguiendo el layout comprobado de JONUTA. | 110/110 palabras; 550 solapamientos sin fallas. |
| `CAZLVER018` | CARRIZAL | `0015` se corrigió a `0020` Estado del radar y su período cambió 60 → 10 min; dos temperaturas internas finales se tratan como auxiliares. | 28 palabras de sensores + 2 auxiliares; 150 solapamientos sin fallas. |
| `CFE0000043` | Ixcamilpa | Se habilitó exclusivamente para esta clave la variante pseudobinaria con marcador inicial y sin firma `B1`; el catálogo de nueve sensores no cambió. | 18/18 tramas; 38/38 palabras. |
| `000000GR02` | GONZALEZ | Se desactivaron `0016`, `0910` y `0905`, ausentes del wire. | 52/52 palabras; 312 solapamientos sin fallas. |
| `GUACAXXXXX` | GUACAMAYAS | `0014` y `0015`: período 60 → 10 min. | 146/146; 730 solapamientos sin fallas. |
| `SITAL07000` | SITALA | Rango 60 → 120 min; se desactivaron `0021`, `0022`, `0023`. | 122/122; 610 solapamientos sin fallas. |
| `EESCA07186` | EL ESCALON | Rango 60 → 120 min; se desactivaron `0021`, `0022`, `0023`. | 122/122; 610 solapamientos sin fallas. |
| `CHACCHIA05` | CHACAMAX | Rango 60 → 120 min; batería a 60 min y orden final corregido. | 86/86; 430 solapamientos sin fallas. |
| `TONAL07168` | TONALA | Rango 60 → 120 min; diez sensores ausentes quedaron inactivos. | 50/50; 175 solapamientos sin fallas. |
| `SILTCHIA23` | SILTEPEC | Rango 60 → 120 min; `0903` y `0904` quedaron inactivos. | 98/98; 490 solapamientos sin fallas. |

## YC05 — decoder corregido, catálogo de sensores pendiente

- DCP: `15CC1620`.
- Decoder anterior: `GS300`; decoder actual en Oracle: `SMN`.
- Trama observada: texto SMN en todas las transmisiones; no contiene firma `bB1`.
- ¿Decoder coincide con la trama?: **Sí**, después de la corrección.
- Pendiente: cada registro transporta 12 columnas y `SENSOR` sólo configura 11; aparecen dos columnas de presión atmosférica y sólo una está catalogada.

## Pendientes, estación por estación

### COTAVER010 — COTAXTLA (H1)

- DCP: `1A509622`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 19; familia `pseudobinary_b` × 19.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **19/19** tramas.
- Wire: 54 (19 tramas); catálogo esperado: 23.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0003` Precipitación: orden 2, período 10.0 min, decimales 1, calculado 0.
  - `0004` Intensidad de precipitación: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0015` Estado del radar: orden 4, período 60.0 min, decimales 0, calculado 0.
  - `0016` Estado del pluvio: orden 5, período 60.0 min, decimales 0, calculado 0.
  - `0017` Nivel Recipiente: orden 6, período 60.0 min, decimales 1, calculado 0.
  - `0018` Voltaje de batería: orden 7, período 60.0 min, decimales 2, calculado 0.
  - `0019` Voltaje de batería: orden 8, período 60.0 min, decimales 2, calculado 0.

### ESCODISI05 — ESCOTADURA 4

- DCP: `1A53044E`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 12, `bB$` × 1; familia `pseudobinary_b` × 12, `unknown` × 1.
- ¿Decoder coincide con la trama?: **Parcial (12/13)**.
- Payload GS300 estructuralmente decodificable: **8/13** tramas.
- Wire: 44 (8 tramas); catálogo esperado: 32.
- Diagnóstico: El wire contiene 12 palabras adicionales (dos bloques) sin sensor inequívoco.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0002` Velocidad del agua: orden 2, período 10.0 min, decimales 3, calculado 0.
  - `0005` Voltaje de batería: orden 7, período 60.0 min, decimales 2, calculado 0.
  - `0006` Temperatura Interna: orden 8, período 60.0 min, decimales 2, calculado 0.
  - `0007` Estado: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0008` Señal de ruido: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0009` Señal de ruido: orden 11, período 10.0 min, decimales 0, calculado 0.

### FARGO07012 — FINCA ARGOVIA

- DCP: `15F1B3CE`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 110 (17 tramas); catálogo esperado: 75.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0004` Humedad del suelo: orden 4, período 10.0 min, decimales 3, calculado 0.
  - `0005` Temperatura: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 12, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 13, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 14, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 15, período 60.0 min, decimales 2, calculado 0.

### FCOITAB004 — FRANCISCO I. MADERO

- DCP: `1A53C150`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 9; familia `pseudobinary_b` × 9.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **9/9** tramas.
- Wire: 56 (9 tramas); catálogo esperado: 55.
- Diagnóstico: La palabra final es temperatura interna (~27 °C), ausente del catálogo.
- Sensores activos:

  - `0031` Precipitación: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0036` Temperatura: orden 2, período 10.0 min, decimales 1, calculado 0.
  - `0041` Humedad relativa: orden 3, período 10.0 min, decimales 0, calculado 0.
  - `0046` Velocidad del viento: orden 4, período 10.0 min, decimales 1, calculado 0.
  - `0047` Dirección del viento: orden 5, período 10.0 min, decimales 0, calculado 0.
  - `0048` Velocidad de ráfaga: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0049` Dirección de ráfaga: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0901` Voltaje de batería: orden 10, período 60.0 min, decimales 2, calculado 0.
  - `0902` Punto de rocío: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0903` Precipitación acumulada: orden 12, período 10.0 min, decimales 1, calculado 0.

### GFLAGUNA04 — ESTACION LAGUNA

- DCP: `15F492E2`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 106 (17 tramas); catálogo esperado: 39.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0002` Nivel de agua: orden 2, período 10.0 min, decimales 2, calculado 0.
  - `0004` Precipitación: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0005` Intensidad de precipitación: orden 4, período 10.0 min, decimales 1, calculado 0.
  - `0006` Temperatura: orden 5, período 60.0 min, decimales 2, calculado 0.
  - `0007` Humedad relativa: orden 6, período 60.0 min, decimales 2, calculado 0.
  - `0008` Punto de rocío: orden 7, período 60.0 min, decimales 2, calculado 0.
  - `0009` Presión Atmosférica: orden 8, período 60.0 min, decimales 1, calculado 0.
  - `0010` Radiación Solar: orden 9, período 60.0 min, decimales 1, calculado 0.
  - `0011` Velocidad del viento: orden 10, período 60.0 min, decimales 1, calculado 0.
  - `0012` Dirección del viento: orden 11, período 60.0 min, decimales 1, calculado 0.
  - `0013` Velocidad de ráfaga: orden 12, período 60.0 min, decimales 1, calculado 0.
  - `0014` Dirección de ráfaga: orden 13, período 60.0 min, decimales 1, calculado 0.
  - `0015` Señal de ruido: orden 14, período 60.0 min, decimales 1, calculado 0.
  - `0016` Estado RLS: orden 15, período 60.0 min, decimales 0, calculado 0.
  - `0017` Estado burbujeo: orden 16, período 60.0 min, decimales 0, calculado 0.
  - `0020` Estado del pluvio: orden 17, período 60.0 min, decimales 0, calculado 0.
  - `0021` Nivel Recipiente: orden 18, período 60.0 min, decimales 1, calculado 0.
  - `0022` Voltaje de batería: orden 19, período 60.0 min, decimales 2, calculado 0.

### GONZTAM001 — GONZALEZ TAM

- DCP: `15F3A54C`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 18; familia `pseudobinary_b` × 18.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **18/18** tramas.
- Wire: 86 (18 tramas); catálogo esperado: 24.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 60.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 60.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 60.0 min, decimales 1, calculado 0.
  - `0004` Presión Atmosférica: orden 4, período 60.0 min, decimales 0, calculado 0.
  - `0005` Radiación Solar: orden 5, período 60.0 min, decimales 0, calculado 0.
  - `0006` Velocidad del viento: orden 6, período 60.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 7, período 60.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 8, período 60.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 9, período 60.0 min, decimales 0, calculado 0.
  - `0010` Intensidad de precipitación: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0011` Precipitación: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0012` Nivel Recipiente: orden 12, período 60.0 min, decimales 1, calculado 0.
  - `0013` Estado del pluvio: orden 13, período 60.0 min, decimales 0, calculado 0.
  - `0014` Voltaje de batería: orden 14, período 60.0 min, decimales 2, calculado 0.

### HUIMA27XXX — HUIMANGUILLO (INIFAP)

- DCP: `15F355C8`; rango: 120.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 18; familia `pseudobinary_b` × 18.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **18/18** tramas.
- Wire: 110 (18 tramas); catálogo esperado: 126.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 11, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 12, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 13, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 14, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 15, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 16, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 17, período 60.0 min, decimales 2, calculado 0.

### HUIXT07077 — HUIXTLA

- DCP: `15F232D4`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 110 (17 tramas); catálogo esperado: 75.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0004` Humedad del suelo: orden 4, período 10.0 min, decimales 3, calculado 0.
  - `0005` Temperatura: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 12, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 13, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 14, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 15, período 60.0 min, decimales 2, calculado 0.

### JAMAVER008 — JAMAPA (HC)

- DCP: `1A5075D0`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 80 (17 tramas); catálogo esperado: 71.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0003` Precipitación: orden 2, período 10.0 min, decimales 1, calculado 0.
  - `0004` Intensidad de precipitación: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0005` Temperatura: orden 4, período 10.0 min, decimales 1, calculado 0.
  - `0006` Humedad relativa: orden 5, período 10.0 min, decimales 0, calculado 0.
  - `0007` Punto de rocío: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0008` Presión Atmosférica: orden 7, período 10.0 min, decimales 1, calculado 0.
  - `0010` Velocidad del viento: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0011` Dirección del viento: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0012` Velocidad de ráfaga: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0013` Dirección de ráfaga: orden 11, período 10.0 min, decimales 0, calculado 0.
  - `0014` Señal de ruido: orden 12, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del radar: orden 13, período 60.0 min, decimales 0, calculado 0.
  - `0016` Estado del pluvio: orden 14, período 60.0 min, decimales 0, calculado 0.
  - `0017` Nivel Recipiente: orden 15, período 60.0 min, decimales 1, calculado 0.
  - `0019` Voltaje de batería: orden 16, período 60.0 min, decimales 2, calculado 0.

### LACAN07337 — LACANTUN (SGT)

- DCP: `15F2D126`; rango: 120.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 18; familia `pseudobinary_b` × 18.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **18/18** tramas.
- Wire: 148 (18 tramas); catálogo esperado: 140.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0010` Velocidad de ráfaga: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0011` Dirección de ráfaga: orden 11, período 10.0 min, decimales 0, calculado 0.
  - `0012` Precipitación: orden 14, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 15, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 16, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 17, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 18, período 60.0 min, decimales 2, calculado 0.
  - `0019` Nivel de agua: orden 19, período 10.0 min, decimales 2, calculado 0.
  - `0020` Estado del CBS: orden 20, período 10.0 min, decimales 0, calculado 0.
  - `0021` Temperatura Interna: orden 21, período 60.0 min, decimales 2, calculado 0.

### LENCR07XXX — LA ENCRUCIJADA

- DCP: `15F21438`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 110 (17 tramas); catálogo esperado: 75.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0004` Humedad del suelo: orden 4, período 10.0 min, decimales 3, calculado 0.
  - `0005` Temperatura: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 12, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 13, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 14, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 15, período 60.0 min, decimales 2, calculado 0.

### LFLOR07102 — LAS FLORES

- DCP: `15F271DE`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 110 (17 tramas); catálogo esperado: 75.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0004` Humedad del suelo: orden 4, período 10.0 min, decimales 3, calculado 0.
  - `0005` Temperatura: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 12, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 13, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 14, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 15, período 60.0 min, decimales 2, calculado 0.

### LOMAPUE004 — PUENTE PALOMAS (H1)

- DCP: `1A5036DA`; rango: 120.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 18; familia `pseudobinary_b` × 18.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **18/18** tramas.
- Wire: 64 (18 tramas); catálogo esperado: 56.
- Diagnóstico: El último bloque corresponde a temperatura interna, ausente del catálogo.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0003` Precipitación: orden 2, período 10.0 min, decimales 1, calculado 0.
  - `0004` Intensidad de precipitación: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0014` Señal de ruido: orden 4, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del radar: orden 5, período 60.0 min, decimales 0, calculado 0.
  - `0016` Estado del pluvio: orden 6, período 10.0 min, decimales 0, calculado 0.
  - `0017` Nivel Recipiente: orden 7, período 60.0 min, decimales 1, calculado 0.
  - `0019` Voltaje de batería: orden 8, período 60.0 min, decimales 2, calculado 0.

### MMIZTAB018 — MACAYO MARGEN IZQUIERDA

- DCP: `1A526352`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 97 (17 tramas); catálogo esperado: 104.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0011` Velocidad del agua: orden 2, período 10.0 min, decimales 3, calculado 0.
  - `0012` Velocidad del agua: orden 3, período 10.0 min, decimales 3, calculado 0.
  - `0013` Velocidad del agua: orden 4, período 10.0 min, decimales 3, calculado 0.
  - `0031` Precipitación: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0036` Temperatura: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0041` Humedad relativa: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0046` Velocidad del viento: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0047` Dirección del viento: orden 11, período 10.0 min, decimales 0, calculado 0.
  - `0048` Velocidad de ráfaga: orden 12, período 10.0 min, decimales 1, calculado 0.
  - `0049` Dirección de ráfaga: orden 13, período 10.0 min, decimales 0, calculado 0.
  - `0902` Voltaje de batería: orden 16, período 60.0 min, decimales 2, calculado 0.
  - `0903` Estado RLS: orden 17, período 10.0 min, decimales 0, calculado 0.
  - `0904` Señal RLS: orden 18, período 10.0 min, decimales 1, calculado 0.
  - `0905` Señal de Velocidad: orden 19, período 10.0 min, decimales 1, calculado 0.
  - `0906` Señal de Velocidad: orden 20, período 10.0 min, decimales 1, calculado 0.
  - `0907` Señal de Velocidad: orden 21, período 10.0 min, decimales 1, calculado 0.
  - `0909` Nivel Recipiente: orden 24, período 60.0 min, decimales 1, calculado 0.
  - `0910` Estado del pluvio: orden 25, período 10.0 min, decimales 0, calculado 0.

### MOTOZ07119 — MOTOZINTLA

- DCP: `15F2815A`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 110 (17 tramas); catálogo esperado: 75.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0004` Humedad del suelo: orden 4, período 10.0 min, decimales 3, calculado 0.
  - `0005` Temperatura: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 12, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 13, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 14, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 15, período 60.0 min, decimales 2, calculado 0.

### QR05 — NICOLÁS BRAVO

- DCP: `15CC60B0`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `"\r\n2 17:30:0` × 1; familia `table_text` × 1.
- ¿Decoder coincide con la trama?: **No**.
- Payload GS300 estructuralmente decodificable: **0/1** tramas.
- Wire: sin B1 válida; catálogo esperado: 66.
- Diagnóstico: Trama no B1, textual, incompleta o con caracteres inválidos; no es una corrección segura de SENSOR.
- Sensores activos:

  - `0001` Dirección del viento: orden 1, período 10.0 min, decimales 0, calculado 0.
  - `0002` Dirección del viento: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Velocidad del viento: orden 3, período 10.0 min, decimales 0, calculado 0.
  - `0004` Velocidad del viento: orden 4, período 10.0 min, decimales 0, calculado 0.
  - `0005` Temperatura: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0006` Humedad relativa: orden 6, período 10.0 min, decimales 0, calculado 0.
  - `0007` Presión Atmosférica: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0008` Precipitación: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0009` Radiación Solar: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0010` Voltaje de batería: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0011` Voltaje del panel solar: orden 11, período 10.0 min, decimales 1, calculado 0.

### SJERO07146 — SAN JERONIMO

- DCP: `15F2A7B6`; rango: 120.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 16; familia `pseudobinary_b` × 16.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **16/16** tramas.
- Wire: 26 (16 tramas); catálogo esperado: 150.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0004` Humedad del suelo: orden 4, período 10.0 min, decimales 3, calculado 0.
  - `0005` Temperatura: orden 5, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 7, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 11, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 12, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 13, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 14, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 15, período 60.0 min, decimales 2, calculado 0.

### SOLEVER007 — SOLEDAD DE DOBLADO (HC1)

- DCP: `1A5066A6`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 100 (17 tramas); catálogo esperado: 41.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0003` Precipitación: orden 2, período 10.0 min, decimales 1, calculado 0.
  - `0004` Intensidad de precipitación: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0005` Temperatura: orden 4, período 10.0 min, decimales 1, calculado 0.
  - `0006` Humedad relativa: orden 5, período 10.0 min, decimales 0, calculado 0.
  - `0007` Punto de rocío: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0014` Señal de ruido: orden 7, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del radar: orden 8, período 60.0 min, decimales 0, calculado 0.
  - `0016` Estado del pluvio: orden 9, período 60.0 min, decimales 0, calculado 0.
  - `0017` Nivel Recipiente: orden 10, período 60.0 min, decimales 1, calculado 0.
  - `0019` Voltaje de batería: orden 11, período 60.0 min, decimales 2, calculado 0.

### STODCHIA22 — SANTO DOMINGO

- DCP: `15D3F4DE`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 36 (17 tramas); catálogo esperado: 12.
- Diagnóstico: El wire contiene un tercer bloque de 12 palabras no identificado en SENSOR.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0900` Voltaje de batería: orden 2, período 10.0 min, decimales 1, calculado 0.

### SUCHIXXXXX — SUCHIATE

- DCP: `15F390D6`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 18; familia `pseudobinary_b` × 18.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **18/18** tramas.
- Wire: 50 (18 tramas); catálogo esperado: 68.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 2, calculado 0.
  - `0006` Velocidad del viento: orden 4, período 60.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 5, período 60.0 min, decimales 0, calculado 0.
  - `0011` Velocidad de ráfaga: orden 6, período 60.0 min, decimales 1, calculado 0.
  - `0012` Dirección de ráfaga: orden 7, período 60.0 min, decimales 0, calculado 0.
  - `0018` Intensidad de precipitación: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0019` Precipitación: orden 9, período 10.0 min, decimales 1, calculado 0.
  - `0020` Nivel Recipiente: orden 10, período 60.0 min, decimales 1, calculado 0.
  - `0021` Estado del pluvio: orden 11, período 60.0 min, decimales 0, calculado 0.
  - `0022` Nivel de agua: orden 12, período 10.0 min, decimales 2, calculado 0.
  - `0023` Nivel de agua: orden 13, período 10.0 min, decimales 2, calculado 0.
  - `0024` Velocidad del agua: orden 14, período 10.0 min, decimales 2, calculado 0.
  - `0025` Velocidad del agua: orden 15, período 10.0 min, decimales 2, calculado 0.
  - `0026` Señal de ruido: orden 16, período 10.0 min, decimales 2, calculado 0.
  - `0027` Gasto: orden 17, período 10.0 min, decimales 2, calculado 1.
  - `0028` Voltaje de batería: orden 18, período 60.0 min, decimales 2, calculado 0.
  - `0029` Voltaje de batería: orden 19, período 60.0 min, decimales 2, calculado 0.

### TALIS07000 — TALISMAN

- DCP: `15F383A0`; rango: 120.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 98 (17 tramas); catálogo esperado: 124.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 2, calculado 0.
  - `0006` Velocidad del viento: orden 4, período 60.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 5, período 60.0 min, decimales 0, calculado 0.
  - `0011` Velocidad de ráfaga: orden 6, período 60.0 min, decimales 1, calculado 0.
  - `0012` Dirección de ráfaga: orden 7, período 60.0 min, decimales 0, calculado 0.
  - `0018` Intensidad de precipitación: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0019` Precipitación: orden 9, período 10.0 min, decimales 1, calculado 0.
  - `0020` Nivel Recipiente: orden 10, período 60.0 min, decimales 1, calculado 0.
  - `0021` Estado del pluvio: orden 11, período 60.0 min, decimales 0, calculado 0.
  - `0022` Nivel de agua: orden 12, período 10.0 min, decimales 2, calculado 0.
  - `0023` Velocidad del agua: orden 13, período 10.0 min, decimales 2, calculado 0.
  - `0026` Señal de ruido: orden 14, período 10.0 min, decimales 2, calculado 0.
  - `0024` Gasto: orden 15, período 10.0 min, decimales 2, calculado 1.
  - `0025` Voltaje de batería: orden 16, período 60.0 min, decimales 2, calculado 0.
  - `0027` Voltaje de Bateria Radio: orden 17, período 60.0 min, decimales 2, calculado 0.
  - `0030` Indefinido: orden 18, período 10.0 min, decimales 1, calculado 0.

### TBLASLP020 — TIERRA BLANCA

- DCP: `15D57204`; rango: 180.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 6; familia `pseudobinary_b` × 6.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **0/6** tramas.
- Wire: sin B1 válida; catálogo esperado: 57.
- Diagnóstico: Trama no B1, textual, incompleta o con caracteres inválidos; no es una corrección segura de SENSOR.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0002` Precipitación: orden 2, período 10.0 min, decimales 1, calculado 0.
  - `0003` Temperatura: orden 3, período 60.0 min, decimales 2, calculado 0.
  - `0004` Velocidad del viento: orden 4, período 60.0 min, decimales 1, calculado 0.
  - `0005` Dirección del viento: orden 5, período 60.0 min, decimales 0, calculado 0.
  - `0009` Velocidad de ráfaga: orden 6, período 60.0 min, decimales 1, calculado 0.
  - `0010` Dirección de ráfaga: orden 7, período 60.0 min, decimales 0, calculado 0.
  - `0011` Humedad relativa: orden 8, período 60.0 min, decimales 0, calculado 0.
  - `0012` Voltaje de batería: orden 9, período 60.0 min, decimales 2, calculado 0.

### TEJAVER009 — EL TEJAR (HC1)

- DCP: `1A508554`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 20; familia `pseudobinary_b` × 20.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **20/20** tramas.
- Wire: 78 (20 tramas); catálogo esperado: 41.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0003` Precipitación: orden 2, período 10.0 min, decimales 1, calculado 0.
  - `0004` Intensidad de precipitación: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0005` Temperatura: orden 4, período 10.0 min, decimales 1, calculado 0.
  - `0006` Humedad relativa: orden 5, período 10.0 min, decimales 0, calculado 0.
  - `0007` Punto de rocío: orden 6, período 10.0 min, decimales 1, calculado 0.
  - `0015` Estado del radar: orden 7, período 60.0 min, decimales 0, calculado 0.
  - `0016` Estado del pluvio: orden 8, período 60.0 min, decimales 0, calculado 0.
  - `0017` Nivel Recipiente: orden 9, período 60.0 min, decimales 1, calculado 0.
  - `0018` Voltaje de batería: orden 10, período 60.0 min, decimales 2, calculado 0.
  - `0019` Voltaje de batería: orden 11, período 60.0 min, decimales 2, calculado 0.

### TIN1DISI06 — TINTILLO 1

- DCP: `1A52D0DC`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 5; familia `pseudobinary_b` × 5.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **5/5** tramas.
- Wire: 32 (5 tramas); catálogo esperado: 26.
- Diagnóstico: El wire contiene un bloque adicional de 6 palabras no identificado.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0002` Velocidad del agua: orden 2, período 10.0 min, decimales 3, calculado 0.
  - `0005` Voltaje de batería: orden 7, período 60.0 min, decimales 2, calculado 0.
  - `0006` Temperatura Interna: orden 8, período 60.0 min, decimales 2, calculado 0.
  - `0007` Estado: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0008` Señal de ruido: orden 10, período 10.0 min, decimales 1, calculado 0.

### TIN2DISI07 — TINTILLO 2

- DCP: `1A52E546`; rango: 60.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 32 (17 tramas); catálogo esperado: 26.
- Diagnóstico: El wire contiene un bloque adicional de 6 palabras no identificado.
- Sensores activos:

  - `0001` Nivel de agua: orden 1, período 10.0 min, decimales 2, calculado 0.
  - `0002` Velocidad del agua: orden 2, período 10.0 min, decimales 3, calculado 0.
  - `0005` Voltaje de batería: orden 7, período 60.0 min, decimales 2, calculado 0.
  - `0006` Temperatura Interna: orden 8, período 60.0 min, decimales 2, calculado 0.
  - `0007` Estado: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0008` Señal de ruido: orden 10, período 10.0 min, decimales 1, calculado 0.

### ZAPAL07099 — ZAPALUTA

- DCP: `15F262A8`; rango: 120.0 min; intervalo TX: 60.0 min.
- Decoder configurado: `GS300`; firma esperada: `bB1`, `` `B1`` o `"B1` (pseudobinario B).
- Trama observada: firma `bB1` × 17; familia `pseudobinary_b` × 17.
- ¿Decoder coincide con la trama?: **Sí**.
- Payload GS300 estructuralmente decodificable: **17/17** tramas.
- Wire: 86 (17 tramas); catálogo esperado: 126.
- Diagnóstico: La longitud es estable, pero requiere identificar canales, períodos u orden; hay más de una configuración aritméticamente posible.
- Sensores activos:

  - `0001` Temperatura: orden 1, período 10.0 min, decimales 1, calculado 0.
  - `0002` Humedad del aire: orden 2, período 10.0 min, decimales 0, calculado 0.
  - `0003` Punto de rocío: orden 3, período 10.0 min, decimales 1, calculado 0.
  - `0006` Velocidad del viento: orden 8, período 10.0 min, decimales 1, calculado 0.
  - `0007` Dirección del viento: orden 9, período 10.0 min, decimales 0, calculado 0.
  - `0008` Velocidad de ráfaga: orden 10, período 10.0 min, decimales 1, calculado 0.
  - `0009` Dirección de ráfaga: orden 11, período 10.0 min, decimales 0, calculado 0.
  - `0011` Intensidad de precipitación: orden 12, período 10.0 min, decimales 1, calculado 0.
  - `0012` Precipitación: orden 13, período 10.0 min, decimales 1, calculado 0.
  - `0013` Radiación Solar: orden 14, período 10.0 min, decimales 0, calculado 0.
  - `0014` Nivel Recipiente: orden 15, período 60.0 min, decimales 1, calculado 0.
  - `0015` Estado del pluvio: orden 16, período 60.0 min, decimales 0, calculado 0.
  - `0016` Voltaje de batería: orden 17, período 60.0 min, decimales 2, calculado 0.
