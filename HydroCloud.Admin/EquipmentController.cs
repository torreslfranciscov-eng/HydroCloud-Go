using System.Security.Cryptography;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Mvc;

namespace HydroCloud.Admin;

[Authorize(Roles="Administrator")]
public sealed class EquipmentController(IEquipmentRepository repository,IDataProtectionProvider protection,ILogger<EquipmentController> log) : Controller
{
    private readonly IDataProtector protector=protection.CreateProtector("HydroCloud.Equipment.Version.v1");
    private string Protect(EquipmentForm f,EquipmentRow row)=>protector.Protect($"{f.StationId}|{f.ModuleKey}|{row.Id}|{row.Version()}");
    private string Version(EquipmentForm f)
    {
        var parts=protector.Unprotect(f.Token??"").Split('|');
        if(parts.Length!=4 || parts[0]!=f.StationId || parts[1]!=f.ModuleKey || parts[2]!=f.Id) throw new CryptographicException();
        return parts[3];
    }
    public async Task<IActionResult> Index(string stationId,string moduleKey="goes")
    {
        var m=EquipmentModule.Find(moduleKey); if(m is null) return NotFound();
        var page=await repository.Load(stationId,m); return page is null?NotFound():View(page);
    }
    [HttpGet] public async Task<IActionResult> Edit(string stationId,string moduleKey,string? id)
    {
        var m=EquipmentModule.Find(moduleKey); if(m is null) return NotFound(); var page=await repository.Load(stationId,m); if(page is null) return NotFound();
        var form=new EquipmentForm{StationId=stationId,ModuleKey=moduleKey,Id=id,Page=page};
        if(id is not null)
        {
            var row=page.Rows.SingleOrDefault(x=>x.Id==id); if(row is null) return NotFound(); form.Values=new(row.Values); form.Token=Protect(form,row);
        }
        else foreach(var f in page.Fields.Where(f=>f.Boolean && f.Editable)) form.Values[f.Name]=f.Name is "ACTIVO" or "VISIBLE"?"1":"0";
        return View(form);
    }
    [HttpPost] public async Task<IActionResult> Edit(EquipmentForm form)
    {
        var m=EquipmentModule.Find(form.ModuleKey); if(m is null) return NotFound();
        string? version=null;
        if(!string.IsNullOrEmpty(form.Id)) { try { version=Version(form); } catch(CryptographicException) { return BadRequest("Formulario inválido. Recarga el registro."); } }
        else if(!string.IsNullOrEmpty(form.Token)) return BadRequest("Formulario inválido.");
        var page=await repository.Load(form.StationId,m); if(page is null) return NotFound(); form.Page=page;
        if(version is not null && !page.Rows.Any(r=>r.Id==form.Id)) return NotFound();
        foreach(var (key,error) in EquipmentValidation.Validate(page,form.Values)) ModelState.AddModelError("Values["+key+"]",error);
        if(ModelState.IsValid)
        {
            try {
                await repository.Save(form,version,User.Identity!.Name!);
                log.LogInformation("Equipment saved {Module} {Id} station {Station} by {Actor}",m.Key,form.Id??"new",form.StationId,User.Identity.Name);
                TempData["Success"]=$"{m.Title}: registro guardado.";
                return RedirectToAction("Index",new{form.StationId,form.ModuleKey});
            } catch(StationConflictException e) { ModelState.AddModelError("",e.Message); }
        }
        return View(form);
    }
    [HttpGet] public async Task<IActionResult> Remove(string stationId,string moduleKey,string id)
    {
        var m=EquipmentModule.Find(moduleKey); if(m is null || !m.CanRemove) return NotFound(); var page=await repository.Load(stationId,m); if(page is null) return NotFound();
        var row=page.Rows.SingleOrDefault(r=>r.Id==id); if(row is null) return NotFound();
        var form=new EquipmentForm { StationId=stationId,ModuleKey=moduleKey,Id=id,Page=page,Values=new(row.Values) }; form.Token=Protect(form,row); return View(form);
    }
    [HttpPost] public async Task<IActionResult> Remove(EquipmentForm form)
    {
        var m=EquipmentModule.Find(form.ModuleKey); if(m is null || !m.CanRemove) return NotFound(); string version;
        try { version=Version(form); } catch(CryptographicException) { return BadRequest("Confirmación inválida."); }
        var page=await repository.Load(form.StationId,m); if(page is null) return NotFound(); form.Page=page;
        var row=page.Rows.SingleOrDefault(r=>r.Id==form.Id); if(row is null) return NotFound(); form.Values=new(row.Values);
        if(form.Confirmation!=page.Station.Code) ModelState.AddModelError("","Escribe exactamente la clave de la estación.");
        if(ModelState.IsValid) try {
            await repository.Remove(form,version,User.Identity!.Name!);
            log.LogInformation("Equipment removed/finalized {Module} {Id} station {Station} by {Actor}",m.Key,form.Id,form.StationId,User.Identity.Name);
            TempData["Success"]="Baja aplicada. No se eliminaron mediciones históricas."; return RedirectToAction("Index",new{form.StationId,form.ModuleKey});
        } catch(StationConflictException e) { ModelState.AddModelError("",e.Message); }
        return View(form);
    }
}
