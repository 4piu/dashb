"""Optional Windows LibreHardwareMonitor helper bridge.

This module is intentionally not a probe provider. Categorized probes import it
to opt into selected LibreHardwareMonitor sensors while keeping metric ownership
in modules such as cpu.py, memory.py, or gpu.py.
"""

import json
import os
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

HELPER_ENV = "DASHB_LHM_HELPER_PATH"
LIST_CACHE_TTL_S = 30
READ_CACHE_TTL_S = 0.25
CONNECT_TIMEOUT_S = 60
_NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass(frozen=True)
class Sensor:
    id: str
    name: str
    type: str
    value: Optional[float]
    hardware_name: str
    hardware_type: str


class LhmClient:
    def __init__(self, helper_commands: list[list[str]]):
        self.helper_commands = helper_commands
        self.command_index = 0
        self.process: Optional[subprocess.Popen[str]] = None
        self.lock = threading.Lock()
        self.cached_sensors: list[Sensor] = []
        self.cached_at = 0.0
        self.cached_reads: dict[str, tuple[float, Optional[float]]] = {}
        self.last_error: Optional[str] = None

    def list_sensors(self, force_refresh: bool = False) -> list[Sensor]:
        now = time.monotonic()
        if (
            not force_refresh
            and self.cached_sensors
            and (now - self.cached_at) < LIST_CACHE_TTL_S
        ):
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

    def helper_status(self) -> dict[str, Any]:
        response = self._request({"type": "status"})
        return {
            "elevated": bool(response.get("elevated")),
            "type": response.get("type"),
        }

    def close(self) -> None:
        with self.lock:
            self._stop_process()

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            attempts = 0
            while attempts < len(self.helper_commands):
                attempts += 1
                try:
                    process = self._ensure_process()
                    assert process.stdin is not None
                    assert process.stdout is not None

                    process.stdin.write(json.dumps(payload) + "\n")
                    process.stdin.flush()
                    line = process.stdout.readline()
                    if line:
                        break

                    self._stop_process()
                    self._advance_command()
                    self.last_error = "LibreHardwareMonitor helper stopped"
                except OSError as ex:
                    self._stop_process()
                    self._advance_command()
                    self.last_error = str(ex)
            else:
                raise RuntimeError(
                    self.last_error or "LibreHardwareMonitor helper unavailable"
                )

        response = json.loads(line)
        if response.get("type") == "error":
            raise RuntimeError(response.get("message", "LibreHardwareMonitor error"))
        return response

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self.process and self.process.poll() is None:
            return self.process

        self.process = subprocess.Popen(
            self.helper_commands[self.command_index],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=_NO_WINDOW_FLAGS,
        )
        return self.process

    def _advance_command(self):
        if len(self.helper_commands) > 1:
            self.command_index = (self.command_index + 1) % len(self.helper_commands)

    def _stop_process(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
        self.process = None


class ElevatedLhmClient:
    def __init__(self, helper_path: Path):
        self.helper_path = helper_path
        self.socket: Optional[socket.socket] = None
        self.reader = None
        self.writer = None
        self.lock = threading.Lock()
        self.cached_sensors: list[Sensor] = []
        self.cached_at = 0.0
        self.cached_reads: dict[str, tuple[float, Optional[float]]] = {}
        self.token = secrets.token_urlsafe(32)
        self.port = _free_loopback_port()
        self.last_error: Optional[str] = None

    @property
    def helper_commands(self) -> list[list[str]]:
        return [[str(self.helper_path), "--server", str(self.port), "<token>"]]

    @property
    def command_index(self) -> int:
        return 0

    def list_sensors(self, force_refresh: bool = False) -> list[Sensor]:
        now = time.monotonic()
        if (
            not force_refresh
            and self.cached_sensors
            and (now - self.cached_at) < LIST_CACHE_TTL_S
        ):
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

    def helper_status(self) -> dict[str, Any]:
        response = self._request({"type": "status"})
        return {
            "elevated": bool(response.get("elevated")),
            "type": response.get("type"),
        }

    def close(self) -> None:
        with self.lock:
            self._close_connection()

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self._ensure_connection()
            assert self.writer is not None
            assert self.reader is not None

            payload = {**payload, "token": self.token}
            self.writer.write(json.dumps(payload) + "\n")
            self.writer.flush()
            line = self.reader.readline()
            if not line:
                self._close_connection()
                raise RuntimeError("LibreHardwareMonitor elevated helper stopped")

        response = json.loads(line)
        if response.get("type") == "error":
            raise RuntimeError(response.get("message", "LibreHardwareMonitor error"))
        return response

    def _ensure_connection(self):
        if self.socket is not None:
            return

        self._start_elevated_server()
        deadline = time.monotonic() + CONNECT_TIMEOUT_S
        last_error: Optional[Exception] = None

        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection(("127.0.0.1", self.port), timeout=1)
                self.socket = sock
                self.reader = sock.makefile("r", encoding="utf-8", newline="\n")
                self.writer = sock.makefile("w", encoding="utf-8", newline="\n")
                return
            except OSError as ex:
                last_error = ex
                time.sleep(0.25)

        self.last_error = str(last_error or "timed out waiting for elevated helper")
        raise RuntimeError(self.last_error)

    def _start_elevated_server(self):
        # powershell -Command does not bind trailing argv into $args (that only
        # happens with -File), so $args[0]/$args[1] would be $null and
        # Start-Process would fail silently with no UAC prompt. Embed the
        # already-quoted values directly into the command text instead.
        quoted_helper = _ps_quote(str(self.helper_path))
        quoted_args = ", ".join(
            _ps_quote(arg) for arg in ("--server", str(self.port), self.token)
        )
        ps_command = (
            f"Start-Process -Verb RunAs -WindowStyle Hidden -FilePath {quoted_helper} "
            f"-ArgumentList {quoted_args}"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW_FLAGS,
        )

    def _close_connection(self):
        for file_obj in (self.reader, self.writer):
            try:
                if file_obj is not None:
                    file_obj.close()
            except Exception:
                pass
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
        self.socket = None
        self.reader = None
        self.writer = None


def is_available() -> bool:
    return _get_client() is not None


def status() -> dict[str, Any]:
    client = _get_client()
    if not client:
        return {"available": False, "commands": [], "last_error": "helper not found"}
    helper: dict[str, Any] = {}
    try:
        helper = client.helper_status()
    except Exception as ex:
        helper = {"error": str(ex)}
    return {
        "available": True,
        "commands": client.helper_commands,
        "active_command": client.helper_commands[client.command_index],
        "last_error": client.last_error,
        "helper": helper,
    }


def list_sensors(force_refresh: bool = False) -> list[Sensor]:
    client = _get_client()
    if not client:
        return []
    try:
        return client.list_sensors(force_refresh=force_refresh)
    except Exception:
        return []


def close() -> None:
    """Stop the helper process/connection, if one is running.

    Called on server shutdown so an elevated helper (which cannot be reached
    by killing the server process, since UAC elevation puts it outside that
    process tree) is not left running after the server stops.
    """
    global _client, _client_checked

    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _client_checked = False


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


def _find_helper_commands() -> list[list[str]]:
    if os.name != "nt":
        return []

    env_path = os.getenv(HELPER_ENV)
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return _commands_for_helper_path(path)

    root = Path(__file__).resolve().parents[2]
    candidates = [
        root / "dashb-lhm-helper.exe",
        root / "helpers" / "lhm-helper" / "dashb-lhm-helper.exe",
        root
        / "helpers"
        / "lhm-helper"
        / "bin"
        / "Release"
        / "net8.0"
        / "win-x64"
        / "publish"
        / "dashb-lhm-helper.exe",
        root
        / "helpers"
        / "lhm-helper"
        / "bin"
        / "Release"
        / "net8.0"
        / "win-x64"
        / "publish"
        / "Dashb.LhmHelper.exe",
    ]

    commands: list[list[str]] = []
    for path in candidates:
        if path.is_file():
            commands.extend(_commands_for_helper_path(path))
    return _dedupe_commands(commands)


def _find_elevated_helper_path() -> Optional[Path]:
    if os.name != "nt":
        return None

    env_path = os.getenv(HELPER_ENV)
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file() and path.suffix.lower() == ".exe":
            return path

    root = Path(__file__).resolve().parents[2]
    candidates = [
        root / "dashb-lhm-helper.exe",
        root / "helpers" / "lhm-helper" / "dashb-lhm-helper.exe",
        root
        / "helpers"
        / "lhm-helper"
        / "bin"
        / "Release"
        / "net8.0"
        / "win-x64"
        / "publish"
        / "dashb-lhm-helper.exe",
        root
        / "helpers"
        / "lhm-helper"
        / "bin"
        / "Release"
        / "net8.0"
        / "win-x64"
        / "publish"
        / "Dashb.LhmHelper.exe",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _commands_for_helper_path(path: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    if path.suffix.lower() == ".dll":
        commands.append(["dotnet", str(path)])
        return commands

    commands.append([str(path)])

    dll_path = path.with_suffix(".dll")
    if dll_path.is_file():
        commands.append(["dotnet", str(dll_path)])
    return commands


def _dedupe_commands(commands: list[list[str]]) -> list[list[str]]:
    deduped: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in commands:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(command)
    return deduped


_client: Optional[LhmClient | ElevatedLhmClient] = None
_client_checked = False


def _get_client() -> Optional[LhmClient | ElevatedLhmClient]:
    global _client, _client_checked

    if _client_checked:
        return _client

    _client_checked = True
    elevated_helper_path = _find_elevated_helper_path()
    if elevated_helper_path is not None:
        _client = ElevatedLhmClient(elevated_helper_path)
        return _client

    helper_commands = _find_helper_commands()
    if not helper_commands:
        return None

    _client = LhmClient(helper_commands)
    return _client
