using System.Globalization;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Authorization;
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
public record PublicStation(string Id,string Code,string Name,double? Latitude,double? Longitude,bool Goes,bool Gprs,bool Radio,bool IsDam,int SensorCount,int DcpCount);
public record UpstreamStation(string DamStationId,string StationId,string Code,string Name,double? Latitude,double? Longitude,string River,string RelationStatus,int Priority);
public record UpstreamMetric(string SensorType,string Unit,double? Value,DateTimeOffset? Timestamp,bool? Valid,double? PreviousValue,DateTimeOffset? PreviousTimestamp,bool? PreviousValid);
public record UpstreamCondition(string DamStationId,string StationId,UpstreamMetric? Level,double? Rain1Hour,double? Rain6Hours,string RainUnit,DateTimeOffset? RainTimestamp,UpstreamMetric? Flow,UpstreamMetric? WaterVelocity);
public record LevelPoint(DateTimeOffset Timestamp,double Value);
public record LatestLevel(string StationId,bool SensorConfigured,string? SensorId,string? SensorType,string? Unit,double? Value,DateTimeOffset? Timestamp,bool? Valid,double? PreviousValue,DateTimeOffset? PreviousTimestamp,bool? PreviousValid,List<LevelPoint> History);
public record QuerySeries(string SensorId,string Name,string Unit,string ConfiguredChartType);
public record QueryData(string Product,QueryWindow Window,List<string> Columns,List<Dictionary<string,object?>> Rows,List<QuerySeries> Series,bool Truncated,string Note);
public interface IConsultationRepository
{
    Task<List<PublicStation>> Stations();
    Task<List<UpstreamStation>> UpstreamStations(CancellationToken cancellation);
    Task<List<UpstreamCondition>> UpstreamConditions(CancellationToken cancellation);
    Task<List<LatestLevel>> LatestDamLevels(CancellationToken cancellation);
    Task<QueryData> Query(string stationId,QueryProduct product,QueryWindow window,CancellationToken cancellation,string? sensorId=null,string? variable=null);
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
    public async Task<List<PublicStation>> Stations()
    {
        await using var c=await OpenAtlas();
        await using var cmd=new NpgsqlCommand(@"SELECT CAST(e.Id AS varchar(36)),e.IdAsignado,e.Nombre,e.Latitud,e.Longitud,e.GOES,e.GPRS,e.RADIO,
CASE WHEN EsPresa=1 OR UPPER(COALESCE(Nombre,'')) LIKE '%PRESA%' THEN true ELSE false END AS EsPresaClasificada,
(SELECT COUNT(*)::int FROM dbo.Sensor s WHERE s.IdEstacion=e.Id AND s.Activo=1 AND s.Visible=1) AS SensorCount,
(SELECT COUNT(*)::int FROM dbo.DatosGOES g WHERE g.IdEstacion=e.Id) AS DcpCount
FROM dbo.Estacion e WHERE e.Activo=1 AND e.Visible=1 ORDER BY e.Nombre,e.Id",c){CommandTimeout=30};
        await using var r=await cmd.ExecuteReaderAsync();var rows=new List<PublicStation>();
        while(await r.ReadAsync()) rows.Add(ReadStationRow(r));
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
        return new(r.GetString(0),r.IsDBNull(1)?"":r.GetString(1),r.IsDBNull(2)?"Sin nombre":r.GetString(2),lat,lon,!r.IsDBNull(5)&&r.GetBoolean(5),!r.IsDBNull(6)&&r.GetBoolean(6),!r.IsDBNull(7)&&r.GetBoolean(7),!r.IsDBNull(8)&&r.GetBoolean(8),r.GetInt32(9),r.GetInt32(10));
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
        await using(var sensorCommand=new NpgsqlCommand(@"SELECT TRIM(s.NumeroSensor),COALESCE(ts.Nombre,'Sensor'),COALESCE(u.Abreviatura,u.Nombre,''),COALESCE(s.TipoGrafica,'line')
FROM dbo.Sensor s
JOIN dbo.TipoSensor ts ON ts.Id=s.IdTipoSensor
LEFT JOIN dbo.UnidadMedida u ON u.Id=s.IdUnidadMedida
WHERE UPPER(s.IdEstacion)=@id AND s.Activo=1 AND s.Visible=1 AND s.NumeroSensor IS NOT NULL
ORDER BY s.Orden,s.NumeroSensor",c){CommandTimeout=15})
        {
            sensorCommand.Parameters.AddWithValue("id",NpgsqlDbType.Text,stationIdText);
            await using var sensorReader=await sensorCommand.ExecuteReaderAsync(ct);
            while(await sensorReader.ReadAsync(ct))series.Add(new(sensorReader.GetString(0),sensorReader.GetString(1),sensorReader.GetString(2),sensorReader.GetString(3)));
        }
        var keys=new List<string>();
        if(p.Scope=="DCP_ID")
        {
            await using var dcps=new NpgsqlCommand("SELECT DISTINCT IdSatelital FROM dbo.DatosGOES WHERE UPPER(IdEstacion)=@id",c){CommandTimeout=15};
            dcps.Parameters.AddWithValue("id",NpgsqlDbType.Text,stationIdText);
            await using var dr=await dcps.ExecuteReaderAsync(ct);while(await dr.ReadAsync(ct)) keys.Add(dr.GetString(0).Trim());
        } else keys.Add(Convert.ToString(code,CultureInfo.InvariantCulture)!.Trim());
        var columns=p.Columns.Split(',').ToList();
        if(keys.Count==0) return new(p.Key,window,columns,[],series,false,"No hay un identificador GOES configurado para esta estación.");
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
        return new(p.Key,window,columns,rows,series,truncated,"Datos consultados en PostgreSQL/Timescale. El tipo de gráfica, nombre y unidad proceden del catálogo de sensores en DB_ATLAS. Fechas en UTC. Resúmenes y acumulados son productos almacenados, no recalculados ni certificados. Solo se incluyen periodos completos dentro del rango. Sin registros no significa valor cero."+(truncated?" Se muestran/exportan las primeras 2,000 filas: reduce el periodo para obtener el resto.":""));
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
            var stations=await repository.Stations();
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
                log.LogWarning("Catálogo DB_ATLAS no disponible: {Type}; se conserva la última copia verificada",e.GetType().Name);
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
