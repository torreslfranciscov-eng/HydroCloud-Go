using System.Text.Json;

namespace HydroCloud.Admin;

public sealed class VisitorDay
{
    public string Date {get;set;}="";
    public long PublicVisits {get;set;}
    public long AuthenticatedVisits {get;set;}
    public long Queries {get;set;}
    public long Exports {get;set;}
}
// Aggregate counts only: no IP, user agent, identity, browsing path or tracking cookie.
// Single-process durable storage. Use a shared transactional store before scaling to replicas.
public sealed class VisitorCounter(IConfiguration config,TimeProvider clock,ILogger<VisitorCounter> log)
{
    private readonly SemaphoreSlim gate=new(1,1);
    private string PathName=>config["Analytics:Path"]??System.IO.Path.Combine(AppContext.BaseDirectory,"App_Data","visitors.json");
    private async Task<List<VisitorDay>> Load()=>File.Exists(PathName)?JsonSerializer.Deserialize<List<VisitorDay>>(await File.ReadAllTextAsync(PathName))??[]:[];
    public async Task Record(string kind,bool authenticated)
    {
        await gate.WaitAsync();
        try
        {
            var rows=await Load();var today=clock.GetUtcNow().ToString("yyyy-MM-dd");var day=rows.SingleOrDefault(x=>x.Date==today);
            if(day is null) {day=new(){Date=today};rows.Add(day);}
            switch(kind) {case "visits":if(authenticated) day.AuthenticatedVisits++;else day.PublicVisits++;break;case "queries":day.Queries++;break;case "exports":day.Exports++;break;default:throw new ArgumentException("Unknown metric");}
            rows=rows.OrderByDescending(x=>x.Date).Take(400).ToList();
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(PathName))!);
            var temp=PathName+".tmp";await File.WriteAllTextAsync(temp,JsonSerializer.Serialize(rows));
            if(!OperatingSystem.IsWindows()) File.SetUnixFileMode(temp,UnixFileMode.UserRead|UnixFileMode.UserWrite);
            File.Move(temp,PathName,true);
        }
        catch(Exception e) when(e is IOException or UnauthorizedAccessException or JsonException) {log.LogError("No se pudo persistir el conteo de visitas: {Type}",e.GetType().Name);}
        finally {gate.Release();}
    }
    public async Task<List<VisitorDay>> Read() {await gate.WaitAsync();try{return (await Load()).OrderByDescending(x=>x.Date).ToList();}finally{gate.Release();}}
}
