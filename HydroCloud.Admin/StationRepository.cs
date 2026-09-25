using System.Data;
using System.Globalization;
using Oracle.ManagedDataAccess.Client;

namespace HydroCloud.Admin;

public interface IStationRepository
{
    Task<StationList> List(string search, string state, int page);
    Task<Station?> Find(string id);
    Task<Dictionary<string,List<CatalogItem>>> Catalogs();
    Task Save(Station station, string? version, string actor);
    Task Deactivate(string id, string version, string actor);
}

public sealed class StationRepository(IConfiguration config) : IStationRepository
{
    private const string Columns = "ID,IDASIGNADO,NOMBRE,LATITUD,LONGITUD,IDCUENCA,IDSUBCUENCA,IDENTIDADFEDERATIVA,IDMUNICIPIO,IDORGANISMO,IDESTADO,ETIQUETA,COMENTARIO,ACTIVO,VISIBLE,GOES,GPRS,RADIO,ESPRESA";
    private async Task<OracleConnection> Open()
    {
        var value = config.GetConnectionString("HydroCloud");
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidOperationException("Configura ConnectionStrings:HydroCloud antes de consultar estaciones.");
        var c = new OracleConnection(value);
        try { await c.OpenAsync(); return c; } catch { c.Dispose(); throw; }
    }
    private static OracleCommand Command(OracleConnection c, string sql, OracleTransaction? tx = null)
        => new(sql, c) { BindByName = true, CommandTimeout = 30, Transaction = tx };
    private static void Bind(OracleCommand cmd, string name, OracleDbType type, object? value)
        => cmd.Parameters.Add(name, type).Value = value ?? DBNull.Value;
    private static Station Read(OracleDataReader r)
    {
        string? S(int i) => r.IsDBNull(i) ? null : r.GetString(i).TrimEnd();
        int? I(int i) => r.IsDBNull(i) ? null : Convert.ToInt32(r.GetValue(i), CultureInfo.InvariantCulture);
        return new Station { Id = S(0)!, Code = S(1) ?? "", Name = S(2) ?? "",
            Latitude = r.IsDBNull(3) ? null : r.GetDouble(3), Longitude = r.IsDBNull(4) ? null : r.GetDouble(4),
            Basin = S(5), SubBasin = S(6), State = I(7), Municipality = I(8), Organization = I(9), Status = I(10),
            Tag = S(11), Comment = S(12), Active = I(13) == 1, Visible = I(14) == 1,
            Goes = I(15) == 1, Gprs = I(16) == 1, Radio = I(17) == 1, IsDam = I(18) == 1 };
    }
    public async Task<StationList> List(string search, string state, int page)
    {
        using var c = await Open();
        var where = " WHERE (:search IS NULL OR INSTR(UPPER(NOMBRE),UPPER(:search))>0 OR INSTR(UPPER(IDASIGNADO),UPPER(:search))>0) AND (:state='all' OR NVL(ACTIVO,0)=:active)";
        using var count = Command(c, "SELECT COUNT(*) FROM HYDROCLOUD.ESTACION" + where);
        void Filter(OracleCommand cmd) { Bind(cmd,"search",OracleDbType.NVarchar2,search); Bind(cmd,"state",OracleDbType.Varchar2,state); Bind(cmd,"active",OracleDbType.Int32,state == "inactive" ? 0 : 1); }
        Filter(count);
        var total = Convert.ToInt32(await count.ExecuteScalarAsync());
        page = Math.Clamp(page, 1, Math.Max(1, (total + 24) / 25));
        using var cmd = Command(c, "SELECT " + Columns + " FROM HYDROCLOUD.ESTACION" + where + " ORDER BY NOMBRE NULLS LAST,ID OFFSET :skip ROWS FETCH NEXT 25 ROWS ONLY");
        Filter(cmd); Bind(cmd,"skip",OracleDbType.Int32,(page-1)*25);
        using var reader = (OracleDataReader)await cmd.ExecuteReaderAsync();
        var rows = new List<Station>(); while (await reader.ReadAsync()) rows.Add(Read(reader));
        using var active = Command(c, "SELECT COUNT(*) FROM HYDROCLOUD.ESTACION WHERE ACTIVO=1");
        return new(rows,total,Convert.ToInt32(await active.ExecuteScalarAsync()),page,search,state);
    }
    private static async Task<Station?> Find(OracleConnection c, string id, OracleTransaction? tx = null)
    {
        using var cmd = Command(c, "SELECT " + Columns + " FROM HYDROCLOUD.ESTACION WHERE ID=:id" + (tx is null ? "" : " FOR UPDATE WAIT 5"), tx);
        Bind(cmd,"id",OracleDbType.Char,id);
        using var r = (OracleDataReader)await cmd.ExecuteReaderAsync();
        return await r.ReadAsync() ? Read(r) : null;
    }
    public async Task<Station?> Find(string id) { using var c = await Open(); return await Find(c,id); }
    public async Task<Dictionary<string,List<CatalogItem>>> Catalogs()
    {
        using var c = await Open();
        var result = new Dictionary<string,List<CatalogItem>>();
        foreach (var (key,table,parent) in new[] { ("Basin","CUENCA","NULL"),("SubBasin","SUBCUENCA","IDCUENCA"),("State","ENTIDADFEDERATIVA","NULL"),("Municipality","MUNICIPIO","TO_CHAR(IDENTIDADFEDERATIVA)"),("Organization","ORGANISMO","NULL"),("Status","ESTATUSESTACIONBITACORA","NULL") })
        {
            using var cmd = Command(c,$"SELECT ID,NOMBRE,{parent} FROM HYDROCLOUD.{table} ORDER BY NOMBRE");
            using var r = (OracleDataReader)await cmd.ExecuteReaderAsync();
            var items = new List<CatalogItem>();
            while (await r.ReadAsync()) items.Add(new(Convert.ToString(r.GetValue(0),CultureInfo.InvariantCulture)!.Trim(), r.IsDBNull(1)?"Sin nombre":r.GetString(1),r.IsDBNull(2)?null:r.GetString(2).Trim()));
            result[key] = items;
        }
        return result;
    }
    public async Task Save(Station s, string? originalVersion, string actor)
    {
        using var c = await Open(); using var tx = c.BeginTransaction();
        var create = originalVersion is null;
        if (!create)
        {
            var old = await Find(c,s.Id,tx);
            if (old is null || old.Version()!=originalVersion) throw new StationConflictException("La estación cambió desde que abriste el formulario. Recarga antes de guardar.");
        }
        using (var duplicate = Command(c,"SELECT COUNT(*) FROM HYDROCLOUD.ESTACION WHERE UPPER(TRIM(IDASIGNADO))=UPPER(:code) AND ID<>:id",tx))
        {
            Bind(duplicate,"code",OracleDbType.NVarchar2,s.Code.Trim()); Bind(duplicate,"id",OracleDbType.Char,s.Id);
            if (Convert.ToInt32(await duplicate.ExecuteScalarAsync())>0) throw new StationConflictException("La clave ya pertenece a otra estación.");
        }
        var names = new[] {"IDASIGNADO","NOMBRE","LATITUD","LONGITUD","IDCUENCA","IDSUBCUENCA","IDENTIDADFEDERATIVA","IDMUNICIPIO","IDORGANISMO","IDESTADO","ETIQUETA","COMENTARIO","ACTIVO","VISIBLE","GOES","GPRS","RADIO","ESPRESA","COORDENADAS"};
        var sql = create
            ? $"INSERT INTO HYDROCLOUD.ESTACION (ID,{string.Join(',',names)},USUARIOREGISTRO,FECHAREGISTRO) VALUES (:id,{string.Join(',',names.Select(n=>":"+n))},:actor,:dateText)"
            : $"UPDATE HYDROCLOUD.ESTACION SET {string.Join(',',names.Select(n=>n+"=:"+n))},USUARIOMODIFICACION=:actor,FECHAMODIFICACION=:dateText WHERE ID=:id";
        using var cmd = Command(c,sql,tx);
        Bind(cmd,"id",OracleDbType.Char,s.Id);
        Bind(cmd,"IDASIGNADO",OracleDbType.NVarchar2,s.Code.Trim()); Bind(cmd,"NOMBRE",OracleDbType.NVarchar2,s.Name.Trim());
        Bind(cmd,"LATITUD",OracleDbType.BinaryDouble,s.Latitude); Bind(cmd,"LONGITUD",OracleDbType.BinaryDouble,s.Longitude);
        Bind(cmd,"IDCUENCA",OracleDbType.Char,s.Basin); Bind(cmd,"IDSUBCUENCA",OracleDbType.Char,s.SubBasin);
        Bind(cmd,"IDENTIDADFEDERATIVA",OracleDbType.Int32,s.State); Bind(cmd,"IDMUNICIPIO",OracleDbType.Int32,s.Municipality);
        Bind(cmd,"IDORGANISMO",OracleDbType.Int32,s.Organization); Bind(cmd,"IDESTADO",OracleDbType.Int32,s.Status);
        Bind(cmd,"ETIQUETA",OracleDbType.Varchar2,s.Tag); Bind(cmd,"COMENTARIO",OracleDbType.NClob,s.Comment);
        foreach(var (name,value) in new[] {("ACTIVO",s.Active),("VISIBLE",s.Visible),("GOES",s.Goes),("GPRS",s.Gprs),("RADIO",s.Radio),("ESPRESA",s.IsDam)}) Bind(cmd,name,OracleDbType.Int32,value?1:0);
        Bind(cmd,"COORDENADAS",OracleDbType.NVarchar2,s.Latitude.HasValue && s.Longitude.HasValue ? FormattableString.Invariant($"{s.Latitude},{s.Longitude}") : null);
        Bind(cmd,"actor",OracleDbType.Varchar2,actor); Bind(cmd,"dateText",OracleDbType.Varchar2,DateTimeOffset.UtcNow.ToString("O"));
        await cmd.ExecuteNonQueryAsync(); tx.Commit();
    }
    public async Task Deactivate(string id, string version, string actor)
    {
        using var c = await Open(); using var tx = c.BeginTransaction();
        var s = await Find(c,id,tx);
        if (s is null || s.Version()!=version) throw new StationConflictException("La estación cambió. Recarga la confirmación de baja.");
        using var cmd = Command(c,"UPDATE HYDROCLOUD.ESTACION SET ACTIVO=0,VISIBLE=0,USUARIOMODIFICACION=:actor,FECHAMODIFICACION=:dt WHERE ID=:id",tx);
        Bind(cmd,"actor",OracleDbType.Varchar2,actor); Bind(cmd,"dt",OracleDbType.Varchar2,DateTimeOffset.UtcNow.ToString("O")); Bind(cmd,"id",OracleDbType.Char,id);
        await cmd.ExecuteNonQueryAsync(); tx.Commit();
    }
}
