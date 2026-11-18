import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from dashb.probe import MetricCatalog


class SlowProbe:
    def __init__(self):
        self.threads: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def get_supported_metrics(self):
        return {}

    def supports_metric(self, metric):
        return metric.startswith("slow.")

    def collect_metric(self, metric):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.threads.append(threading.current_thread().name)
        time.sleep(0.2)
        with self.lock:
            self.active -= 1
        return metric


class MetricCatalogTests(unittest.TestCase):
    def test_slow_probe_does_not_block_event_loop_and_reads_are_serialized(self):
        probe = SlowProbe()
        catalog = MetricCatalog({"slow.a": {}, "slow.b": {}})

        async def scenario():
            ticks = 0

            async def ticker():
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.01)
                    ticks += 1

            ticker_task = asyncio.create_task(ticker())
            results = await asyncio.gather(
                catalog.collect("slow.a"), catalog.collect("slow.b")
            )
            ticker_task.cancel()
            return results, ticks

        with patch("dashb.probe.PROBE_MODULES", (probe,)):
            results, ticks = asyncio.run(scenario())

        self.assertEqual(results, ["slow.a", "slow.b"])
        # The loop kept running (~40 ticks in 0.4 s) while the probes slept.
        self.assertGreater(ticks, 10)
        self.assertEqual(probe.max_active, 1)
        self.assertTrue(all(name.startswith("dashb-probe") for name in probe.threads))


if __name__ == "__main__":
    unittest.main()
