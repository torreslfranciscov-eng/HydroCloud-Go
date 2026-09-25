using HydroCloud.Admin;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Identity;
using System.Threading.RateLimiting;

if (args.Contains("--hash-password"))
{
    Console.WriteLine(new PasswordHasher<string>().HashPassword("admin", Console.ReadLine() ?? ""));
    return;
}
var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllersWithViews(o => o.Filters.Add(new AutoValidateAntiforgeryTokenAttribute()));
builder.Services.AddDataProtection();
builder.Services.AddScoped<IStationRepository, StationRepository>();
builder.Services.AddScoped<IEquipmentRepository, EquipmentRepository>();
builder.Services.AddScoped<IConsultationRepository, ConsultationRepository>();
builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<VisitorCounter>();
builder.Services.AddSingleton<StationAvailability>();
builder.Services.AddAuthentication(CookieAuthenticationDefaults.AuthenticationScheme).AddCookie(o =>
{
    o.LoginPath = "/Account/Login";
    o.Cookie.Name = "HydroCloud.Admin";
    o.Cookie.HttpOnly = true;
    o.Cookie.SameSite = SameSiteMode.Strict;
    o.Cookie.SecurePolicy = builder.Environment.IsDevelopment() ? CookieSecurePolicy.SameAsRequest : CookieSecurePolicy.Always;
    o.ExpireTimeSpan = TimeSpan.FromHours(2);
});
builder.Services.AddAuthorization();
builder.Services.AddRateLimiter(o =>
{
    o.RejectionStatusCode = 429;
    o.AddPolicy("consultation", context => RateLimitPartition.GetFixedWindowLimiter(
        context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = 60, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
    o.AddPolicy("login", context => RateLimitPartition.GetFixedWindowLimiter(
        context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
        _ => new FixedWindowRateLimiterOptions { PermitLimit = 10, Window = TimeSpan.FromMinutes(1), QueueLimit = 0 }));
});
var app = builder.Build();
app.UseExceptionHandler("/Account/Error");
if (!app.Environment.IsDevelopment()) { app.UseHsts(); app.UseHttpsRedirection(); }
app.Use(async (ctx, next) =>
{
    ctx.Response.Headers["X-Content-Type-Options"] = "nosniff";
    ctx.Response.Headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; script-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; frame-ancestors 'none'; form-action 'self'; base-uri 'self'";
    ctx.Response.Headers["Referrer-Policy"]="strict-origin-when-cross-origin";
    await next();
});
app.UseStaticFiles();
app.UseRouting();
app.UseRateLimiter();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllerRoute("default", "{controller=Explore}/{action=Index}/{id?}");
app.Run();
