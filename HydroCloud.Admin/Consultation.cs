using System.Globalization;
using System.Text;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
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
        new("variables","Variables · lecturas y calidad","DCP_DATOS","TS","TS,SENSOR_ID,VARIABLE,VALOR,VALIDO,QC_FLAG,QC_DETAIL"),
        new("horario","Variables · resumen horario","RESUMEN_HORARIO","TS","TS,SENSOR_ID,VARIABLE,CONTEO,PROMEDIO,MINIMO,MAXIMO,ACUMULADO",Bucket:"hour"),
        new("diario","Variables · resumen diario","RESUMEN_DIARIO","FECHA","FECHA,SENSOR_ID,VARIABLE,CONTEO,PROMEDIO,MINIMO,MAXIMO,ACUMULADO",Bucket:"day"),
        new("transmisiones","GOES · transmisiones y señal","DCP_HEADERS","TS","TS,DCP_ID,TIMESTAMP_MSG,SIGNAL_STRENGTH,FREQUENCY_OFFSET,MOD_INDEX,CHANNEL,SPACECRAFT,FAILURE_CODE,DATA_QUALITY,EB_NO,PARITY_ERROR,WINDOW_OFFSET_SEC","DCP_ID"),
        new("recepcion","GOES · intentos de recepción","BITACORA_GOES","TIMESTAMP_UTC","TIMESTAMP_UTC,DCP_ID,EXITO","DCP_ID"),
        new("eficiencia","GOES · eficiencia diaria","DIAGNOSTICO_DIARIO_GOES","FECHA","FECHA,DCP_ID,TX_PROGRAMADAS,TX_RECIBIDAS,PORCENTAJE_EFICIENCIA,POTENCIA_PROM,POTENCIA_MIN,POTENCIA_MAX,CALIDAD_SENAL,ESTADO_OPERATIVO",Bucket:"day"),
        new("lluvia","Lluvia · acumulados por periodo","LLUVIA_ACUMULADA","PERIODO_INICIO","PERIODO_INICIO,PERIODO_FIN,SENSOR_ID,VARIABLE,TIPO_PERIODO,ACUMULADO,HORAS_CON_DATO",End:"PERIODO_FIN"),
        new("eventos","Lluvia · eventos","EVENTOS_LLUVIA","INICIO","INICIO,FIN,SENSOR_ID,ACUMULADO_MM,INTENSIDAD_MAX_MMH,DURACION_MINUTOS,ESTADO,SOSPECHOSO,MOTIVO_SOSPECHA",End:"COALESCE(FIN,ULTIMA_ACTUALIZACION)"),
        new("alertas","Lluvia · alertas registradas","ALERTAS_PRECIPITACION","TS","TS,SENSOR_ID,UMBRAL_NOMBRE,VALOR_REFERENCIA,VALOR_MEDIDO,PERIODO_MINUTOS,ACTIVA")
    ];
    public static readonly QueryProduct SensorCatalog=new("sensorcatalog","Variables disponibles","DCP_DATOS","TS","SENSOR_ID,VARIABLE");
    public static QueryProduct? Find(string key)=>All.SingleOrDefault(x=>x.Key==key);
}
public record PublicStation(string Id,string Code,string Name,double? Latitude,double? Longitude,bool Goes,bool Gprs,bool Radio);
public record QueryData(string Product,QueryWindow Window,List<string> Columns,List<Dictionary<string,object?>> Rows,bool Truncated,string Note);
public interface IConsultationRepository
{
    Task<List<PublicStation>> Stations();
    Task<QueryData> Query(string stationId,QueryProduct product,QueryWindow window,CancellationToken cancellation,string? sensorId=null,string? variable=null);
}
public sealed class ConsultationRepository(IConfiguration config) : IConsultationRepository
{
    private async Task<OracleConnection> Open(string name,CancellationToken ct=default)
    {
        var cs=config.GetConnectionString(name); if(string.IsNullOrWhiteSpace(cs)) throw new InvalidOperationException("La conexión de consulta todavía no está configurada.");
        var c=new OracleConnection(cs); try { await c.OpenAsync(ct);return c; }catch { c.Dispose();throw; }
    }
    private static OracleCommand Cmd(OracleConnection c,string sql)=>new(sql,c){BindByName=true,CommandTimeout=30};
    public async Task<List<PublicStation>> Stations()
    {
        try
        {
            using var c=await Open("HydroCloud");using var cmd=Cmd(c,"SELECT ID,IDASIGNADO,NOMBRE,LATITUD,LONGITUD,GOES,GPRS,RADIO FROM MYCLOUD_TS.ESTACION WHERE ACTIVO=1 AND VISIBLE=1 ORDER BY NOMBRE,ID");
            using var r=(OracleDataReader)await cmd.ExecuteReaderAsync();var rows=new List<PublicStation>();
            while(await r.ReadAsync()) rows.Add(ReadStationRow(r));
            if(rows.Count>0) return rows;
        }
        catch(OracleException ex) when(ex.Number==942) { }

        using var cFallback=await Open("HydroCloud");
        var sql=@"SELECT e.dcp_id AS ID, NVL(st.IDASIGNADO, NVL(d.id_asignado, e.dcp_id)) AS IDASIGNADO, NVL(st.NOMBRE, NVL(cp.nombre, NVL(d.id_asignado, e.dcp_id))) AS NOMBRE, NVL(st.LATITUD, cp.latitud) AS LATITUD, NVL(st.LONGITUD, cp.longitud) AS LONGITUD, 1 AS GOES, 0 AS GPRS, 0 AS RADIO FROM MYCLOUD_TS.ESTATUS_ESTACIONES e LEFT JOIN MYCLOUD_TS.ESTACION st ON (UPPER(e.dcp_id) = UPPER(st.ID) OR UPPER(e.dcp_id) = UPPER(st.IDASIGNADO)) LEFT JOIN (SELECT dcp_id, MAX(id_asignado) AS id_asignado FROM MYCLOUD_TS.DCP_DATOS GROUP BY dcp_id) d ON e.dcp_id = d.dcp_id LEFT JOIN MYCLOUD_TS.HM_CENTRAL_PARAMS cp ON (UPPER(d.id_asignado) = UPPER(cp.clave20) OR UPPER(d.id_asignado) = UPPER(cp.clave_sap) OR UPPER(d.id_asignado) = UPPER(cp.clave_cenace) OR UPPER(e.dcp_id) = UPPER(cp.clave20) OR INSTR(UPPER(cp.nombre), UPPER(NVL(d.id_asignado, e.dcp_id))) > 0) WHERE e.dcp_id IS NOT NULL ORDER BY NOMBRE";
        using var cmdFallback=Cmd(cFallback,sql);
        using var rFallback=(OracleDataReader)await cmdFallback.ExecuteReaderAsync();var fallbackRows=new List<PublicStation>();
        while(await rFallback.ReadAsync()) fallbackRows.Add(ReadStationRow(rFallback));
        return fallbackRows;
    }
    private static PublicStation ReadStationRow(OracleDataReader r)
    {
        double? lat=r.IsDBNull(3)?null:r.GetDouble(3);
        double? lon=r.IsDBNull(4)?null:r.GetDouble(4);
        if(lat.HasValue && lon.HasValue && Math.Abs(lat.Value)>90 && Math.Abs(lon.Value)<=90) (lat,lon)=(lon,lat);
        if(lon.HasValue && lon.Value>80 && lon.Value<130) lon=-lon.Value;
        return new(r.GetString(0).TrimEnd(),r.IsDBNull(1)?"":r.GetString(1),r.IsDBNull(2)?"Sin nombre":r.GetString(2),lat,lon,!r.IsDBNull(5)&&r.GetInt32(5)==1,!r.IsDBNull(6)&&r.GetInt32(6)==1,!r.IsDBNull(7)&&r.GetInt32(7)==1);
    }
    public async Task<QueryData> Query(string stationId,QueryProduct p,QueryWindow window,CancellationToken ct,string? sensorId=null,string? variable=null)
    {
        // Visibility and station-to-DCP mapping are resolved server-side, not accepted from a URL.
        using var catalog=await Open("HydroCloud",ct);
        object? code = null;
        try
        {
            using var station=Cmd(catalog,"SELECT IDASIGNADO FROM HYDROCLOUD.ESTACION WHERE ID=:id AND ACTIVO=1 AND VISIBLE=1");station.Parameters.Add("id",OracleDbType.Char).Value=stationId;
            code=await station.ExecuteScalarAsync(ct);
        }
        catch(OracleException ex) when(ex.Number==942)
        {
            using var station=Cmd(catalog,"SELECT MAX(id_asignado) FROM MYCLOUD_TS.DCP_DATOS WHERE dcp_id=:id OR id_asignado=:id");station.Parameters.Add("id",OracleDbType.Varchar2).Value=stationId;
            var res=await station.ExecuteScalarAsync(ct);
            code = res is null || res is DBNull ? stationId : res;
        }
        if(code is null || code is DBNull) throw new ArgumentException("La estación no está disponible para consulta.");
        var keys=new List<string>();
        if(p.Scope=="DCP_ID")
        {
            try
            {
                using var dcps=Cmd(catalog,"SELECT DISTINCT IDSATELITAL FROM HYDROCLOUD.DATOSGOES WHERE IDESTACION=:id");dcps.Parameters.Add("id",OracleDbType.Char).Value=stationId;
                using var dr=(OracleDataReader)await dcps.ExecuteReaderAsync(ct);while(await dr.ReadAsync(ct)) keys.Add(dr.GetString(0).Trim());
            }
            catch(OracleException ex) when(ex.Number==942)
            {
                keys.Add(stationId);
            }
        } else keys.Add(Convert.ToString(code,CultureInfo.InvariantCulture)!.Trim());
        var columns=p.Columns.Split(',').ToList();
        if(keys.Count==0) return new(p.Key,window,columns,[],false,"No hay un identificador GOES configurado para esta estación.");
        using var c=await Open("TimeSeries",ct);
        var date=p.Bucket=="day";
        var begin=date?"CAST(SYS_EXTRACT_UTC(:startTime) AS DATE)":":startTime";
        var end=date?"CAST(SYS_EXTRACT_UTC(:endTime) AS DATE)":":endTime";
        var extra=p.End is not null?$" AND {p.End} <= :endTime":p.Bucket=="day"?$" AND {p.Time}+1 <= {end}":p.Bucket=="hour"?$" AND {p.Time}+INTERVAL '1' HOUR <= :endTime":"";
        var sql=$"SELECT {p.Columns} FROM MYCLOUD_TS.{p.Table} WHERE {p.Scope} IN ({string.Join(',',keys.Select((_,i)=>":k"+i))}) AND {p.Time}>={begin} AND {p.Time}<={end}{extra} ORDER BY {p.Time},{string.Join(',',columns.Where(x=>x!=p.Time && x is "SENSOR_ID" or "VARIABLE" or "DCP_ID").DefaultIfEmpty(p.Scope))} FETCH FIRST 2001 ROWS ONLY";
        using var cmd=Cmd(c,sql);
        for(var i=0;i<keys.Count;i++) cmd.Parameters.Add("k"+i,OracleDbType.Varchar2).Value=keys[i];
        // Explicit UTC offsets avoid driver/session time-zone interpretation.
        cmd.Parameters.Add("startTime",OracleDbType.TimeStampTZ).Value=new Oracle.ManagedDataAccess.Types.OracleTimeStampTZ(window.Start.UtcDateTime,"+00:00");
        cmd.Parameters.Add("endTime",OracleDbType.TimeStampTZ).Value=new Oracle.ManagedDataAccess.Types.OracleTimeStampTZ(window.End.UtcDateTime,"+00:00");
        using var r=(OracleDataReader)await cmd.ExecuteReaderAsync(ct); var rows=new List<Dictionary<string,object?>>();
        while(await r.ReadAsync(ct))
        {
            var row=new Dictionary<string,object?>();
            for(int i=0;i<r.FieldCount;i++)
            {
                if(r.IsDBNull(i)) {row[columns[i]]=null;continue;}
                var providerType=r.GetProviderSpecificFieldType(i).Name;
                var value=r.GetValue(i);
                if(providerType=="OracleTimeStampTZ") row[columns[i]]=r.GetOracleTimeStampTZ(i).ToUniversalTime().Value.ToString("yyyy-MM-ddTHH:mm:ss.fff'Z'",CultureInfo.InvariantCulture);
                else if(value is DateTime dt) row[columns[i]]=dt.ToString("yyyy-MM-ddTHH:mm:ss'Z'",CultureInfo.InvariantCulture);
                else if(value is decimal or double or float or long or int or short) { var n=Convert.ToDouble(value,CultureInfo.InvariantCulture);row[columns[i]]=double.IsFinite(n)?n:null; }
                else row[columns[i]]=r.GetString(i);
            }
            rows.Add(row);
        }
        bool truncated=rows.Count>2000;if(truncated) rows.RemoveAt(rows.Count-1);
        return new(p.Key,window,columns,rows,truncated,"Fechas en UTC. Resúmenes y acumulados son productos almacenados, no recalculados ni certificados. Solo se incluyen periodos completos dentro del rango. Sin registros no significa valor cero."+(truncated?" Se muestran/exportan las primeras 2,000 filas: reduce el periodo para obtener el resto.":""));
    }
}

