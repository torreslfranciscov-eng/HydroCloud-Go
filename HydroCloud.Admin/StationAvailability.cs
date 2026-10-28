using Microsoft.Data.SqlClient;
using Npgsql;
using NpgsqlTypes;

namespace HydroCloud.Admin;

public record StationSignal(string StationId,string State,DateTimeOffset? LastTransmission=null,int? ExpectedIntervalMinutes=null,int DcpCount=0);
public record AvailabilitySnapshot(DateTimeOffset CheckedAt,List<StationSignal> Stations);

// Short-lived TX health cache. Status comes from the ingestion-maintained
// estatus_estaciones row and each DCP's expected transmission interval.
public sealed class StationAvailability(IConfiguration config,TimeProvider clock)
{
    private sealed record DcpHealth(string State,DateTimeOffset? LastTransmission,int? ExpectedIntervalMinutes);
    private readonly SemaphoreSlim gate=new(1,1);
    private AvailabilitySnapshot? cached;

    public static string Combine(IEnumerable<string> states)
    {
        var all=states.ToList();
        if(all.Contains("recent"))return "recent";
        if(all.Contains("week"))return "week";
        if(all.Contains("unknown")||all.Count==0)return "unknown";
        if(all.Contains("historical"))return "historical";
        if(all.Contains("empty"))return "empty";
        return "unknown";
    }

    public async Task<AvailabilitySnapshot> Get()
    {
        await gate.WaitAsync();
        try
        {
            var now=clock.GetUtcNow();
            if(cached is not null&&now-cached.CheckedAt<TimeSpan.FromSeconds(30))return cached;
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(20));var ct=timeout.Token;
            var connectionString=config.GetConnectionString("Postgres");
            if(string.IsNullOrWhiteSpace(connectionString))throw new InvalidOperationException("La conexión de telemetría todavía no está configurada.");
            await using var telemetry=new NpgsqlConnection(connectionString);await telemetry.OpenAsync(ct);
            var mappings=new Dictionary<string,List<string>>();
            await using(var command=new NpgsqlCommand("SELECT CAST(E.Id AS varchar(36)),G.IdSatelital FROM dbo.Estacion E LEFT JOIN dbo.DatosGOES G ON G.IdEstacion=E.Id WHERE E.Activo=1 AND E.Visible=1",telemetry){CommandTimeout=12})
            await using(var reader=await command.ExecuteReaderAsync(ct))
            {
                while(await reader.ReadAsync(ct))
                {
                    var id=reader.GetString(0);if(!mappings.ContainsKey(id))mappings[id]=[];
                    if(!reader.IsDBNull(1)&&!string.IsNullOrWhiteSpace(reader.GetString(1)))mappings[id].Add(reader.GetString(1).Trim());
                }
            }

            var dcps=mappings.Values.SelectMany(x=>x).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
            var dcpStates=new Dictionary<string,DcpHealth>(StringComparer.OrdinalIgnoreCase);
            if(dcps.Length>0)
            {
                const string sql="""
                    SELECT dcp_id,
                           CASE
                             WHEN fecha_ultima_tx IS NULL THEN 'empty'
                             WHEN fecha_ultima_tx > @now THEN 'unknown'
                             WHEN EXTRACT(EPOCH FROM (@now-fecha_ultima_tx))/60.0 <= GREATEST(COALESCE(rango_transmision,60),1)*1.5 THEN 'recent'
                             WHEN EXTRACT(EPOCH FROM (@now-fecha_ultima_tx))/60.0 <= GREATEST(COALESCE(rango_transmision,60),1)*3.0 THEN 'week'
                             ELSE 'historical'
                           END AS state,
                           fecha_ultima_tx,
                           rango_transmision
                    FROM public.estatus_estaciones
                    WHERE dcp_id=ANY(@dcps)
                    """;
                await using var command=new NpgsqlCommand(sql,telemetry){CommandTimeout=12};
                command.Parameters.AddWithValue("now",NpgsqlDbType.TimestampTz,now.UtcDateTime);
                command.Parameters.AddWithValue("dcps",NpgsqlDbType.Array|NpgsqlDbType.Text,dcps);
                await using var reader=await command.ExecuteReaderAsync(ct);
                while(await reader.ReadAsync(ct))
                {
                    DateTimeOffset? lastTransmission=reader.IsDBNull(2)?null:new DateTimeOffset(reader.GetFieldValue<DateTime>(2));
                    int? interval=reader.IsDBNull(3)?null:Convert.ToInt32(reader.GetValue(3));
                    dcpStates[reader.GetString(0).Trim()]=new(reader.GetString(1),lastTransmission,interval);
                }
            }

            var results=mappings.Select(entry=>
            {
                var stationDcps=entry.Value.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                if(stationDcps.Count==0)return new StationSignal(entry.Key,"unknown");
                var health=stationDcps.Select(dcp=>dcpStates.GetValueOrDefault(dcp,new("empty",null,null))).ToList();
                var state=Combine(health.Select(x=>x.State));
                var representative=health.Where(x=>x.State==state).OrderByDescending(x=>x.LastTransmission).FirstOrDefault();
                return new StationSignal(entry.Key,state,health.Max(x=>x.LastTransmission),representative?.ExpectedIntervalMinutes,stationDcps.Count);
            }).OrderBy(x=>x.StationId).ToList();
            cached=new(now,results);return cached;
        }
        finally{gate.Release();}
    }
}
