"""Shared probe scheduler for metrics.

Keeps one sampler per metric and fan-outs to subscribed clients.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from dashb.probe import MetricCatalog
from dashb.server_constants import MIN_INTERVAL_MS, MAX_INTERVAL_MS

SendFn = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class Subscriber:
    client_id: str
    send: SendFn
    interval_ms: int


@dataclass
class ProbeTask:
    metric: str
    catalog: MetricCatalog
    unit: Optional[str]
    kind: str
    subscribers: Dict[str, Subscriber] = field(default_factory=dict)
    interval_ms: int = MAX_INTERVAL_MS
    task: Optional[asyncio.Task] = None
    stopped: bool = False

    async def _run(self):
        while not self.stopped and self.subscribers:
            started = time.time()
            value = await self.catalog.collect(self.metric)
            ts_ms = int(time.time() * 1000)
            payload = {
                "type": "sample",
                "ts_ms": ts_ms,
                "values": [
                    {
                        "metric": self.metric,
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
    def __init__(self, catalog: MetricCatalog):
        self.catalog = catalog
        self.tasks: Dict[str, ProbeTask] = {}

    def subscribe(
        self,
        metric: str,
        interval_ms: int,
        client_id: str,
        send: SendFn,
    ):
        meta = self.catalog.meta(metric)
        task = self.tasks.get(metric)
        if not task:
            task = ProbeTask(
                metric=metric,
                catalog=self.catalog,
                unit=meta.get("unit"),
                kind=meta.get("kind"),
            )
            self.tasks[metric] = task
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

    def unsubscribe(self, metric: str, client_id: str):
        task = self.tasks.get(metric)
        if not task:
            return
        if client_id in task.subscribers:
            del task.subscribers[client_id]
            task.update_interval()
        if not task.subscribers:
            task.stop()
            self.tasks.pop(metric, None)

    def shutdown(self):
        for task in self.tasks.values():
            task.stop()
        self.tasks.clear()
