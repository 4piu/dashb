import psutil

from dashb.probe.types import MetricMap

METRICS = {
    "cpu.utilization": {"unit": "%", "kind": "gauge", "subscribable": True},
    "cpu.per_core.utilization": {"unit": "%", "kind": "gauge", "subscribable": True},
    "cpu.logical_cores": {"unit": "count", "kind": "gauge", "subscribable": False},
    "cpu.physical_cores": {"unit": "count", "kind": "gauge", "subscribable": False},
}


def get_cpu_percent(percpu: bool = False) -> float | list[float]:
    return psutil.cpu_percent(percpu=percpu)


def get_cpu_freq(percpu: bool = False) -> dict[str, float] | list[dict[str, float]]:
    result = psutil.cpu_freq(percpu=percpu)
    return [cpu._asdict() for cpu in result] if percpu else result._asdict()


def get_load_avg() -> tuple[float, float, float]:
    return psutil.getloadavg()


def get_supported_metrics() -> MetricMap:
    return METRICS.copy()


def supports_metric(metric: str) -> bool:
    return metric in METRICS


def collect_metric(metric: str) -> float | int | list[float]:
    if metric == "cpu.utilization":
        return get_cpu_percent(percpu=False)
    if metric == "cpu.per_core.utilization":
        return get_cpu_percent(percpu=True)
    if metric == "cpu.logical_cores":
        return psutil.cpu_count(logical=True) or 0
    if metric == "cpu.physical_cores":
        return psutil.cpu_count(logical=False) or 0
    raise KeyError(metric)
