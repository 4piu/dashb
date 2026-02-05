"""GPU metrics provider (NVIDIA first, via NVML)."""

import subprocess
from typing import Any, Dict, Optional

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
        return 0
    if field == "utilization":
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        return float(util.gpu)
    if field == "memory_used_bytes":
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        return float(mem.used)
    if field == "temperature_c":
        return float(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
    return 0


def _smi_metric(field: str, index: Optional[int]) -> Any:
    query_map = {
        "utilization": "utilization.gpu",
        "memory_used_bytes": "memory.used",
        "temperature_c": "temperature.gpu",
    }
    query = query_map.get(field)
    if not query:
        return 0
    cmd = ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"]
    if index is not None:
        cmd.extend(["-i", str(index)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout:
        return 0
    line = result.stdout.strip().splitlines()[0].strip()
    try:
        val = float(line)
    except ValueError:
        return 0
    if field == "memory_used_bytes":
        # nvidia-smi reports MiB
        return val * 1024 * 1024
    return val


def get_gpu_metric(field: str, index: Optional[int] = None) -> Any:
    idx = 0 if index is None else int(index)
    if _ensure_nvml():
        return _nvml_metric(field, idx)
    return _smi_metric(field, idx)


__all__ = ["get_gpu_metric"]
