using System.Globalization;
using Oracle.ManagedDataAccess.Client;

namespace HydroCloud.Admin;

public interface IEquipmentRepository
{
    Task<EquipmentPage?> Load(string stationId, EquipmentModule module);
    Task Save(EquipmentForm form, string? version, string actor);
    Task Remove(EquipmentForm form, string version, string actor);
}

public sealed class EquipmentRepository(IConfiguration config, IStationRepository stations) : IEquipmentRepository
{
    private async Task<OracleConnection> Open()
    {
        var c=new OracleConnection(config.GetConnectionString("HydroCloud"));
        try { await c.OpenAsync(); return c; } catch { c.Dispose(); throw; }
    }
    private static OracleCommand Cmd(OracleConnection c,string sql,OracleTransaction? tx=null) => new(sql,c){BindByName=true,CommandTimeout=30,Transaction=tx};
    private static void Bind(OracleCommand cmd,string key,object? value,OracleDbType type=OracleDbType.Varchar2) => cmd.Parameters.Add(key,type).Value=value??DBNull.Value;
    private static string Scope(EquipmentModule m) => m.SensorScoped
        ? "IDSENSOR IN (SELECT ID FROM HYDROCLOUD.SENSOR WHERE IDESTACION=:station)" : "IDESTACION=:station";
    private static async Task<List<EquipmentField>> Fields(OracleConnection c,EquipmentModule m,OracleTransaction? tx=null)
    {
        using var cmd=Cmd(c,"SELECT COLUMN_NAME,DATA_TYPE,CHAR_LENGTH,DATA_PRECISION,DATA_SCALE,NULLABLE FROM ALL_TAB_COLUMNS WHERE OWNER='HYDROCLOUD' AND TABLE_NAME=:tableName ORDER BY COLUMN_ID",tx);
        Bind(cmd,"tableName",m.Table);
        using var r=(OracleDataReader)await cmd.ExecuteReaderAsync(); var result=new List<EquipmentField>();
        while(await r.ReadAsync()) result.Add(new(r.GetString(0),r.GetString(1),r.GetInt32(2),r.IsDBNull(3)?0:r.GetInt32(3),r.IsDBNull(4)?0:r.GetInt32(4),r.GetString(5)=="N"));
        if(result.Count==0) throw new InvalidOperationException("No se encontró el esquema del módulo.");
        return result;
    }
    private static OracleDbType Type(EquipmentField f) => f.Type switch {
        "CHAR"=>OracleDbType.Char,"NVARCHAR2"=>OracleDbType.NVarchar2,"NUMBER"=>OracleDbType.Decimal,"DATE"=>OracleDbType.Date,
        "CLOB"=>OracleDbType.Clob,"NCLOB"=>OracleDbType.NClob,_ when f.Date=>OracleDbType.TimeStamp,_=>OracleDbType.Varchar2 };
    private static object? Value(EquipmentField f,string? v) => string.IsNullOrEmpty(v)?null:f.Numeric?decimal.Parse(v,CultureInfo.InvariantCulture):f.Date?DateTime.Parse(v,CultureInfo.InvariantCulture):v;
    private static void Id(OracleCommand cmd,List<EquipmentField> fields,string id) { var f=fields.Single(x=>x.Name=="ID"); Bind(cmd,"id",Value(f,id),Type(f)); }
    private static async Task<List<EquipmentRow>> Rows(OracleConnection c,EquipmentModule m,List<EquipmentField> fields,string station,string? id=null,OracleTransaction? tx=null)
    {
        using var cmd=Cmd(c,$"SELECT {string.Join(',',fields.Select(f=>f.Name))} FROM HYDROCLOUD.{m.Table} WHERE {Scope(m)}"+(id is null?" ORDER BY ID":" AND ID=:id")+(tx is null?"":" FOR UPDATE WAIT 5"),tx);
        Bind(cmd,"station",station,OracleDbType.Char); if(id is not null) Id(cmd,fields,id);
        using var r=(OracleDataReader)await cmd.ExecuteReaderAsync(); var rows=new List<EquipmentRow>();
        while(await r.ReadAsync())
        {
            var row=new EquipmentRow();
            for(int i=0;i<fields.Count;i++) row.Values[fields[i].Name]=r.IsDBNull(i)?null:fields[i].Date?r.GetDateTime(i).ToString("yyyy-MM-ddTHH:mm:ss.fff",CultureInfo.InvariantCulture):fields[i].Numeric?r.GetDecimal(i).ToString(CultureInfo.InvariantCulture):r.GetString(i).TrimEnd();
            rows.Add(row);
        }
        return rows;
    }
    private static async Task<Dictionary<string,List<CatalogItem>>> Options(OracleConnection c,EquipmentModule m,string station,OracleTransaction? tx=null)
    {
        var result=new Dictionary<string,List<CatalogItem>>();
        var queries=new Dictionary<string,string>();
        if(m.Key=="sensores") {
            queries["IDTIPOSENSOR"]="SELECT ID,NOMBRE FROM HYDROCLOUD.TIPOSENSOR ORDER BY NOMBRE";
            queries["IDUNIDADMEDIDA"]="SELECT ID,NOMBRE || ' (' || ABREVIATURA || ')' FROM HYDROCLOUD.UNIDADMEDIDA ORDER BY NOMBRE";
        }
        if(m.SensorScoped) queries["IDSENSOR"]="SELECT S.ID,NVL(S.NUMEROSENSOR,'Sin número') || ' · ' || T.NOMBRE FROM HYDROCLOUD.SENSOR S LEFT JOIN HYDROCLOUD.TIPOSENSOR T ON T.ID=S.IDTIPOSENSOR WHERE S.IDESTACION=:station ORDER BY S.NUMEROSENSOR";
        foreach(var (key,sql) in queries)
        {
            using var cmd=Cmd(c,sql,tx); if(m.SensorScoped) Bind(cmd,"station",station,OracleDbType.Char);
            using var r=(OracleDataReader)await cmd.ExecuteReaderAsync(); var values=new List<CatalogItem>();
            while(await r.ReadAsync()) values.Add(new(r.GetString(0).TrimEnd(),r.IsDBNull(1)?"Sin nombre":r.GetString(1)));
            result[key]=values;
        }
        if(m.SensorScoped) result["OPERADOR"]=[new("+","Sumar (+)"),new("-","Restar (−)")];
        return result;
    }
    public async Task<EquipmentPage?> Load(string stationId,EquipmentModule module)
    {
        var station=await stations.Find(stationId); if(station is null) return null;
        using var c=await Open(); var fields=await Fields(c,module);
        var page=new EquipmentPage { Station=station,Module=module,Fields=fields,Rows=await Rows(c,module,fields,stationId),Options=await Options(c,module,stationId) };
        foreach(var m in EquipmentModule.All)
        {
            using var cmd=Cmd(c,$"SELECT COUNT(*) FROM HYDROCLOUD.{m.Table} WHERE {Scope(m)}"); Bind(cmd,"station",stationId,OracleDbType.Char);
            page.Counts[m.Key]=Convert.ToInt32(await cmd.ExecuteScalarAsync());
        }
        return page;
    }
    private static async Task LockStation(OracleConnection c,OracleTransaction tx,string id)
    {
        using var cmd=Cmd(c,"SELECT ID FROM HYDROCLOUD.ESTACION WHERE ID=:station FOR UPDATE WAIT 5",tx); Bind(cmd,"station",id,OracleDbType.Char);
        if(await cmd.ExecuteScalarAsync() is null) throw new StationConflictException("La estación ya no existe.");
    }
    private static string AuditValue(EquipmentField f,string actor) => f.Name.Contains("FECHA")?DateTime.UtcNow.ToString("yyyy-MM-dd HH:mm:ss",CultureInfo.InvariantCulture):actor;
    public async Task Save(EquipmentForm form,string? version,string actor)
    {
        var m=EquipmentModule.Find(form.ModuleKey)??throw new InvalidOperationException();
        using var c=await Open(); using var tx=c.BeginTransaction(); await LockStation(c,tx,form.StationId);
        var fields=await Fields(c,m,tx); var create=version is null;
        if(!create)
        {
            var old=(await Rows(c,m,fields,form.StationId,form.Id!,tx)).SingleOrDefault();
            if(old is null || old.Version()!=version) throw new StationConflictException("El registro cambió o ya no pertenece a esta estación. Recarga el formulario.");
        }
        var page=new EquipmentPage{Module=m,Fields=fields,Options=await Options(c,m,form.StationId,tx)};
        if(EquipmentValidation.Validate(page,form.Values).Count>0) throw new StationConflictException("Los datos o catálogos cambiaron. Revisa los campos antes de guardar.");
        // Some imported relationships lack foreign keys: validate explicitly on every write.
        if(m.Key=="sensores" && form.Values.GetValueOrDefault("NUMEROSENSOR") is string number)
        {
            using var duplicate=Cmd(c,"SELECT COUNT(*) FROM HYDROCLOUD.SENSOR WHERE IDESTACION=:station AND TRIM(NUMEROSENSOR)=:num AND (:id IS NULL OR ID<>:id)",tx);
            Bind(duplicate,"station",form.StationId,OracleDbType.Char); Bind(duplicate,"num",number,OracleDbType.NVarchar2); Bind(duplicate,"id",create?null:form.Id,OracleDbType.Char);
            if(Convert.ToInt32(await duplicate.ExecuteScalarAsync())>0) throw new StationConflictException("Ese número de sensor ya está asignado en esta estación.");
        }
        if(m.SensorScoped && form.Values.GetValueOrDefault("FIN")!="1")
        {
            using var duplicate=Cmd(c,"SELECT COUNT(*) FROM HYDROCLOUD.COTASENSOR WHERE IDSENSOR=:sensor AND NVL(FIN,0)=0 AND (:id IS NULL OR ID<>:id)",tx);
            Bind(duplicate,"sensor",form.Values["IDSENSOR"],OracleDbType.Char); Bind(duplicate,"id",create?null:decimal.Parse(form.Id!,CultureInfo.InvariantCulture),OracleDbType.Decimal);
            if(Convert.ToInt32(await duplicate.ExecuteScalarAsync())>0) throw new StationConflictException("El sensor ya tiene una cota abierta. Finalízala antes de crear otra vigente.");
        }
        var saveFields=fields.Where(f=>f.Editable || f.Audit && (create || f.Name is "FECHAMODIFICACION" or "USUARIOMODIFICACION")).ToList();
        if(create && !m.SensorScoped) saveFields.Add(fields.Single(f=>f.Name=="IDESTACION"));
        if(create && m.Key=="sensores") { form.Id=Guid.NewGuid().ToString().ToUpperInvariant(); saveFields.Add(fields.Single(f=>f.Name=="ID")); }
        var sql=create?$"INSERT INTO HYDROCLOUD.{m.Table} ({string.Join(',',saveFields.Select(f=>f.Name))}) VALUES ({string.Join(',',saveFields.Select((_,i)=>":p"+i))})"
            :$"UPDATE HYDROCLOUD.{m.Table} SET {string.Join(',',saveFields.Select((f,i)=>f.Name+"=:p"+i))} WHERE ID=:id AND {Scope(m)}";
        if(create) sql+=" RETURNING ID INTO :newId";
        using var cmd=Cmd(c,sql,tx);
        for(int i=0;i<saveFields.Count;i++)
        {
            var f=saveFields[i]; var v=f.Audit?AuditValue(f,actor):f.Name=="IDESTACION"?form.StationId:f.Name=="ID"?form.Id:form.Values.GetValueOrDefault(f.Name);
            Bind(cmd,"p"+i,Value(f,v),Type(f));
        }
        if(!create) { Id(cmd,fields,form.Id!); Bind(cmd,"station",form.StationId,OracleDbType.Char); }
        if(create) { var output=cmd.Parameters.Add("newId",Type(fields.Single(f=>f.Name=="ID"))); output.Direction=System.Data.ParameterDirection.Output; output.Size=36; }
        try { if(await cmd.ExecuteNonQueryAsync()!=1) throw new StationConflictException("No se pudo guardar el registro."); }
        catch(OracleException e) when(e.Number==1) { throw new StationConflictException("La clave ya existe. Revisa duplicados y la secuencia de identidad migrada."); }
        if(create) form.Id=cmd.Parameters["newId"].Value.ToString()!.TrimEnd();
        if(create && m.Channel is not null) await Channel(c,tx,m,form.StationId,actor);
        tx.Commit();
    }
    private static async Task Channel(OracleConnection c,OracleTransaction tx,EquipmentModule m,string station,string actor)
    {
        using var cmd=Cmd(c,$"UPDATE HYDROCLOUD.ESTACION SET {m.Channel}=CASE WHEN EXISTS (SELECT 1 FROM HYDROCLOUD.{m.Table} WHERE IDESTACION=:station) THEN 1 ELSE 0 END,USUARIOMODIFICACION=:actor,FECHAMODIFICACION=:dt WHERE ID=:station",tx);
        Bind(cmd,"station",station,OracleDbType.Char); Bind(cmd,"actor",actor); Bind(cmd,"dt",DateTimeOffset.UtcNow.ToString("O")); await cmd.ExecuteNonQueryAsync();
    }
    public async Task Remove(EquipmentForm form,string version,string actor)
    {
        var m=EquipmentModule.Find(form.ModuleKey)??throw new InvalidOperationException(); if(!m.CanRemove) throw new InvalidOperationException();
        using var c=await Open(); using var tx=c.BeginTransaction(); await LockStation(c,tx,form.StationId); var fields=await Fields(c,m,tx);
        using(var confirm=Cmd(c,"SELECT IDASIGNADO FROM HYDROCLOUD.ESTACION WHERE ID=:station",tx))
        {
            Bind(confirm,"station",form.StationId,OracleDbType.Char);
            if(!string.Equals(Convert.ToString(await confirm.ExecuteScalarAsync())?.TrimEnd(),form.Confirmation,StringComparison.Ordinal)) throw new StationConflictException("Escribe exactamente la clave de la estación.");
        }
        var old=(await Rows(c,m,fields,form.StationId,form.Id!,tx)).SingleOrDefault();
        if(old is null || old.Version()!=version) throw new StationConflictException("El registro cambió. Recarga la confirmación.");
        var sql=m.Key=="sensores"?"UPDATE HYDROCLOUD.SENSOR SET ACTIVO=0,VISIBLE=0,USUARIOMODIFICACION=:actor,FECHAMODIFICACION=:dt"
            :m.SensorScoped?"UPDATE HYDROCLOUD.COTASENSOR SET FIN=1":$"DELETE FROM HYDROCLOUD.{m.Table}";
        using var cmd=Cmd(c,sql+$" WHERE ID=:id AND {Scope(m)}",tx); Id(cmd,fields,form.Id!); Bind(cmd,"station",form.StationId,OracleDbType.Char);
        if(m.Key=="sensores") { Bind(cmd,"actor",actor); Bind(cmd,"dt",DateTimeOffset.UtcNow.ToString("O")); }
        if(await cmd.ExecuteNonQueryAsync()!=1) throw new StationConflictException("No se pudo aplicar la baja.");
        if(m.Channel is not null) await Channel(c,tx,m,form.StationId,actor);
        tx.Commit();
    }
}
