using HydroCloud.Admin;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ViewFeatures;
using Microsoft.Extensions.Logging.Abstractions;
using System.Security.Claims;

var provider = new EphemeralDataProtectionProvider();
var repo = new FakeRepository();
StationsController Controller()
{
    var context = new DefaultHttpContext { User = new ClaimsPrincipal(new ClaimsIdentity(new[]{new Claim(ClaimTypes.Name,"tester")},"test")) };
    return new(repo,provider,NullLogger<StationsController>.Instance)
    {
        ControllerContext = new ControllerContext { HttpContext=context },
        TempData = new TempDataDictionary(context,new MemoryTempData())
    };
}
void Check(bool condition,string name) { if(!condition) throw new Exception("FAIL: "+name); Console.WriteLine("PASS: "+name); }
var edit = (StationForm)((ViewResult)await Controller().Edit("station-1")).Model!;
edit.Station.Name="Nuevo nombre";
Check(await Controller().Edit(edit) is RedirectToActionResult,"Edición válida y token original");
Check(repo.Saved==1 && repo.Current.Name=="Nuevo nombre","Persistencia solicitada una vez");
Check(await Controller().Edit(edit) is ViewResult && repo.Saved==1,"Edición obsoleta rechazada");
edit.Token="tampered";
Check(await Controller().Edit(edit) is BadRequestObjectResult && repo.Saved==1,"Token manipulado rechazado");
var invalid = new StationForm { Station=new Station { Code="NEW",Name="Test",SubBasin="sub",Basin="wrong" } };
Check(await Controller().Create(invalid) is ViewResult && repo.Saved==1,"Relación cuenca/subcuenca inválida rechazada");
var create = new StationForm { Station=new Station { Code="NEW",Name="Test",Basin="basin",SubBasin="sub" } };
Check(await Controller().Create(create) is RedirectToActionResult && Guid.TryParse(create.Station.Id,out _),"Alta con UUID generado en servidor");
var deletion=(StationForm)((ViewResult)await Controller().Delete(repo.Current.Id)).Model!;
Check(await Controller().Delete(repo.Current.Id,deletion.Token!,"WRONG") is ViewResult && repo.Deactivated==0,"Baja exige confirmación exacta");
Check(await Controller().Delete(repo.Current.Id,deletion.Token!,repo.Current.Code) is RedirectToActionResult && !repo.Current.Active && repo.Deactivated==1,"Baja lógica conserva registro");
Console.WriteLine("8 comprobaciones completas. Sin escrituras en Oracle.");
await EquipmentTests.Run();
await ConsultationTests.Run();

sealed class FakeRepository : IStationRepository
{
    public Station Current=new(){Id="station-1",Code="TEST",Name="Original"};
    public int Saved,Deactivated;
    public Task<Station?> Find(string id)=>Task.FromResult<Station?>(System.Text.Json.JsonSerializer.Deserialize<Station>(System.Text.Json.JsonSerializer.Serialize(Current)));
    public Task<StationList> List(string s,string f,int p)=>Task.FromResult(new StationList(new(){Current},1,1,1,s,f));
    public Task<Dictionary<string,List<CatalogItem>>> Catalogs()=>Task.FromResult(new Dictionary<string,List<CatalogItem>> {
        ["Basin"]=new(){new("basin","Cuenca")},["SubBasin"]=new(){new("sub","Subcuenca","basin")},["State"]=new(),["Municipality"]=new(),["Organization"]=new(),["Status"]=new() });
    public Task Save(Station s,string? version,string actor) { if(version is not null && Current.Version()!=version) throw new StationConflictException("Conflicto"); Current=System.Text.Json.JsonSerializer.Deserialize<Station>(System.Text.Json.JsonSerializer.Serialize(s))!; Saved++; return Task.CompletedTask; }
    public Task Deactivate(string id,string version,string actor) { if(Current.Version()!=version) throw new StationConflictException("Conflicto"); Current.Active=false;Deactivated++;return Task.CompletedTask; }
}
sealed class MemoryTempData : ITempDataProvider
{
    public IDictionary<string,object> LoadTempData(HttpContext c)=>new Dictionary<string,object>();
    public void SaveTempData(HttpContext c,IDictionary<string,object> v) { }
}
