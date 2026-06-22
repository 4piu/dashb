"""Disk I/O probe helpers."""

import re
import time
from typing import Any, Optional

import psutil

from dashb.probe.types import MetricMap

DISK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
DISK_RATE_FIELDS = ("bytes_read_per_s", "bytes_written_per_s")


class DiskDelta:
    CACHE_WINDOW_S = 0.1

    def __init__(self):
        self.last_ts: Optional[float] = None
        self.last_total: Any = None
        self.last_perdisk: dict[str, Any] = {}
        self.cached_ts: Optional[float] = None
        self.cached_deltas: dict[Optional[str], dict[str, float]] = {}

    def bytes_per_second(self, disk_name: Optional[str] = None) -> dict[str, float]:
        now = time.time()
        if self.cached_ts is not None and (now - self.cached_ts) < self.CACHE_WINDOW_S:
            return self.cached_deltas.get(disk_name, _zero_rate())

        total = psutil.disk_io_counters()
        perdisk = psutil.disk_io_counters(perdisk=True)
        if self.last_ts is None:
            self.last_ts = now
            self.last_total = total
            self.last_perdisk = perdisk
            zero = _zero_rate()
            self.cached_ts = now
            self.cached_deltas = {None: zero, **{name: zero for name in perdisk}}
            return zero

        elapsed = now - self.last_ts
        if elapsed <= 0:
            return _zero_rate()

        deltas = {None: _counter_rate(total, self.last_total, elapsed)}
        for name, current in perdisk.items():
            deltas[name] = _counter_rate(current, self.last_perdisk.get(name), elapsed)

        self.last_ts = now
        self.last_total = total
        self.last_perdisk = perdisk
        self.cached_ts = now
        self.cached_deltas = deltas
        return deltas.get(disk_name, _zero_rate())


_delta = DiskDelta()


def get_supported_metrics() -> MetricMap:
    metrics: MetricMap = {
        "disk.devices": {"unit": "list", "kind": "info", "subscribable": False}
    }
    total = psutil.disk_io_counters()
    if total:
        for field in DISK_RATE_FIELDS:
            metrics[f"disk.{field}"] = _rate_metric_meta()
        for field in total._fields:
            metrics[f"disk.{field}"] = _metric_meta(field)

    for disk_name, counters in psutil.disk_io_counters(perdisk=True).items():
        if not _is_safe_disk_id(disk_name):
            continue
        for field in DISK_RATE_FIELDS:
            metrics[f"disk.[{disk_name}].{field}"] = _rate_metric_meta()
        for field in counters._fields:
            metrics[f"disk.[{disk_name}].{field}"] = _metric_meta(field)

    return metrics


def supports_metric(metric: str) -> bool:
    return metric == "disk.devices" or metric.startswith("disk.")


def collect_metric(metric: str) -> Any:
    if metric == "disk.devices":
        return _disk_devices()

    disk_name, field = _parse_disk_metric(metric)
    if field in DISK_RATE_FIELDS:
        return get_disk_bytes_per_second(disk_name).get(field, 0.0)

    if disk_name:
        counters = psutil.disk_io_counters(perdisk=True).get(disk_name)
    else:
        counters = psutil.disk_io_counters()

    if not counters or not hasattr(counters, field):
        raise KeyError(metric)
    return getattr(counters, field)


def get_disk_bytes_per_second(disk_name: Optional[str] = None) -> dict[str, float]:
    """Return disk read/write bytes per second, optionally for a specific disk."""
    return _delta.bytes_per_second(disk_name)


def _disk_devices() -> list[dict[str, str]]:
    return [
        {"id": disk_name, "name": disk_name}
        for disk_name in psutil.disk_io_counters(perdisk=True).keys()
        if _is_safe_disk_id(disk_name)
    ]


def _parse_disk_metric(metric: str) -> tuple[Optional[str], str]:
    if metric.startswith("disk.["):
        disk_name, field = metric.removeprefix("disk.[").split("].", 1)
        return disk_name, field
    return None, metric.removeprefix("disk.")


def _metric_meta(field: str) -> dict[str, object]:
    return {
        "unit": _unit_for_field(field),
        "kind": "counter",
        "subscribable": True,
    }


def _rate_metric_meta() -> dict[str, object]:
    return {
        "unit": "bytes/s",
        "kind": "gauge",
        "subscribable": True,
    }


def _unit_for_field(field: str) -> str:
    if field.endswith("_bytes"):
        return "bytes"
    if field.endswith("_time"):
        return "ms"
    return "count"


def _is_safe_disk_id(disk_name: str) -> bool:
    return bool(DISK_ID_PATTERN.fullmatch(disk_name))


def _zero_rate() -> dict[str, float]:
    return {"bytes_read_per_s": 0.0, "bytes_written_per_s": 0.0}


def _counter_rate(current: Any, previous: Any, elapsed: float) -> dict[str, float]:
    if not current or not previous:
        return _zero_rate()
    return {
        "bytes_read_per_s": max(0.0, (current.read_bytes - previous.read_bytes) / elapsed),
        "bytes_written_per_s": max(
            0.0,
            (current.write_bytes - previous.write_bytes) / elapsed,
        ),
    }


__all__ = [
    "collect_metric",
    "get_disk_bytes_per_second",
    "get_supported_metrics",
    "supports_metric",
]
