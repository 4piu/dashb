import psutil

from dashb.probe.types import MetricMap

PERCENT_FIELDS = {"percent"}
PHYSICAL_FIELDS = tuple(psutil.virtual_memory()._asdict().keys())
SWAP_FIELDS = tuple(psutil.swap_memory()._asdict().keys())


def get_virtual_memory() -> dict[str, int | float]:
    return psutil.virtual_memory()._asdict()


def get_swap_memory() -> dict[str, int | float]:
    return psutil.swap_memory()._asdict()


def _metric_meta(field: str) -> dict[str, object]:
    return {
        "unit": "%" if field in PERCENT_FIELDS else "bytes",
        "kind": "gauge",
        "subscribable": field not in {"total"},
    }


def get_supported_metrics() -> MetricMap:
    metrics: MetricMap = {}
    for field in PHYSICAL_FIELDS:
        metrics[f"memory.physical.{field}"] = _metric_meta(field)
    for field in SWAP_FIELDS:
        metrics[f"memory.swap.{field}"] = _metric_meta(field)
    return metrics


def supports_metric(metric: str) -> bool:
    return metric.startswith("memory.physical.") or metric.startswith("memory.swap.")


def collect_metric(metric: str) -> int | float:
    if metric.startswith("memory.physical."):
        field = metric.removeprefix("memory.physical.")
        return get_virtual_memory()[field]
    if metric.startswith("memory.swap."):
        field = metric.removeprefix("memory.swap.")
        return get_swap_memory()[field]
    raise KeyError(metric)
