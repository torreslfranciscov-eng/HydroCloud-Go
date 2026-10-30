# Conciliación de precipitación horaria y diaria — 2026-10-06

## Alcance y método

- Ventana: dos días UTC completos, etiquetas `2026-10-04` y `2026-10-05`.
- Variable: nombre exacto `precipitación`; no se mezclan precipitación acumulada,
  intensidad ni estado del pluviómetro.
- Se compararon las lecturas crudas válidas agrupadas con la regla
  `TRUNC(ts - 1 minuto)`, la suma de `resumen_horario.acumulado` y
  `resumen_diario.acumulado`.
- Tolerancia numérica: `0.01 mm`.
- Solo lectura. No se modificó Oracle.

## Resultado

| Métrica | Resultado |
| --- | ---: |
| Estaciones activas en HYDROCLOUD | 818 |
| Estaciones activas con sensor directo de precipitación | 663 |
| Pares estación/sensor activos en el catálogo | 674 |
| Pares con algún dato o resumen en la ventana | 390 |
| Pares sin datos ni resúmenes en ambos días | 284 |
| Días-estación/sensor evaluados | 1,348 |
| Días que cuadran entre crudo, horario y diario | 677 |
| Días con discrepancia de suma | 100 |
| Días sin crudo ni resumen horario/diario | 571 |
| Pares que cuadran ambos días | 312 |
| Pares con al menos un día discrepante | 75 |
| Pares incompletos (un día sin datos) | 3 |
| Estaciones con discrepancia de suma | 75 |

En 99 de los 100 días discrepantes, las lecturas crudas y el resumen horario
coinciden dentro de la tolerancia; el resumen diario no coincide. En el caso
restante difieren también las lecturas crudas y el resumen horario. Esto
confirma que la igualdad no está corregida todavía para todos los datos ya
almacenados. Los resúmenes anteriores al cambio pueden requerir reconstrucción.

La conciliación se hizo contra `HYDROCLOUD.ESTACION`, `SENSOR` y `TIPOSENSOR`,
incluyendo todos los 674 sensores directos activos de las 663 estaciones que
los tienen. Las otras 155 estaciones activas no tienen un sensor activo cuyo
nombre sea exactamente `Precipitación`, por lo que no se les atribuye una suma
de precipitación. No se interpretó la falta de datos como precipitación cero.

El [CSV con la matriz completa](/Users/subgerenciagrijalva/HydroCloud-Go/CONCILIACION_PRECIPITACION_TODAS_ESTACIONES_20261006.csv)
incluye una fila por cada par activo estación/sensor, con estado y lecturas,
suma horaria y suma diaria de cada día. Los 284 pares sin registros en toda la
ventana se conservan explícitamente como `NO_DATA_BOTH_DAYS`; no se omiten.

## Estaciones afectadas

`Días` enumera las etiquetas UTC discrepantes. `Diferencia máxima` es la mayor
diferencia absoluta entre suma horaria y diaria observada para esa estación en
la ventana; `sin dato` significa que ese día no tuvo lecturas crudas ni
resúmenes disponibles para comparar.

