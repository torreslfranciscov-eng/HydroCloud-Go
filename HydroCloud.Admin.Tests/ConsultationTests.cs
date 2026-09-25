using HydroCloud.Admin;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;

public static class ConsultationTests
{
    public static async Task Run()
    {
        var now=DateTimeOffset.Parse("2026-09-25T12:00:00Z");int count=0;
        void Check(bool yes,string label){if(!yes)throw new Exception(label);count++;Console.WriteLine("PASS: "+label);}
        bool Reject(Action a){try{a();return false;}catch(ArgumentException){return true;}}
        Check(QueryWindow.Create(now.AddDays(-7),now,false,now).Start==now.AddDays(-7),"Frontera pública de siete días incluida");
        var later=now.AddHours(3);
        Check(QueryWindow.Create(null,null,false,later)==new QueryWindow(later.AddDays(-7),later),"Periodo automático usa la hora de consulta aunque la página lleve horas abierta");
        Check(Reject(()=>QueryWindow.Create(now.AddDays(-7).AddTicks(-1),now,false,now)),"Un instante anterior al límite se rechaza");
        Check(Reject(()=>QueryWindow.Create(now.AddDays(-30),now.AddDays(-29),false,now)),"Periodo corto antiguo también se rechaza");
        Check(QueryWindow.Create(now.AddYears(-10),now,true,now).Start==now.AddYears(-10),"Usuario autenticado sin límite de antigüedad");
        Check(Reject(()=>QueryWindow.Create(now,now,false,now))&&Reject(()=>QueryWindow.Create(now,now.AddMinutes(1),true,now)),"Fechas iguales y futuras rechazadas");
        Check(QueryWindow.Create(now.AddDays(-7).ToOffset(TimeSpan.FromHours(-6)),now,false,now).Start.Offset==TimeSpan.Zero,"Límite independiente de zona horaria del navegador");
        Check(QueryProduct.All.Length==9&&QueryProduct.Find("ASPNETUSERS")==null,"Nueve productos permitidos, sin SQL arbitrario");
        Check(StationAvailability.Combine(["empty","recent"])=="recent"&&StationAvailability.Combine(["historical","week"])=="week","Semáforo prioriza datos recientes entre DCP de una estación");
        Check(StationAvailability.Combine(["empty","unknown"])=="unknown"&&StationAvailability.Combine([])=="unknown","Una consulta fallida o sin vínculo nunca se presenta como sin datos");
        Check(StationAvailability.Combine(["empty","historical"])=="historical"&&StationAvailability.Combine(["empty","empty"])=="empty","Histórico sin datos recientes se distingue de ausencia de mediciones asociadas");
        Check(ExploreController.Csv("=SUM(A1:A2)").StartsWith("\"'")&&ExploreController.Csv(-4d)=="\"-4\"","CSV neutraliza fórmulas y conserva números negativos");
        var path=Path.Combine(Path.GetTempPath(),"hydrocloud-visitors-test-"+Guid.NewGuid()+".json");
        var config=new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string,string?>{["Analytics:Path"]=path}).Build();
        try {
            var counter=new VisitorCounter(config,TimeProvider.System,NullLogger<VisitorCounter>.Instance);
            await Task.WhenAll(Enumerable.Range(0,25).Select(_=>counter.Record("visits",false)));
            await counter.Record("visits",true);await counter.Record("queries",false);await counter.Record("exports",false);
            var rows=await new VisitorCounter(config,TimeProvider.System,NullLogger<VisitorCounter>.Instance).Read();
            Check(rows.Sum(x=>x.PublicVisits)==25&&rows.Sum(x=>x.AuthenticatedVisits)==1,"Conteo concurrente persiste al recrear el servicio");
            Check(rows.Sum(x=>x.Queries)==1&&rows.Sum(x=>x.Exports)==1,"Visitas separadas de consultas y descargas");
            var json=await File.ReadAllTextAsync(path);Check(!json.Contains("IP")&&!json.Contains("Username"),"Métricas agregadas sin identidad ni IP");
        } finally {if(File.Exists(path))File.Delete(path);if(File.Exists(path+".tmp"))File.Delete(path+".tmp");}
        Console.WriteLine($"{count} comprobaciones de consulta y visitas.");
    }
}
