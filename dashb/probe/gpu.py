"""GPU metrics provider (NVIDIA first, via NVML/nvidia-smi, then LibreHardwareMonitor).

Provider order per NVIDIA metric:

1. NVML (in-process, cheap).
2. nvidia-smi, only while NVML is unavailable. nvidia-smi is itself built on NVML,
   so when NVML is healthy but reports a field as unsupported, nvidia-smi can't do
   better and is not consulted. All fields for all GPUs are fetched in one batched,
   cached call, and failures back off exponentially.
3. LibreHardwareMonitor sensors.

Spawning nvidia-smi is the expensive, visible part: the packaged GUI build has no
console, so every child console process would pop up its own window unless it is
started with CREATE_NO_WINDOW. A driver upgrade breaks NVML for the running process,
which previously sent *every* metric sample through nvidia-smi - an endless stream of
console windows. The batching, caching, backoff, and hidden-window flags below keep
that path bounded to at most one hidden spawn per cache/backoff window.
"""

import os
import subprocess
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

from dashb.probe import lhm
from dashb.probe.types import MetricMap

try:
    import pynvml  # provided by nvidia-ml-py

    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

_NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SMI_TIMEOUT_S = 5
SMI_CACHE_TTL_S = 1.0
# After NVML or nvidia-smi fails, wait this long before trying again, doubling on
# each consecutive failure up to the max.
RETRY_BACKOFF_MIN_S = 10.0
RETRY_BACKOFF_MAX_S = 300.0

GPU_FIELDS = {
    "utilization": {"unit": "%", "kind": "gauge"},
    "memory_used_bytes": {"unit": "bytes", "kind": "gauge"},
    "memory_total_bytes": {"unit": "bytes", "kind": "gauge"},
    "temperature_c": {"unit": "C", "kind": "gauge"},
    "power_draw_w": {"unit": "W", "kind": "gauge"},
    "power_limit_w": {"unit": "W", "kind": "gauge"},
    "fan_speed": {"unit": "%", "kind": "gauge"},
    "core_clock_mhz": {"unit": "MHz", "kind": "gauge"},
    "memory_clock_mhz": {"unit": "MHz", "kind": "gauge"},
}

SMI_QUERY_FIELDS = {
    "utilization": "utilization.gpu",
    "memory_used_bytes": "memory.used",
    "memory_total_bytes": "memory.total",
    "temperature_c": "temperature.gpu",
    "power_draw_w": "power.draw",
    "power_limit_w": "power.limit",
    "fan_speed": "fan.speed",
    "core_clock_mhz": "clocks.current.graphics",
    "memory_clock_mhz": "clocks.current.memory",
}


class _Backoff:
    """Exponential retry gate shared by the NVML and nvidia-smi paths."""

    def __init__(self):
        self.failures = 0
        self.retry_at = 0.0

    def ready(self) -> bool:
        return time.monotonic() >= self.retry_at

    def succeeded(self) -> None:
        self.failures = 0
        self.retry_at = 0.0

    def failed(self) -> None:
        delay = min(
            RETRY_BACKOFF_MAX_S, RETRY_BACKOFF_MIN_S * (2 ** self.failures)
        )
        self.failures += 1
        self.retry_at = time.monotonic() + delay


_nvml_inited = False
_nvml_backoff = _Backoff()
_smi_backoff = _Backoff()
_smi_cache: tuple[float, dict[int, dict[str, Optional[float]]]] | None = None
_lhm_gpu_sensor_ids: dict[int, dict[str, str]] | None = None


def _run_hidden(cmd: list[str]) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a console tool without flashing a window; None if it can't run."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SMI_TIMEOUT_S,
            creationflags=_NO_WINDOW_FLAGS,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _vendor_from_name(name: str) -> str:
    lower = name.lower()
    if "nvidia" in lower or "geforce" in lower or "quadro" in lower:
        return "nvidia"
    if "amd" in lower or "radeon" in lower:
        return "amd"
    if "intel" in lower or "uhd" in lower or "iris" in lower:
        return "intel"
    return "other"


def _as_str(value: Any) -> str:
    # nvidia-ml-py >= 11.515 returns str; older releases returned bytes.
    return value.decode() if isinstance(value, bytes) else str(value)


