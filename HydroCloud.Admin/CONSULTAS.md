# Consulta pública, histórico y visitas

## Modalidades

- `/` y `/Explore`: portada pública con catálogo de estaciones activas/visibles, mapa, gráfica temporal y tabla.
- Sin sesión: únicamente `[ahora UTC − 7 días, ahora UTC]`. No se limita la lista de variables o productos. Un periodo de un día hace un mes también se rechaza.
- Con sesión: sin límite de antigüedad. Rol `Reader` solo consulta; `Administrator` también administra equipos/estaciones y ve las métricas.
- La política se comprueba en servidor en `/Explore/Data` y `/Explore/Export`, no depende de controles del navegador. No se permite consultar fechas futuras.
- El formulario comienza en «Últimos 7 días (automático)»: omite fechas fijas y cada petición usa la hora actual del servidor. La página puede permanecer abierta sin que caduque su rango predeterminado. Las fechas mostradas se actualizan con la ventana realmente consultada. La descarga automática vuelve a consultar una ventana móvil actualizada; puede variar respecto a una tabla cargada anteriormente.
- «Fechas personalizadas» habilita los controles; no ajusta silenciosamente lo elegido. Si el rango queda fuera de la ventana pública, el mensaje explica cómo volver al modo automático o acceder al histórico.
- Se muestran y exportan como máximo 2,000 filas por petición, con aviso de resultado parcial y nombre CSV `PARCIAL-2000`. Se puede recorrer todo el histórico con rangos menores/resúmenes; todavía no hay exportación masiva asincrónica ni paginación de series.
- Tabla y gráfica muestran las mismas filas. Highstock ofrece zoom, selector de rango y navegador temporal. En modo individual usa el tipo configurado para el sensor en `DB_ATLAS.dbo.TipoSensor.TipoGrafica`; por compatibilidad, instalaciones anteriores pueden resolverlo desde `dbo.Sensor.TipoGrafica`. En modo combinado cada serie conserva su propio tipo, nombre y unidad. Las estadísticas se calculan únicamente sobre las series visibles y no representan el periodo entero si hay truncamiento.
- La presentación individual se especializa sin crear más paneles: nivel de agua se identifica como limnigrama, precipitación como hietograma, caudal como hidrograma, viento como anemograma, temperatura como termograma y presión como barograma. El hietograma superpone además el acumulado progresivo del periodo en un eje secundario; solo se suman aportaciones no negativas y la estadística principal permanece referida a las lecturas incrementales. También se ajustan escalas físicas (precipitación desde cero, humedad 0–100 %, rumbo 0–360°), colores, trazo y precisión del tooltip; `TipoGrafica` continúa determinando la geometría base de Highstock.

## Productos implementados y fuentes

| Producto | PostgreSQL/Timescale | Criterio temporal |
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

Los productos almacenados no se recalculan ni certifican. La ausencia de registros no implica cero ni ausencia de un fenómeno. Los resúmenes legacy pueden contener valores inválidos; el portal muestra lo almacenado. Fechas DATE de resúmenes se presentan como calendario UTC. El resumen horario agrupa mediciones de :01 a la siguiente :00; el diario usa esa misma frontera y cubre desde las 00:01 UTC hasta las 00:00 UTC del día siguiente, de modo que sus acumulados diarios coincidan con la suma de sus horas.

La estación y sus DCP se resuelven con parámetros enlazados desde SQL Server `DB_ATLAS`: `dbo.Estacion` y `dbo.DatosGOES`. El catálogo del mapa incluye exclusivamente estaciones con `Activo=1 AND Visible=1`; ante una interrupción temporal se identifica explícitamente la última copia verificada mientras se reintenta la conexión. Una estación se clasifica como presa cuando `EsPresa=1` o cuando `Nombre` contiene la palabra `PRESA`; esta segunda regla es necesaria porque actualmente las 770 filas activas/visibles tienen `EsPresa=0` y permite identificar 54 registros por su nombre almacenado. Las series y productos hidrometeorológicos se consultan después en PostgreSQL/Timescale `mycloud_timescale`. No se aceptan nombres de tablas ni identificadores DCP arbitrarios del cliente. Los productos GOES no representan transmisiones GPRS/radio. No se exponen payloads crudos, direcciones de servidores, cuentas ni configuración privada.

### Alcance todavía pendiente

Comparación simultánea entre estaciones, unidades amigables vinculadas a cada variable, filtros espaciales/cuencas, exportaciones masivas, informes PDF, curvas derivadas y estadísticas recalculadas de faltantes. Las tablas BHG, FUNVASOS, pronósticos, peligros y modelos hidrológicos tienen otras claves y semánticas; no se ofrecen como productos vinculados a una estación sin validar sus asociaciones. Nueve productos implementados no equivalen a todos los productos posibles de esas bases.

## Mapa

La portada compacta elimina el bloque de bienvenida y la navegación pública redundante, conserva el aviso de siete días en una línea y prioriza el mapa. Leyenda con conteos, filtro de estados, etiquetas en selector y detalle por marcador; no se depende únicamente del color. Las estaciones clasificadas como presa por `EsPresa=1` o por la palabra `PRESA` en su nombre se muestran con un pin distintivo y pueden aislarse con el filtro **Presas**.

Al pasar el puntero por una presa, el tooltip muestra su última lectura de nivel. El catálogo se toma de `DB_ATLAS.dbo.Sensor`, unido a `TipoSensor`, `UnidadMedida` y `DatosGOES`; solo admite los tipos exactos `Nivel de agua` y `Nivel Recipiente`. La lectura se busca en PostgreSQL `mycloud_timescale.public.dcp_datos` mediante la pareja indexada `dcp_id + sensor_id`. Se muestran valor, unidad, fecha UTC, tipo y advertencia cuando `valido=false`. La ausencia de sensor o lectura se declara explícitamente y nunca se sustituye con otro parámetro.

