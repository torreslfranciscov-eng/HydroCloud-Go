using Oracle.ManagedDataAccess.Client;
using Oracle.ManagedDataAccess.Types;

namespace HydroCloud.Admin;

public record StationSignal(string StationId,string State);
public record AvailabilitySnapshot(DateTimeOffset CheckedAt,List<StationSignal> Stations);

// Short-lived, single-flight cache: no use of the stale ULTIMAS_MEDICIONES summary.
public sealed class StationAvailability(IConfiguration config,TimeProvider clock,ILogger<StationAvailability> log)
{
    private readonly SemaphoreSlim gate=new(1,1);
    private AvailabilitySnapshot? cached;
    public static string Combine(IEnumerable<string> states)
    {
        var all=states.ToList();
        if(all.Contains("recent"))return "recent";
        if(all.Contains("corrupt"))return "corrupt";
        if(all.Contains("unknown")||all.Count==0)return "unknown";
        if(all.Contains("week"))return "week";
        if(all.Contains("historical"))return "historical";
        return "empty";
    }
    public async Task<AvailabilitySnapshot> Get()
    {
        await gate.WaitAsync();
        try
        {
            var now=clock.GetUtcNow();if(cached is not null && now-cached.CheckedAt<TimeSpan.FromMinutes(2))return cached;
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(55));var ct=timeout.Token;
            var mappings=new Dictionary<string,(string Code,List<string> Dcps)>();
            using(var c=new OracleConnection(config.GetConnectionString("HydroCloud")))
            {
                await c.OpenAsync(ct);
                using var cmd=new OracleCommand("SELECT E.ID,E.IDASIGNADO,G.IDSATELITAL FROM HYDROCLOUD.ESTACION E LEFT JOIN HYDROCLOUD.DATOSGOES G ON G.IDESTACION=E.ID WHERE E.ACTIVO=1 AND E.VISIBLE=1",c){CommandTimeout=15};
                using var r=(OracleDataReader)await cmd.ExecuteReaderAsync(ct);
                while(await r.ReadAsync(ct))
                {
                    var id=r.GetString(0).TrimEnd();
                    if(!mappings.ContainsKey(id))mappings[id]=(r.IsDBNull(1)?"":r.GetString(1).Trim(),[]);
                    if(!r.IsDBNull(2))mappings[id].Dcps.Add(r.GetString(2).Trim());
                }
            }
            var results=new System.Collections.Concurrent.ConcurrentBag<StationSignal>();
            await Parallel.ForEachAsync(mappings,new ParallelOptions{MaxDegreeOfParallelism=4},async (entry,_)=>
            {
                var states=new List<string>();
                if(entry.Value.Dcps.Count==0 || string.IsNullOrEmpty(entry.Value.Code)){results.Add(new(entry.Key,"unknown"));return;}
                try
                {
                    using var c=new OracleConnection(config.GetConnectionString("TimeSeries"));await c.OpenAsync(ct);
                    foreach(var dcp in entry.Value.Dcps.Distinct())
                    {
                        // The DCP prefix uses the existing index; no full ID_ASIGNADO scan.
                        const string match="DCP_ID=:dcp AND ID_ASIGNADO=:code AND TS<=:nowTime";
                        const string rawMatch="DCP_ID=:dcp AND SYS_EXTRACT_UTC(TIMESTAMP_MSG)<=SYS_EXTRACT_UTC(:nowTime) AND SYS_EXTRACT_UTC(TIMESTAMP_MSG)>=SYS_EXTRACT_UTC(:dayTime) AND RAW_MESSAGE IS NOT NULL AND INSTR(RAW_MESSAGE,'Missing message from')=0 AND INSTR(RAW_MESSAGE,'SATLINK DATA BUFFER EMPTY')=0";
                        using var cmd=new OracleCommand($"SELECT CASE WHEN EXISTS (SELECT 1 FROM MYCLOUD_TS.DCP_DATOS WHERE {match} AND SYS_EXTRACT_UTC(TS)>=SYS_EXTRACT_UTC(:dayTime) AND ROWNUM=1) THEN 'recent' WHEN EXISTS (SELECT 1 FROM MYCLOUD_TS.DCP_HEADERS WHERE {rawMatch} AND ROWNUM=1) THEN 'corrupt' WHEN EXISTS (SELECT 1 FROM MYCLOUD_TS.DCP_DATOS WHERE {match} AND SYS_EXTRACT_UTC(TS)>=SYS_EXTRACT_UTC(:weekTime) AND ROWNUM=1) THEN 'week' WHEN EXISTS (SELECT 1 FROM MYCLOUD_TS.DCP_DATOS WHERE {match} AND ROWNUM=1) THEN 'historical' ELSE 'empty' END FROM DUAL",c){BindByName=true,CommandTimeout=6};
                        cmd.Parameters.Add("dcp",OracleDbType.Varchar2).Value=dcp;cmd.Parameters.Add("code",OracleDbType.Varchar2).Value=entry.Value.Code;
                        cmd.Parameters.Add("nowTime",OracleDbType.TimeStampTZ).Value=new OracleTimeStampTZ(now.UtcDateTime,"+00:00");
                        cmd.Parameters.Add("dayTime",OracleDbType.TimeStampTZ).Value=new OracleTimeStampTZ(now.AddDays(-1).UtcDateTime,"+00:00");
                        cmd.Parameters.Add("weekTime",OracleDbType.TimeStampTZ).Value=new OracleTimeStampTZ(now.AddDays(-7).UtcDateTime,"+00:00");
                        states.Add((string)(await cmd.ExecuteScalarAsync(ct))!);
                        if(states[^1]=="recent")break;
                    }
                }
                catch(Exception e) when(e is OracleException or OperationCanceledException or InvalidOperationException)
                {states.Add("unknown");log.LogDebug("Disponibilidad no verificada para {Station}: {Type}",entry.Key,e.GetType().Name);}
                results.Add(new(entry.Key,Combine(states)));
            });
            cached=new(now,results.OrderBy(x=>x.StationId).ToList());return cached;
        }
        finally{gate.Release();}
    }
}
