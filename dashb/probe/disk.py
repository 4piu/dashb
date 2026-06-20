"""Disk I/O probe helpers."""

import re
from typing import Any, Optional

import psutil

from dashb.probe.types import MetricMap

DISK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def get_supported_metrics() -> MetricMap:
    metrics: MetricMap = {
        "disk.devices": {"unit": "list", "kind": "info", "subscribable": False}
    }
    total = psutil.disk_io_counters()
    if total:
        for field in total._fields:
            metrics[f"disk.{field}"] = _metric_meta(field)

    for disk_name, counters in psutil.disk_io_counters(perdisk=True).items():
        if not _is_safe_disk_id(disk_name):
            continue
        for field in counters._fields:
            metrics[f"disk.[{disk_name}].{field}"] = _metric_meta(field)

    return metrics


def supports_metric(metric: str) -> bool:
    return metric == "disk.devices" or metric.startswith("disk.")


def collect_metric(metric: str) -> Any:
    if metric == "disk.devices":
        return _disk_devices()

    disk_name, field = _parse_disk_metric(metric)
    if disk_name:
        counters = psutil.disk_io_counters(perdisk=True).get(disk_name)
    else:
        counters = psutil.disk_io_counters()

    if not counters or not hasattr(counters, field):
        raise KeyError(metric)
    return getattr(counters, field)


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


def _unit_for_field(field: str) -> str:
    if field.endswith("_bytes"):
        return "bytes"
    if field.endswith("_time"):
        return "ms"
    return "count"


def _is_safe_disk_id(disk_name: str) -> bool:
    return bool(DISK_ID_PATTERN.fullmatch(disk_name))