[EnableRateLimiting("consultation")]
[ResponseCache(NoStore=true,Location=ResponseCacheLocation.None)]
public sealed class ExploreController(IConsultationRepository repository,VisitorCounter visitors,TimeProvider clock,ILogger<ExploreController> log) : Controller
{
    [HttpGet] public async Task<IActionResult> Availability([FromServices] StationAvailability availability)
    {
        try{return Json(await availability.Get());}
        catch(Exception e) when(e is OracleException or OperationCanceledException or InvalidOperationException)
        {return StatusCode(503,new{error="No se pudo verificar la disponibilidad. El gris indica estado desconocido, no ausencia de datos."});}
    }
    [HttpGet] public async Task<IActionResult> Index() { await visitors.Record("visits",User.Identity?.IsAuthenticated==true);return View(); }
    [HttpGet] public async Task<IActionResult> Stations()
    {
        try { return Json(await repository.Stations()); }
        catch(Exception e) when(e is OracleException or OperationCanceledException or InvalidOperationException)
        { return StatusCode(503, new { error = "El servicio de catálogo de estaciones no está disponible temporalmente." }); }
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
        catch(OracleException e) {log.LogWarning("Consulta Oracle fallida: código {Code}",e.Number);return StatusCode(503,new{error="No fue posible completar la consulta. Reduce el periodo o inténtalo de nuevo."});}
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
internal static class CsvStringExtensions
{
    public static bool StartsWithAny(this string value,params char[] chars)=>value.Length>0&&chars.Contains(value[0]);
}
