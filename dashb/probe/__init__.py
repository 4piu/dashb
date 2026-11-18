"""Probe metric catalog.

Each probe module owns platform detection for the metrics it can provide.
The server builds this catalog once at startup and treats it as the sole
authority for metric validation and collection.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from dashb.probe import cpu, disk, gpu, info, memory, network
from dashb.probe.types import MetricMap, MetricMeta, ProbeProvider

PROBE_MODULES: tuple[ProbeProvider, ...] = (cpu, memory, network, disk, gpu, info)

# Probe reads are synchronous and some can be slow (nvidia-smi, the LHM helper's
# socket). Run them on one dedicated worker thread: off the event loop, so a slow
# sensor can't stall websocket/HTTP handling, yet still serialized, so the probe
# modules' module-level state (rate baselines, NVML session, caches) needs no locks.
_probe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dashb-probe")


@dataclass(frozen=True)
class MetricCatalog:
    metrics: MetricMap

    def has(self, metric: Any) -> bool:
        return isinstance(metric, str) and metric in self.metrics

    def meta(self, metric: Any) -> MetricMeta:
        if not isinstance(metric, str):
            return {}
        return self.metrics.get(metric, {})

    def can_subscribe(self, metric: Any) -> bool:
        return self.has(metric) and self.meta(metric).get("subscribable") is not False

    def unit(self, metric: Any) -> Any:
        return self.meta(metric).get("unit")

    def as_payload(self) -> list[dict[str, Any]]:
        return [{"metric": name, **meta} for name, meta in self.metrics.items()]

    async def collect(self, metric: Any) -> Any:
        if not self.has(metric):
            raise KeyError(metric)
        for module in PROBE_MODULES:
            if module.supports_metric(metric):
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    _probe_executor, module.collect_metric, metric
                )
        raise KeyError(metric)


def shutdown_probe_executor() -> None:
    """Stop accepting probe work; doesn't wait for an in-flight read."""
    _probe_executor.shutdown(wait=False, cancel_futures=True)


def build_metric_catalog() -> MetricCatalog:
    metrics: MetricMap = {}
    for module in PROBE_MODULES:
        metrics.update(module.get_supported_metrics())
    return MetricCatalog(dict(sorted(metrics.items())))


__all__ = [
    "MetricCatalog",
    "build_metric_catalog",
    "shutdown_probe_executor",
]
