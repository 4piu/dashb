"""Probe dispatcher for supported metrics."""

from typing import Any, Dict

from dashb.probe import cpu, memory, network, gpu


async def collect_metric(metric: str, params: Dict[str, Any]) -> Any:
    # CPU
    if metric == "cpu.utilization":
        return cpu.get_cpu_percent(percpu=False)
    if metric == "cpu.per_core.utilization":
        return cpu.get_cpu_percent(percpu=True)

    # Memory
    if metric == "memory.used_bytes":
        return memory.get_virtual_memory()["used"]
    if metric == "memory.total_bytes":
        return memory.get_virtual_memory()["total"]
    if metric == "memory.utilization":
        return memory.get_virtual_memory()["percent"]

    # Network
    if metric.startswith("network"):
        iface = params.get("iface")
        # metric endswith field name
        field = metric.split(".")[-1]
        delta = network.get_network_bytes_per_second(iface)
        return delta.get(field, 0.0)

    # GPU
    if metric.startswith("gpu"):
        index = params.get("index")
        field = metric.split(".")[-1]
        return gpu.get_gpu_metric(field, index=index)

    return None


__all__ = ["collect_metric"]
