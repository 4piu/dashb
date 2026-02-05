"""Shared probe scheduler for metrics.

Keeps one sampler per metric+params and fan-outs to subscribed clients.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from dashb.probe import collect_metric
from dashb.server_constants import SUPPORTED_METRICS, MIN_INTERVAL_MS, MAX_INTERVAL_MS

SendFn = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class Subscriber:
    client_id: str
    send: SendFn
    interval_ms: int


@dataclass
class ProbeTask:
    metric: str
    params: Dict[str, Any]
    unit: Optional[str]
    kind: str
    subscribers: Dict[str, Subscriber] = field(default_factory=dict)
    interval_ms: int = MAX_INTERVAL_MS
    task: Optional[asyncio.Task] = None
    stopped: bool = False

    async def _run(self):
        while not self.stopped and self.subscribers:
            started = time.time()
            value = await collect_metric(self.metric, self.params)
            ts_ms = int(time.time() * 1000)
            payload = {
                "type": "sample",
                "ts_ms": ts_ms,
                "values": [
                    {
                        "metric": self.render_metric_name(),
                        "value": value,
                        "unit": self.unit,
                    }
                ],
            }
            await asyncio.gather(
                *[sub.send(payload) for sub in self.subscribers.values()],
                return_exceptions=True,
            )

            elapsed = (time.time() - started) * 1000
            sleep_ms = max(0, self.interval_ms - int(elapsed))
            await asyncio.sleep(sleep_ms / 1000)

    def render_metric_name(self) -> str:
        if not self.params:
            return self.metric
        if self.metric.startswith("network") and "iface" in self.params:
            return f"network.[{self.params['iface']}].{self.metric.split('.')[-1]}"
        if self.metric.startswith("gpu") and "index" in self.params:
            return f"gpu.[{self.params['index']}].{self.metric.split('.')[-1]}"
        return self.metric

    def update_interval(self):
        if not self.subscribers:
            self.interval_ms = MAX_INTERVAL_MS
            return
        self.interval_ms = max(
            MIN_INTERVAL_MS, min(sub.interval_ms for sub in self.subscribers.values())
        )

    def ensure_running(self):
        if self.task and not self.task.done():
            return
        self.stopped = False
        self.task = asyncio.create_task(self._run())

    def stop(self):
        self.stopped = True
        if self.task:
            self.task.cancel()


class ProbeRegistry:
    def __init__(self):
        self.tasks: Dict[str, ProbeTask] = {}

    def key_for(self, metric: str, params: Dict[str, Any]) -> str:
        if metric.startswith("network") and "iface" in params:
            return f"{metric}|{params['iface']}"
        if metric.startswith("gpu") and "index" in params:
            return f"{metric}|{params['index']}"
        return metric

    def subscribe(
        self,
        metric: str,
        params: Dict[str, Any],
        interval_ms: int,
        client_id: str,
        send: SendFn,
    ):
        key = self.key_for(metric, params)
        meta = SUPPORTED_METRICS.get(metric, {"unit": None, "kind": "gauge"})
        task = self.tasks.get(key)
        if not task:
            task = ProbeTask(
                metric=metric,
                params=params,
                unit=meta.get("unit"),
                kind=meta.get("kind"),
            )
            self.tasks[key] = task
        task.subscribers[client_id] = Subscriber(
            client_id=client_id, send=send, interval_ms=interval_ms
        )
        task.update_interval()
        task.ensure_running()

    def unsubscribe_client(self, client_id: str):
        dead_keys = []
        for key, task in self.tasks.items():
            if client_id in task.subscribers:
                del task.subscribers[client_id]
                task.update_interval()
            if not task.subscribers:
                task.stop()
                dead_keys.append(key)
        for key in dead_keys:
            self.tasks.pop(key, None)

    def unsubscribe(self, metric: str, params: Dict[str, Any], client_id: str):
        key = self.key_for(metric, params)
        task = self.tasks.get(key)
        if not task:
            return
        if client_id in task.subscribers:
            del task.subscribers[client_id]
            task.update_interval()
        if not task.subscribers:
            task.stop()
            self.tasks.pop(key, None)

    def shutdown(self):
        for task in self.tasks.values():
            task.stop()
        self.tasks.clear()
