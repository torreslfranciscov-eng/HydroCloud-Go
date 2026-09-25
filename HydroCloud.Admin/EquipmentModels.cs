using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc.ModelBinding.Validation;

namespace HydroCloud.Admin;

// Only these modules may supply SQL identifiers. Route/form values never become identifiers.
public record EquipmentModule(string Key, string Table, string Title, string Description, string? Channel = null)
{
    public bool SensorScoped => Key == "cotas";
    public bool CanRemove => Channel is not null || Key is "sensores" or "cotas";
    public static readonly EquipmentModule[] All = [
        new("goes", "DATOSGOES", "GOES", "Identificador satelital, canales, velocidades, ventanas y decodificador.", "GOES"),
        new("gprs", "DATOSGPRS", "GPRS", "Periodo de transmisión y comentarios de la conexión celular.", "GPRS"),
        new("radio", "DATOSRADIO", "Radio", "Periodo de transmisión y comentarios del enlace de radio.", "RADIO"),
        new("sensores", "SENSOR", "Sensores", "Variables, unidades, muestreo, límites, precisión y disponibilidad."),
        new("cotas", "COTASENSOR", "Cotas de sensores", "Correcciones por sensor y sus fechas de vigencia; finalizar conserva el histórico."),
        new("componentes", "COMPONENTE_ESTACION", "Componentes", "Inventario de equipos: marca, modelo, serie y condición física."),
        new("inventario", "COMP_SENSORINVENTARIO", "Inventario de sensores", "Inventario físico, cableado y soportes. Es distinto del sensor de medición.")
    ];
    public static EquipmentModule? Find(string key) => All.SingleOrDefault(m => m.Key == key);
}

public record EquipmentField(string Name, string Type, int Length, int Precision, int Scale, bool Required)
{
    public bool Audit => Name is "FECHAREGISTRO" or "USUARIOREGISTRO" or "FECHAMODIFICACION" or "USUARIOMODIFICACION" or "IDUSUARIOREGISTRA" or "NOMBRECOMPLETO";
    public bool Editable => !Audit && Name is not ("ID" or "IDESTACION" or "TRANSMITE" or "ESPERADOS" or "RECIBIDOS" or "FUNCIONA" or "VALIDO");
    public bool Numeric => Type is "NUMBER" or "BINARY_DOUBLE";
    public bool Boolean => Type == "NUMBER" && Precision == 1 && Scale == 0;
    public bool Date => Type == "DATE" || Type.StartsWith("TIMESTAMP", StringComparison.Ordinal);
    public bool Lob => Type is "CLOB" or "NCLOB";
    public string Label => Labels.GetValueOrDefault(Name, Name);
    private static readonly Dictionary<string,string> Labels = new() {
        ["IDSATELITAL"]="Identificador satelital (DCP)", ["CANALPRIMARIO"]="Canal primario", ["VELOCIDAD"]="Velocidad", ["PRIMERATRANSMISION"]="Primera transmisión (hh:mm:ss)",
        ["VENTANATRANSMISION"]="Ventana de transmisión (hh:mm:ss)", ["SATELITE"]="Satélite", ["RANGOTRANSMISION"]="Rango de transmisión (hh:mm:ss)", ["INTERVALOTRANSMISION"]="Intervalo de transmisión (hh:mm:ss)",
        ["CANALALARMA"]="Canal de alarma", ["VELOCIDADALARMA"]="Velocidad de alarma", ["DECODIFICADOR"]="Decodificador", ["PERIODOTRANSMISION"]="Periodo de transmisión", ["COMENTARIOS"]="Comentarios",
        ["NUMEROSENSOR"]="Número de sensor", ["IDTIPOSENSOR"]="Tipo de sensor", ["IDUNIDADMEDIDA"]="Unidad de medida", ["IDSENSOR"]="Sensor de esta estación", ["VISIBLE"]="Visible", ["ACTIVO"]="Activo",
        ["VALORMINIMO"]="Valor mínimo", ["VALORMAXIMO"]="Valor máximo", ["VALORMINERROR"]="Límite inferior de error", ["VALORMAXERROR"]="Límite superior de error", ["PERIODOMUESTRA"]="Periodo de muestra (minutos)",
        ["PUNTODECIMAL"]="Decimales", ["ORDEN"]="Orden", ["ESPECIFICACION"]="Especificación", ["TIPOGRAFICA"]="Tipo de gráfica", ["MODOALMACENAMIENTO"]="Modo de almacenamiento", ["APLICACOTA"]="Aplica cota",
        ["VALORCOTA"]="Valor de cota", ["OPERADOR"]="Operador (+ / −)", ["FECHAINICIO"]="Inicio de vigencia", ["FECHAFINAL"]="Fin de vigencia", ["FIN"]="Finalizada", ["COMPONENTE"]="Componente",
        ["MARCA"]="Marca", ["MODELO"]="Modelo", ["SERIE"]="Serie", ["CAPACIDAD"]="Capacidad", ["MEDIDAS"]="Medidas", ["MATERIAL"]="Material", ["CIMENTACION"]="Cimentación", ["TIPOCOMPONENTE"]="Tipo de componente", ["ESTADO"]="Estado",
        ["OBSERVACIONES"]="Observaciones", ["IMAGEN"]="Referencia de imagen (sin carga de archivos)", ["PRINCIPIOOPERACION"]="Principio de operación", ["ESTADOCABLEADO"]="Estado del cableado", ["DETALLECABLEADO"]="Detalle del cableado", ["ESTADOSOPORTE"]="Estado del soporte", ["DETALLESOPORTE"]="Detalle del soporte", ["TIPOSENSOR"]="Tipo de sensor físico",
        ["TRANSMITE"]="Transmite (sistema)", ["ESPERADOS"]="Esperados (sistema)", ["RECIBIDOS"]="Recibidos (sistema)", ["FUNCIONA"]="Funciona (sistema)", ["VALIDO"]="Válido (sistema)"
    };
}

