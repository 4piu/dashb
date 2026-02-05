"""Network probe helpers."""

import time
from typing import Any, Dict, Optional

import psutil


class NetworkDelta:
    def __init__(self):
        self.last_ts: Optional[float] = None
        self.last_counters: Optional[Dict[str, Any]] = None

    def bytes_per_second(self, iface: Optional[str] = None) -> Dict[str, float]:
        now = time.time()
        counters = psutil.net_io_counters(pernic=True)
        if self.last_ts is None or self.last_counters is None:
            self.last_ts = now
            self.last_counters = counters
            return {"bytes_sent_per_s": 0.0, "bytes_recv_per_s": 0.0}

        elapsed = now - self.last_ts
        if elapsed <= 0:
            return {"bytes_sent_per_s": 0.0, "bytes_recv_per_s": 0.0}

        def diff(c1, c0):
            return {
                "bytes_sent_per_s": (c1.bytes_sent - c0.bytes_sent) / elapsed,
                "bytes_recv_per_s": (c1.bytes_recv - c0.bytes_recv) / elapsed,
            }

        if iface:
            c1 = counters.get(iface)
            c0 = self.last_counters.get(iface) if self.last_counters else None
            if not c1 or not c0:
                self.last_ts = now
                self.last_counters = counters
                return {"bytes_sent_per_s": 0.0, "bytes_recv_per_s": 0.0}
            delta = diff(c1, c0)
        else:
            total1_sent = total1_recv = 0
            total0_sent = total0_recv = 0
            for name, c1 in counters.items():
                c0 = self.last_counters.get(name) if self.last_counters else None
                total1_sent += c1.bytes_sent
                total1_recv += c1.bytes_recv
                if c0:
                    total0_sent += c0.bytes_sent
                    total0_recv += c0.bytes_recv
            delta = {
                "bytes_sent_per_s": (total1_sent - total0_sent) / elapsed,
                "bytes_recv_per_s": (total1_recv - total0_recv) / elapsed,
            }

        self.last_ts = now
        self.last_counters = counters
        return delta


_delta = NetworkDelta()


def get_network_bytes_per_second(iface: Optional[str] = None) -> Dict[str, float]:
    """Return bytes sent/recv per second, optionally for a specific interface."""
    return _delta.bytes_per_second(iface)


__all__ = ["get_network_bytes_per_second"]
