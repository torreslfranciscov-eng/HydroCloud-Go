using HydroCloud.Admin;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ViewFeatures;
using Microsoft.Extensions.Logging.Abstractions;
using System.Security.Claims;

public static class EquipmentTests
{
    public static async Task Run()
    {
        int count=0;
        void Check(bool ok,string label) { if(!ok) throw new Exception("FAIL: "+label); count++; Console.WriteLine("PASS: "+label); }
        var repository=new FakeEquipment(); var protection=new EphemeralDataProtectionProvider();
        EquipmentController Controller()
        {
            var context=new DefaultHttpContext{User=new ClaimsPrincipal(new ClaimsIdentity(new[]{new Claim(ClaimTypes.Name,"tester")},"test"))};
            return new(repository,protection,NullLogger<EquipmentController>.Instance) { ControllerContext=new(){HttpContext=context},TempData=new TempDataDictionary(context,new MemoryTempData()) };
        }
        Check(await Controller().Index("station-1","ASPNETUSERS") is NotFoundResult,"Lista cerrada de módulos: no expone usuarios ni tablas arbitrarias");
        Check(await Controller().Edit("station-2","sensores","sensor-1") is NotFoundResult,"No permite editar sensor desde otra estación");
        var form=(EquipmentForm)((ViewResult)await Controller().Edit("station-1","sensores","sensor-1")).Model!;
        form.Values["NUMEROSENSOR"]="0002";
        Check(await Controller().Edit(form) is RedirectToActionResult && repository.Saves==1,"Guarda sensor con versión firmada");
        Check(await Controller().Edit(form) is ViewResult && repository.Saves==1,"Rechaza versión obsoleta del sensor");
        form.StationId="station-2";
        Check(await Controller().Edit(form) is BadRequestObjectResult && repository.Saves==1,"Token ligado a estación");
        form.StationId="station-1";form.ModuleKey="goes";
        Check(await Controller().Edit(form) is BadRequestObjectResult,"Token ligado al módulo");
        form.ModuleKey="sensores";form.Id="sensor-2";
        Check(await Controller().Edit(form) is BadRequestObjectResult,"Token ligado al registro");
        var create=(EquipmentForm)((ViewResult)await Controller().Edit("station-1","sensores",null)).Model!;
        create.Values["IDTIPOSENSOR"]="not-in-catalog";
        Check(await Controller().Edit(create) is ViewResult && repository.Saves==1,"Rechaza tipo de sensor fuera de catálogo");
        create.Values["IDTIPOSENSOR"]="type-1";create.Values["VALORMINIMO"]="20";create.Values["VALORMAXIMO"]="10";
        Check(await Controller().Edit(create) is ViewResult && repository.Saves==1,"Rechaza mínimo mayor que máximo");
        create.Values["VALORMINIMO"]="0";
        Check(await Controller().Edit(create) is RedirectToActionResult && repository.Saves==2,"Alta de sensor con catálogos válidos");
        var removal=(EquipmentForm)((ViewResult)await Controller().Remove("station-1","sensores","sensor-1")).Model!;
        removal.Confirmation="WRONG";
        Check(await Controller().Remove(removal) is ViewResult && repository.Removals==0,"Confirmación incorrecta no da de baja");
        removal.Confirmation="TEST";
        Check(await Controller().Remove(removal) is RedirectToActionResult && repository.Removals==1,"Baja confirmada con versión");
        Check(await Controller().Remove("station-1","componentes","1") is NotFoundResult,"No permite borrado de inventario sin política definida");
        var page=FakeEquipment.Page();
        var values=new Dictionary<string,string?> { ["IDTIPOSENSOR"]="type-1",["VALORMINIMO"]="1.001",["ACTIVO"]="2",["PERIODOMUESTRA"]="0" };
        var errors=EquipmentValidation.Validate(page,values);
        Check(errors.ContainsKey("VALORMINIMO") && errors.ContainsKey("ACTIVO") && errors.ContainsKey("PERIODOMUESTRA"),"Precisión decimal, booleanos y muestreo validados");
        values["VALORMINIMO"]="-79228162514264337593543950335";
        Check(EquipmentValidation.Validate(page,values).ContainsKey("VALORMINIMO"),"Números extremos se rechazan sin desbordamiento");
        var cota=new EquipmentPage { Module=EquipmentModule.Find("cotas")!,Fields=[new("IDSENSOR","CHAR",36,0,0,false),new("VALORCOTA","NUMBER",0,19,2,false)],Options=new(){["IDSENSOR"]=[new("local","Sensor local")]} };
        Check(EquipmentValidation.Validate(cota,new(){["IDSENSOR"]="foreign",["VALORCOTA"]="1",["OPERADOR"]="*"}).Count==2,"Cota: sensor de otra estación y operador inválido rechazados");
        var goes=new EquipmentPage { Module=EquipmentModule.Find("goes")! };
        Check(EquipmentValidation.Validate(goes,new(){["PRIMERATRANSMISION"]="25:99:00"}).ContainsKey("PRIMERATRANSMISION"),"Formato de horario GOES validado");
        Check(new EquipmentField("RECIBIDOS","NUMBER",0,10,0,false).Editable==false && new EquipmentField("USUARIOREGISTRO","VARCHAR2",50,0,0,false).Editable==false,"Contadores y auditoría no editables");
        Console.WriteLine($"{count} comprobaciones adicionales de equipos. Sin escrituras en Oracle.");
    }
}

sealed class FakeEquipment : IEquipmentRepository
{
    public int Saves,Removals;
    private EquipmentRow row=new(){Values=new(){["ID"]="sensor-1",["NUMEROSENSOR"]="0001",["IDTIPOSENSOR"]="type-1",["ACTIVO"]="1"}};
    public static EquipmentPage Page()=>new() { Station=new(){Id="station-1",Code="TEST",Name="Test"},Module=EquipmentModule.Find("sensores")!,Fields=[new("ID","CHAR",36,0,0,true),new("NUMEROSENSOR","NVARCHAR2",255,0,0,false),new("IDTIPOSENSOR","CHAR",36,0,0,true),new("ACTIVO","NUMBER",0,1,0,true),new("VALORMINIMO","NUMBER",0,18,2,false),new("VALORMAXIMO","NUMBER",0,18,2,false),new("PERIODOMUESTRA","NUMBER",0,18,2,false)],Options=new(){["IDTIPOSENSOR"]=[new("type-1","Nivel")]} };
    public Task<EquipmentPage?> Load(string id,EquipmentModule module) { if(id!="station-1") return Task.FromResult<EquipmentPage?>(null); var p=Page();p.Module=module;p.Rows=[new(){Values=new(row.Values)}];return Task.FromResult<EquipmentPage?>(p); }
    public Task Save(EquipmentForm f,string? version,string actor) { if(version is not null && version!=row.Version()) throw new StationConflictException("Conflicto"); if(version is not null) row.Values=new(f.Values); Saves++;return Task.CompletedTask; }
    public Task Remove(EquipmentForm f,string version,string actor) { if(version!=row.Version()) throw new StationConflictException("Conflicto");Removals++;return Task.CompletedTask; }
}
