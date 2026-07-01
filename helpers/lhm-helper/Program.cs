using System.Text.Json;
using System.Text.Json.Serialization;
using System.Security.Principal;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using LibreHardwareMonitor.Hardware;

var jsonOptions = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
};

var computer = new Computer
{
    IsCpuEnabled = true,
    IsGpuEnabled = true,
    IsMemoryEnabled = true,
    IsMotherboardEnabled = true,
    IsControllerEnabled = true,
    IsStorageEnabled = true,
    IsNetworkEnabled = false,
};

computer.Open();

if (args.Length >= 3 && args[0] == "--server")
{
    var port = int.Parse(args[1]);
    var token = args[2];
    RunServer(port, token);
    computer.Close();
    return;
}

if (args.Length >= 2 && args[0] == "--debug-once")
{
    var outputPath = args[1];
    var ids = new[]
    {
        "/amdcpu/0/temperature/2",
        "/amdcpu/0/power/0",
        "/amdcpu/0/clock/1",
        "/amdcpu/0/clock/2",
        "/amdcpu/0/clock/3",
        "/amdcpu/0/clock/4",
        "/amdcpu/0/voltage/2",
    };
    var response = new
    {
        Type = "debug_once",
        Elevated = IsElevated(),
        Sensors = ReadSensors(),
        TargetSamples = ReadDebugSamples(ids, 8, 500),
        Reports = ReadReports("Cpu"),
    };
    File.WriteAllText(outputPath, JsonSerializer.Serialize(response, jsonOptions));
    computer.Close();
    return;
}

while (Console.ReadLine() is { } line)
{
    if (string.IsNullOrWhiteSpace(line))
    {
        continue;
    }

    Write(HandleRequestLine(line));
}

computer.Close();

void RunServer(int port, string token)
{
    var listener = new TcpListener(IPAddress.Loopback, port);
    listener.Start(1);

    using var client = listener.AcceptTcpClient();
    listener.Stop();

    using var stream = client.GetStream();
    using var reader = new StreamReader(stream);
    using var writer = new StreamWriter(stream) { AutoFlush = true };

    while (reader.ReadLine() is { } line)
    {
        if (string.IsNullOrWhiteSpace(line))
        {
            continue;
        }

        var response = HandleRequestLine(line, token);
        writer.WriteLine(JsonSerializer.Serialize(response, jsonOptions));
    }
}

object HandleRequestLine(string line, string? requiredToken = null)
{
    try
    {
        var request = JsonSerializer.Deserialize<Request>(line, jsonOptions);
        if (request is null)
        {
            return new ErrorResponse("invalid_request", "Request must be a JSON object");
        }

        if (requiredToken is not null && request.Token != requiredToken)
        {
            return new ErrorResponse("unauthorized", "Invalid helper token");
        }

        return HandleRequest(request);
    }
    catch (Exception ex)
    {
        return new ErrorResponse("helper_error", ex.Message);
    }
}

object HandleRequest(Request request)
{
    return request.Type switch
    {
        "list" => new ListResponse(ReadSensors()),
        "read" => new ReadResponse(ReadSensors(request.Ids)),
        "status" => new StatusResponse(IsElevated()),
        "debug" => new DebugResponse(IsElevated(), request.DelayMs ?? 250, ReadDebugSamples(request.Ids, request.Cycles ?? 5, request.DelayMs ?? 250)),
        "report" => new ReportResponse(IsElevated(), ReadReports(request.HardwareType)),
        "ping" => new PongResponse(),
        _ => new ErrorResponse("unknown_type", $"Unknown request type: {request.Type}"),
    };
}

void Write(object response)
{
    Console.WriteLine(JsonSerializer.Serialize(response, jsonOptions));
    Console.Out.Flush();
}

List<SensorDto> ReadSensors(IReadOnlyCollection<string>? ids = null)
{
    var filter = ids is null ? null : new HashSet<string>(ids);
    var sensors = new List<SensorDto>();

    foreach (var hardware in computer.Hardware)
    {
        VisitHardware(hardware, sensors, filter);
    }

    return sensors;
}

