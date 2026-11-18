"""Network probe helpers."""

import time
from typing import Any, Dict, Optional

import psutil

from dashb.probe.types import MetricMap

NETWORK_FIELDS = ("bytes_sent_per_s", "bytes_recv_per_s")


class NetworkDelta:
    """Per-interface and total send/receive rates.

    Every interface is computed from the same pair of snapshots so subscribing to
    several interfaces (or the total plus one interface) doesn't reset each other's
    baseline.
    """

    CACHE_WINDOW_S = 0.1

    def __init__(self):
        self.last_ts: Optional[float] = None
        self.last_counters: Dict[str, Any] = {}
        self.cached_ts: Optional[float] = None
        self.cached_deltas: Dict[Optional[str], Dict[str, float]] = {}

    def bytes_per_second(self, iface: Optional[str] = None) -> Dict[str, float]:
        now = time.time()
        if self.cached_ts is not None and (now - self.cached_ts) < self.CACHE_WINDOW_S:
            return self.cached_deltas.get(iface, _zero_rate())

        counters = psutil.net_io_counters(pernic=True)
        if self.last_ts is None:
            deltas: Dict[Optional[str], Dict[str, float]] = {
                None: _zero_rate(),
                **{name: _zero_rate() for name in counters},
            }
        else:
            elapsed = now - self.last_ts
            if elapsed <= 0:
                return self.cached_deltas.get(iface, _zero_rate())
            deltas = {
                name: _counter_rate(current, self.last_counters.get(name), elapsed)
                for name, current in counters.items()
            }
            deltas[None] = {
                field: sum(rate[field] for rate in deltas.values())
                for field in NETWORK_FIELDS
            }

        self.last_ts = now
        self.last_counters = counters
        self.cached_ts = now
        self.cached_deltas = deltas
        return deltas.get(iface, _zero_rate())


def _zero_rate() -> Dict[str, float]:
    return {"bytes_sent_per_s": 0.0, "bytes_recv_per_s": 0.0}


def _counter_rate(current: Any, previous: Any, elapsed: float) -> Dict[str, float]:
    if not current or not previous:
        return _zero_rate()
    # Counters reset when an adapter is disabled/re-enabled; clamp rather than
    # report a huge negative rate.
    return {
        "bytes_sent_per_s": max(0.0, (current.bytes_sent - previous.bytes_sent) / elapsed),
        "bytes_recv_per_s": max(0.0, (current.bytes_recv - previous.bytes_recv) / elapsed),
    }


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
