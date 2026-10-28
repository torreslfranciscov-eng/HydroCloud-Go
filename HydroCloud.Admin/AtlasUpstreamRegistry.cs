using Microsoft.Data.SqlClient;

namespace HydroCloud.Admin;

public static class AtlasUpstreamRegistry
{
    public static async Task<int> Apply(IConfiguration config,CancellationToken ct=default)
    {
        var connectionString=config.GetConnectionString("Atlas");
        if(string.IsNullOrWhiteSpace(connectionString))throw new InvalidOperationException("La conexión Atlas no está configurada.");
        const string sql="""
IF OBJECT_ID('dbo.EstacionAguasArriba','U') IS NULL
BEGIN
    CREATE TABLE dbo.EstacionAguasArriba(
        IdPresa uniqueidentifier NOT NULL,
        IdEstacion uniqueidentifier NOT NULL,
        Rio nvarchar(120) NOT NULL,
        EstadoRelacion varchar(20) NOT NULL,
        Prioridad tinyint NOT NULL,
        Fuente nvarchar(500) NULL,
        Activo bit NOT NULL CONSTRAINT DF_EstacionAguasArriba_Activo DEFAULT(1),
        CreadoUtc datetime2(0) NOT NULL CONSTRAINT DF_EstacionAguasArriba_CreadoUtc DEFAULT(SYSUTCDATETIME()),
        CONSTRAINT PK_EstacionAguasArriba PRIMARY KEY(IdPresa,IdEstacion),
        CONSTRAINT FK_EstacionAguasArriba_Presa FOREIGN KEY(IdPresa) REFERENCES dbo.Estacion(Id),
        CONSTRAINT FK_EstacionAguasArriba_Estacion FOREIGN KEY(IdEstacion) REFERENCES dbo.Estacion(Id),
        CONSTRAINT CK_EstacionAguasArriba_Estado CHECK(EstadoRelacion IN ('confirmada','candidata'))
    );
END;

DECLARE @Presa uniqueidentifier='DC9CFEF6-44D4-40C7-A11C-615EA8319EFA';
DECLARE @Fuente nvarchar(500)='DOF: Estudios técnicos de aguas nacionales superficiales, Alto Grijalva, publicación 2010-04-29';
DECLARE @Relaciones TABLE(IdEstacion uniqueidentifier,Rio nvarchar(120),EstadoRelacion varchar(20),Prioridad tinyint);
INSERT INTO @Relaciones VALUES
('296194E9-6440-4335-A8F9-C1EDDCA9DC6B','Selegua / San Gregorio','confirmada',1),
('3AD2FEFB-0A47-48B6-BDF7-CE3F11D08712','Cuilco / Alto Grijalva','confirmada',1),
('7CE2FA82-E0B0-479A-9D88-9E8295E78470','San Miguel','confirmada',1),
('5A0BF077-9A84-443B-BEE0-42F4BB3C0180','Custepeques / La Concordia','confirmada',2),
('6162BBD1-2356-4BCF-8A90-ECA705C45E16','El Dorado / San Pedro','confirmada',2),
('A302ADE2-EDE4-438A-A1C9-095F88CDCFDC','Jaltenango','candidata',3);

UPDATE target SET Rio=source.Rio,EstadoRelacion=source.EstadoRelacion,Prioridad=source.Prioridad,Fuente=@Fuente,Activo=1
FROM dbo.EstacionAguasArriba target JOIN @Relaciones source ON source.IdEstacion=target.IdEstacion
WHERE target.IdPresa=@Presa;

INSERT dbo.EstacionAguasArriba(IdPresa,IdEstacion,Rio,EstadoRelacion,Prioridad,Fuente)
SELECT @Presa,source.IdEstacion,source.Rio,source.EstadoRelacion,source.Prioridad,@Fuente
FROM @Relaciones source
WHERE EXISTS(SELECT 1 FROM dbo.Estacion WHERE Id=@Presa)
  AND EXISTS(SELECT 1 FROM dbo.Estacion WHERE Id=source.IdEstacion)
  AND NOT EXISTS(SELECT 1 FROM dbo.EstacionAguasArriba target WHERE target.IdPresa=@Presa AND target.IdEstacion=source.IdEstacion);

SELECT COUNT(*) FROM dbo.EstacionAguasArriba WHERE IdPresa=@Presa AND Activo=1;
""";
        await using var connection=new SqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var command=new SqlCommand(sql,connection){CommandTimeout=30};
        return Convert.ToInt32(await command.ExecuteScalarAsync(ct));
    }
}