| Clave | Estación | DCP | Sensor | Días | Diferencia máxima (mm) |
| --- | --- | --- | --- | --- | ---: |
| 0000000005 | Agua Salada | E8903378 | 0008 | 04, 05 | 3.800 |
| 0000000G02 | PUEBLO NUEVO | 15B24798 | 0002 | 04, 05 | 0.100 |
| 0000000G03 | PLATANAR | 15B27202 | 0002 | 05 | 0.200 |
| 0000000G12 | POSTA | 15DBF078 | 0002 | 04, 05 | 0.600 |
| 00000CFE06 | DESFOGUE MALPASO | E890C3FC | 0003 | 05 | 82.600 |
| 000OCLSP09 | SAN ANTONIO GUARACHA | 15CAD3F0 | 0002 | 04, 05 | 1.800 |
| 000OCLSP16 | PRESA DE GONZALO | 15D7B2EE | 0002 | 04, 05 | 0.200 |
| ABASTAM040 | ABASOLO | 1A51772A | 0003 | 05 | 0.100 |
| ACULCO0028 | ACULCO | AC509C0A | 1001 | 04 | 1.000 |
| ADJUSLP025 | LAS ADJUNTAS | 15D5D2FC | 0002 | 05 | 0.100 |
| BAR1TAM038 | BARRETAL 1 | 1A5151C6 | 0003 | 05 | sin dato |
| BOSQTLA034 | BOSQUE DE TLALPAN | AC50B434 | 1001 | 04 | 0.500 |
| CAMPMEC007 | CAMPAMENTO MECOAYA | AC503CF2 | 1001 | 04, 05 | 0.250 |
| CANDECAMP | LA CANDELARIA | 15D8F776 | 0003 | 05 | 0.100 |
| CEDROCILA1 | EL CEDRO | B12EE6E0 | 1002 | 04 | 0.410 |
| CERESTR030 | CERRO DE LA ESTRELLA | AC50A990 | 1001 | 04 | 1.000 |
| CFE0000009 | Santo Domingo | E890DE58 | 0003 | 05 | 1.100 |
| CFE0000021 | Presa Malpaso | E89149C0 | 0003 | 04, 05 | 0.100 |
| CFE0000023 | Las Flores | E8915AB6 | 0003 | 05 | 3.000 |
| CFE0000024 | Ocotepec | E8902EDC | 0002 | 05 | 0.100 |
| CFE0000042 | Presa Mazatepec | E8924ECE | 0002 | 04, 05 | 0.900 |
| CFE0000046 | Tepeyac | E8928BD0 | 0002 | 04 | 6.100 |
| CFE0000048 | Presa Cerro de Oro (Miguel de la Madrid) | E89298A6 | 0002 | 04, 05 | 0.400 |
| CH49 | JANOS | 15D79402 | 0008 | 05 | sin dato |
| CHAPTAB001 | CHAPULTENANGO | 1A53912C | 0031 | 04, 05 | 0.100 |
| CHENCHIA06 | CHALCHIHUITÁN | 15DC41C2 | 0031 | 04, 05 | 1.900 |
| CHURLAG014 | CHURUBUSCO LAGO | AC506C8E | 1001 | 04 | 0.250 |
| CS58 | EL TRIUNFO | 15AFA092 | 0008 | 04, 05 | 0.200 |
| DF04 | TEZONTLE | 15A0158E | 0008 | 04 | 1.500 |
| DVALLE074Q | 74 - DEL VALLE | AC53288A | 1001 | 04 | 0.750 |
| EBURR07040 | EL BURRERO | 15F2074E | 0012 | 05 | 0.600 |
| EJERORI029 | EJERCITO ORIENTE | AC50A742 | 1001 | 04 | 0.500 |
| FRAIMADE30 | PRESA FRANCISCO I. MADERO | 15AD2372 | 0002 | 04 | 19.400 |
| GALLSLP018 | GALLINAS | 15D5479E | 0002 | 05 | 0.200 |
| GDF0000011 | GDF ZOCALO | AC5057C6 | 1001 | 04 | 0.250 |
| GFLAGUNA04 | ESTACION LAGUNA | 15F492E2 | 0004 | 05 | 0.100 |
| GT53 | SIERRA GORDA II | 16A01768 | 0008 | 04, 05 | 1.200 |
| GUACAXXXXX | GUACAMAYAS | 15F2F7CA | 0012 | 04, 05 | 10.200 |
| HI04 | ZIMAPAN | 15C9370C | 0008 | 04, 05 | 2.400 |
| HI18 | EL CHICO | 15DA8412 | 0008 | 05 | 0.400 |
| HUIXCHIA12 | HUIXTÁN | 15DC2424 | 0031 | 04, 05 | 0.800 |
| HUIXT07077 | HUIXTLA | 15F232D4 | 0012 | 05 | 1.700 |
| HULEVER027 | LOS HULES | 15D7426A | 0002 | 05 | 0.200 |
| JA24 | NEVADO DE COLIMA | 16A1337E | 0008 | 05 | 0.200 |
| JONUT27028 | JONUTA | 15F36052 | 0012 | 04, 05 | 3.400 |
| LARRA07207 | LARRAINZAR | 15F002BA | 0017 | 05 | 2.300 |
| LENCR07XXX | LA ENCRUCIJADA | 15F21438 | 0012 | 05 | 0.100 |
| LFLOR07102 | LAS FLORES | 15F271DE | 0012 | 05 | 6.200 |
| LOPMATE013 | LOPEZ MATEOS | AC50625C | 1001 | 04 | 0.750 |
| LVENTA022Q | 22 - LA VENTA | AC522A70 | 1001 | 04 | 0.250 |
| MARCARR012 | MARCOS CARRILLO | AC505914 | 1001 | 04 | 3.750 |
| MMIZTAB018 | MACAYO MARGEN IZQUIERDA | 1A526352 | 0031 | 04, 05 | 0.100 |
| MONTEA026Q | 26 - MONTE ALEGRE | AC524F96 | 1001 | 05 | 0.750 |
| MUNLIBR020 | MUNICIPIO LIBRE | AC508F7C | 1001 | 04 | 3.750 |
| NARASLP019 | EL NARANJO | 15D554E8 | 0002 | 04, 05 | 0.200 |
| NY07 | MARISMAS NACIONALES | 16A17074 | 0008 | 04, 05 | 5.000 |
| PAVAPUE001 | PAHUATLAN DEL VALLE (C1) | 1A50D528 | 0003 | 04 | 0.100 |
| PENON00051 | 51-PEÑON (CAMPAMENTO MATAMOROS) | AC50E448 | 1001 | 04 | 0.250 |
| PICJUP096Q | PLANTA PICACHO AJUSCO PERIFERICO | AC51C05E | 1001 | 04 | 0.500 |
| POZOCU080Q | POZO CU | AC5118E4 | 1001 | 04 | 0.250 |
| PU04 | PALIZADA | 15AE370A | 0008 | 05 | sin dato |
| QO09 | PRESA JALPAN | 15B00166 | 0008 | 04, 05 | 1.600 |
| QUIOCHIA19 | PUENTE QUIOSCO | 1A5470EA | 0031 | 05 | 2.000 |
| RADIOCO019 | RADIOCOMUNICACIÓN | AC5081AE | 1001 | 04 | 0.500 |
| RIOJTAB011 | RIO DE JANEIRO | 1A53D226 | 0031 | 04, 05 | 0.100 |
| SAFETAM051 | SAN FERNANDO | 16AA054C | 0003 | 04, 05 | 1.400 |
| SERVTAM004 | LA SERVILLETA | 15ACC27A | 0002 | 04, 05 | 0.200 |
| TALIS07000 | TALISMAN | 15F383A0 | 0019 | 05 | 0.700 |
| TANCSLP063 | TANCHACHIN | 16AAB6C2 | 0003 | 05 | 0.100 |
| TANLIE017Q | 17 - TANQUE LIENZO | AC521FEA | 1001 | 04 | 0.250 |
| TIGRECILA1 | EL TIGRE | B12EF596 | 1002 | 04 | 1.260 |
| TRIANGU015 | TRIANGULO | AC50712A | 1001 | 05 | 0.250 |
| UNIVERS018 | UNIVERSIDAD | AC507FF8 | 1001 | 04 | 0.500 |
| VALLTAM046 | PUERTO DE VALLES | 1A51D7D2 | 0003 | 04, 05 | 0.400 |
| VICESLP016 | SAN VICENTE | 15B506A6 | 0002 | 04 | 0.800 |
| VR29 | PRESA TUXPANGO | 16A0917C | 0008 | 04 | 3.000 |
| XOTEPIN027 | XOTEPINGO | AC5092D8 | 1001 | 04 | 2.000 |
| ZONTVER066 | ZONTECOMATLÁN | 1A5653F2 | 0003 | 05 | 1.300 |

