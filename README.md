# HydroCloud-Go - Non-Blocking LRGS Satellite & Analytical Service

High-performance Go / Python ingestion service for LRGS satellite telemetry data, featuring non-blocking post-processing queue, real-time terminal logging, and Oracle Cloud Autonomous Database support.

## Migration & DB Setup

This workspace contains a restartable migration utility for moving SQL Server `DB_ATLAS` and PostgreSQL/TimescaleDB `mycloud_timescale` into Oracle schema `MYCLOUD_TS`.

Required environment variables for deployment (e.g., Render / Docker):

- `DB_BACKEND`: `oracle` (or `postgres`)
- `ORACLE_USER`: `MYCLOUD_TS`
- `ORACLE_PASSWORD`: `<your-oracle-password>`
- `ORACLE_DSN`: `(description=(retry_count=20)(retry_delay=3)...)`

## Deployment

Configured for containerized 24/7 background execution via Dockerfile / `render.yaml`.

## Administración web en .NET

El proyecto [HydroCloud.Admin](HydroCloud.Admin/README.md) administra el catálogo
`HYDROCLOUD.ESTACION` con ASP.NET Core MVC: altas, edición, búsqueda y bajas lógicas.
Tiene autenticación propia y no cambia el despliegue del colector Python.
Consulta su README para configurar los secretos, ejecutarlo y publicarlo.
