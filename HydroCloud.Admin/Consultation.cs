using System.Globalization;
using System.Security.Claims;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Data.SqlClient;
using Npgsql;
using NpgsqlTypes;
using Oracle.ManagedDataAccess.Client;

namespace HydroCloud.Admin;

public record QueryWindow(DateTimeOffset Start,DateTimeOffset End)
{
    public const string PublicNotice="Consulta libre: únicamente los últimos 7 días. Todas las variables y productos disponibles están incluidos. Inicia sesión para consultar periodos anteriores.";
    public static QueryWindow Create(DateTimeOffset? start,DateTimeOffset? end,bool authenticated,DateTimeOffset now)
    {
        var window=new QueryWindow((start??now.AddDays(-7)).ToUniversalTime(),(end??now).ToUniversalTime());
        if(window.Start>=window.End) throw new ArgumentException("La fecha inicial debe ser anterior a la final.");
        if(window.End>now) throw new ArgumentException("La fecha final no puede estar en el futuro.");
        if(!authenticated && window.Start<now.AddDays(-7)) throw new ArgumentException("La fecha inicial quedó fuera de los últimos 7 días. Selecciona «Últimos 7 días (automático)» y vuelve a consultar, o inicia sesión para consultar ese periodo histórico.");
        return window;
    }
}
public record QueryProduct(string Key,string Title,string Table,string Time,string Columns,string Scope="ID_ASIGNADO",string? End=null,string? Bucket=null)
{
    public static readonly QueryProduct[] All=[
        new("variables","Variables · lecturas y calidad","DCP_DATOS","TS","TS,SENSOR_ID,VARIABLE,VALOR,VALIDO,DESCRIPCION"),
        new("horario","Variables · resumen horario","RESUMEN_HORARIO","TS","TS,SENSOR_ID,VARIABLE,CONTEO,PROMEDIO,MINIMO,MAXIMO,ACUMULADO",Bucket:"hour"),
        new("diario","Variables · resumen diario","RESUMEN_DIARIO","FECHA","FECHA,SENSOR_ID,VARIABLE,CONTEO,PROMEDIO,MINIMO,MAXIMO,ACUMULADO",Bucket:"day"),
        new("transmisiones","GOES · transmisiones y mensajes","DCP_HEADERS","TIMESTAMP_MSG","TIMESTAMP_MSG,DCP_ID,TS,SIGNAL_STRENGTH,FREQUENCY_OFFSET,MOD_INDEX,CHANNEL,SPACECRAFT,FAILURE_CODE,DATA_QUALITY,RAW_MESSAGE","DCP_ID"),
        new("recepcion","GOES · intentos de recepción","BITACORA_GOES","TIMESTAMP_UTC","TIMESTAMP_UTC,DCP_ID,EXITO","DCP_ID"),
        new("eficiencia","GOES · eficiencia diaria","DIAGNOSTICO_DIARIO_GOES","FECHA","FECHA,DCP_ID,TX_PROGRAMADAS,TX_RECIBIDAS,PORCENTAJE_EFICIENCIA,POTENCIA_PROM,POTENCIA_MIN,POTENCIA_MAX,CALIDAD_SENAL,ESTADO_OPERATIVO",Bucket:"day"),
        new("lluvia","Lluvia · acumulados por periodo","LLUVIA_ACUMULADA","PERIODO_INICIO","PERIODO_INICIO,PERIODO_FIN,SENSOR_ID,VARIABLE,TIPO_PERIODO,ACUMULADO,HORAS_CON_DATO",End:"PERIODO_FIN"),
        new("eventos","Lluvia · eventos","EVENTOS_LLUVIA","INICIO","INICIO,FIN,SENSOR_ID,ACUMULADO_MM,INTENSIDAD_MAX_MMH,DURACION_MINUTOS,ESTADO,SOSPECHOSO,MOTIVO_SOSPECHA",End:"COALESCE(FIN,ULTIMA_ACTUALIZACION)"),
        new("alertas","Lluvia · alertas registradas","ALERTAS_PRECIPITACION","TS","TS,SENSOR_ID,UMBRAL_NOMBRE,VALOR_REFERENCIA,VALOR_MEDIDO,PERIODO_MINUTOS,ACTIVA")
    ];
    public static readonly QueryProduct SensorCatalog=new("sensorcatalog","Variables disponibles","DCP_DATOS","TS","SENSOR_ID,VARIABLE");
    public static QueryProduct? Find(string key)=>All.SingleOrDefault(x=>x.Key==key);
}
public record PublicStation(string Id,string Code,string Name,double? Latitude,double? Longitude,bool Goes,bool Gprs,bool Radio,bool IsDam,int SensorCount,int DcpCount,string? BasinId=null,string? UserId=null);
public record UpstreamStation(string DamStationId,string StationId,string Code,string Name,double? Latitude,double? Longitude,string River,string RelationStatus,int Priority);
public record UpstreamMetric(string SensorType,string Unit,double? Value,DateTimeOffset? Timestamp,bool? Valid,double? PreviousValue,DateTimeOffset? PreviousTimestamp,bool? PreviousValid);
public record UpstreamCondition(string DamStationId,string StationId,UpstreamMetric? Level,double? Rain1Hour,double? Rain6Hours,string RainUnit,DateTimeOffset? RainTimestamp,UpstreamMetric? Flow,UpstreamMetric? WaterVelocity);
public record LevelPoint(DateTimeOffset Timestamp,double Value);
public record LatestLevel(string StationId,bool SensorConfigured,string? SensorId,string? SensorType,string? Unit,double? Value,DateTimeOffset? Timestamp,bool? Valid,double? PreviousValue,DateTimeOffset? PreviousTimestamp,bool? PreviousValid,List<LevelPoint> History);
public record QuerySeries(string SensorId,string Name,string Unit,string ConfiguredChartType,int Decimals=0,double PeriodMinutes=10,int Order=999,bool IsCalculated=false,double? MinValue=null,double? MaxValue=null);
public record GoesScheduleInfo(string DcpId,string FirstTransmission,string Interval,string Window,int? Channel,string Satellite,string Decoder,int ExpectedPerDay,int RangeMinutes=60);
public record QueryData(string Product,QueryWindow Window,List<string> Columns,List<Dictionary<string,object?>> Rows,List<QuerySeries> Series,bool Truncated,string Note,GoesScheduleInfo? GoesSchedule=null);
public record SaasUser(Guid Id, string Email, string PasswordHash, string Nombre, string Plan, string? PaypalSubscriptionId, bool Activo, DateTimeOffset CreadoEl);
public record SaasUserGroup(Guid Id, Guid IdUsuario, string Nombre, string? Descripcion, string[] Estaciones, DateTimeOffset CreadoEl, DateTimeOffset ActualizadoEl);
public record SaasRegisterRequest(string Email, string Password, string Nombre);
public record SaasLoginRequest(string Email, string Password);
public record SaasSaveGroupRequest(Guid? Id, string Nombre, string? Descripcion, string[] Estaciones);
public record SaasDeleteGroupRequest(Guid Id);
public record PayPalSubscriptionConfirm(string SubscriptionId, string? PayerId, string? Plan = "PRO");

public record UserSensorInput(string TipoSensorId, string? NumeroSensor, int Orden, int Decimals = 1, double Min = 0, double Max = 100);
public record UserStationInput(
    string? Id,
    string Code,
    string Name,
    double Latitude,
    double Longitude,
    string? BasinId,
    string DcpId,
    string FirstTransmission,
    string Interval,
    int Channel = 169,
    string Satellite = "GOES-E",
    int BaudRate = 300,
    string Decoder = "GS300",
    List<UserSensorInput>? Sensors = null
);
public record UserSensorDetail(string Id, string NumeroSensor, string TipoSensorId, string TipoSensorNombre, int Orden, int Decimals, double Min, double Max);
public record UserStationDetail(
    string Id,
    string Code,
    string Name,
    double Latitude,
    double Longitude,
    string? BasinId,
    string? BasinName,
    string DcpId,
    string FirstTransmission,
    string Interval,
    int Channel,
    string Satellite,
    int BaudRate,
    string Decoder,
    bool Activo,
    List<UserSensorDetail> Sensors
);

