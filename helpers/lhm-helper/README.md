# Dashb LHM Helper

Windows-only helper process for reading selected LibreHardwareMonitor sensors without
depending on LibreHardwareMonitor's HTTP server.

Dashb starts this helper elevated on Windows, which shows a UAC prompt. Elevated
mode runs a loopback-only JSON-lines TCP server because UAC elevation cannot keep
the normal redirected stdin/stdout pipes attached to the parent Python process.
The original stdin/stdout JSON-lines mode is still available for direct debugging.

## Build

Install the .NET SDK, then run:

```powershell
dotnet publish helpers\lhm-helper\Dashb.LhmHelper.csproj -c Release -r win-x64 --self-contained true
```

The Python bridge looks for `dashb-lhm-helper.exe` via `DASHB_LHM_HELPER_PATH` first,
then common project/build output locations.

At runtime the bridge starts the `.exe` with UAC using `Start-Process -Verb RunAs`
and connects to a random `127.0.0.1` port using a per-launch token.

## Debugging CPU sensor access

AMD CPU temperature, power, VID, and clock fields may require an elevated helper
process. The helper supports a one-shot debug mode that writes raw LHM output to a
JSON file:

```powershell
$out = Join-Path $env:TEMP 'dashb-lhm-debug.json'
helpers\lhm-helper\bin\Release\net8.0\win-x64\publish\dashb-lhm-helper.exe --debug-once $out
Get-Content $out -Raw | ConvertFrom-Json
```

Run the same command from an elevated PowerShell, or launch the helper with
`Start-Process -Verb RunAs`, to compare `elevated`, `targetSamples`, and the CPU
`reports` section. On Ryzen systems, a non-elevated helper can list CPU sensor
names but return `0`/`null` values when the low-level AMD backend cannot read MSR,
SMN, or SMU data.

## Protocol

Requests:

```json
{"type":"list"}
{"type":"read","ids":["/intelcpu/0/temperature/0"]}
{"type":"status"}
{"type":"ping"}
```

Responses:

```json
{"type":"sensor_list","sensors":[]}
{"type":"sensor_values","sensors":[]}
{"type":"status","elevated":true}
{"type":"pong"}
{"type":"error","code":"helper_error","message":"..."}
```
