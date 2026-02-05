"""Shared server constants and supported metrics metadata."""

PROTOCOL_VERSION = 1
MIN_INTERVAL_MS = 200
MAX_INTERVAL_MS = 60_000
MAX_SUBSCRIPTIONS = 128
MAX_CLIENTS = 3

SUPPORTED_METRICS = {
    "cpu.utilization": {"unit": "%", "kind": "gauge"},
    "cpu.per_core.utilization": {"unit": "%", "kind": "gauge"},
    "memory.used_bytes": {"unit": "bytes", "kind": "gauge"},
    "memory.total_bytes": {"unit": "bytes", "kind": "gauge"},
    "memory.utilization": {"unit": "%", "kind": "gauge"},
    # Network metrics can be parameterized by interface name: network.[eth0].bytes_sent_per_s
    "network.bytes_sent_per_s": {
        "unit": "bytes/s",
        "kind": "gauge",
        "params": [{"name": "iface", "required": False, "type": "string"}],
    },
    "network.bytes_recv_per_s": {
        "unit": "bytes/s",
        "kind": "gauge",
        "params": [{"name": "iface", "required": False, "type": "string"}],
    },
    # GPU metrics can be parameterized by GPU index: gpu.[0].utilization
    "gpu.utilization": {
        "unit": "%",
        "kind": "gauge",
        "params": [{"name": "index", "required": False, "type": "int"}],
    },
    "gpu.memory_used_bytes": {
        "unit": "bytes",
        "kind": "gauge",
        "params": [{"name": "index", "required": False, "type": "int"}],
    },
    "gpu.temperature_c": {
        "unit": "C",
        "kind": "gauge",
        "params": [{"name": "index", "required": False, "type": "int"}],
    },
}