public interface IConsultationRepository
{
    Task<List<PublicStation>> Stations(Guid? currentUserId = null, CancellationToken cancellation = default);
    Task<List<UpstreamStation>> UpstreamStations(CancellationToken cancellation);
    Task<List<UpstreamCondition>> UpstreamConditions(CancellationToken cancellation);
    Task<List<LatestLevel>> LatestDamLevels(CancellationToken cancellation);
    Task<QueryData> Query(string stationId,QueryProduct product,QueryWindow window,CancellationToken cancellation,string? sensorId=null,string? variable=null);
    Task<SaasUser?> FindSaasUserByEmail(string email, CancellationToken cancellation = default);
    Task<SaasUser?> FindSaasUserById(Guid id, CancellationToken cancellation = default);
    Task<SaasUser> CreateSaasUser(string email, string passwordHash, string nombre, CancellationToken cancellation = default);
    Task<List<SaasUserGroup>> GetUserGroups(Guid userId, CancellationToken cancellation = default);
    Task<int> CountUserGroups(Guid userId, CancellationToken cancellation = default);
    Task<SaasUserGroup> SaveUserGroup(Guid userId, Guid? groupId, string nombre, string? descripcion, string[] estaciones, CancellationToken cancellation = default);
    Task<bool> DeleteUserGroup(Guid userId, Guid groupId, CancellationToken cancellation = default);
    Task<bool> UpdateUserPlan(Guid userId, string plan, string? subscriptionId = null, string? payerId = null, CancellationToken cancellation = default);
    Task<bool> DeleteSaasAccount(Guid userId, CancellationToken cancellation = default);
    Task<int> CountUserStations(Guid userId, CancellationToken cancellation = default);
    Task<List<UserStationDetail>> GetUserStations(Guid userId, CancellationToken cancellation = default);
    Task<UserStationDetail> SaveUserStation(Guid userId, UserStationInput input, CancellationToken cancellation = default);
    Task<bool> DeleteUserStation(Guid userId, string stationId, CancellationToken cancellation = default);
    Task<List<Dictionary<string, string>>> GetSensorTypesCatalog(CancellationToken cancellation = default);
    Task<List<Dictionary<string, string>>> GetCuencasCatalog(CancellationToken cancellation = default);
}
public sealed class ConsultationRepository(IConfiguration config) : IConsultationRepository
{
    private sealed record LevelSensor(string StationId,string DcpId,string SensorId,string SensorType,string Unit);
    private sealed record LevelReading(DateTimeOffset? Timestamp,double? Value,bool? Valid);
    private sealed record UpstreamSensor(string DamStationId,string StationId,string DcpId,string SensorId,string SensorType,string Unit);
    private Task<NpgsqlConnection> OpenAtlas(CancellationToken ct=default)=>OpenPostgres(ct);
    private async Task<NpgsqlConnection> OpenPostgres(CancellationToken ct=default)
    {
        var cs=config.GetConnectionString("Postgres"); if(string.IsNullOrWhiteSpace(cs)) throw new InvalidOperationException("La conexión a PostgreSQL todavía no está configurada.");
        var c=new NpgsqlConnection(cs); try { await c.OpenAsync(ct);return c; }catch { await c.DisposeAsync();throw; }
    }
    public async Task<List<PublicStation>> Stations(Guid? currentUserId = null, CancellationToken ct = default)
    {
        await using var c=await OpenAtlas(ct);
        await using var cmd=new NpgsqlCommand(@"SELECT CAST(e.Id AS varchar(36)),e.IdAsignado,e.Nombre,e.Latitud,e.Longitud,e.GOES,e.GPRS,e.RADIO,
CASE WHEN EsPresa=1 OR UPPER(COALESCE(Nombre,'')) LIKE '%PRESA%' THEN true ELSE false END AS EsPresaClasificada,
(SELECT COUNT(*)::int FROM dbo.Sensor s WHERE s.IdEstacion=e.Id AND s.Activo=1 AND s.Visible=1) AS SensorCount,
(SELECT COUNT(*)::int FROM dbo.DatosGOES g WHERE g.IdEstacion=e.Id) AS DcpCount,
e.IdCuenca AS IdCuenca,
CAST(e.id_usuario AS varchar(36)) AS IdUsuario
FROM dbo.Estacion e 
WHERE e.Activo=1 AND e.Visible=1 
  AND (e.id_usuario IS NULL OR (@uid::uuid IS NOT NULL AND e.id_usuario = @uid::uuid))
ORDER BY e.Nombre,e.Id",c){CommandTimeout=30};
        cmd.Parameters.Add(new NpgsqlParameter("uid", NpgsqlTypes.NpgsqlDbType.Uuid) { Value = (object?)currentUserId ?? DBNull.Value });
        await using var r=await cmd.ExecuteReaderAsync(ct);var rows=new List<PublicStation>();
        while(await r.ReadAsync(ct)) rows.Add(ReadStationRow(r));
        return rows;
    }
    public async Task<List<UpstreamStation>> UpstreamStations(CancellationToken ct)
    {
        await using var connection=await OpenAtlas(ct);
        await using var command=new NpgsqlCommand(@"SELECT CAST(r.IdPresa AS varchar(36)),CAST(e.Id AS varchar(36)),e.IdAsignado,e.Nombre,e.Latitud,e.Longitud,r.Rio,r.EstadoRelacion,CAST(r.Prioridad AS int)
FROM dbo.EstacionAguasArriba r
JOIN dbo.Estacion p ON p.Id=r.IdPresa AND p.Activo=1 AND p.Visible=1
JOIN dbo.Estacion e ON e.Id=r.IdEstacion AND e.Activo=1 AND e.Visible=1
WHERE r.Activo=1
ORDER BY r.IdPresa,r.Prioridad,e.Nombre",connection){CommandTimeout=15};
        await using var reader=await command.ExecuteReaderAsync(ct);var rows=new List<UpstreamStation>();
        while(await reader.ReadAsync(ct))
        {
            double? latitude=reader.IsDBNull(4)?null:reader.GetDouble(4),longitude=reader.IsDBNull(5)?null:reader.GetDouble(5);
            if(latitude.HasValue&&longitude.HasValue&&Math.Abs(latitude.Value)>90&&Math.Abs(longitude.Value)<=90)(latitude,longitude)=(longitude,latitude);
            if(longitude is >80 and <130)longitude=-longitude.Value;
            rows.Add(new(reader.GetString(0),reader.GetString(1),reader.IsDBNull(2)?"":reader.GetString(2),reader.IsDBNull(3)?"Sin nombre":reader.GetString(3),latitude,longitude,reader.GetString(6),reader.GetString(7),reader.GetInt32(8)));
        }
        return rows;
    }
    public async Task<List<UpstreamCondition>> UpstreamConditions(CancellationToken ct)
    {
        var sensors=new List<UpstreamSensor>();
        await using(var atlas=await OpenAtlas(ct))
        await using(var command=new NpgsqlCommand(@"SELECT CAST(r.IdPresa AS varchar(36)),CAST(e.Id AS varchar(36)),g.IdSatelital,s.NumeroSensor,ts.Nombre,COALESCE(u.Abreviatura,u.Nombre,'')
FROM dbo.EstacionAguasArriba r
JOIN dbo.Estacion e ON e.Id=r.IdEstacion AND e.Activo=1 AND e.Visible=1
JOIN dbo.DatosGOES g ON g.IdEstacion=e.Id
JOIN dbo.Sensor s ON s.IdEstacion=e.Id AND s.Activo=1 AND s.Visible=1
JOIN dbo.TipoSensor ts ON ts.Id=s.IdTipoSensor
LEFT JOIN dbo.UnidadMedida u ON u.Id=s.IdUnidadMedida
WHERE r.Activo=1 AND s.NumeroSensor IS NOT NULL AND g.IdSatelital IS NOT NULL
  AND (ts.Nombre IN ('Nivel de agua','Nivel Recipiente','Precipitación','Velocidad del agua') OR ts.Nombre LIKE '%Caudal%' OR ts.Nombre LIKE '%Gasto%')
ORDER BY r.IdPresa,e.Id,s.Orden,s.NumeroSensor",atlas){CommandTimeout=20})
        await using(var reader=await command.ExecuteReaderAsync(ct))
            while(await reader.ReadAsync(ct))sensors.Add(new(reader.GetString(0),reader.GetString(1),reader.GetString(2).Trim(),reader.GetString(3).Trim(),reader.GetString(4),reader.GetString(5).Trim()));

        if(sensors.Count==0)return [];
        var pairs=sensors.Select(x=>(x.DcpId,x.SensorId)).Distinct().ToList();
        var values=string.Join(',',pairs.Select((_,i)=>$"(@dcp{i},@sensor{i})"));
        var latestSql=$@"SELECT c.dcp_id,c.sensor_id,d.ts,d.valor,d.valido,d.reading_rank
FROM (VALUES {values}) AS c(dcp_id,sensor_id)
LEFT JOIN LATERAL (
  SELECT ts,valor,valido,ROW_NUMBER() OVER (ORDER BY ts DESC) AS reading_rank FROM public.dcp_datos
  WHERE dcp_id=c.dcp_id AND sensor_id=c.sensor_id
  ORDER BY ts DESC LIMIT 2
) d ON TRUE";
        await using var postgres=await OpenPostgres(ct);
        await using var latestCommand=new NpgsqlCommand(latestSql,postgres){CommandTimeout=30};
        for(var i=0;i<pairs.Count;i++)
        {
            latestCommand.Parameters.Add($"dcp{i}",NpgsqlDbType.Text).Value=pairs[i].DcpId;
            latestCommand.Parameters.Add($"sensor{i}",NpgsqlDbType.Text).Value=pairs[i].SensorId;
        }
        var readings=new Dictionary<(string Dcp,string Sensor),LevelReading?[]>();
        await using(var reader=await latestCommand.ExecuteReaderAsync(ct))
        while(await reader.ReadAsync(ct))
        {
            var key=(reader.GetString(0),reader.GetString(1));
            if(!readings.TryGetValue(key,out var pair))readings[key]=pair=new LevelReading?[2];
            var rank=reader.IsDBNull(5)?1:reader.GetInt64(5);
            if(rank is >=1 and <=2)pair[rank-1]=new(reader.IsDBNull(2)?null:new DateTimeOffset(reader.GetDateTime(2).ToUniversalTime()),reader.IsDBNull(3)?null:reader.GetFloat(3),reader.IsDBNull(4)?null:reader.GetBoolean(4));
        }

        var rainSensors=sensors.Where(x=>x.SensorType=="Precipitación").GroupBy(x=>(x.DcpId,x.SensorId)).Select(x=>x.First()).ToList();
        var rain=new Dictionary<(string Dcp,string Sensor),(double? Hour,double? SixHours,DateTimeOffset? Timestamp)>();
        if(rainSensors.Count>0)
        {
            var rainValues=string.Join(',',rainSensors.Select((_,i)=>$"(@rdcp{i},@rsensor{i})"));
            var rainSql=$@"SELECT c.dcp_id,c.sensor_id,
  SUM(d.valor) FILTER(WHERE d.ts>=CURRENT_TIMESTAMP-INTERVAL '1 hour' AND d.valido IS NOT FALSE AND d.valor>=0),
  SUM(d.valor) FILTER(WHERE d.ts>=CURRENT_TIMESTAMP-INTERVAL '6 hours' AND d.valido IS NOT FALSE AND d.valor>=0),
  MAX(d.ts) FILTER(WHERE d.valido IS NOT FALSE)
FROM (VALUES {rainValues}) AS c(dcp_id,sensor_id)
LEFT JOIN public.dcp_datos d ON d.dcp_id=c.dcp_id AND d.sensor_id=c.sensor_id AND d.ts>=CURRENT_TIMESTAMP-INTERVAL '6 hours'
GROUP BY c.dcp_id,c.sensor_id";
            await using var rainCommand=new NpgsqlCommand(rainSql,postgres){CommandTimeout=30};
            for(var i=0;i<rainSensors.Count;i++)
            {
                rainCommand.Parameters.Add($"rdcp{i}",NpgsqlDbType.Text).Value=rainSensors[i].DcpId;
                rainCommand.Parameters.Add($"rsensor{i}",NpgsqlDbType.Text).Value=rainSensors[i].SensorId;
            }
            await using var reader=await rainCommand.ExecuteReaderAsync(ct);
            while(await reader.ReadAsync(ct))rain[(reader.GetString(0),reader.GetString(1))]=(reader.IsDBNull(2)?null:reader.GetDouble(2),reader.IsDBNull(3)?null:reader.GetDouble(3),reader.IsDBNull(4)?null:new DateTimeOffset(reader.GetDateTime(4).ToUniversalTime()));
        }

        UpstreamMetric? Metric(UpstreamSensor? sensor)
        {
            if(sensor is null)return null;readings.TryGetValue((sensor.DcpId,sensor.SensorId),out var pair);var current=pair?[0];var previous=pair?[1];
            return new(sensor.SensorType,sensor.Unit,current?.Value,current?.Timestamp,current?.Valid,previous?.Value,previous?.Timestamp,previous?.Valid);
        }
        return sensors.GroupBy(x=>(x.DamStationId,x.StationId)).Select(group=>
        {
            var levelSensor=group.FirstOrDefault(x=>x.SensorType is "Nivel de agua" or "Nivel Recipiente");
            var rainSensor=group.FirstOrDefault(x=>x.SensorType=="Precipitación");
            var flowSensor=group.FirstOrDefault(x=>x.SensorType.Contains("Caudal",StringComparison.OrdinalIgnoreCase)||x.SensorType.Contains("Gasto",StringComparison.OrdinalIgnoreCase));
            var velocitySensor=group.FirstOrDefault(x=>x.SensorType=="Velocidad del agua");
            (double? Hour,double? SixHours,DateTimeOffset? Timestamp) rainfall=rainSensor is null?(null,null,null):rain.GetValueOrDefault((rainSensor.DcpId,rainSensor.SensorId));
            return new UpstreamCondition(group.Key.DamStationId,group.Key.StationId,Metric(levelSensor),rainfall.Item1,rainfall.Item2,rainSensor?.Unit??"mm",rainfall.Item3,Metric(flowSensor),Metric(velocitySensor));
        }).OrderBy(x=>x.DamStationId).ThenBy(x=>x.StationId).ToList();
    }
    public async Task<List<LatestLevel>> LatestDamLevels(CancellationToken ct)
    {
        var sensors=new List<LevelSensor>();
        await using(var atlas=await OpenAtlas(ct))
        await using(var cmd=new NpgsqlCommand(@"SELECT CAST(e.Id AS varchar(36)),g.IdSatelital,s.NumeroSensor,ts.Nombre,COALESCE(u.Abreviatura,u.Nombre,'')
FROM dbo.Sensor s
JOIN dbo.TipoSensor ts ON ts.Id=s.IdTipoSensor
JOIN dbo.Estacion e ON e.Id=s.IdEstacion
JOIN dbo.DatosGOES g ON g.IdEstacion=e.Id
LEFT JOIN dbo.UnidadMedida u ON u.Id=s.IdUnidadMedida
WHERE s.Activo=1 AND s.Visible=1 AND e.Activo=1 AND e.Visible=1
  AND (e.EsPresa=1 OR UPPER(COALESCE(e.Nombre,'')) LIKE '%PRESA%')
  AND ts.Nombre IN ('Nivel de agua','Nivel Recipiente')
  AND s.NumeroSensor IS NOT NULL AND g.IdSatelital IS NOT NULL
ORDER BY e.Id,g.IdSatelital,s.Orden,s.NumeroSensor",atlas){CommandTimeout=30})
        await using(var reader=await cmd.ExecuteReaderAsync(ct))
            while(await reader.ReadAsync(ct)) sensors.Add(new(reader.GetString(0),reader.GetString(1).Trim(),reader.GetString(2).Trim(),reader.GetString(3),reader.GetString(4).Trim()));

        if(sensors.Count==0)return [];
        var pairs=sensors.Select(x=>(x.DcpId,x.SensorId)).Distinct().ToList();
        var values=string.Join(',',pairs.Select((_,i)=>$"(@dcp{i},@sensor{i})"));
        var sql=$@"SELECT c.dcp_id,c.sensor_id,d.ts,d.valor,d.valido,d.reading_rank
FROM (VALUES {values}) AS c(dcp_id,sensor_id)
LEFT JOIN LATERAL (
  SELECT ts,valor,valido,ROW_NUMBER() OVER (ORDER BY ts DESC) AS reading_rank FROM public.dcp_datos
  WHERE dcp_id=c.dcp_id AND sensor_id=c.sensor_id
  ORDER BY ts DESC LIMIT 2
) d ON TRUE";
        await using var postgres=await OpenPostgres(ct);
        await using var latest=new NpgsqlCommand(sql,postgres){CommandTimeout=30};
        for(var i=0;i<pairs.Count;i++)
        {
            latest.Parameters.Add($"dcp{i}",NpgsqlDbType.Text).Value=pairs[i].DcpId;
            latest.Parameters.Add($"sensor{i}",NpgsqlDbType.Text).Value=pairs[i].SensorId;
        }
        var readings=new Dictionary<(string Dcp,string Sensor),LevelReading?[]>();
        await using(var reader=await latest.ExecuteReaderAsync(ct))
        while(await reader.ReadAsync(ct))
        {
            var key=(reader.GetString(0),reader.GetString(1));
            DateTimeOffset? timestamp=reader.IsDBNull(2)?null:new DateTimeOffset(reader.GetDateTime(2).ToUniversalTime());
            var reading=new LevelReading(timestamp,reader.IsDBNull(3)?null:reader.GetFloat(3),reader.IsDBNull(4)?null:reader.GetBoolean(4));
            if(!readings.TryGetValue(key,out var pair))readings[key]=pair=new LevelReading?[2];
            var rank=reader.IsDBNull(5)?1:reader.GetInt64(5);
            if(rank is >=1 and <=2)pair[rank-1]=reading;
        }
        var historySql=$@"SELECT c.dcp_id,c.sensor_id,d.ts,d.valor
FROM (VALUES {values}) AS c(dcp_id,sensor_id)
JOIN LATERAL (
  SELECT ts,valor FROM public.dcp_datos
  WHERE dcp_id=c.dcp_id AND sensor_id=c.sensor_id
    AND ts>=CURRENT_TIMESTAMP-INTERVAL '6 hours' AND valor IS NOT NULL AND valido IS NOT FALSE
  ORDER BY ts DESC LIMIT 120
) d ON TRUE";
        await using var historyCommand=new NpgsqlCommand(historySql,postgres){CommandTimeout=30};
        for(var i=0;i<pairs.Count;i++)
        {
            historyCommand.Parameters.Add($"dcp{i}",NpgsqlDbType.Text).Value=pairs[i].DcpId;
            historyCommand.Parameters.Add($"sensor{i}",NpgsqlDbType.Text).Value=pairs[i].SensorId;
        }
        var histories=new Dictionary<(string Dcp,string Sensor),List<LevelPoint>>();
        await using(var reader=await historyCommand.ExecuteReaderAsync(ct))
        while(await reader.ReadAsync(ct))
        {
            var key=(reader.GetString(0),reader.GetString(1));
            if(!histories.TryGetValue(key,out var points))histories[key]=points=[];
            points.Add(new(new DateTimeOffset(reader.GetDateTime(2).ToUniversalTime()),reader.GetFloat(3)));
        }
        foreach(var points in histories.Values)points.Sort((a,b)=>a.Timestamp.CompareTo(b.Timestamp));
        return sensors.GroupBy(x=>x.StationId).Select(group=>group
            .Select(sensor=>
            {
                readings.TryGetValue((sensor.DcpId,sensor.SensorId),out var pair);
                histories.TryGetValue((sensor.DcpId,sensor.SensorId),out var history);
                var current=pair?[0];var previous=pair?[1];
                return new LatestLevel(sensor.StationId,true,sensor.SensorId,sensor.SensorType,sensor.Unit,current?.Value,current?.Timestamp,current?.Valid,previous?.Value,previous?.Timestamp,previous?.Valid,history??[]);
            })
            .OrderByDescending(x=>x.Timestamp.HasValue)
            .ThenByDescending(x=>x.Timestamp)
            .ThenBy(x=>x.SensorType=="Nivel de agua"?0:1)
            .First()).OrderBy(x=>x.StationId).ToList();
    }
    private static PublicStation ReadStationRow(NpgsqlDataReader r)
    {
        double? lat=r.IsDBNull(3)?null:r.GetDouble(3);
        double? lon=r.IsDBNull(4)?null:r.GetDouble(4);
        if(lat.HasValue && lon.HasValue && Math.Abs(lat.Value)>90 && Math.Abs(lon.Value)<=90) (lat,lon)=(lon,lat);
        if(lon.HasValue && lon.Value>80 && lon.Value<130) lon=-lon.Value;
        string? basinId=r.IsDBNull(11)?null:r.GetString(11);
        string? userId = r.FieldCount > 12 && !r.IsDBNull(12) ? r.GetString(12) : null;
        return new(r.GetString(0),r.IsDBNull(1)?"":r.GetString(1),r.IsDBNull(2)?"Sin nombre":r.GetString(2),lat,lon,!r.IsDBNull(5)&&r.GetBoolean(5),!r.IsDBNull(6)&&r.GetBoolean(6),!r.IsDBNull(7)&&r.GetBoolean(7),!r.IsDBNull(8)&&r.GetBoolean(8),r.GetInt32(9),r.GetInt32(10),basinId,userId);
    }
    public async Task<QueryData> Query(string stationId,QueryProduct p,QueryWindow window,CancellationToken ct,string? sensorId=null,string? variable=null)
    {
        // Visibility and station-to-DCP mapping are resolved server-side, not accepted from a URL.
        if(!Guid.TryParse(stationId,out var stationGuid)) throw new ArgumentException("La estación solicitada no es válida.");
        var stationIdText=stationGuid.ToString().ToUpperInvariant();
        await using var c=await OpenPostgres(ct);
        await using var station=new NpgsqlCommand("SELECT IdAsignado FROM dbo.Estacion WHERE UPPER(Id)=@id AND Activo=1 AND Visible=1",c){CommandTimeout=15};
        station.Parameters.AddWithValue("id",NpgsqlDbType.Text,stationIdText);
        var code=await station.ExecuteScalarAsync(ct);
        if(code is null || code is DBNull) throw new ArgumentException("La estación no está disponible para consulta.");
        var series=new List<QuerySeries>();
        await using(var sensorCommand=new NpgsqlCommand(@"SELECT TRIM(s.NumeroSensor),COALESCE(ts.Nombre,'Sensor'),COALESCE(u.Abreviatura,u.Nombre,''),COALESCE(s.TipoGrafica,'line'),COALESCE(s.PuntoDecimal,0),COALESCE(s.PeriodoMuestra,10),COALESCE(s.Orden,999),COALESCE(ts.EsCalculada,false),s.ValorMinimo,s.ValorMaximo
FROM dbo.Sensor s
JOIN dbo.TipoSensor ts ON ts.Id=s.IdTipoSensor
LEFT JOIN dbo.UnidadMedida u ON u.Id=s.IdUnidadMedida
WHERE UPPER(s.IdEstacion)=@id AND s.Activo=1 AND s.Visible=1 AND s.NumeroSensor IS NOT NULL
ORDER BY s.Orden,s.NumeroSensor",c){CommandTimeout=15})
        {
            sensorCommand.Parameters.AddWithValue("id",NpgsqlDbType.Text,stationIdText);
            await using var sensorReader=await sensorCommand.ExecuteReaderAsync(ct);
            while(await sensorReader.ReadAsync(ct))
            {
                int dec=sensorReader.IsDBNull(4)?0:Convert.ToInt32(sensorReader.GetValue(4),CultureInfo.InvariantCulture);
                double per=sensorReader.IsDBNull(5)?10:Convert.ToDouble(sensorReader.GetValue(5),CultureInfo.InvariantCulture);
                int ord=sensorReader.IsDBNull(6)?999:Convert.ToInt32(sensorReader.GetValue(6),CultureInfo.InvariantCulture);
                bool calc=!sensorReader.IsDBNull(7)&&Convert.ToBoolean(sensorReader.GetValue(7),CultureInfo.InvariantCulture);
                double? minV=sensorReader.IsDBNull(8)?null:Convert.ToDouble(sensorReader.GetValue(8),CultureInfo.InvariantCulture);
                double? maxV=sensorReader.IsDBNull(9)?null:Convert.ToDouble(sensorReader.GetValue(9),CultureInfo.InvariantCulture);
                series.Add(new(sensorReader.GetString(0),sensorReader.GetString(1),sensorReader.GetString(2),sensorReader.GetString(3),dec,per,ord,calc,minV,maxV));
            }
        }
        var keys=new List<string>();
        GoesScheduleInfo? goesSchedule=null;
        await using(var dcps=new NpgsqlCommand("SELECT TRIM(IdSatelital),COALESCE(PrimeraTransmision,'00:00:00'),COALESCE(IntervaloTransmision,'01:00:00'),COALESCE(VentanaTransmision,'00:00:10'),CanalPrimario,COALESCE(Satelite,'GOES-E'),COALESCE(Decodificador,''),COALESCE(RangoTransmision,'01:00:00') FROM dbo.DatosGOES WHERE UPPER(IdEstacion)=@id AND IdSatelital IS NOT NULL",c){CommandTimeout=15})
        {
            dcps.Parameters.AddWithValue("id",NpgsqlDbType.Text,stationIdText);
            await using var dr=await dcps.ExecuteReaderAsync(ct);
            while(await dr.ReadAsync(ct))
            {
                var dcp=dr.GetString(0);
                if(p.Scope=="DCP_ID" && !keys.Contains(dcp)) keys.Add(dcp);
                if(goesSchedule is null)
                {
                    var firstTx=dr.GetString(1).Trim();
                    var interval=dr.GetString(2).Trim();
                    var win=dr.GetString(3).Trim();
                    int? chan=dr.IsDBNull(4)?null:Convert.ToInt32(dr.GetValue(4),CultureInfo.InvariantCulture);
                    var sat=dr.GetString(5).Trim();
                    var dec=dr.GetString(6).Trim();
                    var rango=dr.GetString(7).Trim();
                    int expectedDay=24,rangeMin=60;
                    if(TimeSpan.TryParse(interval,CultureInfo.InvariantCulture,out var tsInt) && tsInt.TotalMinutes>=1)
                        expectedDay=Math.Max(1,(int)Math.Round(1440.0/tsInt.TotalMinutes));
                    if(TimeSpan.TryParse(rango,CultureInfo.InvariantCulture,out var tsRng) && tsRng.TotalMinutes>=1)
                        rangeMin=Math.Max(1,(int)Math.Round(tsRng.TotalMinutes));
                    goesSchedule=new(dcp,firstTx,interval,win,chan,string.IsNullOrEmpty(sat)?"GOES-E":sat,dec,expectedDay,rangeMin);
                }
            }
        }
        if(p.Scope!="DCP_ID") keys.Add(Convert.ToString(code,CultureInfo.InvariantCulture)!.Trim());
        var columns=p.Columns.Split(',').ToList();
        if(keys.Count==0) return new(p.Key,window,columns,[],series,false,"No hay un identificador GOES configurado para esta estación.",goesSchedule);
        var date=p.Bucket=="day";
        var begin=date?"@startDate":"@startTime";
        var end=date?"@endDate":"@endTime";
        var extra=p.End is not null?$" AND {p.End} <= @endTime":p.Bucket=="day"?$" AND {p.Time}+1 <= {end}":p.Bucket=="hour"?$" AND {p.Time}+INTERVAL '1 hour' <= @endTime":"";
        var order=string.Join(',',columns.Where(x=>x!=p.Time && x is "SENSOR_ID" or "VARIABLE" or "DCP_ID").DefaultIfEmpty(p.Scope));
        var sql=$"SELECT {p.Columns} FROM public.{p.Table} WHERE {p.Scope}=ANY(@keys) AND {p.Time}>={begin} AND {p.Time}<={end}{extra} ORDER BY {p.Time},{order} LIMIT 2001";
        await using var cmd=new NpgsqlCommand(sql,c){CommandTimeout=60};
        cmd.Parameters.Add("keys",NpgsqlDbType.Array|NpgsqlDbType.Text).Value=keys.ToArray();
        if(date)
        {
            cmd.Parameters.Add("startDate",NpgsqlDbType.Date).Value=DateOnly.FromDateTime(window.Start.UtcDateTime);
            cmd.Parameters.Add("endDate",NpgsqlDbType.Date).Value=DateOnly.FromDateTime(window.End.UtcDateTime);
        }
        else
        {
            cmd.Parameters.Add("startTime",NpgsqlDbType.TimestampTz).Value=window.Start.UtcDateTime;
            cmd.Parameters.Add("endTime",NpgsqlDbType.TimestampTz).Value=window.End.UtcDateTime;
        }
        await using var r=await cmd.ExecuteReaderAsync(ct); var rows=new List<Dictionary<string,object?>>();
        while(await r.ReadAsync(ct))
        {
            var row=new Dictionary<string,object?>();
            for(int i=0;i<r.FieldCount;i++)
            {
                if(r.IsDBNull(i)) {row[columns[i]]=null;continue;}
                var value=r.GetValue(i);
                if(value is DateTimeOffset dto)row[columns[i]]=dto.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fff'Z'",CultureInfo.InvariantCulture);
                else if(value is DateTime dt)row[columns[i]]=DateTime.SpecifyKind(dt,dt.Kind==DateTimeKind.Unspecified?DateTimeKind.Utc:dt.Kind).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fff'Z'",CultureInfo.InvariantCulture);
                else if(value is DateOnly day)row[columns[i]]=day.ToString("yyyy-MM-dd",CultureInfo.InvariantCulture);
                else if(value is decimal or double or float or long or int or short) { var n=Convert.ToDouble(value,CultureInfo.InvariantCulture);row[columns[i]]=double.IsFinite(n)?n:null; }
                else if(value is bool boolean)row[columns[i]]=boolean;
                else row[columns[i]]=Convert.ToString(value,CultureInfo.InvariantCulture);
            }
            rows.Add(row);
        }
        bool truncated=rows.Count>2000;if(truncated) rows.RemoveAt(rows.Count-1);
        return new(p.Key,window,columns,rows,series,truncated,"Datos consultados en PostgreSQL/Timescale. El tipo de gráfica, nombre y unidad proceden del catálogo de sensores en DB_ATLAS. Fechas en UTC. Resúmenes y acumulados son productos almacenados, no recalculados ni certificados. Solo se incluyen periodos completos dentro del rango. Sin registros no significa valor cero."+(truncated?" Se muestran/exportan las primeras 2,000 filas: reduce el periodo para obtener el resto.":""),goesSchedule);
    }
    public async Task<SaasUser?> FindSaasUserByEmail(string email, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand("SELECT id, email, password_hash, nombre, plan, paypal_subscription_id, activo, creado_el FROM dbo.usuarios_saas WHERE LOWER(email) = LOWER(@e) AND activo = true", c);
        cmd.Parameters.AddWithValue("e", email.Trim());
        await using var r = await cmd.ExecuteReaderAsync(ct);
        if (await r.ReadAsync(ct))
        {
            return new SaasUser(r.GetGuid(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), r.IsDBNull(5) ? null : r.GetString(5), r.GetBoolean(6), r.GetDateTime(7));
        }
        return null;
    }
    public async Task<SaasUser?> FindSaasUserById(Guid id, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand("SELECT id, email, password_hash, nombre, plan, paypal_subscription_id, activo, creado_el FROM dbo.usuarios_saas WHERE id = @id AND activo = true", c);
        cmd.Parameters.AddWithValue("id", id);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        if (await r.ReadAsync(ct))
        {
            return new SaasUser(r.GetGuid(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), r.IsDBNull(5) ? null : r.GetString(5), r.GetBoolean(6), r.GetDateTime(7));
        }
        return null;
    }
    public async Task<SaasUser> CreateSaasUser(string email, string passwordHash, string nombre, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand(@"
            INSERT INTO dbo.usuarios_saas (email, password_hash, nombre, plan)
            VALUES (@email, @hash, @nombre, 'FREE')
            RETURNING id, email, password_hash, nombre, plan, paypal_subscription_id, activo, creado_el", c);
        cmd.Parameters.AddWithValue("email", email.Trim().ToLowerInvariant());
        cmd.Parameters.AddWithValue("hash", passwordHash);
        cmd.Parameters.AddWithValue("nombre", nombre.Trim());
        await using var r = await cmd.ExecuteReaderAsync(ct);
        await r.ReadAsync(ct);
        return new SaasUser(r.GetGuid(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), r.IsDBNull(5) ? null : r.GetString(5), r.GetBoolean(6), r.GetDateTime(7));
    }
    public async Task<List<SaasUserGroup>> GetUserGroups(Guid userId, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand(@"
            SELECT id, id_usuario, nombre, descripcion, estaciones, creado_el, actualizado_el
            FROM dbo.grupos_personalizados
            WHERE id_usuario = @uid
            ORDER BY actualizado_el DESC", c);
        cmd.Parameters.AddWithValue("uid", userId);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        var list = new List<SaasUserGroup>();
        while (await r.ReadAsync(ct))
        {
            var estaciones = r.GetFieldValue<string[]>(4);
            list.Add(new SaasUserGroup(r.GetGuid(0), r.GetGuid(1), r.GetString(2), r.IsDBNull(3) ? null : r.GetString(3), estaciones, r.GetDateTime(5), r.GetDateTime(6)));
        }
        return list;
    }
    public async Task<int> CountUserGroups(Guid userId, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand("SELECT COUNT(*)::int FROM dbo.grupos_personalizados WHERE id_usuario = @uid", c);
        cmd.Parameters.AddWithValue("uid", userId);
        var val = await cmd.ExecuteScalarAsync(ct);
        return Convert.ToInt32(val);
    }
    public async Task<SaasUserGroup> SaveUserGroup(Guid userId, Guid? groupId, string nombre, string? descripcion, string[] estaciones, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        if (groupId.HasValue && groupId.Value != Guid.Empty)
        {
            await using var cmd = new NpgsqlCommand(@"
                UPDATE dbo.grupos_personalizados
                SET nombre = @nom, descripcion = @desc, estaciones = @est, actualizado_el = NOW()
                WHERE id = @id AND id_usuario = @uid
                RETURNING id, id_usuario, nombre, descripcion, estaciones, creado_el, actualizado_el", c);
            cmd.Parameters.AddWithValue("id", groupId.Value);
            cmd.Parameters.AddWithValue("uid", userId);
            cmd.Parameters.AddWithValue("nom", nombre.Trim());
            cmd.Parameters.AddWithValue("desc", (object?)descripcion?.Trim() ?? DBNull.Value);
            cmd.Parameters.AddWithValue("est", estaciones);
            await using var r = await cmd.ExecuteReaderAsync(ct);
            if (await r.ReadAsync(ct))
            {
                return new SaasUserGroup(r.GetGuid(0), r.GetGuid(1), r.GetString(2), r.IsDBNull(3) ? null : r.GetString(3), r.GetFieldValue<string[]>(4), r.GetDateTime(5), r.GetDateTime(6));
            }
            throw new InvalidOperationException("El grupo no existe o no pertenece al usuario.");
        }
        else
        {
            await using var cmd = new NpgsqlCommand(@"
                INSERT INTO dbo.grupos_personalizados (id_usuario, nombre, descripcion, estaciones)
                VALUES (@uid, @nom, @desc, @est)
                RETURNING id, id_usuario, nombre, descripcion, estaciones, creado_el, actualizado_el", c);
            cmd.Parameters.AddWithValue("uid", userId);
            cmd.Parameters.AddWithValue("nom", nombre.Trim());
            cmd.Parameters.AddWithValue("desc", (object?)descripcion?.Trim() ?? DBNull.Value);
            cmd.Parameters.AddWithValue("est", estaciones);
            await using var r = await cmd.ExecuteReaderAsync(ct);
            await r.ReadAsync(ct);
            return new SaasUserGroup(r.GetGuid(0), r.GetGuid(1), r.GetString(2), r.IsDBNull(3) ? null : r.GetString(3), r.GetFieldValue<string[]>(4), r.GetDateTime(5), r.GetDateTime(6));
        }
    }
    public async Task<bool> DeleteUserGroup(Guid userId, Guid groupId, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand("DELETE FROM dbo.grupos_personalizados WHERE id = @id AND id_usuario = @uid", c);
        cmd.Parameters.AddWithValue("id", groupId);
        cmd.Parameters.AddWithValue("uid", userId);
        return (await cmd.ExecuteNonQueryAsync(ct)) > 0;
    }
    public async Task<bool> UpdateUserPlan(Guid userId, string plan, string? subscriptionId = null, string? payerId = null, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand(@"
            UPDATE dbo.usuarios_saas
            SET plan = @plan, paypal_subscription_id = COALESCE(@sub, paypal_subscription_id), paypal_payer_id = COALESCE(@payer, paypal_payer_id), actualizado_el = NOW()
            WHERE id = @uid", c);
        cmd.Parameters.AddWithValue("uid", userId);
        cmd.Parameters.AddWithValue("plan", plan.Trim().ToUpperInvariant());
        cmd.Parameters.AddWithValue("sub", (object?)subscriptionId ?? DBNull.Value);
        cmd.Parameters.AddWithValue("payer", (object?)payerId ?? DBNull.Value);
        return (await cmd.ExecuteNonQueryAsync(ct)) > 0;
    }
    public async Task<bool> DeleteSaasAccount(Guid userId, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var tx = await c.BeginTransactionAsync(ct);
        try
        {
            await using var cmdDelSensors = new NpgsqlCommand("DELETE FROM dbo.sensor WHERE idestacion IN (SELECT id FROM dbo.estacion WHERE id_usuario = @uid)", c, tx);
            cmdDelSensors.Parameters.AddWithValue("uid", userId);
            await cmdDelSensors.ExecuteNonQueryAsync(ct);

            await using var cmdDelGoes = new NpgsqlCommand("DELETE FROM dbo.datosgoes WHERE idestacion IN (SELECT id FROM dbo.estacion WHERE id_usuario = @uid)", c, tx);
            cmdDelGoes.Parameters.AddWithValue("uid", userId);
            await cmdDelGoes.ExecuteNonQueryAsync(ct);

            await using var cmdDelEst = new NpgsqlCommand("DELETE FROM dbo.estacion WHERE id_usuario = @uid", c, tx);
            cmdDelEst.Parameters.AddWithValue("uid", userId);
            await cmdDelEst.ExecuteNonQueryAsync(ct);

            await using var cmdGroups = new NpgsqlCommand("DELETE FROM dbo.grupos_personalizados WHERE id_usuario = @uid", c, tx);
            cmdGroups.Parameters.AddWithValue("uid", userId);
            await cmdGroups.ExecuteNonQueryAsync(ct);

            await using var cmdUser = new NpgsqlCommand("DELETE FROM dbo.usuarios_saas WHERE id = @uid", c, tx);
            cmdUser.Parameters.AddWithValue("uid", userId);
            var affected = await cmdUser.ExecuteNonQueryAsync(ct);

            await tx.CommitAsync(ct);
            return affected > 0;
        }
        catch
        {
            await tx.RollbackAsync(ct);
            throw;
        }
    }

    public async Task<int> CountUserStations(Guid userId, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand("SELECT COUNT(*)::int FROM dbo.estacion WHERE id_usuario = @uid", c);
        cmd.Parameters.AddWithValue("uid", userId);
        return (int)(await cmd.ExecuteScalarAsync(ct) ?? 0);
    }

    public async Task<List<UserStationDetail>> GetUserStations(Guid userId, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        var stations = new List<UserStationDetail>();
        
        await using (var cmd = new NpgsqlCommand(@"
            SELECT 
                CAST(e.id AS varchar(36)),
                e.idasignado,
                e.nombre,
                e.latitud,
                e.longitud,
                e.idcuenca,
                c.nombre AS nombre_cuenca,
                g.idsatelital,
                g.primeratransmision,
                g.intervalotransmision,
                COALESCE(g.canalprimario, 169),
                COALESCE(g.satelite, 'GOES-E'),
                COALESCE(g.velocidad, 300),
                COALESCE(g.decodificador, 'GS300'),
                COALESCE(e.activo, true)
            FROM dbo.estacion e
            LEFT JOIN dbo.datosgoes g ON g.idestacion = e.id
            LEFT JOIN dbo.cuenca c ON c.id = e.idcuenca
            WHERE e.id_usuario = @uid
            ORDER BY e.fecharegistro DESC, e.nombre ASC", c))
        {
            cmd.Parameters.AddWithValue("uid", userId);
            await using var r = await cmd.ExecuteReaderAsync(ct);
            while (await r.ReadAsync(ct))
            {
                stations.Add(new UserStationDetail(
                    r.GetString(0),
                    r.IsDBNull(1) ? "" : r.GetString(1),
                    r.IsDBNull(2) ? "Sin nombre" : r.GetString(2),
                    r.IsDBNull(3) ? 0 : r.GetDouble(3),
                    r.IsDBNull(4) ? 0 : r.GetDouble(4),
                    r.IsDBNull(5) ? null : r.GetString(5),
                    r.IsDBNull(6) ? null : r.GetString(6),
                    r.IsDBNull(7) ? "" : r.GetString(7),
                    r.IsDBNull(8) ? "00:00:00" : r.GetString(8),
                    r.IsDBNull(9) ? "01:00:00" : r.GetString(9),
                    r.GetInt32(10),
                    r.GetString(11),
                    r.GetInt32(12),
                    r.GetString(13),
                    r.GetBoolean(14),
                    new List<UserSensorDetail>()
                ));
            }
        }

        foreach (var st in stations)
        {
            await using var cmdS = new NpgsqlCommand(@"
                SELECT 
                    CAST(s.id AS varchar(36)),
                    COALESCE(s.numerosensor, ''),
                    CAST(s.idtiposensor AS varchar(36)),
                    COALESCE(ts.nombre, 'Desconocido'),
                    COALESCE(s.orden, 1),
                    COALESCE(s.puntodecimal, 1),
                    COALESCE(s.valorminimo, 0),
                    COALESCE(s.valormaximo, 100)
                FROM dbo.sensor s
                LEFT JOIN dbo.tiposensor ts ON ts.id = s.idtiposensor
                WHERE s.idestacion = @eid
                ORDER BY s.orden ASC", c);
            cmdS.Parameters.AddWithValue("eid", st.Id);
            await using var rS = await cmdS.ExecuteReaderAsync(ct);
            while (await rS.ReadAsync(ct))
            {
                st.Sensors.Add(new UserSensorDetail(
                    rS.GetString(0),
                    rS.GetString(1),
                    rS.GetString(2),
                    rS.GetString(3),
                    rS.GetInt32(4),
                    rS.GetInt32(5),
                    rS.GetDouble(6),
                    rS.GetDouble(7)
                ));
            }
        }

        return stations;
    }

    public async Task<UserStationDetail> SaveUserStation(Guid userId, UserStationInput input, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var tx = await c.BeginTransactionAsync(ct);
        try
        {
            var user = await FindSaasUserById(userId, ct) ?? throw new InvalidOperationException("Usuario no encontrado.");
            var stationId = string.IsNullOrWhiteSpace(input.Id) ? Guid.NewGuid().ToString().ToUpperInvariant() : input.Id.Trim().ToUpperInvariant();
            var nowStr = DateTime.UtcNow.ToString("yyyy-MM-dd");
            var coordsStr = $"{input.Latitude:F6},{input.Longitude:F6}";

            await using (var checkCmd = new NpgsqlCommand("SELECT COUNT(*) FROM dbo.estacion WHERE id = @id", c, tx))
            {
                checkCmd.Parameters.AddWithValue("id", stationId);
                var exists = ((long)(await checkCmd.ExecuteScalarAsync(ct) ?? 0L)) > 0;

                if (exists)
                {
                    await using var authCheck = new NpgsqlCommand("SELECT COUNT(*) FROM dbo.estacion WHERE id = @id AND id_usuario = @uid", c, tx);
                    authCheck.Parameters.AddWithValue("id", stationId);
                    authCheck.Parameters.AddWithValue("uid", userId);
                    if (((long)(await authCheck.ExecuteScalarAsync(ct) ?? 0L)) == 0)
                        throw new UnauthorizedAccessException("No tienes permiso para modificar esta estación.");

                    await using var updateEst = new NpgsqlCommand(@"
                        UPDATE dbo.estacion
                        SET idasignado = @code, nombre = @name, latitud = @lat, longitud = @lon,
                            coordenadas = @coords, idcuenca = @cuenca, fechamodificacion = @now, usuariomodificacion = @email
                        WHERE id = @id AND id_usuario = @uid", c, tx);
                    updateEst.Parameters.AddWithValue("code", input.Code.Trim().ToUpperInvariant());
                    updateEst.Parameters.AddWithValue("name", input.Name.Trim());
                    updateEst.Parameters.AddWithValue("lat", input.Latitude);
                    updateEst.Parameters.AddWithValue("lon", input.Longitude);
                    updateEst.Parameters.AddWithValue("coords", coordsStr);
                    updateEst.Parameters.AddWithValue("cuenca", (object?)input.BasinId ?? DBNull.Value);
                    updateEst.Parameters.AddWithValue("now", nowStr);
                    updateEst.Parameters.AddWithValue("email", user.Email);
                    updateEst.Parameters.AddWithValue("id", stationId);
                    updateEst.Parameters.AddWithValue("uid", userId);
                    await updateEst.ExecuteNonQueryAsync(ct);

                    await using var updateGoes = new NpgsqlCommand(@"
                        UPDATE dbo.datosgoes
                        SET idsatelital = @dcp, primeratransmision = @primera, intervalotransmision = @intervalo,
                            canalprimario = @canal, satelite = @satelite, velocidad = @velocidad,
                            decodificador = @decodificador, fechamodificacion = @now, usuariomodificacion = @email
                        WHERE idestacion = @id", c, tx);
                    updateGoes.Parameters.AddWithValue("dcp", input.DcpId.Trim().ToUpperInvariant());
                    updateGoes.Parameters.AddWithValue("primera", input.FirstTransmission.Trim());
                    updateGoes.Parameters.AddWithValue("intervalo", input.Interval.Trim());
                    updateGoes.Parameters.AddWithValue("canal", input.Channel);
                    updateGoes.Parameters.AddWithValue("satelite", input.Satellite.Trim());
                    updateGoes.Parameters.AddWithValue("velocidad", input.BaudRate);
                    updateGoes.Parameters.AddWithValue("decodificador", input.Decoder.Trim());
                    updateGoes.Parameters.AddWithValue("now", nowStr);
                    updateGoes.Parameters.AddWithValue("email", user.Email);
                    updateGoes.Parameters.AddWithValue("id", stationId);
                    await updateGoes.ExecuteNonQueryAsync(ct);
                }
                else
                {
                    await using var insertEst = new NpgsqlCommand(@"
                        INSERT INTO dbo.estacion (
                            id, idasignado, nombre, latitud, longitud, coordenadas,
                            idcuenca, goes, gprs, radio, activo, visible,
                            fecharegistro, usuarioregistro, id_usuario
                        ) VALUES (
                            @id, @code, @name, @lat, @lon, @coords,
                            @cuenca, true, false, false, true, true,
                            @now, @email, @uid
                        )", c, tx);
                    insertEst.Parameters.AddWithValue("id", stationId);
                    insertEst.Parameters.AddWithValue("code", input.Code.Trim().ToUpperInvariant());
                    insertEst.Parameters.AddWithValue("name", input.Name.Trim());
                    insertEst.Parameters.AddWithValue("lat", input.Latitude);
                    insertEst.Parameters.AddWithValue("lon", input.Longitude);
                    insertEst.Parameters.AddWithValue("coords", coordsStr);
                    insertEst.Parameters.AddWithValue("cuenca", (object?)input.BasinId ?? DBNull.Value);
                    insertEst.Parameters.AddWithValue("now", nowStr);
                    insertEst.Parameters.AddWithValue("email", user.Email);
                    insertEst.Parameters.AddWithValue("uid", userId);
                    await insertEst.ExecuteNonQueryAsync(ct);

                    await using var insertGoes = new NpgsqlCommand(@"
                        INSERT INTO dbo.datosgoes (
                            id, idestacion, idsatelital, primeratransmision, intervalotransmision,
                            rangotransmision, canalprimario, satelite, velocidad, decodificador,
                            transmite, fecharegistro, usuarioregistro
                        ) VALUES (
                            (SELECT COALESCE(MAX(id), 0) + 1 FROM dbo.datosgoes),
                            @id, @dcp, @primera, @intervalo,
                            '01:00:00', @canal, @satelite, @velocidad, @decodificador,
                            true, @now, @email
                        )", c, tx);
                    insertGoes.Parameters.AddWithValue("id", stationId);
                    insertGoes.Parameters.AddWithValue("dcp", input.DcpId.Trim().ToUpperInvariant());
                    insertGoes.Parameters.AddWithValue("primera", input.FirstTransmission.Trim());
                    insertGoes.Parameters.AddWithValue("intervalo", input.Interval.Trim());
                    insertGoes.Parameters.AddWithValue("canal", input.Channel);
                    insertGoes.Parameters.AddWithValue("satelite", input.Satellite.Trim());
                    insertGoes.Parameters.AddWithValue("velocidad", input.BaudRate);
                    insertGoes.Parameters.AddWithValue("decodificador", input.Decoder.Trim());
                    insertGoes.Parameters.AddWithValue("now", nowStr);
                    insertGoes.Parameters.AddWithValue("email", user.Email);
                    await insertGoes.ExecuteNonQueryAsync(ct);
                }
            }

            await using (var delSensors = new NpgsqlCommand("DELETE FROM dbo.sensor WHERE idestacion = @id", c, tx))
            {
                delSensors.Parameters.AddWithValue("id", stationId);
                await delSensors.ExecuteNonQueryAsync(ct);
            }

            var sensors = input.Sensors ?? new List<UserSensorInput>();
            int order = 1;
            foreach (var s in sensors)
            {
                var sensorId = Guid.NewGuid().ToString().ToUpperInvariant();
                var numSensor = string.IsNullOrWhiteSpace(s.NumeroSensor) ? $"00{order:D2}" : s.NumeroSensor.Trim();
                await using var insSensor = new NpgsqlCommand(@"
                    INSERT INTO dbo.sensor (
                        id, numerosensor, idestacion, idtiposensor, visible, activo,
                        valorminimo, valormaximo, orden, puntodecimal, fecharegistro, usuarioregistro
                    ) VALUES (
                        @sid, @num, @eid, @tipo, true, true,
                        @min, @max, @orden, @decimals, @now, @email
                    )", c, tx);
                insSensor.Parameters.AddWithValue("sid", sensorId);
                insSensor.Parameters.AddWithValue("num", numSensor);
                insSensor.Parameters.AddWithValue("eid", stationId);
                insSensor.Parameters.AddWithValue("tipo", s.TipoSensorId.Trim().ToUpperInvariant());
                insSensor.Parameters.AddWithValue("min", s.Min);
                insSensor.Parameters.AddWithValue("max", s.Max);
                insSensor.Parameters.AddWithValue("orden", order++);
                insSensor.Parameters.AddWithValue("decimals", s.Decimals);
                insSensor.Parameters.AddWithValue("now", nowStr);
                insSensor.Parameters.AddWithValue("email", user.Email);
                await insSensor.ExecuteNonQueryAsync(ct);
            }

            await tx.CommitAsync(ct);
            var list = await GetUserStations(userId, ct);
            return list.First(x => x.Id == stationId);
        }
        catch
        {
            await tx.RollbackAsync(ct);
            throw;
        }
    }

    public async Task<bool> DeleteUserStation(Guid userId, string stationId, CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var tx = await c.BeginTransactionAsync(ct);
        try
        {
            await using var auth = new NpgsqlCommand("SELECT COUNT(*) FROM dbo.estacion WHERE id = @id AND id_usuario = @uid", c, tx);
            auth.Parameters.AddWithValue("id", stationId);
            auth.Parameters.AddWithValue("uid", userId);
            if (((long)(await auth.ExecuteScalarAsync(ct) ?? 0L)) == 0)
                return false;

            await using var cmdS = new NpgsqlCommand("DELETE FROM dbo.sensor WHERE idestacion = @id", c, tx);
            cmdS.Parameters.AddWithValue("id", stationId);
            await cmdS.ExecuteNonQueryAsync(ct);

            await using var cmdG = new NpgsqlCommand("DELETE FROM dbo.datosgoes WHERE idestacion = @id", c, tx);
            cmdG.Parameters.AddWithValue("id", stationId);
            await cmdG.ExecuteNonQueryAsync(ct);

            await using var cmdE = new NpgsqlCommand("DELETE FROM dbo.estacion WHERE id = @id AND id_usuario = @uid", c, tx);
            cmdE.Parameters.AddWithValue("id", stationId);
            cmdE.Parameters.AddWithValue("uid", userId);
            var affected = await cmdE.ExecuteNonQueryAsync(ct);

            await tx.CommitAsync(ct);
            return affected > 0;
        }
        catch
        {
            await tx.RollbackAsync(ct);
            throw;
        }
    }

    public async Task<List<Dictionary<string, string>>> GetSensorTypesCatalog(CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand(@"
            SELECT id, nombre, COALESCE(tipovariable, 'General') 
            FROM dbo.tiposensor 
            ORDER BY nombre", c);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        var list = new List<Dictionary<string, string>>();
        while (await r.ReadAsync(ct))
        {
            list.Add(new Dictionary<string, string> {
                ["id"] = r.GetString(0),
                ["nombre"] = r.GetString(1),
                ["tipo"] = r.GetString(2)
            });
        }
        return list;
    }

    public async Task<List<Dictionary<string, string>>> GetCuencasCatalog(CancellationToken ct = default)
    {
        await using var c = await OpenPostgres(ct);
        await using var cmd = new NpgsqlCommand("SELECT id, nombre FROM dbo.cuenca ORDER BY nombre", c);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        var list = new List<Dictionary<string, string>>();
        while (await r.ReadAsync(ct))
        {
            list.Add(new Dictionary<string, string> {
                ["id"] = r.GetString(0),
                ["nombre"] = r.GetString(1)
            });
        }
        return list;
    }
}

[EnableRateLimiting("consultation")]
[ResponseCache(NoStore=true,Location=ResponseCacheLocation.None)]
public sealed class ExploreController(IConsultationRepository repository,VisitorCounter visitors,TimeProvider clock,StationCatalogCache stationCache,ILogger<ExploreController> log) : Controller
{
    [HttpGet] public async Task<IActionResult> Availability([FromServices] StationAvailability availability)
    {
        try{return Json(await availability.Get());}
        catch(Exception e) when(e is OracleException or SqlException or NpgsqlException or OperationCanceledException or InvalidOperationException)
        {return StatusCode(503,new{error="No se pudo verificar la disponibilidad. El gris indica estado desconocido, no ausencia de datos."});}
    }
    [HttpGet] public async Task<IActionResult> Index() { await visitors.Record("visits",User.Identity?.IsAuthenticated==true);return View(); }
    [HttpGet] public async Task<IActionResult> Stations()
    {
        try
        {
            var uid = GetCurrentSaasUserId();
            var stations=await repository.Stations(uid, HttpContext.RequestAborted);
            if(stations.Count>0)await stationCache.Store(stations);
            Response.Headers["X-HydroCloud-Catalog"]="aiven-postgres";
            return Json(stations);
        }
        catch(SqlException e)
        {
            var cached=await stationCache.Read();
            if(cached is not null)
            {
                log.LogWarning("Catálogo DB_ATLAS no disponible: código SQL Server {Code}; se conserva la última copia verificada",e.Number);
                Response.Headers["X-HydroCloud-Catalog"]="verified-cache";
                Response.Headers["X-HydroCloud-Catalog-Checked-At"]=cached.CheckedAt.ToString("O",CultureInfo.InvariantCulture);
                return Json(cached.Stations);
            }
            log.LogWarning("Catálogo DB_ATLAS no disponible: código SQL Server {Code}; no existe copia verificada",e.Number);
            Response.Headers["X-HydroCloud-Catalog"]="unavailable";
            return StatusCode(503,new{error="Sin conexión a DB_ATLAS. No se muestran estaciones ni ubicaciones."});
        }
        catch(Exception e) when(e is NpgsqlException or ArgumentException or OperationCanceledException or InvalidOperationException)
        {
            var cached=await stationCache.Read();
            if(cached is not null)
            {
                log.LogWarning("Catálogo DB_ATLAS no disponible: {Type} - {Message}; se conserva la última copia verificada", e.GetType().Name, e.Message);
                Response.Headers["X-HydroCloud-Catalog"]="verified-cache";
                Response.Headers["X-HydroCloud-Catalog-Checked-At"]=cached.CheckedAt.ToString("O",CultureInfo.InvariantCulture);
                return Json(cached.Stations);
            }
            log.LogWarning("Catálogo DB_ATLAS no disponible: {Type}; no existe copia verificada",e.GetType().Name);
            Response.Headers["X-HydroCloud-Catalog"]="unavailable";
            return StatusCode(503,new{error="Sin conexión a DB_ATLAS. No se muestran estaciones ni ubicaciones."});
        }
    }
    [HttpGet] public async Task<IActionResult> LatestLevels()
    {
        try{return Json(await repository.LatestDamLevels(HttpContext.RequestAborted));}
        catch(SqlException e){log.LogWarning("Catálogo de sensores de nivel no disponible: código SQL Server {Code}",e.Number);return StatusCode(503,new{error="No fue posible consultar el catálogo de sensores de nivel."});}
        catch(PostgresException e){log.LogWarning("Lecturas de nivel no disponibles: código PostgreSQL {Code}",e.SqlState);return StatusCode(503,new{error="No fue posible consultar las últimas lecturas de nivel."});}
        catch(NpgsqlException e){log.LogWarning("Lecturas de nivel no disponibles: {Type}",e.GetType().Name);return StatusCode(503,new{error="No fue posible conectar con las lecturas de nivel."});}
        catch(Exception e) when(e is ArgumentException or OperationCanceledException or InvalidOperationException){return StatusCode(503,new{error="Las últimas lecturas de nivel no están disponibles temporalmente."});}
    }
    [HttpGet] public async Task<IActionResult> UpstreamStations()
    {
        try{return Json(await repository.UpstreamStations(HttpContext.RequestAborted));}
        catch(SqlException e){log.LogWarning("Relaciones aguas arriba no disponibles: código SQL Server {Code}",e.Number);return StatusCode(503,new{error="No fue posible consultar las estaciones aguas arriba."});}
        catch(Exception e) when(e is NpgsqlException or ArgumentException or OperationCanceledException or InvalidOperationException){return StatusCode(503,new{error="Las estaciones aguas arriba no están disponibles temporalmente."});}
    }
    [HttpGet] public async Task<IActionResult> UpstreamConditions()
    {
        try{return Json(await repository.UpstreamConditions(HttpContext.RequestAborted));}
        catch(SqlException e){log.LogWarning("Sensores aguas arriba no disponibles: código SQL Server {Code}",e.Number);return StatusCode(503,new{error="No fue posible consultar los sensores aguas arriba."});}
        catch(PostgresException e){log.LogWarning("Lecturas aguas arriba no disponibles: código PostgreSQL {Code}",e.SqlState);return StatusCode(503,new{error="No fue posible consultar las lecturas aguas arriba."});}
        catch(NpgsqlException e){log.LogWarning("Lecturas aguas arriba no disponibles: {Type}",e.GetType().Name);return StatusCode(503,new{error="No fue posible conectar con las lecturas aguas arriba."});}
        catch(Exception e) when(e is ArgumentException or OperationCanceledException or InvalidOperationException){return StatusCode(503,new{error="Las condiciones aguas arriba no están disponibles temporalmente."});}
    }
    [HttpGet] public async Task<IActionResult> Cuencas([FromServices] IHttpClientFactory httpClientFactory)
    {
        try
        {
            var client = httpClientFactory.CreateClient();
            var resp = await client.GetAsync("http://127.0.0.1:5555/api/cuencas", HttpContext.RequestAborted);
            if (resp.IsSuccessStatusCode)
            {
                var content = await resp.Content.ReadAsStringAsync();
                return Content(content, "application/json; charset=utf-8");
            }
            return StatusCode((int)resp.StatusCode, new { error = "El servicio de cuencas respondió con error." });
        }
        catch (Exception ex)
        {
            log.LogWarning("Fallo al contactar el colector para /api/cuencas: {Msg}", ex.Message);
            return StatusCode(503, new { error = "El catálogo de cuencas no está disponible temporalmente." });
        }
    }
    [HttpGet] public async Task<IActionResult> CuencaRainfall(string? cuenca, string? estaciones, string? nombre = null, string? grupoId = null, int horas = 24, int tzOffset = -6, [FromServices] IHttpClientFactory httpClientFactory = null!)
    {
        try
        {
            var client = httpClientFactory.CreateClient();
            var qs = new List<string>();
            if (!string.IsNullOrWhiteSpace(cuenca)) qs.Add($"cuenca={Uri.EscapeDataString(cuenca)}");
            if (!string.IsNullOrWhiteSpace(estaciones)) qs.Add($"estaciones={Uri.EscapeDataString(estaciones)}");
            if (!string.IsNullOrWhiteSpace(nombre)) qs.Add($"nombre={Uri.EscapeDataString(nombre)}");
            if (!string.IsNullOrWhiteSpace(grupoId)) qs.Add($"grupo_id={Uri.EscapeDataString(grupoId)}");
            qs.Add($"horas={horas}");
            qs.Add($"tz_offset={tzOffset}");
            var url = $"http://127.0.0.1:5555/api/cuenca/lluvia_horaria?{string.Join("&", qs)}";
            var resp = await client.GetAsync(url, HttpContext.RequestAborted);
            var content = await resp.Content.ReadAsStringAsync();
            return Content(content, "application/json; charset=utf-8");
        }
        catch (Exception ex)
        {
            log.LogWarning("Fallo al contactar el colector para /api/cuenca/lluvia_horaria: {Msg}", ex.Message);
            return StatusCode(503, new { error = "El servicio de cálculo de lluvia horaria no está disponible temporalmente." });
        }
    }

    private Guid? GetCurrentSaasUserId()
    {
        var sub = User.FindFirstValue(ClaimTypes.NameIdentifier);
        return Guid.TryParse(sub, out var guid) ? guid : null;
    }

    private static int GetMaxEstaciones(string? plan) => (plan?.ToUpperInvariant()) switch
    {
        "UNLIMITED" or "ILIMITADO" => 9999,
        "ENTERPRISE" => 10,
        "PRO" => 5,
        _ => 1
    };

    private static int GetMaxGrupos(string? plan) => (plan?.ToUpperInvariant()) switch
    {
        "UNLIMITED" or "ILIMITADO" or "ENTERPRISE" => 9999,
        "PRO" => 10,
        _ => 3
    };

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> RegisterSaas([FromBody] SaasRegisterRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Email) || !req.Email.Contains('@'))
            return BadRequest(new { error = "Correo electrónico inválido." });
        if (string.IsNullOrWhiteSpace(req.Nombre))
            return BadRequest(new { error = "El nombre es obligatorio." });
        if (string.IsNullOrWhiteSpace(req.Password) || req.Password.Length < 6)
            return BadRequest(new { error = "La contraseña debe tener al menos 6 caracteres." });

        var existing = await repository.FindSaasUserByEmail(req.Email, HttpContext.RequestAborted);
        if (existing != null)
            return Conflict(new { error = "El correo ya está registrado. Inicia sesión con tus credenciales." });

        var hasher = new PasswordHasher<string>();
        var hash = hasher.HashPassword(req.Email.Trim().ToLowerInvariant(), req.Password);
        var user = await repository.CreateSaasUser(req.Email, hash, req.Nombre, HttpContext.RequestAborted);

        var claims = new List<Claim>
        {
            new(ClaimTypes.NameIdentifier, user.Id.ToString()),
            new(ClaimTypes.Name, user.Nombre),
            new(ClaimTypes.Email, user.Email),
            new(ClaimTypes.Role, "SaasUser"),
            new("Plan", user.Plan)
        };
        await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
            new ClaimsPrincipal(new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme)));

        return Json(new {
            status = "ok",
            user = new {
                id = user.Id,
                email = user.Email,
                nombre = user.Nombre,
                plan = user.Plan,
                grupos_count = 0,
                max_grupos = GetMaxGrupos(user.Plan),
                estaciones_count = 0,
                max_estaciones = GetMaxEstaciones(user.Plan)
            }
        });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> LoginSaas([FromBody] SaasLoginRequest req)
    {
        if (string.IsNullOrWhiteSpace(req.Email) || string.IsNullOrWhiteSpace(req.Password))
            return BadRequest(new { error = "Correo y contraseña son requeridos." });

        var user = await repository.FindSaasUserByEmail(req.Email, HttpContext.RequestAborted);
        if (user == null)
            return Unauthorized(new { error = "Usuario no encontrado o inactivo." });

        var hasher = new PasswordHasher<string>();
        var result = hasher.VerifyHashedPassword(user.Email, user.PasswordHash, req.Password);
        if (result == PasswordVerificationResult.Failed)
            return Unauthorized(new { error = "Contraseña incorrecta." });

        var claims = new List<Claim>
        {
            new(ClaimTypes.NameIdentifier, user.Id.ToString()),
            new(ClaimTypes.Name, user.Nombre),
            new(ClaimTypes.Email, user.Email),
            new(ClaimTypes.Role, "SaasUser"),
            new("Plan", user.Plan)
        };
        await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
            new ClaimsPrincipal(new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme)));

        var countG = await repository.CountUserGroups(user.Id, HttpContext.RequestAborted);
        var countE = await repository.CountUserStations(user.Id, HttpContext.RequestAborted);
        return Json(new {
            status = "ok",
            user = new {
                id = user.Id,
                email = user.Email,
                nombre = user.Nombre,
                plan = user.Plan,
                subscription_id = user.PaypalSubscriptionId,
                grupos_count = countG,
                max_grupos = GetMaxGrupos(user.Plan),
                estaciones_count = countE,
                max_estaciones = GetMaxEstaciones(user.Plan)
            }
        });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> LogoutSaas()
    {
        await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
        return Json(new { status = "ok" });
    }

    [HttpGet]
    public async Task<IActionResult> Me()
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Json(new { authenticated = false });

        var user = await repository.FindSaasUserById(uid.Value, HttpContext.RequestAborted);
        if (user == null)
        {
            await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
            return Json(new { authenticated = false });
        }

        var countG = await repository.CountUserGroups(user.Id, HttpContext.RequestAborted);
        var countE = await repository.CountUserStations(user.Id, HttpContext.RequestAborted);
        return Json(new {
            authenticated = true,
            user = new {
                id = user.Id,
                email = user.Email,
                nombre = user.Nombre,
                plan = user.Plan,
                subscription_id = user.PaypalSubscriptionId,
                grupos_count = countG,
                max_grupos = GetMaxGrupos(user.Plan),
                estaciones_count = countE,
                max_estaciones = GetMaxEstaciones(user.Plan)
            }
        });
    }

    [HttpGet]
    public async Task<IActionResult> UserGroups()
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "Debes iniciar sesión para consultar tus grupos guardados." });

        var groups = await repository.GetUserGroups(uid.Value, HttpContext.RequestAborted);
        return Json(new { status = "ok", groups });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> SaveGroup([FromBody] SaasSaveGroupRequest req)
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "auth_required", message = "Inicia sesión o regístrate gratis para guardar tus grupos de estaciones." });

        var user = await repository.FindSaasUserById(uid.Value, HttpContext.RequestAborted);
        if (user == null)
            return Unauthorized(new { error = "Usuario no válido." });

        if (string.IsNullOrWhiteSpace(req.Nombre))
            return BadRequest(new { error = "El nombre del grupo es obligatorio." });
        if (req.Estaciones == null || req.Estaciones.Length == 0)
            return BadRequest(new { error = "Debes seleccionar al menos una estación." });

        if (!req.Id.HasValue || req.Id == Guid.Empty)
        {
            var count = await repository.CountUserGroups(uid.Value, HttpContext.RequestAborted);
            var maxAllowed = GetMaxGrupos(user.Plan);
            if (count >= maxAllowed)
            {
                if (user.Plan.ToUpperInvariant() == "FREE")
                {
                    return StatusCode(402, new {
                        error = "limit_reached",
                        message = "Has alcanzado el límite de 3 grupos del Plan Gratuito. Suscríbete a Pro ($100 MXN / mes por hasta 10 grupos) o Enterprise ($200 MXN / mes por más de 10 grupos)."
                    });
                }
                else if (user.Plan.ToUpperInvariant() == "PRO")
                {
                    return StatusCode(402, new {
                        error = "limit_reached_pro",
                        message = "Has alcanzado el límite de 10 grupos de tu suscripción Pro ($100 MXN / mes). Actualiza al Plan Enterprise por $200 MXN / mes para crear grupos sin límite."
                    });
                }
            }
        }

        var saved = await repository.SaveUserGroup(uid.Value, req.Id, req.Nombre, req.Descripcion, req.Estaciones, HttpContext.RequestAborted);
        var totalCount = await repository.CountUserGroups(uid.Value, HttpContext.RequestAborted);
        return Json(new {
            status = "ok",
            group = saved,
            grupos_count = totalCount,
            max_grupos = GetMaxGrupos(user.Plan)
        });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> DeleteGroup([FromBody] SaasDeleteGroupRequest req)
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "No autenticado." });

        var ok = await repository.DeleteUserGroup(uid.Value, req.Id, HttpContext.RequestAborted);
        var totalCount = await repository.CountUserGroups(uid.Value, HttpContext.RequestAborted);
        return Json(new { status = ok ? "ok" : "not_found", grupos_count = totalCount });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> DeleteAccount()
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "No autenticado." });

        var ok = await repository.DeleteSaasAccount(uid.Value, HttpContext.RequestAborted);
        await HttpContext.SignOutAsync(CookieAuthenticationDefaults.AuthenticationScheme);
        return Json(new { status = ok ? "ok" : "not_found" });
    }

    [HttpGet]
    public async Task<IActionResult> UserStations()
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "Debes iniciar sesión para consultar tus estaciones." });

        var user = await repository.FindSaasUserById(uid.Value, HttpContext.RequestAborted);
        if (user == null)
            return Unauthorized(new { error = "Usuario no válido." });

        var stations = await repository.GetUserStations(uid.Value, HttpContext.RequestAborted);
        return Json(new {
            status = "ok",
            stations,
            estaciones_count = stations.Count,
            max_estaciones = GetMaxEstaciones(user.Plan)
        });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> SaveUserStation([FromBody] UserStationInput req)
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "Debes iniciar sesión para guardar tu estación." });

        var user = await repository.FindSaasUserById(uid.Value, HttpContext.RequestAborted);
        if (user == null)
            return Unauthorized(new { error = "Usuario no válido." });

        if (string.IsNullOrWhiteSpace(req.Code))
            return BadRequest(new { error = "La clave o ID asignado de la estación es obligatorio." });
        if (string.IsNullOrWhiteSpace(req.Name))
            return BadRequest(new { error = "El nombre de la estación es obligatorio." });
        if (string.IsNullOrWhiteSpace(req.DcpId) || req.DcpId.Trim().Length != 8)
            return BadRequest(new { error = "El DCP ID satelital debe tener exactamente 8 caracteres hexadecimales (ej. CE1A4B02)." });

        if (string.IsNullOrWhiteSpace(req.Id))
        {
            var count = await repository.CountUserStations(uid.Value, HttpContext.RequestAborted);
            var maxAllowed = GetMaxEstaciones(user.Plan);
            if (count >= maxAllowed)
            {
                return StatusCode(402, new {
                    error = "limit_reached",
                    message = user.Plan.ToUpperInvariant() switch {
                        "FREE" => "Has alcanzado el límite de 1 estación GOES de tu Plan Gratuito. Suscríbete a Pro ($100 MXN / mes) para monitorear hasta 5 estaciones.",
                        "PRO" => "Has alcanzado el límite de 5 estaciones GOES del Plan Pro. Actualiza a Enterprise ($200 MXN / mes) para monitorear hasta 10 estaciones o al Plan Todo Ilimitado.",
                        "ENTERPRISE" => "Has alcanzado el límite de 10 estaciones GOES del Plan Enterprise. Actualiza al Plan Todo Ilimitado ($500 MXN / mes) para estaciones y grupos ilimitados o agrega estaciones por $30 MXN/mes c/u.",
                        _ => "Has alcanzado el límite de estaciones de tu plan."
                    }
                });
            }
        }

        var saved = await repository.SaveUserStation(uid.Value, req, HttpContext.RequestAborted);
        var totalCount = await repository.CountUserStations(uid.Value, HttpContext.RequestAborted);

        // Notificar recarga al colector Python
        _ = Task.Run(async () => {
            try {
                using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
                await http.PostAsync("http://localhost:5555/api/reload", null);
            } catch { }
        });

        return Json(new {
            status = "ok",
            station = saved,
            estaciones_count = totalCount,
            max_estaciones = GetMaxEstaciones(user.Plan)
        });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> DeleteUserStation([FromBody] UserStationInput req)
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "No autenticado." });

        if (string.IsNullOrWhiteSpace(req.Id))
            return BadRequest(new { error = "ID de estación requerido." });

        var ok = await repository.DeleteUserStation(uid.Value, req.Id, HttpContext.RequestAborted);
        var totalCount = await repository.CountUserStations(uid.Value, HttpContext.RequestAborted);

        // Notificar recarga al colector Python
        _ = Task.Run(async () => {
            try {
                using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
                await http.PostAsync("http://localhost:5555/api/reload", null);
            } catch { }
        });

        return Json(new { status = ok ? "ok" : "not_found", estaciones_count = totalCount });
    }

    [HttpGet]
    public async Task<IActionResult> SensorCatalogList()
    {
        var list = await repository.GetSensorTypesCatalog(HttpContext.RequestAborted);
        return Json(list);
    }

    [HttpGet]
    public async Task<IActionResult> CuencasCatalogList()
    {
        var list = await repository.GetCuencasCatalog(HttpContext.RequestAborted);
        return Json(list);
    }
    [HttpGet] public Task<IActionResult> Data(string stationId,string product,DateTimeOffset? start,DateTimeOffset? end)=>Read(stationId,product,start,end,false);
    [HttpGet] public Task<IActionResult> Export(string stationId,string product,DateTimeOffset? start,DateTimeOffset? end)=>Read(stationId,product,start,end,true);
    private async Task<IActionResult> Read(string stationId,string product,DateTimeOffset? start,DateTimeOffset? end,bool csv)
    {
        if(!ModelState.IsValid) return BadRequest(new{error="Fechas inválidas. Usa ISO 8601 con zona horaria."});
        var p=QueryProduct.Find(product);if(p is null) return BadRequest(new{error="Producto desconocido."});
        try
        {
            var auth=User.Identity?.IsAuthenticated==true;
            var window=QueryWindow.Create(start,end,auth,clock.GetUtcNow());
            var data=await repository.Query(stationId,p,window,HttpContext.RequestAborted);
            await visitors.Record(csv?"exports":"queries",auth);
            if(!csv) return Json(data);
            var text=new StringBuilder();text.AppendLine(string.Join(',',data.Columns.Select(Csv)));
            foreach(var row in data.Rows) text.AppendLine(string.Join(',',data.Columns.Select(k=>Csv(row[k]))));
            if(data.Truncated) Response.Headers["X-HydroCloud-Truncated"]="true";
            return File(Encoding.UTF8.GetPreamble().Concat(Encoding.UTF8.GetBytes(text.ToString())).ToArray(),"text/csv; charset=utf-8",$"hydrocloud-{p.Key}{(data.Truncated?"-PARCIAL-2000":"")}.csv");
        }
        catch(ArgumentException e) {return BadRequest(new{error=e.Message});}
        catch(SqlException e) {log.LogWarning("Consulta de catálogo DB_ATLAS fallida: código {Code}",e.Number);return StatusCode(503,new{error="No fue posible consultar el catálogo de estaciones."});}
        catch(PostgresException e) {log.LogWarning("Consulta PostgreSQL fallida: código {Code}",e.SqlState);return StatusCode(503,new{error="No fue posible consultar las series en PostgreSQL. Verifica el producto o inténtalo de nuevo."});}
        catch(NpgsqlException e) {log.LogWarning("Conexión PostgreSQL fallida: {Type}",e.GetType().Name);return StatusCode(503,new{error="No fue posible conectar con PostgreSQL. Inténtalo de nuevo."});}
        catch(InvalidOperationException) {return StatusCode(503,new{error="El servicio de consulta no está disponible temporalmente."});}
    }
    public static string Csv(object? value)
    {
        var s=Convert.ToString(value,CultureInfo.InvariantCulture)??"";
        if(value is string && s.TrimStart().StartsWithAny('=','+','-','@','\t','\r')) s="'"+s;
        return "\""+s.Replace("\"","\"\"")+"\"";
    }
    [Authorize(Roles="Administrator"),HttpGet] public async Task<IActionResult> Visitors()=>View(await visitors.Read());

    [HttpGet]
    public IActionResult PayPalConfig([FromServices] IConfiguration cfg)
    {
        return Json(new {
            clientId = cfg["PayPal:ClientId"] ?? "sb",
            planIdPro = cfg["PayPal:PlanId"] ?? "P-HYDROCLOUD-PRO-100MXN",
            planIdEnterprise = cfg["PayPal:PlanIdEnterprise"] ?? "P-HYDROCLOUD-ENTERPRISE-200MXN",
            planIdUnlimited = cfg["PayPal:PlanIdUnlimited"] ?? "P-HYDROCLOUD-UNLIMITED-500MXN",
            currency = cfg["PayPal:Currency"] ?? "MXN",
            amountPro = cfg["PayPal:Amount"] ?? "100.00",
            amountEnterprise = cfg["PayPal:AmountEnterprise"] ?? "200.00",
            amountUnlimited = cfg["PayPal:AmountUnlimited"] ?? "500.00",
            sandbox = cfg.GetValue<bool>("PayPal:Sandbox", true)
        });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> ConfirmSubscription([FromBody] PayPalSubscriptionConfirm req)
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "auth_required", message = "Inicia sesión para activar tu suscripción." });