List<List<SensorDto>> ReadDebugSamples(IReadOnlyCollection<string>? ids, int cycles, int delayMs)
{
    var samples = new List<List<SensorDto>>();
    var safeCycles = Math.Clamp(cycles, 1, 20);
    var safeDelayMs = Math.Clamp(delayMs, 0, 5000);

    for (var i = 0; i < safeCycles; i++)
    {
        samples.Add(ReadSensors(ids));
        if (i + 1 < safeCycles && safeDelayMs > 0)
        {
            Thread.Sleep(safeDelayMs);
        }
    }

    return samples;
}

bool IsElevated()
{
    using var identity = WindowsIdentity.GetCurrent();
    var principal = new WindowsPrincipal(identity);
    return principal.IsInRole(WindowsBuiltInRole.Administrator);
}

List<HardwareReportDto> ReadReports(string? hardwareType = null)
{
    var reports = new List<HardwareReportDto>();

    foreach (var hardware in computer.Hardware)
    {
        VisitHardwareReports(hardware, reports, hardwareType);
    }

    return reports;
}

void VisitHardwareReports(IHardware hardware, List<HardwareReportDto> reports, string? hardwareType)
{
    hardware.Update();

    if (hardwareType is null || string.Equals(hardware.HardwareType.ToString(), hardwareType, StringComparison.OrdinalIgnoreCase))
    {
        reports.Add(new HardwareReportDto(
            Name: hardware.Name,
            Type: hardware.HardwareType.ToString(),
            Report: hardware.GetReport()
        ));
    }

    foreach (var subHardware in hardware.SubHardware)
    {
        VisitHardwareReports(subHardware, reports, hardwareType);
    }
}

void VisitHardware(IHardware hardware, List<SensorDto> sensors, HashSet<string>? ids)
{
    hardware.Update();

    foreach (var subHardware in hardware.SubHardware)
    {
        VisitHardware(subHardware, sensors, ids);
    }

    foreach (var sensor in hardware.Sensors)
    {
        var id = sensor.Identifier.ToString();
        if (ids is not null && !ids.Contains(id))
        {
            continue;
        }

        sensors.Add(new SensorDto(
            Id: id,
            Name: sensor.Name,
            Type: sensor.SensorType.ToString(),
            Value: sensor.Value,
            HardwareName: hardware.Name,
            HardwareType: hardware.HardwareType.ToString()
        ));
    }
}

record Request(
    string Type,
    List<string>? Ids,
    int? Cycles,
    int? DelayMs,
    string? HardwareType,
    string? Token
);

record SensorDto(
    string Id,
    string Name,
    string Type,
    float? Value,
    string HardwareName,
    string HardwareType
);

record ListResponse(string Type, List<SensorDto> Sensors)
{
    public ListResponse(List<SensorDto> sensors) : this("sensor_list", sensors)
    {
    }
}

record ReadResponse(string Type, List<SensorDto> Sensors)
{
    public ReadResponse(List<SensorDto> sensors) : this("sensor_values", sensors)
    {
    }
}

record StatusResponse(string Type, bool Elevated)
{
    public StatusResponse(bool elevated) : this("status", elevated)
    {
    }
}

record DebugResponse(string Type, bool Elevated, int DelayMs, List<List<SensorDto>> Samples)
{
    public DebugResponse(bool elevated, int delayMs, List<List<SensorDto>> samples) : this("debug", elevated, delayMs, samples)
    {
    }
}

record HardwareReportDto(
    string Name,
    string Type,
    string Report
);

record ReportResponse(string Type, bool Elevated, List<HardwareReportDto> Reports)
{
    public ReportResponse(bool elevated, List<HardwareReportDto> reports) : this("report", elevated, reports)
    {
    }
}

record PongResponse(string Type)
{
    public PongResponse() : this("pong")
    {
    }
}

record ErrorResponse(string Type, string Code, string Message)
{
    public ErrorResponse(string code, string message) : this("error", code, message)
    {
    }
}