def _nvidia_from_nvml() -> List[Dict[str, Any]]:
    if not _ensure_nvml():
        return []

    devices = []
    try:
        count = pynvml.nvmlDeviceGetCount()
    except Exception:
        _mark_nvml_failed()
        return []
    for idx in range(count):
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
            name = _as_str(pynvml.nvmlDeviceGetName(handle))
        except Exception:
            continue
        devices.append(
            {"index": idx, "name": name, "vendor": "nvidia", "provider": "nvml"}
        )
    return devices


def _nvidia_from_smi() -> List[Dict[str, Any]]:
    result = _run_hidden(["nvidia-smi", "-L"])
    if result is None or result.returncode != 0 or not result.stdout:
        return []
    devices = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("GPU"):
            continue
        try:
            left, right = line.split(":", 1)
            idx_str = left.split()[1]
            name = right.split("(")[0].strip()
            idx = int(idx_str)
        except Exception:
            continue
        devices.append(
            {"index": idx, "name": name, "vendor": "nvidia", "provider": "nvidia-smi"}
        )
    return devices


def _gpus_from_lhm() -> List[Dict[str, Any]]:
    devices_by_name: dict[str, Dict[str, Any]] = {}
    for sensor in lhm.list_sensors():
        if not sensor.hardware_type.lower().startswith("gpu"):
            continue
        key = _normalize_gpu_name(sensor.hardware_name)
        if key in devices_by_name:
            continue
        devices_by_name[key] = {
            "index": len(devices_by_name),
            "name": sensor.hardware_name,
            "vendor": _vendor_from_lhm_sensor(sensor),
            "provider": "lhm",
        }
    return list(devices_by_name.values())


def _vendor_from_lhm_sensor(sensor: lhm.Sensor) -> str:
    hardware_type = sensor.hardware_type.lower()
    if "nvidia" in hardware_type:
        return "nvidia"
    if "amd" in hardware_type or "ati" in hardware_type:
        return "amd"
    if "intel" in hardware_type:
        return "intel"
    return _vendor_from_name(sensor.hardware_name)


def get_gpu_info() -> List[Dict[str, Any]]:
    """Enumerate GPUs. NVIDIA devices come first so their list index matches the
    NVML/nvidia-smi device index used by the metric readers."""
    devices: List[Dict[str, Any]] = []

    nvidia_nvml = _nvidia_from_nvml()
    devices.extend(nvidia_nvml)

    if not nvidia_nvml:
        devices.extend(_nvidia_from_smi())

    devices.extend(_gpus_from_lhm())
    return _dedupe_devices(devices)