Los tres pares incompletos, con un día sin datos pero el otro con datos, son
BARRETAL 1, JANOS y PALIZADA. Además, 284 pares no tienen datos en ninguno de
los dos días. Ninguno de esos vacíos se trató como precipitación cero.

## Ejemplos de mayor diferencia diaria-horaria

| Estación | DCP / sensor | Día UTC | Suma horaria (mm) | Resumen diario (mm) | Diferencia (mm) |
| --- | --- | --- | ---: | ---: | ---: |
| DESFOGUE MALPASO | E890C3FC / 0003 | 2026-10-05 | 637.700 | 555.100 | 82.600 |
| PRESA FRANCISCO I. MADERO | 15AD2372 / 0002 | 2026-10-04 | 1500.800 | 1481.400 | 19.400 |
| GUACAMAYAS | 15F2F7CA / 0012 | 2026-10-05 | 1869.700 | 1859.500 | 10.200 |
| LAS FLORES | 15F271DE / 0012 | 2026-10-05 | 19.400 | 13.200 | 6.200 |
| TEPEYAC | E8928BD0 / 0002 | 2026-10-04 | 37.400 | 43.500 | 6.100 |

## Nota de interpretación

La diferencia puede corresponder a resúmenes diarios ya almacenados bajo la
frontera anterior, a un resumen horario desactualizado o a ambas cosas. El
código corregido alinea nuevos resúmenes, pero no reconstruye automáticamente
los históricos. Antes de reparar producción, conviene ejecutar una conciliación
acotada con copia/validación de respaldo y reconstruir los días afectados.
