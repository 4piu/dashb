using System.Text.Json;
using System.Text.Json.Serialization;
using System.Security.Principal;
using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
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
    if (args.Length >= 4 && int.TryParse(args[3], out var ownerPid))
    {
        // The owner (dashb server process) is the sole thing allowed to keep
        // this elevated helper alive. Watching its PID directly - rather than
        // relying only on the client explicitly asking us to shut down - means
        // the helper can never outlive it, even if the owner is killed
        // ungracefully (crash, taskkill, etc).
        WatchOwnerProcess(ownerPid);
    }
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
    listener.Start();

    // Keep listening across multiple sequential connections instead of
    // exiting after the first client disconnects. A loopback connection can
    // drop (e.g. across a Windows sleep/resume cycle) without the owning
    // dashb server process ever restarting, so the client may come back and
    // reconnect - staying up lets it do that without a fresh UAC prompt.
    // WatchOwnerProcess (and an explicit "shutdown" request) are what
    // actually end this loop.
    while (true)
    {
        using var client = listener.AcceptTcpClient();
        using var stream = client.GetStream();
        using var reader = new StreamReader(stream);
        using var writer = new StreamWriter(stream) { AutoFlush = true };

        var shuttingDown = false;
        while (reader.ReadLine() is { } line)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                continue;
            }

            var response = HandleRequestLine(line, token);
            writer.WriteLine(JsonSerializer.Serialize(response, jsonOptions));
            if (response is ShutdownResponse)
            {
                shuttingDown = true;
                break;
            }
        }

        if (shuttingDown)
        {
            listener.Stop();
            return;
        }
    }
}

void WatchOwnerProcess(int ownerPid)
{
    _ = Task.Run(async () =>
    {
        try
        {
            using var owner = Process.GetProcessById(ownerPid);
            await owner.WaitForExitAsync();
        }
        catch (ArgumentException)
        {
            // Owner process was already gone by the time we looked it up.
        }
        catch (Exception)
        {
            // If the wait itself fails for some other reason, still exit
            // rather than risk lingering as an orphan.
        }
        Environment.Exit(0);
    });
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
        "shutdown" => new ShutdownResponse(),
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

record ShutdownResponse(string Type)
{
    public ShutdownResponse() : this("shutdown_ack")
    {
    }
}

record ErrorResponse(string Type, string Code, string Message)
{
    public ErrorResponse(string code, string message) : this("error", code, message)
    {
    }
}