def _dedupe_devices(devices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for device in devices:
        key = (
            str(device.get("vendor") or "other"),
            _normalize_gpu_name(str(device.get("name") or "")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(device)

    return [
        {**device, "index": index}
        for index, device in enumerate(deduped)
    ]


def _normalize_gpu_name(name: str) -> str:
    return " ".join(name.casefold().split())


def _ensure_nvml() -> bool:
    global _nvml_inited
    if not NVML_AVAILABLE:
        return False
    if _nvml_inited:
        return True
    if not _nvml_backoff.ready():
        return False
    try:
        pynvml.nvmlInit()
    except Exception:
        _nvml_backoff.failed()
        return False
    _nvml_inited = True
    _nvml_backoff.succeeded()
    return True


def _mark_nvml_failed() -> None:
    """Drop the NVML session (e.g. after a driver upgrade/reset invalidated it) and
    retry initialization later instead of on every sample."""
    global _nvml_inited
    if _nvml_inited:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    _nvml_inited = False
    _nvml_backoff.failed()


def _nvml_field_unsupported(ex: Exception) -> bool:
    """True for per-field errors that don't mean NVML itself is broken."""
    value = getattr(ex, "value", None)
    return value in {
        getattr(pynvml, "NVML_ERROR_NOT_SUPPORTED", object()),
        getattr(pynvml, "NVML_ERROR_NO_PERMISSION", object()),
        getattr(pynvml, "NVML_ERROR_INVALID_ARGUMENT", object()),
        getattr(pynvml, "NVML_ERROR_NOT_FOUND", object()),
    }


def _nvml_metric(field: str, index: int) -> Any:
    if not _ensure_nvml():
        return None
    try:
        return _read_nvml_field(field, index)
    except Exception as ex:
        if not _nvml_field_unsupported(ex):
            _mark_nvml_failed()
        return None


def _read_nvml_field(field: str, index: int) -> Any:
    count = pynvml.nvmlDeviceGetCount()
    if index < 0 or index >= count:
        return None
    h = pynvml.nvmlDeviceGetHandleByIndex(index)
    if field == "utilization":
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        return float(util.gpu)
    if field == "memory_used_bytes":
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        return float(mem.used)
    if field == "memory_total_bytes":
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        return float(mem.total)
    if field == "temperature_c":
        return float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
    if field == "power_draw_w":
        return float(pynvml.nvmlDeviceGetPowerUsage(h)) / 1000
    if field == "power_limit_w":
        return float(pynvml.nvmlDeviceGetEnforcedPowerLimit(h)) / 1000
    if field == "fan_speed":
        return float(pynvml.nvmlDeviceGetFanSpeed(h))
    if field == "core_clock_mhz":
        return float(pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS))
    if field == "memory_clock_mhz":
        return float(pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM))
    return None


def _smi_snapshot() -> dict[int, dict[str, Optional[float]]]:
    """All SMI_QUERY_FIELDS for all GPUs from a single cached nvidia-smi call."""
    global _smi_cache

    now = time.monotonic()
    if _smi_cache is not None and (now - _smi_cache[0]) < SMI_CACHE_TTL_S:
        return _smi_cache[1]
    if not _smi_backoff.ready():
        return {}

    fields = list(SMI_QUERY_FIELDS)
    query = ",".join(["index", *(SMI_QUERY_FIELDS[f] for f in fields)])
    result = _run_hidden(
        ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"]
    )
    if result is None or result.returncode != 0 or not result.stdout:
        _smi_backoff.failed()
        _smi_cache = None
        return {}

    snapshot: dict[int, dict[str, Optional[float]]] = {}
    for line in result.stdout.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != len(fields) + 1:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        snapshot[index] = {
            field: _parse_smi_value(field, raw) for field, raw in zip(fields, parts[1:])
        }

    _smi_backoff.succeeded()
    _smi_cache = (now, snapshot)
    return snapshot


def _parse_smi_value(field: str, raw: str) -> Optional[float]:
    try:
        value = float(raw)
    except ValueError:
        return None  # "[N/A]", "[Not Supported]", ...
    if field in {"memory_used_bytes", "memory_total_bytes"}:
        return value * 1024 * 1024  # nvidia-smi reports MiB
    return value


def _smi_metric(field: str, index: int) -> Any:
    return _smi_snapshot().get(index, {}).get(field)


def _lhm_gpu_metric(field: str, index: int) -> Any:
    sensor_id = _get_lhm_gpu_sensor_ids().get(index, {}).get(field)
    if not sensor_id:
        return None
    value = lhm.read_sensor(sensor_id)
    if value is None:
        return None
    if field in {"memory_used_bytes", "memory_total_bytes"}:
        return value * 1024 * 1024
    return value


def _get_lhm_gpu_sensor_ids() -> dict[int, dict[str, str]]:
    global _lhm_gpu_sensor_ids

    if _lhm_gpu_sensor_ids is not None:
        return _lhm_gpu_sensor_ids

    sensors_by_hardware = _lhm_sensors_by_hardware()
    mapped: dict[int, dict[str, str]] = {}
    for device in _gpu_inventory():
        index = device.get("index")
        if not isinstance(index, int):
            continue
        sensors = sensors_by_hardware.get(
            _normalize_gpu_name(str(device.get("name") or "")),
            [],
        )
        if not sensors:
            continue
        mapped[index] = _map_lhm_gpu_sensors(sensors)

    _lhm_gpu_sensor_ids = mapped
    return mapped


def _lhm_sensors_by_hardware() -> dict[str, list[lhm.Sensor]]:
    sensors_by_hardware: dict[str, list[lhm.Sensor]] = {}
    for sensor in lhm.list_sensors():
        if not sensor.hardware_type.lower().startswith("gpu"):
            continue
        key = _normalize_gpu_name(sensor.hardware_name)
        sensors_by_hardware.setdefault(key, []).append(sensor)
    return sensors_by_hardware


def _map_lhm_gpu_sensors(sensors: list[lhm.Sensor]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    field_selectors = {
        "utilization": (("Load",), ("gpu core",)),
        "memory_used_bytes": (("SmallData", "Data"), ("gpu memory used",)),
        "memory_total_bytes": (("SmallData", "Data"), ("gpu memory total",)),
        "temperature_c": (("Temperature",), ("gpu core",)),
        "power_draw_w": (("Power",), ("package", "board", "power")),
        "fan_speed": (("Control",), ("gpu fan", "fan")),
        "core_clock_mhz": (("Clock",), ("gpu core",)),
        "memory_clock_mhz": (("Clock",), ("gpu memory",)),
    }
    for field, (sensor_types, name_contains) in field_selectors.items():
        sensor = _first_lhm_sensor(
            sensors,
            sensor_types=sensor_types,
            name_contains=name_contains,
        )
        if sensor:
            mapped[field] = sensor.id
    return mapped


def _first_lhm_sensor(
    sensors: list[lhm.Sensor],
    *,
    sensor_types: tuple[str, ...],
    name_contains: tuple[str, ...],
) -> lhm.Sensor | None:
    fallback: lhm.Sensor | None = None
    for sensor in sensors:
        if sensor.type not in sensor_types:
            continue
        if fallback is None:
            fallback = sensor
        name = sensor.name.lower()
        if any(part in name for part in name_contains):
            return sensor
    return fallback


@lru_cache(maxsize=1)
def _gpu_inventory() -> tuple[Dict[str, Any], ...]:
    return tuple(get_gpu_info())


def _has_nvidia(index: int) -> bool:
    return any(
        d.get("vendor") == "nvidia" and d.get("index") == index
        for d in _gpu_inventory()
    )


def _gpu_indices() -> list[int]:
    return sorted(
        int(device["index"])
        for device in _gpu_inventory()
        if isinstance(device.get("index"), int)
    )


def get_supported_metrics() -> MetricMap:
    metrics: MetricMap = {
        "gpu.devices": {"unit": "list", "kind": "info", "subscribable": False}
    }
    indices = _gpu_indices()
    if not indices:
        return metrics

    for index in indices:
        for field, meta in GPU_FIELDS.items():
            if get_gpu_metric(field, index=index) is None:
                continue
            metrics[f"gpu.[{index}].{field}"] = {**meta, "subscribable": True}

    first_index = indices[0]
    for field, meta in GPU_FIELDS.items():
        if f"gpu.[{first_index}].{field}" in metrics:
            metrics[f"gpu.{field}"] = {**meta, "subscribable": True}

    return metrics


def supports_metric(metric: str) -> bool:
    return metric == "gpu.devices" or metric.startswith("gpu.")


def _parse_gpu_metric(metric: str) -> tuple[str, Optional[int]]:
    if metric.startswith("gpu.["):
        index_part, field = metric.removeprefix("gpu.[").split("].", 1)
        return field, int(index_part)
    return metric.removeprefix("gpu."), None


def get_gpu_metric(field: str, index: Optional[int] = None) -> Any:
    idx = 0 if index is None else int(index)
    if _has_nvidia(idx):
        val = _nvml_metric(field, idx)
        if val is not None:
            return val
        # nvidia-smi is a fallback for when NVML itself is unusable, not for a
        # field NVML reports as unsupported (nvidia-smi wouldn't have it either).
        if not _nvml_inited:
            val = _smi_metric(field, idx)
            if val is not None:
                return val
    return _lhm_gpu_metric(field, idx)


def collect_metric(metric: str) -> Any:
    if metric == "gpu.devices":
        return [dict(device) for device in _gpu_inventory()]
    field, index = _parse_gpu_metric(metric)
    return get_gpu_metric(field, index=index)


__all__ = [
    "collect_metric",
    "get_gpu_info",
    "get_gpu_metric",
    "get_supported_metrics",
    "supports_metric",
]
