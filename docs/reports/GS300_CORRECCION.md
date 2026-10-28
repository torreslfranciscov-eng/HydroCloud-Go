# Corrección de configuración GS300

El decoder carga estaciones y sensores desde `HYDROCLOUD.DATOSGOES`,
`ESTACION`, `SENSOR` y `TIPOSENSOR`. No reconstruye el catálogo a partir de
lecturas históricas ni fuerza periodo de 60 minutos o dos decimales.

- Primera transmisión: fase UTC, incluyendo segundos.
- Intervalo de transmisión: frecuencia de envío/descarga (+120 segundos).
- Rango de transmisión: duración del bloque de mediciones; determina posiciones
  junto con el periodo de cada sensor. No programa las descargas.
- Los mensajes GS300 cuya cantidad de valores no coincide con el catálogo no
  se insertan. Una configuración rechazada se registra explícitamente.
- La conversión binaria y las reglas existentes de fechas de muestras no se
  cambiaron. El significado temporal del prefijo de cuatro caracteres todavía
  requiere validación; no afirmar que los timestamps se corrigieron.

## Acceso al catálogo

La cuenta de ingesta MYCLOUD_TS no tiene acceso a HYDROCLOUD.SENSOR (verificado
con consulta de solo lectura). Se añadió una conexión independiente mediante:

```
ORACLE_CATALOG_USER
ORACLE_CATALOG_PASSWORD
ORACLE_CATALOG_DSN
```

También admite la sección `[oracle_catalog]` con `user`, `password`, `dsn`.
Si no se especifica DSN, usa el de `[oracle_cloud]`/`ORACLE_DSN`.
Inyectar las credenciales mediante el gestor de secretos del servicio; no
guardarlas en el repositorio. No se otorgaron permisos nuevos ni se cambió
la cuenta que escribe las mediciones.

## Validación y activación

`python3 -m unittest test_gs300_config -v` prueba posiciones, longitud estricta,
periodo distinto de rango, segundos, medianoche y valores de un mensaje real.

San Bartolo AC52E1BC: primera 00:55:35, intervalo 60 min, rango 60 min.
Catálogo: lluvia cada minuto (60 valores), batería y temperatura cada hora
(1 valor cada una). Mensaje del 28/09/2026 16:55:35: batería 13.60 V,
temperatura 26.50 °C. Se verificaron cargadores contra Oracle sin escrituras.

No se inició la ingesta ni se reprocesó el histórico. No había un proceso
`mycloud_all_timescale.py` activo en el equipo al verificar. Antes de arrancar,
configurar acceso al catálogo y revisar las estaciones rechazadas. El arranque
existente ejecuta sincronización y revalidación de datos; no usar un import del
módulo principal como prueba de solo lectura. Un reprocesamiento histórico debe
ser una operación separada con alcance y respaldo definidos.
