# Consulta pública, histórico y visitas

## Modalidades

- `/` y `/Explore`: portada pública con catálogo de estaciones activas/visibles, mapa, gráfica temporal y tabla.
- Sin sesión: únicamente `[ahora UTC − 7 días, ahora UTC]`. No se limita la lista de variables o productos. Un periodo de un día hace un mes también se rechaza.
- Con sesión: sin límite de antigüedad. Rol `Reader` solo consulta; `Administrator` también administra equipos/estaciones y ve las métricas.
- La política se comprueba en servidor en `/Explore/Data` y `/Explore/Export`, no depende de controles del navegador. No se permite consultar fechas futuras.
- El formulario comienza en «Últimos 7 días (automático)»: omite fechas fijas y cada petición usa la hora actual del servidor. La página puede permanecer abierta sin que caduque su rango predeterminado. Las fechas mostradas se actualizan con la ventana realmente consultada. La descarga automática vuelve a consultar una ventana móvil actualizada; puede variar respecto a una tabla cargada anteriormente.
- «Fechas personalizadas» habilita los controles; no ajusta silenciosamente lo elegido. Si el rango queda fuera de la ventana pública, el mensaje explica cómo volver al modo automático o acceder al histórico.
- Se muestran y exportan como máximo 2,000 filas por petición, con aviso de resultado parcial y nombre CSV `PARCIAL-2000`. Se puede recorrer todo el histórico con rangos menores/resúmenes; todavía no hay exportación masiva asincrónica ni paginación de series.
- Tabla y gráfica muestran las mismas filas. El selector de serie evita mezclar sensores/variables en una sola escala. La gráfica es de puntos: no interpola valores faltantes. Estadísticas de gráfica calculadas únicamente sobre la serie mostrada; no representan el periodo entero si hay truncamiento.

## Productos implementados y fuentes

| Producto | MYCLOUD_TS | Criterio temporal |
| --- | --- | --- |
| Lecturas y calidad | DCP_DATOS | TS |
| Resumen horario | RESUMEN_HORARIO | Hora completa dentro del rango |
| Resumen diario | RESUMEN_DIARIO | Día completo dentro del rango |
| Transmisiones y señal GOES | DCP_HEADERS | TS de recepción |
| Intentos de recepción GOES | BITACORA_GOES | TIMESTAMP_UTC |
| Eficiencia diaria GOES | DIAGNOSTICO_DIARIO_GOES | Día completo dentro del rango |
| Acumulados de lluvia | LLUVIA_ACUMULADA | Inicio y fin dentro del rango |
| Eventos de lluvia | EVENTOS_LLUVIA | Inicio y fin/última actualización dentro del rango |
| Alertas de lluvia registradas | ALERTAS_PRECIPITACION | TS |

Los productos almacenados no se recalculan ni certifican. La ausencia de registros no implica cero ni ausencia de un fenómeno. Los resúmenes legacy pueden contener valores inválidos; el portal muestra lo almacenado. Fechas DATE de resúmenes se presentan como calendario UTC; revisar esta convención si se redefine la fecha hidrológica del productor.

La estación y sus DCP se resuelven desde HYDROCLOUD con parámetros enlazados. No se aceptan nombres de tablas ni identificadores DCP arbitrarios del cliente. Los productos GOES no representan transmisiones GPRS/radio: no se encontró un histórico equivalente de esos canales. No se exponen payloads crudos, direcciones de servidores, cuentas ni configuración privada.

### Alcance todavía pendiente

Comparación simultánea entre estaciones, unidades amigables vinculadas a cada variable, filtros espaciales/cuencas, exportaciones masivas, informes PDF, curvas derivadas y estadísticas recalculadas de faltantes. Las tablas BHG, FUNVASOS, pronósticos, peligros y modelos hidrológicos tienen otras claves y semánticas; no se ofrecen como productos vinculados a una estación sin validar sus asociaciones. Nueve productos implementados no equivalen a todos los productos posibles de esas bases.

## Mapa

La portada compacta elimina el bloque de bienvenida y la navegación pública redundante, conserva el aviso de siete días en una línea y prioriza el mapa. Leyenda con conteos, filtro de estados, etiquetas en selector y detalle por marcador; no se depende únicamente del color.

### Semáforo de presencia de mediciones

Consulta directa de `DCP_DATOS` y `DCP_HEADERS`, enlazada por `ID_ASIGNADO` y los `IDSATELITAL` configurados en `DATOSGOES`. Usa el prefijo DCP del índice existente, cuatro consultas concurrentes como máximo, plazo total de 55 segundos y caché compartida. Los marcadores aparecen antes de terminar la verificación.

- Verde: existe alguna medición en las últimas 24 horas.
- Naranja: existe una transmisión GOES real en las últimas 24 horas, pero no
  produjo mediciones decodificadas. Indica contenido truncado, corrupto o
  incompatible con el decodificador o catálogo configurado; no equivale a una
  estación apagada.
