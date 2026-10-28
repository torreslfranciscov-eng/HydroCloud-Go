using System.Globalization;
using System.IO.Compression;
using System.Text.Json;
using System.Xml.Linq;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.RateLimiting;
using Microsoft.Extensions.Caching.Memory;

namespace HydroCloud.Admin;

public record CycloneTrackPoint(double Latitude,double Longitude,DateTimeOffset? Timestamp,string Classification,int? WindKnots,int? PressureHpa);
public record TropicalCyclone(string Id,string Name,string Classification,double Latitude,double Longitude,int? WindKnots,int? PressureHpa,int? MovementDegrees,int? MovementKnots,DateTimeOffset? Updated,string? AdvisoryUrl,string? GraphicsUrl,IReadOnlyList<CycloneTrackPoint> Track);
public record RegionalEarthquake(string Id,double Magnitude,string Place,double Latitude,double Longitude,double DepthKm,DateTimeOffset Occurred,string ReviewStatus,bool Tsunami,string? DetailUrl);
public record HazardFeed<T>(DateTimeOffset RetrievedAt,string Source,string Scope,IReadOnlyList<T> Items);

public sealed class NaturalHazardService(IHttpClientFactory clients,IMemoryCache cache,TimeProvider clock,ILogger<NaturalHazardService> log)
{
    private const string CycloneUrl="https://www.nhc.noaa.gov/CurrentStorms.json";
    private const string EarthquakeUrl="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson";

    public Task<HazardFeed<TropicalCyclone>> Cyclones(CancellationToken cancellationToken)=>
        cache.GetOrCreateAsync("natural-hazards:cyclones",entry=>
        {
            entry.AbsoluteExpirationRelativeToNow=TimeSpan.FromMinutes(5);
            return ReadCyclones(cancellationToken);
        })!;

    public Task<HazardFeed<RegionalEarthquake>> Earthquakes(CancellationToken cancellationToken)=>
        cache.GetOrCreateAsync("natural-hazards:earthquakes",entry=>
        {
            entry.AbsoluteExpirationRelativeToNow=TimeSpan.FromMinutes(5);
            return ReadEarthquakes(cancellationToken);
        })!;

    private async Task<HazardFeed<TropicalCyclone>> ReadCyclones(CancellationToken cancellationToken)
    {
        var client=clients.CreateClient("natural-hazards");
        using var response=await client.GetAsync(CycloneUrl,cancellationToken);
        response.EnsureSuccessStatusCode();
        await using var stream=await response.Content.ReadAsStreamAsync(cancellationToken);
        using var document=await JsonDocument.ParseAsync(stream,cancellationToken:cancellationToken);
        var storms=new List<TropicalCyclone>();
        if(document.RootElement.TryGetProperty("activeStorms",out var rows)&&rows.ValueKind==JsonValueKind.Array)
        foreach(var row in rows.EnumerateArray())
        {
            var latitude=Number(row,"latitudeNumeric");
            var longitude=Number(row,"longitudeNumeric");
            // Área visible y de influencia para México: Pacífico oriental, Golfo, Caribe y Atlántico occidental.
            if(latitude is null||longitude is null||latitude is < 0 or > 40||longitude is < -140 or > -50)continue;
            var trackUrl=NestedText(row,"bestTrackGIS","kmzFile");
            IReadOnlyList<CycloneTrackPoint> track=[];
            try{track=await ReadTrack(client,trackUrl,cancellationToken);}
            catch(Exception error) when(error is HttpRequestException or InvalidDataException or JsonException or TaskCanceledException)
            {log.LogWarning("Trayectoria NHC no disponible para {Storm}: {Type}",Text(row,"id"),error.GetType().Name);}
            storms.Add(new(
                Text(row,"id")??Guid.NewGuid().ToString("N",CultureInfo.InvariantCulture),
                Text(row,"name")??"Ciclón sin nombre",
                Text(row,"classification")??"CY",
                latitude.Value,longitude.Value,Integer(row,"intensity"),Integer(row,"pressure"),
                Integer(row,"movementDir"),Integer(row,"movementSpeed"),Date(row,"lastUpdate"),
                NestedText(row,"publicAdvisory","url"),NestedText(row,"forecastGraphics","url"),track));
        }
        return new(clock.GetUtcNow(),"NHC / NOAA","Ciclones tropicales activos cercanos a México",storms);
    }

    private static async Task<IReadOnlyList<CycloneTrackPoint>> ReadTrack(HttpClient client,string? url,CancellationToken cancellationToken)
    {
        if(!Uri.TryCreate(url,UriKind.Absolute,out var uri)||uri.Scheme!=Uri.UriSchemeHttps||!uri.Host.Equals("www.nhc.noaa.gov",StringComparison.OrdinalIgnoreCase))return [];
        using var response=await client.GetAsync(uri,cancellationToken);response.EnsureSuccessStatusCode();
        var bytes=await response.Content.ReadAsByteArrayAsync(cancellationToken);
        if(bytes.Length>3_000_000)throw new InvalidDataException("El KMZ de trayectoria excede el límite permitido.");
        using var memory=new MemoryStream(bytes,false);using var archive=new ZipArchive(memory,ZipArchiveMode.Read,false);
        var entry=archive.Entries.FirstOrDefault(item=>item.FullName.EndsWith(".kml",StringComparison.OrdinalIgnoreCase));if(entry is null)return [];
        using var kml=entry.Open();var document=XDocument.Load(kml,LoadOptions.None);var points=new List<CycloneTrackPoint>();
        foreach(var placemark in document.Descendants().Where(element=>element.Name.LocalName=="Placemark"))
        {
            string? Field(string name)=>placemark.Elements().FirstOrDefault(element=>element.Name.LocalName.Equals(name,StringComparison.OrdinalIgnoreCase))?.Value.Trim();
            var coordinates=placemark.Descendants().FirstOrDefault(element=>element.Name.LocalName=="coordinates")?.Value.Split(',',StringSplitOptions.TrimEntries);
            if(coordinates is null||coordinates.Length<2||!double.TryParse(coordinates[0],NumberStyles.Float,CultureInfo.InvariantCulture,out var longitude)||!double.TryParse(coordinates[1],NumberStyles.Float,CultureInfo.InvariantCulture,out var latitude))continue;
            DateTimeOffset? timestamp=null;if(DateTimeOffset.TryParseExact(Field("atcfdtg"),"yyyyMMddHH",CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal,out var parsed))timestamp=parsed;
            int? ParseInteger(string name)=>int.TryParse(Field(name),NumberStyles.Integer,CultureInfo.InvariantCulture,out var parsedInteger)?parsedInteger:null;
            points.Add(new(latitude,longitude,timestamp,Field("stormType")??"CY",ParseInteger("intensity"),ParseInteger("minSeaLevelPres")));
        }
        return points.OrderBy(point=>point.Timestamp).TakeLast(120).ToList();
    }