        if (string.IsNullOrWhiteSpace(req.SubscriptionId))
            return BadRequest(new { error = "El identificador de suscripción es requerido." });

        var targetPlan = (req.Plan?.ToUpperInvariant()) switch
        {
            "UNLIMITED" or "ILIMITADO" => "UNLIMITED",
            "ENTERPRISE" => "ENTERPRISE",
            _ => "PRO"
        };
        var ok = await repository.UpdateUserPlan(uid.Value, targetPlan, req.SubscriptionId, req.PayerId, HttpContext.RequestAborted);
        if (!ok)
            return StatusCode(500, new { error = "No se pudo actualizar el plan del usuario." });

        var user = await repository.FindSaasUserById(uid.Value, HttpContext.RequestAborted);
        if (user != null)
        {
            var claims = new List<Claim>
            {
                new(ClaimTypes.NameIdentifier, user.Id.ToString()),
                new(ClaimTypes.Name, user.Nombre),
                new(ClaimTypes.Email, user.Email),
                new(ClaimTypes.Role, "SaasUser"),
                new("Plan", targetPlan)
            };
            await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
                new ClaimsPrincipal(new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme)));
        }

        var countG = await repository.CountUserGroups(uid.Value, HttpContext.RequestAborted);
        var countE = await repository.CountUserStations(uid.Value, HttpContext.RequestAborted);
        return Json(new {
            status = "ok",
            message = targetPlan switch {
                "UNLIMITED" => "¡Suscripción Todo Ilimitado activada con éxito! (Estaciones y grupos ilimitados)",
                "ENTERPRISE" => "¡Suscripción Enterprise activada con éxito! (10 estaciones y grupos ilimitados)",
                _ => "¡Suscripción Pro activada con éxito! (5 estaciones y 10 grupos)"
            },
            plan = targetPlan,
            grupos_count = countG,
            max_grupos = GetMaxGrupos(targetPlan),
            estaciones_count = countE,
            max_estaciones = GetMaxEstaciones(targetPlan)
        });
    }

    [HttpPost, IgnoreAntiforgeryToken]
    public async Task<IActionResult> CancelSubscription()
    {
        var uid = GetCurrentSaasUserId();
        if (!uid.HasValue)
            return Unauthorized(new { error = "No autenticado." });

        await repository.UpdateUserPlan(uid.Value, "FREE", cancellation: HttpContext.RequestAborted);
        var user = await repository.FindSaasUserById(uid.Value, HttpContext.RequestAborted);
        if (user != null)
        {
            var claims = new List<Claim>
            {
                new(ClaimTypes.NameIdentifier, user.Id.ToString()),
                new(ClaimTypes.Name, user.Nombre),
                new(ClaimTypes.Email, user.Email),
                new(ClaimTypes.Role, "SaasUser"),
                new("Plan", "FREE")
            };
            await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
                new ClaimsPrincipal(new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme)));
        }

        var count = await repository.CountUserGroups(uid.Value, HttpContext.RequestAborted);
        return Json(new { status = "ok", plan = "FREE", grupos_count = count, max_grupos = 3 });
    }
}
public record StationCatalogSnapshot(List<PublicStation> Stations,DateTimeOffset CheckedAt);
public sealed class StationCatalogCache
{
    private readonly string path=Path.Combine(Path.GetTempPath(),"hydrocloud-stations.json");
    private readonly SemaphoreSlim gate=new(1,1);
    public async Task Store(List<PublicStation> stations)
    {
        await gate.WaitAsync();
        try
        {
            var temporary=path+".tmp";
            await using(var stream=new FileStream(temporary,FileMode.Create,FileAccess.Write,FileShare.None,65536,true))await JsonSerializer.SerializeAsync(stream,stations);
            File.Move(temporary,path,true);
        }
        finally{gate.Release();}
    }
    public async Task<StationCatalogSnapshot?> Read()
    {
        await gate.WaitAsync();
        try
        {
            if(!File.Exists(path))return null;
            await using var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read,65536,true);
            var stations=await JsonSerializer.DeserializeAsync<List<PublicStation>>(stream,new JsonSerializerOptions{PropertyNameCaseInsensitive=true});
            if(stations is null||stations.Count==0)return null;
            return new(stations,new DateTimeOffset(File.GetLastWriteTimeUtc(path),TimeSpan.Zero));
        }
        catch(Exception error) when(error is IOException or UnauthorizedAccessException or JsonException){return null;}
        finally{gate.Release();}
    }
}
internal static class CsvStringExtensions
{
    public static bool StartsWithAny(this string value,params char[] chars)=>value.Length>0&&chars.Contains(value[0]);
}