- Amarillo: existe alguna medición en siete días, pero ninguna en 24 horas.
- Rojo: existe histórico asociado, pero ninguna medición en siete días.
- Rojo oscuro: no se encontraron mediciones asociadas a la clave y los DCP actualmente configurados. No equivale a afirmar que nunca haya datos con otra clave/DCP histórico.
- Gris: falta vínculo DCP verificable o una consulta falló/agotó su tiempo. Nunca se interpreta un error como ausencia de datos.

Ventanas UTC móviles calculadas en servidor; se excluyen timestamps futuros. Para varios DCP se combina la evidencia; un error sin evidencia de transmisión o datos en 24 horas deja el estado sin verificar. El verde consulta `DCP_DATOS`; el naranja exige una fila reciente y real en `DCP_HEADERS` —excluye avisos `Missing message` y `SATLINK DATA BUFFER EMPTY`— sin medición reciente decodificada. La modalidad pública solo recibe categorías, no fechas ni valores antiguos. Estaciones GPRS/radio sin vínculo GOES quedan sin verificar hasta contar con un índice/asociación adecuado para su fuente. No se usa `ULTIMAS_MEDICIONES`: la inspección encontró ese resumen atrasado frente a la tabla de lecturas.

[Leaflet 1.9.4](https://leafletjs.com/download.html) se sirve localmente con su licencia en `wwwroot/vendor/leaflet`. El mapa base se carga automáticamente al abrir la portada; el usuario recibe aviso del proveedor externo. OpenStreetMap recibe la IP/origen de la petición de teselas, aunque el portal no registre IP en sus métricas. Se mantienen atribución y encabezado Referer según la [política de teselas de OSM](https://operations.osmfoundation.org/policies/tiles/). Sin mapa base, el selector de estaciones y las consultas siguen funcionando. Antes de despliegues con tráfico considerable, contratar/configurar un proveedor adecuado; el servicio comunitario no tiene SLA.

## Conteo de visitantes

- Panel `/Explore/Visitors`, solo `Administrator`.
- Contadores diarios UTC: cargas de portada públicas, autenticadas, consultas exitosas y descargas CSV.
- Sin cookies analíticas, IP persistidas, identificadores de visitante ni historial individual. No se calcula visitantes únicos; recargas, solicitudes automáticas y robots pueden incrementar visitas.
- No se contabilizan recursos estáticos como visitas. La descarga implica una consulta nueva con la misma política temporal; si el límite público avanzó, puede ser necesario actualizar el rango.
- Archivo agregado JSON, escritura atómica y exclusión mutua en un solo proceso. Retención de 400 días. No está bajo `wwwroot` y se ignora en git.
- Configurar `Analytics__Path` a un archivo persistente fuera del directorio de publicación, por ejemplo `/ruta/persistente/visitors.json`. Si falla la escritura, el portal no interrumpe la consulta y registra un error operativo; las métricas pueden quedar incompletas. Respaldar el archivo y vigilar esos errores.
- Para varias réplicas se requiere una base transaccional compartida; este almacenamiento no debe compartirse entre varios procesos.

## Configuración adicional

`ConnectionStrings__TimeSeries`: conexión a MYCLOUD_TS. Usar un usuario de solo lectura con SELECT sobre las nueve fuentes en producción. La aplicación no realiza DDL ni DML en ese esquema.

`Consultation__Username` y `Consultation__PasswordHash`: cuenta lectora de consulta histórica, distinta de `Admin__Username`. Generar el hash con el comando existente `--hash-password`. No hay registro público de cuentas ni restablecimiento de contraseña implementado. La configuración de cuenta lectora es una primera modalidad local, no un directorio multiusuario.

Límite de 60 peticiones/minuto por IP para endpoints de consulta y 30 segundos por comando Oracle. Detrás de un proxy, configurar proxies confiables antes de usar IP reenviada; nunca confiar en encabezados arbitrarios. TLS requerido para despliegue público. Respuestas de consulta y panel de visitas no se almacenan en caché HTTP.

## Verificación

`dotnet run --project HydroCloud.Admin.Tests`: pruebas de estaciones/equipos, frontera exacta de siete días, rechazo de periodos antiguos cortos, zona horaria, CSV seguro y conteo concurrente/persistencia.

`python3 HydroCloud.Admin.Tests/smoke_explore.py`: requiere las dos conexiones por entorno. Arranca temporalmente en 5091 y prueba los nueve productos con Oracle real, restricciones públicas en datos/CSV, histórico con lector, denegación de administración al lector, estadísticas privadas y exportación. Solo lee Oracle; sus métricas se guardan en un directorio temporal. No valida visualmente la carga de teselas del proveedor.
