"""GPU metrics provider (NVIDIA first, via NVML)."""

import subprocess
from functools import lru_cache
from typing import Any, Dict, Optional

from dashb.probe import info as probe_info

try:
    import pynvml  # provided by nvidia-ml-py

    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False

_nvml_inited = False


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
    if field == "temperature_c":
        return float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
    return None


def _smi_metric(field: str, index: Optional[int]) -> Any:
    query_map = {
        "utilization": "utilization.gpu",
        "memory_used_bytes": "memory.used",
        "temperature_c": "temperature.gpu",
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
    if field == "memory_used_bytes":
        # nvidia-smi reports MiB
        return val * 1024 * 1024
    return val


@lru_cache(maxsize=1)
def _gpu_inventory():
    return probe_info.get_gpu_info()


def _has_nvidia(index: int) -> bool:
    devices = [d for d in _gpu_inventory() if d.get("vendor") == "nvidia"]
    if not devices:
        return False
    return any(d.get("index") == index for d in devices) or index < len(devices)


def get_gpu_metric(field: str, index: Optional[int] = None) -> Any:
    idx = 0 if index is None else int(index)
    if not _has_nvidia(idx):
        return None
    if _ensure_nvml():
        val = _nvml_metric(field, idx)
        if val is not None:
            return val
    return _smi_metric(field, idx)


__all__ = ["get_gpu_metric"]
