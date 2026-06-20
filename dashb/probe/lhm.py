"""Optional Windows LibreHardwareMonitor helper bridge.

This module is intentionally not a probe provider. Categorized probes import it
to opt into selected LibreHardwareMonitor sensors while keeping metric ownership
in modules such as cpu.py, memory.py, or gpu.py.
"""

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


HELPER_ENV = "DASHB_LHM_HELPER_PATH"
LIST_CACHE_TTL_S = 30
READ_CACHE_TTL_S = 0.25


@dataclass(frozen=True)
class Sensor:
    id: str
    name: str
    type: str
    value: Optional[float]
    hardware_name: str
    hardware_type: str


class LhmClient:
    def __init__(self, helper_path: Path):
        self.helper_path = helper_path
        self.process: Optional[subprocess.Popen[str]] = None
        self.lock = threading.Lock()
        self.cached_sensors: list[Sensor] = []
        self.cached_at = 0.0
        self.cached_reads: dict[str, tuple[float, Optional[float]]] = {}

    def list_sensors(self) -> list[Sensor]:
        now = time.monotonic()
        if self.cached_sensors and (now - self.cached_at) < LIST_CACHE_TTL_S:
            return self.cached_sensors

        response = self._request({"type": "list"})
        sensors = _parse_sensors(response.get("sensors", []))
        self.cached_sensors = sensors
        self.cached_at = now
        return sensors

    def read_sensor(self, sensor_id: str) -> Optional[float]:
        cached = self.cached_reads.get(sensor_id)
        now = time.monotonic()
        if cached and (now - cached[0]) < READ_CACHE_TTL_S:
            return cached[1]

        response = self._request({"type": "read", "ids": [sensor_id]})
        sensors = _parse_sensors(response.get("sensors", []))
        value = sensors[0].value if sensors else None
        self.cached_reads[sensor_id] = (now, value)
        return value

    def read_sensors(self, sensor_ids: Iterable[str]) -> dict[str, Optional[float]]:
        ids = list(sensor_ids)
        if not ids:
            return {}

        response = self._request({"type": "read", "ids": ids})
        sensors = _parse_sensors(response.get("sensors", []))
        values = {sensor.id: sensor.value for sensor in sensors}
        now = time.monotonic()
        for sensor_id, value in values.items():
            self.cached_reads[sensor_id] = (now, value)
        return values

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            process = self._ensure_process()
            assert process.stdin is not None
            assert process.stdout is not None

            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                self._stop_process()
                raise RuntimeError("LibreHardwareMonitor helper stopped")

        response = json.loads(line)
        if response.get("type") == "error":
            raise RuntimeError(response.get("message", "LibreHardwareMonitor error"))
        return response

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self.process and self.process.poll() is None:
            return self.process

        self.process = subprocess.Popen(
            [str(self.helper_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        return self.process

    def _stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
        self.process = None


def is_available() -> bool:
    return _get_client() is not None


def list_sensors() -> list[Sensor]:
    client = _get_client()
    if not client:
        return []
    try:
        return client.list_sensors()
    except Exception:
        return []


def read_sensor(sensor_id: str) -> Optional[float]:
    client = _get_client()
    if not client:
        return None
    try:
        return client.read_sensor(sensor_id)
    except Exception:
        return None


def read_sensors(sensor_ids: Iterable[str]) -> dict[str, Optional[float]]:
    client = _get_client()
    if not client:
        return {}
    try:
        return client.read_sensors(sensor_ids)
    except Exception:
        return {}


def _parse_sensors(items: list[dict[str, Any]]) -> list[Sensor]:
    sensors: list[Sensor] = []
    for item in items:
        sensor_id = item.get("id")
        if not isinstance(sensor_id, str):
            continue
        value = item.get("value")
        sensors.append(
            Sensor(
                id=sensor_id,
                name=str(item.get("name") or ""),
                type=str(item.get("type") or ""),
                value=float(value) if isinstance(value, (int, float)) else None,
                hardware_name=str(item.get("hardwareName") or ""),
                hardware_type=str(item.get("hardwareType") or ""),
            )
        )
    return sensors


def _find_helper_path() -> Optional[Path]:
    if os.name != "nt":
        return None

    env_path = os.getenv(HELPER_ENV)
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return path

    root = Path(__file__).resolve().parents[2]
    candidates = [
        root / "dashb-lhm-helper.exe",
        root / "helpers" / "lhm-helper" / "dashb-lhm-helper.exe",
        root / "helpers" / "lhm-helper" / "bin" / "Release" / "net8.0" / "win-x64" / "publish" / "dashb-lhm-helper.exe",
        root / "helpers" / "lhm-helper" / "bin" / "Release" / "net8.0" / "win-x64" / "publish" / "Dashb.LhmHelper.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


_client: Optional[LhmClient] = None
_client_checked = False


def _get_client() -> Optional[LhmClient]:
    global _client, _client_checked

    if _client_checked:
        return _client

    _client_checked = True
    helper_path = _find_helper_path()
    if not helper_path:
        return None

    _client = LhmClient(helper_path)
    return _client
