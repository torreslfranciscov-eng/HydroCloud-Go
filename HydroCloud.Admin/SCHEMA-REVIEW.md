# Revisión funcional de HYDROCLOUD

Inspección de Oracle realizada el 25/09/2026: tablas, columnas, nulabilidad, precisión, claves, identidades, conteos y registros representativos. No se modificó la base para desarrollar o probar los formularios.

## Módulos de la ficha técnica

| Módulo | Tabla | Registros observados | Relación y alcance |
| --- | --- | ---: | --- |
| GOES | DATOSGOES | 742 | IDESTACION; DCP, satélite, canales, velocidades, horarios, decodificador |
| GPRS | DATOSGPRS | 183 | IDESTACION; periodo y comentarios |
| Radio | DATOSRADIO | 18 | IDESTACION; periodo y comentarios |
| Sensores | SENSOR | 7,314 | IDESTACION, IDTIPOSENSOR, IDUNIDADMEDIDA; muestreo, límites, decimales, cota, disponibilidad |
| Cotas | COTASENSOR | 9 | IDSENSOR → SENSOR → ESTACION; valor, operador, vigencia, finalización |
| Componentes | COMPONENTE_ESTACION | 1 | IDESTACION; equipo, marca, modelo, serie y condición |
| Inventario de sensores | COMP_SENSORINVENTARIO | 1 | IDESTACION; sensor físico, cableado y soportes; no confundir con SENSOR |
| Tipos (selección) | TIPOSENSOR | 59 | Catálogo global; no se edita desde la ficha |
| Unidades (selección) | UNIDADMEDIDA | 26 | Catálogo global; no se edita desde la ficha |

No se encontraron huérfanos de estación en DATOSGOES, DATOSGPRS, DATOSRADIO o SENSOR durante la revisión. Estas relaciones no tienen claves foráneas declaradas en la base migrada. Solo se observaron seis claves foráneas en todo el esquema (inventarios/bitácoras y estatus de estación). Por ello el servidor valida los vínculos y restringe consultas/escrituras por estación. No se agregaron restricciones ni se alteraron secuencias en producción.

Las configuraciones y cotas tienen ID numérico con identidad BY DEFAULT; el portal omite el ID al insertar y recupera el generado. SENSOR usa UUID. Antes de las pruebas de escritura sobre una copia, comprobar que las identidades migradas están por encima de los máximos existentes; el portal no usa MAX(ID)+1.

## Integridad y efectos

- Los siete módulos son una lista cerrada. No hay editor SQL ni posibilidad de elegir otra tabla desde la URL.
- Se conservan nulos y se respetan campos obligatorios, longitudes y escalas de Oracle.
- Los contadores TRANSMITE, ESPERADOS, RECIBIDOS y estados FUNCIONA/VALIDO son de solo lectura; no se inventa una semántica de baja para estos indicadores.
- Alta/edición: transacción, bloqueo de estación, comprobación de versión del registro y auditoría en columnas existentes. Los campos de auditoría no se aceptan del navegador.
- Duplicados de número de sensor y cotas abiertas se comprueban dentro de la transacción bajo bloqueo de estación. Otros escritores externos que no usen este bloqueo todavía pueden producir duplicados: falta una política de restricciones compartida con el sistema de adquisición.
- No se modifican tipos o unidades globales ni se reasigna un sensor a otra estación. Una cota solo puede vincularse a sensores de la estación actual.
- Baja de SENSOR: ACTIVO=0, VISIBLE=0. Finalizar COTASENSOR: FIN=1, conserva fechas existentes. Solo DATOSGOES/GPRS/RADIO ofrecen borrado físico de configuración, con confirmación y advertencia; esto no borra mediciones, pero puede afectar adquisición.
- Crear/eliminar una configuración actualiza ESTACION.GOES/GPRS/RADIO en la misma transacción. Una edición general de estación no crea configuraciones automáticamente.
- Las fechas de auditoría nuevas se expresan en UTC; las fechas de vigencia de cotas se conservan como fecha/hora sin conversión de zona. Las cadenas legacy pueden tener formatos distintos. Revisar el ordenamiento de fechas de texto en consumidores antes del uso operativo.
- Los logs identifican actor, estación y operación; no constituyen un historial inmutable ni copia recuperable de configuraciones eliminadas.

## Áreas relacionadas todavía pendientes

| Área | Relaciones observadas | Por qué requiere módulo propio |
| --- | --- | --- |
| Configuración por cliente | ESTACIONCLIENTE, SENSORCLIENTE | Copias/visibilidad por cliente distintas del catálogo central |
| Umbrales y alertas | SENSORCLIENTEUMBRAL, UMBRALALERTAS, ALERTANIVEL, ALERTAPRECIPITACION, ALERTATRANSMISION | Destinatarios, clientes, sensores, periodos y notificaciones; no son solo campos de estación |
| Bitácoras y documentos | BITACORAESTACION, DOCUMENTOESTACION, BITACORAINVENTARIOESTACION, BITACORAINVENTARIOSENSOR | Eventos, autores, adjuntos e historial de mantenimiento |
| Gasto y elevación | TABLAGASTO, TABLAGASTODEFINICION, TABLAELEVACION y tablas de detalle | Curvas y conversiones vinculadas también a SENSORCLIENTE |
| Usuarios y permisos | ASPNETUSERS/ROLES y asociaciones | El acceso temporal del portal no administra ni migra las cuentas legacy |
| Mediciones | Esquema MYCLOUD_TS | Consulta temporal, calidad y agregaciones; no se modifican desde la ficha técnica |

El colector del repositorio consulta números de sensor, tipo, precisión, muestreo, límites y cotas. No se cambió ni reinició el colector durante esta ampliación. Hay que verificar su fuente de configuración y mecanismo de recarga antes de prometer que una modificación del portal tiene efecto inmediato en la adquisición.
