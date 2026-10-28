using System.Threading.RateLimiting;
using HydroCloud.Admin;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

if (args.Contains("--hash-password"))
{
    Console.WriteLine(new PasswordHasher<string>().HashPassword("admin", Console.ReadLine() ?? ""));
    return;
}
var builder = WebApplication.CreateBuilder(args);
if(args.Contains("--register-upstream"))
{
    var count=await AtlasUpstreamRegistry.Apply(builder.Configuration);
    Console.WriteLine($"Relaciones aguas arriba activas: {count}");
    return;
}
builder.Services.AddControllersWithViews(o => o.Filters.Add(new AutoValidateAntiforgeryTokenAttribute()));
builder.Services.AddDataProtection();
builder.Services.AddMemoryCache();
builder.Services.AddHttpClient("natural-hazards",client =>
{
    client.Timeout=TimeSpan.FromSeconds(12);
    client.DefaultRequestHeaders.UserAgent.ParseAdd("HydroCloud-Data-Studio/1.0 (natural-hazard-map)");
});
builder.Services.AddSingleton<NaturalHazardService>();
builder.Services.AddSingleton<StationCatalogCache>();
builder.Services.AddScoped<IConsultationRepository, ConsultationRepository>();
builder.Services.AddScoped<IEquipmentRepository, EquipmentRepository>();
builder.Services.AddScoped<IStationRepository, StationRepository>();
builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<StationAvailability>();
builder.Services.AddSingleton<VisitorCounter>();
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme).AddCookie(o =>
{
    o.Cookie.Name = "HydroAuth";
    o.Cookie.HttpOnly = true;
    o.Cookie.SameSite = SameSiteMode.Strict;
    o.Cookie.SecurePolicy = builder.Environment.IsDevelopment() ? CookieSecurePolicy.SameAsRequest : CookieSecurePolicy.Always;
    o.LoginPath = "/Account/Login";
    o.LogoutPath = "/Account/Logout";
    o.AccessDeniedPath = "/Account/AccessDenied";
    o.ExpireTimeSpan = TimeSpan.FromHours(8);
    o.SlidingExpiration = true;
});
builder.Services.AddAuthorization();
builder.Services.AddRateLimiter(o =>
{
    o.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    o.AddPolicy("consultation", context => RateLimitPartition.GetFixedWindowLimiter(
        context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = 60, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
    o.AddPolicy("login", context => RateLimitPartition.GetFixedWindowLimiter(
        context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = 10, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
});
var app = builder.Build();
var forwardedOptions = new ForwardedHeadersOptions { ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto };
forwardedOptions.KnownNetworks.Clear();
forwardedOptions.KnownProxies.Clear();
app.UseForwardedHeaders(forwardedOptions);
app.UseExceptionHandler("/Account/Error");
if (!app.Environment.IsDevelopment()) { app.UseHsts(); app.UseHttpsRedirection(); }
app.Use(async (ctx, next) =>
{
    ctx.Response.Headers["X-Content-Type-Options"] = "nosniff";
    ctx.Response.Headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' https://fonts.googleapis.com; style-src-attr 'unsafe-inline'; font-src 'self' https://fonts.gstatic.com data:; script-src 'self'; connect-src 'self' https://api.rainviewer.com; img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://*.tile.opentopomap.org https://server.arcgisonline.com https://services.arcgisonline.com https://gibs.earthdata.nasa.gov https://tilecache.rainviewer.com; frame-ancestors 'self' https://huggingface.co https://*.hf.space; form-action 'self'; base-uri 'self'";
    ctx.Response.Headers["Referrer-Policy"]="strict-origin-when-cross-origin";
    await next();
});
app.UseStaticFiles();
app.UseRouting();
app.UseRateLimiter();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllerRoute(name: "default", pattern: "{controller=Explore}/{action=Index}/{id?}");
app.Run();
