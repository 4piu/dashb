"""Host/static info metrics."""

import platform
import socket
import time
from typing import Any, Dict

import psutil

from dashb.probe.types import MetricMap


def get_host_info() -> Dict[str, Any]:
    hostname = socket.gethostname()
    os_name = platform.platform()
    uptime_s = int(time.time() - psutil.boot_time())
    return {"hostname": hostname, "os": os_name, "uptime_s": uptime_s}


METRICS = {
    "host.hostname": {"unit": "string", "kind": "info", "subscribable": False},
    "host.os": {"unit": "string", "kind": "info", "subscribable": False},
    "host.uptime_s": {"unit": "s", "kind": "gauge", "subscribable": True},
}


def get_supported_metrics() -> MetricMap:
    return METRICS.copy()


def supports_metric(metric: str) -> bool:
    return metric in METRICS


def collect_metric(metric: str) -> Any:
    host = get_host_info()
    if metric == "host.hostname":
        return host["hostname"]
    if metric == "host.os":
        return host["os"]
    if metric == "host.uptime_s":
        return host["uptime_s"]
    raise KeyError(metric)
