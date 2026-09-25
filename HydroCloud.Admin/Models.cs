using System.ComponentModel.DataAnnotations;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace HydroCloud.Admin;

public sealed class Station
{
    [Microsoft.AspNetCore.Mvc.ModelBinding.Validation.ValidateNever]
    public string Id { get; set; } = "";
    [Required(ErrorMessage = "La clave es obligatoria."), StringLength(255)]
    [Display(Name = "Clave de estación")] public string Code { get; set; } = "";
    [Required(ErrorMessage = "El nombre es obligatorio."), StringLength(255)]
    [Display(Name = "Nombre")] public string Name { get; set; } = "";
    [Range(-90d, 90d), Display(Name = "Latitud")] public double? Latitude { get; set; }
    [Range(-180d, 180d), Display(Name = "Longitud")] public double? Longitude { get; set; }
    [Display(Name = "Cuenca")] public string? Basin { get; set; }
    [Display(Name = "Subcuenca")] public string? SubBasin { get; set; }
    [Display(Name = "Entidad federativa")] public int? State { get; set; }
    [Display(Name = "Municipio")] public int? Municipality { get; set; }
    [Display(Name = "Organismo")] public int? Organization { get; set; }
    [Display(Name = "Estatus de bitácora")] public int? Status { get; set; }
    [StringLength(50), Display(Name = "Etiqueta")] public string? Tag { get; set; }
    [StringLength(10000), Display(Name = "Comentario")] public string? Comment { get; set; }
    [Display(Name = "Activa")] public bool Active { get; set; } = true;
    [Display(Name = "Visible")] public bool Visible { get; set; } = true;
    public bool Goes { get; set; }
    public bool Gprs { get; set; }
    public bool Radio { get; set; }
    [Display(Name = "Es presa")] public bool IsDam { get; set; }
    public string Version() => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(this))));
}
public record CatalogItem(string Id, string Name, string? Parent = null);
public sealed class StationForm
{
    public Station Station { get; set; } = new();
    public string? Token { get; set; }
    public Dictionary<string, List<CatalogItem>> Catalogs { get; set; } = new();
}
public record StationList(List<Station> Items, int Total, int ActiveCount, int Page, string Search, string StateFilter)
{
    public int Pages => Math.Max(1, (Total + 24) / 25);
}
public sealed class LoginForm
{
    [Required, Display(Name = "Usuario")] public string Username { get; set; } = "";
    [Required, DataType(DataType.Password), Display(Name = "Contraseña")] public string Password { get; set; } = "";
}
public sealed class StationConflictException(string message) : Exception(message);
