"""Network probe helpers."""

import time
from typing import Any, Dict, Optional

import psutil

from dashb.probe.types import MetricMap

NETWORK_FIELDS = ("bytes_sent_per_s", "bytes_recv_per_s")


class NetworkDelta:
    CACHE_WINDOW_S = 0.1

    def __init__(self):
        self.last_ts: Optional[float] = None
        self.last_counters: Optional[Dict[str, Any]] = None
        self.cached_ts: Optional[float] = None
        self.cached_deltas: Dict[Optional[str], Dict[str, float]] = {}

    def bytes_per_second(self, iface: Optional[str] = None) -> Dict[str, float]:
        now = time.time()
        if self.cached_ts is not None and (now - self.cached_ts) < self.CACHE_WINDOW_S:
            cached = self.cached_deltas.get(iface)
            if cached is not None:
                return cached

        counters = psutil.net_io_counters(pernic=True)
        if self.last_ts is None or self.last_counters is None:
            self.last_ts = now
            self.last_counters = counters
            zero = {"bytes_sent_per_s": 0.0, "bytes_recv_per_s": 0.0}
            self.cached_ts = now
            self.cached_deltas = {iface: zero}
            return zero

        elapsed = now - self.last_ts
        if elapsed <= 0:
            return {"bytes_sent_per_s": 0.0, "bytes_recv_per_s": 0.0}

        def diff(c1, c0):
            return {
                "bytes_sent_per_s": (c1.bytes_sent - c0.bytes_sent) / elapsed,
                "bytes_recv_per_s": (c1.bytes_recv - c0.bytes_recv) / elapsed,
            }

        if iface:
            c1 = counters.get(iface)
            c0 = self.last_counters.get(iface) if self.last_counters else None
            if not c1 or not c0:
                self.last_ts = now
                self.last_counters = counters
                zero = {"bytes_sent_per_s": 0.0, "bytes_recv_per_s": 0.0}
                self.cached_ts = now
                self.cached_deltas = {iface: zero}
                return zero
            delta = diff(c1, c0)
        else:
            total1_sent = total1_recv = 0
            total0_sent = total0_recv = 0
            for name, c1 in counters.items():
                c0 = self.last_counters.get(name) if self.last_counters else None
                total1_sent += c1.bytes_sent
                total1_recv += c1.bytes_recv
                if c0:
                    total0_sent += c0.bytes_sent
                    total0_recv += c0.bytes_recv
            delta = {
                "bytes_sent_per_s": (total1_sent - total0_sent) / elapsed,
                "bytes_recv_per_s": (total1_recv - total0_recv) / elapsed,
            }

        self.last_ts = now
        self.last_counters = counters
        self.cached_ts = now
        self.cached_deltas = {iface: delta}
        return delta


_delta = NetworkDelta()


def get_network_bytes_per_second(iface: Optional[str] = None) -> Dict[str, float]:
    """Return bytes sent/recv per second, optionally for a specific interface."""
    return _delta.bytes_per_second(iface)


def get_supported_metrics() -> MetricMap:
    metrics: MetricMap = {
        "network.interfaces": {
            "unit": "list",
            "kind": "info",
            "subscribable": False,
        }
    }

    for field in NETWORK_FIELDS:
        metrics[f"network.{field}"] = {
            "unit": "bytes/s",
            "kind": "gauge",
            "subscribable": True,
        }

    for iface in psutil.net_io_counters(pernic=True).keys():
        for field in NETWORK_FIELDS:
            metrics[f"network.[{iface}].{field}"] = {
                "unit": "bytes/s",
                "kind": "gauge",
                "subscribable": True,
            }

    return metrics


def supports_metric(metric: str) -> bool:
    return metric == "network.interfaces" or metric.startswith("network.")


def _network_interfaces() -> list[dict[str, Any]]:
    interfaces = []
    for name, addrs in psutil.net_if_addrs().items():
        addresses = [addr.address for addr in addrs if addr.address]
        interfaces.append({"name": name, "addresses": addresses})
    return interfaces


def collect_metric(metric: str) -> Any:
    if metric == "network.interfaces":
        return _network_interfaces()

    iface: Optional[str] = None
    field = metric.split(".")[-1]
    if metric.startswith("network.["):
        iface = metric.split("]", 1)[0].removeprefix("network.[")

    return get_network_bytes_per_second(iface).get(field, 0.0)


__all__ = [
    "collect_metric",
    "get_network_bytes_per_second",
    "get_supported_metrics",
    "supports_metric",
]
