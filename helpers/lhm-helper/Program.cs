using System.Text.Json;
using System.Text.Json.Serialization;
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

while (Console.ReadLine() is { } line)
{
    if (string.IsNullOrWhiteSpace(line))
    {
        continue;
    }

    try
    {
        var request = JsonSerializer.Deserialize<Request>(line, jsonOptions);
        if (request is null)
        {
            Write(new ErrorResponse("invalid_request", "Request must be a JSON object"));
            continue;
        }

        switch (request.Type)
        {
            case "list":
                Write(new ListResponse(ReadSensors()));
                break;
            case "read":
                Write(new ReadResponse(ReadSensors(request.Ids)));
                break;
            case "ping":
                Write(new PongResponse());
                break;
            default:
                Write(new ErrorResponse("unknown_type", $"Unknown request type: {request.Type}"));
                break;
        }
    }
    catch (Exception ex)
    {
        Write(new ErrorResponse("helper_error", ex.Message));
    }
}

computer.Close();

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
    List<string>? Ids
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
