# Revisión OTT — 30/09/2026

Fuente: Oracle HYDROCLOUD.Sensor/TipoSensor/UnidadMedida y DCP_HEADERS. Hasta 12 mensajes de medición por estación, últimos siete días. No se validan equipos sin evidencia.

Correcciones verificadas: 19 rangos, cuatro periodos y dos decoders B1. Nombres, tipos, unidades, escalas y orden no se cambiaron.

Jonuta y Chicayán: reclasificadas GS300, doce tramas completas cada una. Las 167 estaciones restantes siguen catalogadas OTTBinario.

## Resumen

- 95: Sin medición disponible en la muestra de 7 días
- 46: Compatible
- 15: Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar
- 3: OTT: fecha interna fuera de ventana de recepción (-7 días / +5 minutos)
- 1: Bloque OTT inválido o truncado
- 1: OTT: intervalo/cantidad de muestras no coincide con catálogo; Bloque OTT inválido o truncado
- 3: OTT: cantidad de bloques no coincide con Sensor
- 1: Cabecera OTT no soportada
- 1: Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar; Cabecera OTT no soportada
- 1: OTT: Sensor.Orden ausente, inválido o duplicado; no se usan perfiles supuestos

## Inventario

| Clave | Estación | Resultado |
|---|---|---|
| 0000000001 | C. H. La Venta | Sin medición disponible en la muestra de 7 días |
| 0000000005 | Agua Salada | Compatible: 12/12 tramas |
| 0000000G03 | PLATANAR | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| 0000000G08 | BOCA DEL CERRO | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| 0000000G09 | SALTO DE AGUA | Sin medición disponible en la muestra de 7 días |
| 0000000G13 | PIGUA | Sin medición disponible en la muestra de 7 días |
| 0000000G14 | FRONTERA | Sin medición disponible en la muestra de 7 días |
| 0000000L03 | EL ARENAL | OTT: fecha interna fuera de ventana de recepción (-7 días / +5 minutos) |
| 000000GR01 | EL PORVENIR | Sin medición disponible en la muestra de 7 días |
| 000000GR03 | SAMARIA | Sin medición disponible en la muestra de 7 días |
| 000000GR04 | SAN JOAQUIN | Sin medición disponible en la muestra de 7 días |
| 000000GR05 | TAPIJULAPA | Sin medición disponible en la muestra de 7 días |
| 000000GR06 | PUYACATENGO | Sin medición disponible en la muestra de 7 días |
| 000000GR07 | TEAPA | Sin medición disponible en la muestra de 7 días |
| 000000LG01 | YURIRIA | Sin medición disponible en la muestra de 7 días |
| 000000LG02 | AMEXHE | Sin medición disponible en la muestra de 7 días |
| 000000LG04 | LOMO DE TORO | Sin medición disponible en la muestra de 7 días |
| 000000LG05 | HACIENDA LA Y | Sin medición disponible en la muestra de 7 días |
| 000000LG06 | SANTA MARIA DEL LLANO | Sin medición disponible en la muestra de 7 días |
| 000000LG10 | MALPAÍS | Sin medición disponible en la muestra de 7 días |
| 000000LG14 | LAGO DE CUITZEO | Sin medición disponible en la muestra de 7 días |
| 000000LG18 | EL TULE | Sin medición disponible en la muestra de 7 días |
| 000000LG24 | JOSÉ FABELA | Sin medición disponible en la muestra de 7 días |
| 000000LG25 | SANTA CATARINA OCLSP | Sin medición disponible en la muestra de 7 días |
| 000000LG29 | LA PURÍSIMA (GUANAJUATO) | Compatible: 12/12 tramas |
| 000000LG30 | PEÑUELITAS | Sin medición disponible en la muestra de 7 días |
| 000000LG31 | LAS ADJUNTAS (GUANAJUATO) | Sin medición disponible en la muestra de 7 días |
| 000000LG33 | SALVATIERRA | Sin medición disponible en la muestra de 7 días |
| 000000LG34 | 3 GUERRAS | Sin medición disponible en la muestra de 7 días |
| 000000LG36 | PRESA EL PALOTE | Sin medición disponible en la muestra de 7 días |
| 000000LG38 | MALTARAÑA | Sin medición disponible en la muestra de 7 días |
| 000000LG39 | MEZCALA | OTT: fecha interna fuera de ventana de recepción (-7 días / +5 minutos) |
| 000000LG40 | YURÉCUARO | Sin medición disponible en la muestra de 7 días |
| 000000LG41 | ZACAPU | Sin medición disponible en la muestra de 7 días |
| 000000LG44 | ACUEDUCTO CHAPALA-GUADALAJARA | Compatible: 12/12 tramas |
| 000000LG46 | RÍO ZULA | Sin medición disponible en la muestra de 7 días |
| 000000LG47 | TUXCUECA | Compatible: 12/12 tramas |
| 000000OXOL | OXOLOTAN | Sin medición disponible en la muestra de 7 días |
| 00000MANGO | EL MANGO | Sin medición disponible en la muestra de 7 días |
| 000OCLSP01 | ARANDAS | Sin medición disponible en la muestra de 7 días |
| 000OCLSP02 | EL BARRIAL | Sin medición disponible en la muestra de 7 días |
| 000OCLSP04 | ALVARO OBREGÓN | Bloque OTT inválido o truncado |
| 000OCLSP10 | LA PIEDAD | Compatible: 12/12 tramas |
| 000OCLSP11 | PRESA LA NORIA | Sin medición disponible en la muestra de 7 días |
| 000OCLSP12 | PRESA LA COFRADIA | Sin medición disponible en la muestra de 7 días |
| 000OCLSP14 | PRESA UREPETIRO | Sin medición disponible en la muestra de 7 días |
| 000OCLSP15 | PRESA JARIPO | Sin medición disponible en la muestra de 7 días |
| 000OCLSP18 | PRESA EL ZAPOTILLO | Sin medición disponible en la muestra de 7 días |
| 0CORCJAL01 | CORCOVADO | Sin medición disponible en la muestra de 7 días |
| 0MEZCALAPA | MEZCALAPA | Sin medición disponible en la muestra de 7 días |
| 1ESCO27109 | ESCOTADURA 1 M. I. | Sin medición disponible en la muestra de 7 días |
| 2ESCO27108 | ESCOTADURA 2 M. I. | Sin medición disponible en la muestra de 7 días |
| 3ESCO27107 | ESCOTADURA 3 M.I. | Sin medición disponible en la muestra de 7 días |
| 4CAMVER012 | PUENTE 4 CAMINOS (HC1) | Compatible: 12/12 tramas |
| AAZUL07004 | AGUA AZUL | Sin medición disponible en la muestra de 7 días |
| ABASTAM040 | ABASOLO | Compatible: 12/12 tramas |
| ACTOVER015 | ACTOPAN | Compatible: 12/12 tramas |
| ADJUSLP025 | LAS ADJUNTAS | Compatible: 11/12 tramas |
| AGRAN07000 | ARROYO GRANDE | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| AHUATAM058 | AHUALULCO | Sin medición disponible en la muestra de 7 días |
| AQUES07000 | AQUESPALA | Sin medición disponible en la muestra de 7 días |
| BAR1TAM038 | BARRETAL 1 | Compatible tras corregir periodo; 12 tramas |
| BAR2TAM037 | BARRETAL 2 | Compatible: 12/12 tramas |
| BARBTAM056 | BARBERENA | Compatible: 12/12 tramas |
| BOCHI07015 | BOCHIL | Sin medición disponible en la muestra de 7 días |
| BOM1TAMO14 | BOMBAS 1 | Sin medición disponible en la muestra de 7 días |
| BOMBA07016 | BOMBANA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| BTCHTAM009 | BOCA TOMA CHAIREL | Sin medición disponible en la muestra de 7 días |
| CANATAM054 | CANDIDO AGUILAR | Sin medición disponible en la muestra de 7 días |
| CANCU07000 | CANCUC | Sin medición disponible en la muestra de 7 días |
| CARDVER061 | EL CARDON | Sin medición disponible en la muestra de 7 días |
| CDELVER019 | CARDEL | Compatible: 12/12 tramas |
| CEIBPUE003 | LA CEIBA (H1) | Sin medición disponible en la muestra de 7 días |
| CHACCHIA05 | CHACAMAX | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| COMAL27125 | COMALCALCO | OTT: intervalo/cantidad de muestras no coincide con catálogo; Bloque OTT inválido o truncado |
| CORDVER020 | CORDOBA (C1) | OTT: cantidad de bloques no coincide con Sensor |
| COROTAM043 | CORONA | Compatible: 12/12 tramas |
| COSCVER021 | COSCOMATEPEC (C1) | Sin medición disponible en la muestra de 7 días |
| ELSALTOJAL | EL SALTO | Sin medición disponible en la muestra de 7 días |
| EZAPA27121 | EMILIANO ZAPATA | Sin medición disponible en la muestra de 7 días |
| FARGO07012 | FINCA ARGOVIA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| FARITAM002 | GOMEZ FARIAS | Compatible: 12/12 tramas |
| FCHAY07055 | FINCA CHAYABE | Compatible: 12/12 tramas |
| FCUXT07037 | FINCA CUXTEPEQUES | Sin medición disponible en la muestra de 7 días |
| GFALAM0111 | ESTACION ALAMEDA 1 | Compatible: 12/12 tramas |
| GFALAM0212 | ESTACION ALAMEDA 2 | Compatible: 12/12 tramas |
| GFLAGUNA04 | ESTACION LAGUNA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| GFLREYES05 | ESTACION LOS REYES | Compatible: 12/12 tramas |
| GFMOYOTL06 | ESTACION MOYOTLA | Sin medición disponible en la muestra de 7 días |
| GFNECAXA01 | ESTACION NECAXA | Compatible: 12/12 tramas |
| GFNEXAPA03 | ESTACION NEXAPA | Compatible: 12/12 tramas |
| GFTAMBOR10 | ESTACION EL TAMBOR | Compatible: 12/12 tramas |
| GFTEMASC09 | ESTACION TEMASCALES | Sin medición disponible en la muestra de 7 días |
| GFTENANG02 | ESTACION TENANGO | Compatible: 12/12 tramas |
| GFTEPUXT08 | ESTACION TEPUXTEPEC | Compatible: 12/12 tramas |
| GFTEXCAP07 | ESTACION TEXCAPA | Compatible: 12/12 tramas |
| GILPE27119 | PTE GIL PEREZ | Sin medición disponible en la muestra de 7 días |
| GONZA27118 | RIO GONZALEZ | Sin medición disponible en la muestra de 7 días |
| GONZTAM001 | GONZALEZ TAM | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| HUIMA27XXX | HUIMANGUILLO (INIFAP) | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| HUIXT07077 | HUIXTLA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| IGNLR07078 | IGNACIO LOPEZ RAYON | Sin medición disponible en la muestra de 7 días |
| JALCVER017 | PASO DE OVEJAS 2 | Compatible: 12/12 tramas |
| LAESTAM057 | LA ESPERANZA | Sin medición disponible en la muestra de 7 días |
| LAGAV27103 | LOS AGAVES | Sin medición disponible en la muestra de 7 días |
| LENCR07XXX | LA ENCRUCIJADA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| LENCTAM001 | LA ENCANTADA | Compatible: 12/12 tramas |
| LFLOR07102 | LAS FLORES | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| LIDOL27111 | LOS IDOLOS | Sin medición disponible en la muestra de 7 días |
| LLAGA27100 | LA LAGARTERA | Cabecera OTT no soportada |
| LLUPI27101 | LA LUPITA | Compatible: 12/12 tramas |
| LOMAPUE004 | PUENTE PALOMAS (H1) | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| MAGYTAM049 | MAGUEYES | Compatible: 12/12 tramas |
| MALUC27110 | MALUCO | Sin medición disponible en la muestra de 7 días |
| MENDTAM052 | MENDEZ | Sin medición disponible en la muestra de 7 días |
| MICOSLP064 | MICOS | Sin medición disponible en la muestra de 7 días |
| MOLITAM042 | PASO DE MOLINA | Sin medición disponible en la muestra de 7 días |
| MOTOZ07119 | MOTOZINTLA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| NOGATAM059 | LOS NOGALES | Sin medición disponible en la muestra de 7 días |
| PADITAM039 | PADILLA | Sin medición disponible en la muestra de 7 días |
| PAMAVER014 | PALO AMARILLO (H1) | Compatible: 12/12 tramas |
| PASOVER016 | PASO DE OVEJAS (C1) | OTT: cantidad de bloques no coincide con Sensor |
| PAVAPUE001 | PAHUATLAN DEL VALLE (C1) | Compatible: 12/12 tramas |
| PCATA07409 | PLAYA DE CATAZAJA | Compatible: 12/12 tramas |
| PENIT07408 | PEÑITAS | Compatible: 12/12 tramas |
| PHUIT07410 | PUENTE HUITUPÁN | Compatible: 12/12 tramas |
| PILOTAM036 | PILÓN | Compatible: 12/12 tramas |
| POLOTAM003 | NUEVA APOLONIA | OTT: fecha interna fuera de ventana de recepción (-7 días / +5 minutos) |
| POZAVER005 | POZA RICA (HC) | Compatible: 12/12 tramas |
| PSOLI27106 | PUENTE SOLIDARIDAD | Compatible: 12/12 tramas |
| PTONA27120 | PTE TONALA | Compatible: 12/12 tramas |
| PUENVER013 | PUENTE DE LA AUTOPISTA (HC1) | Compatible: 12/12 tramas |
| REALSLP035 | El Realito | Sin medición disponible en la muestra de 7 días |
| REPETAM055 | REPUBLICA ESPAÑOLA | Sin medición disponible en la muestra de 7 días |
| RMACA27042 | REFORMA MACAYO | Compatible: 12/12 tramas |
| SACATAM060 | SACA DE AGUA | Sin medición disponible en la muestra de 7 días |
| SAFETAM051 | SAN FERNANDO | Compatible: 12/12 tramas |
| SANLTAM053 | SAN LORENZO | Sin medición disponible en la muestra de 7 días |
| SCIPR27103 | SAN CIPRIANO | Sin medición disponible en la muestra de 7 días |
| SEMARDEMO1 | Estación Protección Civil | OTT: cantidad de bloques no coincide con Sensor |
| SFELHID062 | SAN FELIPE OCGN | Sin medición disponible en la muestra de 7 días |
| SFRAN07145 | SAN FRANCISCO II | Sin medición disponible en la muestra de 7 días |
| SITAL07000 | SITALA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar |
| SJULI27102 | SANTA JULIA | Sin medición disponible en la muestra de 7 días |
| SMARTAM048 | SAN MARCOS | Sin medición disponible en la muestra de 7 días |
| SOTOTAM047 | SOTO LA MARINA | Compatible: 12/12 tramas |
| SPEDR27040 | SAN PEDRO | Sin medición disponible en la muestra de 7 días |
| SROSSLP021 | SANTA ROSA | Sin medición disponible en la muestra de 7 días |
| STAETAM050 | SANTA ENGRACIA | Sin medición disponible en la muestra de 7 días |
| TANCSLP063 | TANCHACHIN | Compatible: 12/12 tramas |
| TAPIL07167 | TAPILULA | Sin medición disponible en la muestra de 7 días |
| TAPJU27042 | TAPIJULAPA II | Sin medición disponible en la muestra de 7 días |
| TBRAZ27050 | TRES BRAZOS | Sin medición disponible en la muestra de 7 días |
| TECOL27112 | TECOLUTA | Sin medición disponible en la muestra de 7 días |
| TENOS27122 | TENOSIQUE | Sin medición disponible en la muestra de 7 días |
| TEPAVER006 | TEPATLAXCO (C1) | Sin medición disponible en la muestra de 7 días |
| TEPET27116 | TEPETITAN | Sin medición disponible en la muestra de 7 días |
| TLAXPUE002 | TLAXCALANTONGO (C1) | Compatible: 12/12 tramas |
| TOMATAM044 | TOMASEÑO | Sin medición disponible en la muestra de 7 días |
| TOMATAM065 | LOS TOMATES | Sin medición disponible en la muestra de 7 días |
| TOROVER011 | PASO DEL TORO (H2) | Sin medición disponible en la muestra de 7 días |
| VALLTAM046 | PUERTO DE VALLES | Compatible: 12/12 tramas |
| VFLOR07XXX | VILLAFLORES | Sin medición disponible en la muestra de 7 días |
| VGUETAM041 | PRESA VICENTE GUERRERO | Compatible: 12/12 tramas |
| VICTTAM013 | VICTORIA | Sin medición disponible en la muestra de 7 días |
| ZAPAL07099 | ZAPALUTA | Catálogo OTT pero cabecera bB: revisar tipo, no autodetectar; Cabecera OTT no soportada |
| ZONTVER066 | ZONTECOMATLÁN | OTT: Sensor.Orden ausente, inválido o duplicado; no se usan perfiles supuestos |

## Qué falta para cerrar los pendientes

- Sin mediciones: restablecer recepción u obtener una trama original vigente.
- B1 con cantidad discordante: exportación vigente del programa del registrador, lista y orden de canales, intervalos y cobertura; no inferirlos a partir del voltaje.
- Córdoba, Paso de Ovejas y Protección Civil: exportación de canales del registrador; el número de bloques no coincide con Sensor.
- Zontecomatlán: confirmar orden real (todos los órdenes del catálogo son cero).
- El Arenal, Mezcala y Nueva Apolonia: corregir/comprobar reloj interno del registrador; no sustituirlo por la fecha de recepción.
- Comalcalco: obtener más tramas o configuración vigente que confirme el rango.

Los respaldos con mensajes originales permanecen locales y excluidos de Git. No se certifica la salud física de una estación por superar la validación estructural.