public sealed class EquipmentRow
{
    public Dictionary<string,string?> Values { get; set; } = new();
    public string Id => Values["ID"]!;
    public string Version() => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(Values.OrderBy(x=>x.Key)))));
}
public sealed class EquipmentPage
{
    public Station Station { get; set; } = new();
    public EquipmentModule Module { get; set; } = EquipmentModule.All[0];
    public List<EquipmentField> Fields { get; set; } = new();
    public List<EquipmentRow> Rows { get; set; } = new();
    public Dictionary<string,List<CatalogItem>> Options { get; set; } = new();
    public Dictionary<string,int> Counts { get; set; } = new();
}
public sealed class EquipmentForm
{
    public string StationId { get; set; } = "";
    public string ModuleKey { get; set; } = "";
    public string? Id { get; set; }
    public string? Token { get; set; }
    public string? Confirmation { get; set; }
    public Dictionary<string,string?> Values { get; set; } = new();
    [ValidateNever] public EquipmentPage Page { get; set; } = new();
}

public static class EquipmentValidation
{
    public static Dictionary<string,string> Validate(EquipmentPage page, Dictionary<string,string?> values)
    {
        var errors = new Dictionary<string,string>();
        foreach(var f in page.Fields.Where(x=>x.Editable))
        {
            var v=values.GetValueOrDefault(f.Name)?.Trim(); values[f.Name]=string.IsNullOrEmpty(v)?null:v;
            if(string.IsNullOrEmpty(v)) { if(f.Required) errors[f.Name]="Este campo es obligatorio."; continue; }
            if(f.Length>0 && v.Length>f.Length || f.Lob && v.Length>10000) errors[f.Name]="El texto excede la longitud permitida.";
            if(f.Numeric)
            {
                if(!decimal.TryParse(v,NumberStyles.AllowLeadingSign|NumberStyles.AllowDecimalPoint,CultureInfo.InvariantCulture,out var n)) errors[f.Name]="Introduce un número válido usando punto decimal.";
                else if(f.Boolean && n is not (0 or 1)) errors[f.Name]="Selecciona Sí o No.";
                else if(decimal.Round(n,f.Scale)!=n || f.Precision>0 && (n>= (decimal)Math.Pow(10,Math.Min(28,f.Precision-f.Scale)) || n<= -(decimal)Math.Pow(10,Math.Min(28,f.Precision-f.Scale)))) errors[f.Name]="El número excede la precisión admitida por Oracle.";
            }
            if(f.Date && !DateTime.TryParseExact(v,new[]{"yyyy-MM-ddTHH:mm:ss.FFF","yyyy-MM-ddTHH:mm:ss","yyyy-MM-ddTHH:mm"},CultureInfo.InvariantCulture,DateTimeStyles.None,out _)) errors[f.Name]="Fecha inválida.";
            if(page.Options.TryGetValue(f.Name,out var options) && !options.Any(o=>o.Id==v)) errors[f.Name]="Selecciona un valor válido del catálogo de esta estación.";
        }
        decimal? N(string k)=>decimal.TryParse(values.GetValueOrDefault(k),NumberStyles.Number,CultureInfo.InvariantCulture,out var n)?n:null;
        foreach(var (min,max) in new[]{("VALORMINIMO","VALORMAXIMO"),("VALORMINERROR","VALORMAXERROR")})
            if(N(min)>N(max)) errors[min]="El mínimo no puede superar al máximo.";
        foreach(var key in new[]{"PERIODOMUESTRA","PUNTODECIMAL","ORDEN","CANALPRIMARIO","CANALALARMA","VELOCIDAD","VELOCIDADALARMA"})
            if(N(key)<0) errors[key]="El valor no puede ser negativo.";
        if(N("PERIODOMUESTRA")==0) errors["PERIODOMUESTRA"]="El periodo debe ser mayor que cero.";
        if(N("PUNTODECIMAL")>15) errors["PUNTODECIMAL"]="Utiliza entre 0 y 15 decimales.";
        if(page.Module.Key=="goes")
            foreach(var key in new[]{"PRIMERATRANSMISION","VENTANATRANSMISION","RANGOTRANSMISION","INTERVALOTRANSMISION"})
                if(values.GetValueOrDefault(key) is string v && !System.Text.RegularExpressions.Regex.IsMatch(v,@"^\d{2}:[0-5]\d:[0-5]\d$")) errors[key]="Utiliza el formato hh:mm:ss.";
        if(page.Module.SensorScoped)
        {
            if(string.IsNullOrEmpty(values.GetValueOrDefault("VALORCOTA"))) errors["VALORCOTA"]="Introduce el valor de la cota.";
            if(values.GetValueOrDefault("OPERADOR") is not ("+" or "-")) errors["OPERADOR"]="Selecciona + o -.";
            if(string.IsNullOrEmpty(values.GetValueOrDefault("IDSENSOR"))) errors["IDSENSOR"]="Selecciona un sensor de esta estación.";
            if(DateTime.TryParse(values.GetValueOrDefault("FECHAINICIO"),out var start) && DateTime.TryParse(values.GetValueOrDefault("FECHAFINAL"),out var end) && start>end) errors["FECHAFINAL"]="El fin debe ser posterior al inicio.";
        }
        return errors;
    }
}
