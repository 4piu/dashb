"""System and static capability information for Dashb server_info payload."""

import os
import platform
import socket
import subprocess
import time
from typing import Any, Dict, List

import psutil


def _now_ts_ms() -> int:
    return int(time.time() * 1000)


def get_cpu_info() -> Dict[str, Any]:
    return {
        "logical_cores": psutil.cpu_count(logical=True),
        "physical_cores": psutil.cpu_count(logical=False),
    }


def get_memory_info() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    return {"total_bytes": vm.total}


def get_network_interfaces() -> List[Dict[str, Any]]:
    interfaces = []
    for name, addrs in psutil.net_if_addrs().items():
        addresses = [addr.address for addr in addrs if addr.address]
        interfaces.append({"name": name, "addresses": addresses})
    return interfaces


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
    try:
        import pynvml
    except Exception:
        return []

    try:
        pynvml.nvmlInit()
    except Exception:
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
        # Example: GPU 0: NVIDIA RTX (UUID: ...)
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
    # Windows-specific, provides vendor-neutral names
    cmd = ["wmic", "path", "win32_videocontroller", "get", "Name"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0 or not result.stdout:
        return []
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # skip header
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
    """Enumerate GPUs with best-effort vendor detection."""
    devices: List[Dict[str, Any]] = []

    nvidia_nvml = _nvidia_from_nvml()
    devices.extend(nvidia_nvml)

    if not nvidia_nvml:
        devices.extend(_nvidia_from_smi())

    devices.extend(_gpus_from_wmic())

    return devices


def get_host_info() -> Dict[str, Any]:
    hostname = socket.gethostname()
    os_name = platform.platform()
    uptime_s = int(time.time() - psutil.boot_time())
    return {"hostname": hostname, "os": os_name, "uptime_s": uptime_s}


def build_server_info_payload(
    supported_metrics: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Compose the server_info payload sent after welcome."""
    return {
        "type": "server_info",
        "ts_ms": _now_ts_ms(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "network": {"interfaces": get_network_interfaces()},
        "gpu": {"devices": get_gpu_info()},
        "host": get_host_info(),
        "metrics": [
            {"metric": name, **meta} for name, meta in supported_metrics.items()
        ],
    }
