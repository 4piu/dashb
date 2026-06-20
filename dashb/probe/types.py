"""Shared probe provider types."""

from typing import Any, Protocol

MetricMeta = dict[str, Any]
MetricMap = dict[str, MetricMeta]


class ProbeProvider(Protocol):
    def get_supported_metrics(self) -> MetricMap:
        ...

    def supports_metric(self, metric: str) -> bool:
        ...

    def collect_metric(self, metric: str) -> Any:
        ...
