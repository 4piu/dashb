"""GPU metrics provider (NVIDIA first, via NVML/nvidia-smi)."""

import subprocess
from functools import lru_cache
from typing import Any, Dict, List, Optional

from dashb.probe.types import MetricMap

try:
    import pynvml  # provided by nvidia-ml-py

    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

_nvml_inited = False

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


def _vendor_from_name(name: str) -> str:
    lower = name.lower()
    if "nvidia" in lower or "geforce" in lower or "quadro" in lower:
        return "nvidia"
    if "amd" in lower or "radeon" in lower:
        return "amd"
    if "intel" in lower or "uhd" in lower or "iris" in lower:
        return "intel"
    return "other"


def _nvidia_from_nvml() -> List[Dict[str, Any]]:
    if not _ensure_nvml():
        return []

    devices = []
    try:
        count = pynvml.nvmlDeviceGetCount()
    except Exception:
        return []
    for idx in range(count):
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
            name = pynvml.nvmlDeviceGetName(handle).decode()
        except Exception:
            continue
        devices.append(
            {"index": idx, "name": name, "vendor": "nvidia", "provider": "nvml"}
        )
    return devices


def _nvidia_from_smi() -> List[Dict[str, Any]]:
    cmd = ["nvidia-smi", "-L"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0 or not result.stdout:
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


def _gpus_from_wmic() -> List[Dict[str, Any]]:
    import os

    if os.name != "nt":
        return []
    cmd = ["wmic", "path", "win32_videocontroller", "get", "Name"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0 or not result.stdout:
        return []
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if lines and lines[0].lower() == "name":
        lines = lines[1:]
    devices = []
    for idx, name in enumerate(lines):
        vendor = _vendor_from_name(name)
        devices.append(
            {"index": idx, "name": name, "vendor": vendor, "provider": "wmic"}
        )
    return devices


def get_gpu_info() -> List[Dict[str, Any]]:
    devices: List[Dict[str, Any]] = []

    nvidia_nvml = _nvidia_from_nvml()
    devices.extend(nvidia_nvml)

    if not nvidia_nvml:
        devices.extend(_nvidia_from_smi())

    devices.extend(_gpus_from_wmic())
    return devices


def _ensure_nvml() -> bool:
    global _nvml_inited
    if not NVML_AVAILABLE:
        return False
    if _nvml_inited:
        return True
    try:
        pynvml.nvmlInit()
        _nvml_inited = True
        return True
    except Exception:
        return False


def _nvml_device_handle(index: int):
    if not _ensure_nvml():
        return None
    count = pynvml.nvmlDeviceGetCount()
    if index < 0 or index >= count:
        return None
    return pynvml.nvmlDeviceGetHandleByIndex(index)


def _nvml_metric(field: str, index: int) -> Any:
    h = _nvml_device_handle(index)
    if not h:
        return None
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


def _smi_metric(field: str, index: Optional[int]) -> Any:
    query_map = {
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
    query = query_map.get(field)
    if not query:
        return None
    cmd = ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"]
    if index is not None:
        cmd.extend(["-i", str(index)])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    line = result.stdout.strip().splitlines()[0].strip()
    try:
        val = float(line)
    except ValueError:
        return None
    if field in {"memory_used_bytes", "memory_total_bytes"}:
        # nvidia-smi reports MiB
        return val * 1024 * 1024
    return val


@lru_cache(maxsize=1)
def _gpu_inventory():
    return get_gpu_info()


def _has_nvidia(index: int) -> bool:
    devices = [d for d in _gpu_inventory() if d.get("vendor") == "nvidia"]
    if not devices:
        return False
    return any(d.get("index") == index for d in devices) or index < len(devices)


def _nvidia_indices() -> list[int]:
    devices = [d for d in _gpu_inventory() if d.get("vendor") == "nvidia"]
    return sorted(
        {int(d["index"]) for d in devices if isinstance(d.get("index"), int)}
    )


def get_supported_metrics() -> MetricMap:
    metrics: MetricMap = {
        "gpu.devices": {"unit": "list", "kind": "info", "subscribable": False}
    }
    indices = _nvidia_indices()
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
    if not _has_nvidia(idx):
        return None
    if _ensure_nvml():
        try:
            val = _nvml_metric(field, idx)
        except Exception:
            val = None
        if val is not None:
            return val
    return _smi_metric(field, idx)


def collect_metric(metric: str) -> Any:
    if metric == "gpu.devices":
        return get_gpu_info()
    field, index = _parse_gpu_metric(metric)
    return get_gpu_metric(field, index=index)


__all__ = [
    "collect_metric",
    "get_gpu_info",
    "get_gpu_metric",
    "get_supported_metrics",
    "supports_metric",
]