    private async Task<HazardFeed<RegionalEarthquake>> ReadEarthquakes(CancellationToken cancellationToken)
    {
        using var response=await clients.CreateClient("natural-hazards").GetAsync(EarthquakeUrl,cancellationToken);
        response.EnsureSuccessStatusCode();
        await using var stream=await response.Content.ReadAsStreamAsync(cancellationToken);
        using var document=await JsonDocument.ParseAsync(stream,cancellationToken:cancellationToken);
        var earthquakes=new List<RegionalEarthquake>();
        if(document.RootElement.TryGetProperty("features",out var features)&&features.ValueKind==JsonValueKind.Array)
        foreach(var feature in features.EnumerateArray())
        {
            if(!feature.TryGetProperty("geometry",out var geometry)||!geometry.TryGetProperty("coordinates",out var coordinates)||coordinates.GetArrayLength()<3)continue;
            var longitude=coordinates[0].GetDouble();
            var latitude=coordinates[1].GetDouble();
            var depth=coordinates[2].GetDouble();
            if(latitude is < 5 or > 35||longitude is < -125 or > -75)continue;
            if(!feature.TryGetProperty("properties",out var properties))continue;
            var magnitude=Number(properties,"mag");if(magnitude is null||magnitude<3.5)continue;
            var epoch=Long(properties,"time");if(epoch is null)continue;
            earthquakes.Add(new(
                Text(feature,"id")??Guid.NewGuid().ToString("N",CultureInfo.InvariantCulture),magnitude.Value,
                Text(properties,"place")??"Ubicación no determinada",latitude,longitude,depth,
                DateTimeOffset.FromUnixTimeMilliseconds(epoch.Value),Text(properties,"status")??"automatic",
                Integer(properties,"tsunami")==1,Text(properties,"url")));
        }
        earthquakes.Sort((left,right)=>right.Occurred.CompareTo(left.Occurred));
        return new(clock.GetUtcNow(),"USGS","Sismos M3.5+ de los últimos 7 días en México y región cercana",earthquakes.Take(150).ToList());
    }

    private static string? Text(JsonElement element,string property)=>element.TryGetProperty(property,out var value)&&value.ValueKind==JsonValueKind.String?value.GetString():null;
    private static string? NestedText(JsonElement element,string parent,string property)=>element.TryGetProperty(parent,out var nested)&&nested.ValueKind==JsonValueKind.Object?Text(nested,property):null;
    private static double? Number(JsonElement element,string property)
    {
        if(!element.TryGetProperty(property,out var value)||value.ValueKind==JsonValueKind.Null)return null;
        if(value.ValueKind==JsonValueKind.Number&&value.TryGetDouble(out var number))return number;
        return value.ValueKind==JsonValueKind.String&&double.TryParse(value.GetString(),NumberStyles.Float,CultureInfo.InvariantCulture,out number)?number:null;
    }
    private static int? Integer(JsonElement element,string property)=>Number(element,property) is { } number?(int)Math.Round(number):null;
    private static long? Long(JsonElement element,string property)=>element.TryGetProperty(property,out var value)&&value.ValueKind==JsonValueKind.Number&&value.TryGetInt64(out var number)?number:null;
    private static DateTimeOffset? Date(JsonElement element,string property)=>DateTimeOffset.TryParse(Text(element,property),CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal,out var date)?date:null;
}

[Route("Hazards")]
[EnableRateLimiting("consultation")]
[ResponseCache(Duration=60,Location=ResponseCacheLocation.Client)]
public sealed class HazardsController(NaturalHazardService hazards,ILogger<HazardsController> log) : Controller
{
    [HttpGet("Cyclones")]
    public async Task<IActionResult> Cyclones()
    {
        try{return Json(await hazards.Cyclones(HttpContext.RequestAborted));}
        catch(Exception error) when(error is HttpRequestException or JsonException or TaskCanceledException)
        {
            log.LogWarning("Fuente NHC no disponible: {Type}",error.GetType().Name);
            return StatusCode(503,new{error="El seguimiento de ciclones no está disponible temporalmente."});
        }
    }

    [HttpGet("Earthquakes")]
    public async Task<IActionResult> Earthquakes()
    {
        try{return Json(await hazards.Earthquakes(HttpContext.RequestAborted));}
        catch(Exception error) when(error is HttpRequestException or JsonException or TaskCanceledException)
        {
            log.LogWarning("Fuente USGS no disponible: {Type}",error.GetType().Name);
            return StatusCode(503,new{error="El seguimiento de sismos no está disponible temporalmente."});
        }
    }
}
