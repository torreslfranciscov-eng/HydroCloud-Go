# DB_ATLAS to Oracle Autonomous Database

This workspace contains a one-time, restartable migration utility for moving
the SQL Server `DB_ATLAS` database into the dedicated Oracle schema
`HYDROCLOUD`.

The separate `migrate_timescale_to_oracle.py` utility migrates the logical
schemas of PostgreSQL/TimescaleDB `mycloud_timescale` into Oracle schema
`MYCLOUD_TS`. PostgreSQL schema names are mapped with prefixes: no prefix for
`public`, `HM_` for `hydro_model`, and `RF_` for `rain_forecast`.

No credentials are stored in this repository. The utility reads connection
details from environment variables and writes a validation summary to
`migration-report.json`.

Required variables:

- `SOURCE_HOST`, `SOURCE_PORT`, `SOURCE_DATABASE`, `SOURCE_USER`, `SOURCE_PASSWORD`
- `TARGET_USER`, `TARGET_PASSWORD`, `TARGET_DSN`

Set `MIGRATION_RESET=1` only when replacing a partial migration. It drops
objects owned by the connected target schema, never objects in `ADMIN`.

## Compatibility notes

- Oracle treats an empty string as `NULL`; empty strings in required text
  columns are represented by one space and counted in the migration report.
- `NV_UltimaBitacoraEstacion` projects its three `NCLOB` display fields to
  2,000 characters because Oracle cannot apply `DISTINCT` directly to LOBs.
