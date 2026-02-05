"""System and static capability information for Dashb server_info payload."""

import os
import platform
import socket
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
        "host": get_host_info(),
        "metrics": [
            {"metric": name, **meta} for name, meta in supported_metrics.items()
        ],
    }
