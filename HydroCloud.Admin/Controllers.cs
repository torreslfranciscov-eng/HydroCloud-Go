using System.Security.Claims;
using System.Security.Cryptography;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;

namespace HydroCloud.Admin;

public sealed class AccountController(IConfiguration config) : Controller
{
    [HttpGet] public IActionResult Login() => View(new LoginForm());
    [HttpGet] public IActionResult AccessDenied() => StatusCode(403,"Tu cuenta permite consultar el histórico, pero no administrar estaciones ni ver estadísticas de visitas.");
    [HttpPost, EnableRateLimiting("login")]
    public async Task<IActionResult> Login(LoginForm form)
    {
        var reader=string.Equals(form.Username,config["Consultation:Username"],StringComparison.Ordinal);
        var username = config[reader?"Consultation:Username":"Admin:Username"];
        var hash = config[reader?"Consultation:PasswordHash":"Admin:PasswordHash"];
        if (string.IsNullOrWhiteSpace(username) || username.Length>50 || string.IsNullOrWhiteSpace(hash))
            ModelState.AddModelError("", "El administrador debe configurar las credenciales de acceso del portal.");
        if (ModelState.IsValid)
        {
            var valid = false;
            try { valid = new PasswordHasher<string>().VerifyHashedPassword(username!,hash!,form.Password)!=PasswordVerificationResult.Failed; }
            catch (FormatException) { }
            if (valid && string.Equals(form.Username,username,StringComparison.Ordinal))
            {
                await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme,
                    new ClaimsPrincipal(new ClaimsIdentity(new[] { new Claim(ClaimTypes.Name,username!),new Claim(ClaimTypes.Role,reader?"Reader":"Administrator") },CookieAuthenticationDefaults.AuthenticationScheme)));
                return RedirectToAction("Index",reader?"Explore":"Stations");
            }
            ModelState.AddModelError("","Usuario o contraseña incorrectos.");
        }
        return View(form);
    }
    [HttpPost, Authorize] public async Task<IActionResult> Logout() { await HttpContext.SignOutAsync(); return RedirectToAction("Login"); }
    [IgnoreAntiforgeryToken] public IActionResult Error() { Response.StatusCode=500; return View(); }
}

[Authorize(Roles="Administrator")]
public sealed class StationsController(IStationRepository repository, IDataProtectionProvider protection, ILogger<StationsController> log) : Controller
{
    private readonly IDataProtector protector = protection.CreateProtector("HydroCloud.Station.Version.v1");
    public async Task<IActionResult> Index(string? search, string state="all", int page=1)
        => View(await repository.List((search??"").Trim()[..Math.Min((search??"").Trim().Length,255)],state is "active" or "inactive" ? state : "all",page));
    [HttpGet] public async Task<IActionResult> Create() => View("Edit",new StationForm { Catalogs=await repository.Catalogs() });
    [HttpGet] public async Task<IActionResult> Edit(string id)
    {
        var s = await repository.Find(id); if(s is null) return NotFound();
        return View(new StationForm { Station=s,Token=protector.Protect(s.Id+"|"+s.Version()),Catalogs=await repository.Catalogs() });
    }
    [HttpPost] public Task<IActionResult> Create(StationForm form) => Save(form,true);
    [HttpPost] public Task<IActionResult> Edit(StationForm form) => Save(form,false);
    private string Version(string id, string? token)
    {
        var parts=protector.Unprotect(token??"").Split('|');
        if(parts.Length!=2 || parts[0]!=id) throw new CryptographicException();
        return parts[1];
    }
    private async Task<IActionResult> Save(StationForm form,bool create)
    {
        string? version=null;
        if(create) form.Station.Id=Guid.NewGuid().ToString();
        else { try { version=Version(form.Station.Id,form.Token); } catch(CryptographicException) { return BadRequest("Formulario inválido. Abre de nuevo la estación."); } }
        form.Catalogs=await repository.Catalogs();
        foreach(var (key,value) in new[] {("Basin",form.Station.Basin),("SubBasin",form.Station.SubBasin),("State",form.Station.State?.ToString()),("Municipality",form.Station.Municipality?.ToString()),("Organization",form.Station.Organization?.ToString()),("Status",form.Station.Status?.ToString())})
            if(value is not null && !form.Catalogs[key].Any(x=>x.Id==value)) ModelState.AddModelError("Station."+key,"Selecciona un valor del catálogo.");
        if(form.Station.SubBasin is not null && !form.Catalogs["SubBasin"].Any(x=>x.Id==form.Station.SubBasin && x.Parent==form.Station.Basin)) ModelState.AddModelError("Station.SubBasin","La subcuenca debe pertenecer a la cuenca seleccionada.");
        if(form.Station.Municipality is not null && !form.Catalogs["Municipality"].Any(x=>x.Id==form.Station.Municipality.ToString() && x.Parent==form.Station.State?.ToString())) ModelState.AddModelError("Station.Municipality","El municipio debe pertenecer a la entidad federativa seleccionada.");
        if(form.Station.Latitude.HasValue!=form.Station.Longitude.HasValue) ModelState.AddModelError("","Indica ambas coordenadas o deja ambas vacías.");
        if(ModelState.IsValid)
        {
            try
            {
                await repository.Save(form.Station,version,User.Identity!.Name!);
                log.LogInformation("Station {Action} {Id} by {Actor}",create?"created":"updated",form.Station.Id,User.Identity.Name);
                TempData["Success"]="Estación guardada correctamente."; return RedirectToAction("Index");
            }
            catch(StationConflictException e) { ModelState.AddModelError("",e.Message); }
        }
        if(create) { form.Station.Id=""; ModelState.Remove("Station.Id"); }
        return View("Edit",form);
    }
    [HttpGet] public async Task<IActionResult> Delete(string id)
    {
        var s=await repository.Find(id); if(s is null) return NotFound();
        return View(new StationForm { Station=s,Token=protector.Protect(s.Id+"|"+s.Version()) });
    }
    [HttpPost] public async Task<IActionResult> Delete(string id,string token,string confirmation)
    {
        string version;
        try { version=Version(id,token); } catch(CryptographicException) { return BadRequest("Confirmación inválida."); }
        var s=await repository.Find(id); if(s is null) return NotFound();
        if(confirmation!=s.Code) ModelState.AddModelError("","Escribe exactamente la clave de la estación para confirmar.");
        if(ModelState.IsValid)
        {
            try { await repository.Deactivate(id,version,User.Identity!.Name!); log.LogInformation("Station deactivated {Id} by {Actor}",id,User.Identity.Name); TempData["Success"]="Estación dada de baja. Sus relaciones e históricos se conservaron."; return RedirectToAction("Index"); }
            catch(StationConflictException e) { ModelState.AddModelError("",e.Message); }
        }
        return View(new StationForm { Station=s,Token=token });
    }
}
