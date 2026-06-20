# Dashb LHM Helper

Windows-only helper process for reading selected LibreHardwareMonitor sensors without
depending on LibreHardwareMonitor's HTTP server.

Dashb talks to this process over JSON lines on stdin/stdout.

## Build

Install the .NET SDK, then run:

```powershell
dotnet publish helpers\lhm-helper\Dashb.LhmHelper.csproj -c Release -r win-x64 --self-contained true
```

The Python bridge looks for `dashb-lhm-helper.exe` via `DASHB_LHM_HELPER_PATH` first,
then common project/build output locations.

## Protocol

Requests:

```json
{"type":"list"}
{"type":"read","ids":["/intelcpu/0/temperature/0"]}
{"type":"ping"}
```

Responses:

```json
{"type":"sensor_list","sensors":[]}
{"type":"sensor_values","sensors":[]}
{"type":"pong"}
{"type":"error","code":"helper_error","message":"..."}
```