### Semáforo operativo de transmisiones

Cruza los `IDSATELITAL` configurados en `DB_ATLAS.dbo.DatosGOES` con
`mycloud_timescale.public.estatus_estaciones`. La tabla de ingesta conserva la
última TX y el intervalo esperado por DCP; el portal resuelve todos los estados
en una sola consulta y mantiene una caché compartida de 30 segundos.

- Verde: última TX dentro de 1.5 veces el intervalo esperado.
- Amarillo: TX retrasada, entre 1.5 y 3 veces el intervalo esperado.
- Rojo: fuera de línea, por encima de 3 veces el intervalo esperado.
- Rojo oscuro: DCP configurado sin historial de TX.
- Gris: estación sin DCP GOES vinculado, timestamp futuro o consulta fallida.

Para estaciones con varios DCP se conserva el mejor estado operativo comprobado.
La modalidad pública recibe únicamente la categoría, nunca la fecha de última TX.
Las estaciones GPRS/radio sin vínculo GOES permanecen sin verificar hasta contar
con una asociación equivalente para su fuente.

[Leaflet 1.9.4](https://leafletjs.com/download.html) se sirve localmente con su licencia en `wwwroot/vendor/leaflet`. El mapa base se carga automáticamente al abrir la portada; el usuario recibe aviso del proveedor externo. OpenStreetMap recibe la IP/origen de la petición de teselas, aunque el portal no registre IP en sus métricas. Se mantienen atribución y encabezado Referer según la [política de teselas de OSM](https://operations.osmfoundation.org/policies/tiles/). Sin mapa base, el selector de estaciones y las consultas siguen funcionando. Antes de despliegues con tráfico considerable, contratar/configurar un proveedor adecuado; el servicio comunitario no tiene SLA.

El selector de capas ofrece tres fondos mutuamente excluyentes: OpenStreetMap cartográfico, OpenTopoMap para relieve y Esri World Imagery para satélite. Cada proveedor recibe directamente las solicitudes de teselas del navegador y conserva su atribución en Leaflet; revisar sus términos, cuotas y política de privacidad antes de producción. Las estaciones, ciclones y sismos permanecen en grupos locales independientes al cambiar el fondo.

[Anime.js 4.5.0](https://animejs.com/) se sirve localmente desde `wwwroot/vendor/animejs` junto con su licencia MIT. Solo anima la apertura del panel, la transición entre fondos y la entrada limitada de símbolos visibles; no altera coordenadas de Leaflet, limita la animación a 120 elementos y respeta `prefers-reduced-motion`.

## Conteo de visitantes

- Panel `/Explore/Visitors`, solo `Administrator`.
- Contadores diarios UTC: cargas de portada públicas, autenticadas, consultas exitosas y descargas CSV.
- Sin cookies analíticas, IP persistidas, identificadores de visitante ni historial individual. No se calcula visitantes únicos; recargas, solicitudes automáticas y robots pueden incrementar visitas.
- No se contabilizan recursos estáticos como visitas. La descarga implica una consulta nueva con la misma política temporal; si el límite público avanzó, puede ser necesario actualizar el rango.
- Archivo agregado JSON, escritura atómica y exclusión mutua en un solo proceso. Retención de 400 días. No está bajo `wwwroot` y se ignora en git.
- Configurar `Analytics__Path` a un archivo persistente fuera del directorio de publicación, por ejemplo `/ruta/persistente/visitors.json`. Si falla la escritura, el portal no interrumpe la consulta y registra un error operativo; las métricas pueden quedar incompletas. Respaldar el archivo y vigilar esos errores.
- Para varias réplicas se requiere una base transaccional compartida; este almacenamiento no debe compartirse entre varios procesos.

## Configuración adicional

`ConnectionStrings__Atlas`: conexión de solo lectura a SQL Server `DB_ATLAS`, usada para el catálogo `dbo.Estacion` y la relación `dbo.DatosGOES`.

`ConnectionStrings__Postgres`: conexión de solo lectura a PostgreSQL `mycloud_timescale`, usada tanto por la consulta temporal como por los niveles y condiciones del mapa. Usar un usuario con SELECT sobre las nueve fuentes en producción. La aplicación no realiza DDL ni DML en ese esquema.

`Consultation__Username` y `Consultation__PasswordHash`: cuenta lectora de consulta histórica, distinta de `Admin__Username`. Generar el hash con el comando existente `--hash-password`. No hay registro público de cuentas ni restablecimiento de contraseña implementado. La configuración de cuenta lectora es una primera modalidad local, no un directorio multiusuario.

Límite de 60 peticiones/minuto por IP para endpoints de consulta y 60 segundos por comando PostgreSQL. Detrás de un proxy, configurar proxies confiables antes de usar IP reenviada; nunca confiar en encabezados arbitrarios. TLS requerido para despliegue público. Respuestas de consulta y panel de visitas no se almacenan en caché HTTP.

## Verificación

`dotnet run --project HydroCloud.Admin.Tests`: pruebas de estaciones/equipos, frontera exacta de siete días, rechazo de periodos antiguos cortos, zona horaria, CSV seguro y conteo concurrente/persistencia.

`python3 HydroCloud.Admin.Tests/smoke_explore.py`: requiere las dos conexiones por entorno. Arranca temporalmente en 5091 y prueba los nueve productos con Oracle real, restricciones públicas en datos/CSV, histórico con lector, denegación de administración al lector, estadísticas privadas y exportación. Solo lee Oracle; sus métricas se guardan en un directorio temporal. No valida visualmente la carga de teselas del proveedor.
