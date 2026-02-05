import asyncio
import base64
import json
import logging
import logging.config
import os
import time
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from quart import Quart, request, send_file, websocket
from hypercorn.config import Config
from hypercorn.asyncio import serve
from dashb.probe import info as probe_info
from dashb.scheduler import ProbeRegistry
from dashb.server_constants import (
    PROTOCOL_VERSION,
    MIN_INTERVAL_MS,
    MAX_INTERVAL_MS,
    MAX_SUBSCRIPTIONS,
    MAX_CLIENTS,
    SUPPORTED_METRICS,
)

WWWROOT = Path(__file__).parent.parent / "web-app" / "dist"

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "custom": {
                "format": "%(asctime)s %(filename)s(%(lineno)d) [%(levelname)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "custom"}
        },
        "__main__": {"handlers": ["console"], "level": "DEBUG"},
        "root": {"handlers": ["console"], "level": "DEBUG"},
    }
)

app = Quart(__name__)
logger = logging.getLogger(__name__)

# Auth credentials (can be empty to disable auth)
username = os.getenv("USERNAME", None)
password = os.getenv("PASSWORD", None)


def check_basic_auth(auth_header: Optional[str]) -> bool:
    """Return True if authorized or auth disabled, False otherwise."""
    if not username or not password:
        return True  # Auth disabled

    if not auth_header or not auth_header.startswith("Basic "):
        return False

    try:
        decoded_auth = base64.b64decode(auth_header[6:]).decode("utf-8")
        auth_username, auth_password = decoded_auth.split(":", 1)
        return auth_username == username and auth_password == password
    except Exception:
        return False


@app.before_request
async def requires_auth():
    auth_header = request.headers.get("Authorization")
    if not check_basic_auth(auth_header):
        return (
            "Unauthorized",
            401,
            {"WWW-Authenticate": 'Basic realm="Login Required"'},
        )


@app.route("/")
@app.route("/<path:path>")
async def static_serve(path: str = "index.html"):
    file_path = WWWROOT / path
    if not file_path.exists():
        return "Not found", 404
    if file_path.is_dir():
        file_path /= "index.html"
        if not file_path.exists():
            return "Not found", 404
    return await send_file(file_path)


def now_ts_ms() -> int:
    return int(time.time() * 1000)


client_pool: Dict[str, Dict[str, Any]] = {}
probe_registry = ProbeRegistry()


NETWORK_PATTERN = re.compile(
    r"^network\.\[(?P<iface>[\w\.-]+)\]\.(?P<field>bytes_sent_per_s|bytes_recv_per_s)$|^network\.(?P<field_all>bytes_sent_per_s|bytes_recv_per_s)$"
)
GPU_PATTERN = re.compile(
    r"^gpu\.\[(?P<index>\d+)\]\.(?P<field>utilization|memory_used_bytes|temperature_c)$|^gpu\.(?P<field_all>utilization|memory_used_bytes|temperature_c)$"
)


def validate_metric_name(metric: str) -> bool:
    """Return True if metric is supported (including parameterized forms)."""
    if metric in SUPPORTED_METRICS:
        return True
    if NETWORK_PATTERN.match(metric):
        return True
    if GPU_PATTERN.match(metric):
        return True
    return False


def parse_metric(metric: str) -> Optional[Dict[str, Any]]:
    """Parse metric into base name and params dict."""
    if metric in SUPPORTED_METRICS:
        return {"base": metric, "params": {}}
    m = NETWORK_PATTERN.match(metric)
    if m:
        iface = m.group("iface")
        field = m.group("field") or m.group("field_all")
        return {"base": f"network.{field}", "params": {"iface": iface} if iface else {}}
    m = GPU_PATTERN.match(metric)
    if m:
        idx = m.group("index")
        field = m.group("field") or m.group("field_all")
        return {
            "base": f"gpu.{field}",
            "params": {"index": int(idx)} if idx is not None else {},
        }
    return None


@app.websocket("/ws")
async def ws_handle():
    send_lock = asyncio.Lock()

    async def send_json_local(message: Dict[str, Any]):
        async with send_lock:
            await websocket.send(json.dumps(message))

    async def send_error_local(code: str, message: str, req_id: Optional[str] = None):
        await send_json_local(
            {
                "type": "error",
                "id": req_id,
                "ts_ms": now_ts_ms(),
                "code": code,
                "message": message,
            }
        )

    if not check_basic_auth(websocket.headers.get("Authorization")):
        await websocket.accept()
        await send_error_local("unauthorized", "Unauthorized")
        await websocket.close()
        return

    await websocket.accept()

    if len(client_pool) >= MAX_CLIENTS:
        await send_error_local("too_many_clients", "Too many clients connected")
        await websocket.close()
        return

    client_id = str(uuid.uuid4())
    state = {"subscriptions": set()}
    client_pool[client_id] = state
    logger.debug(f"Client {client_id} connected")

    try:
        async for raw in websocket:
            logger.debug(f"Received: {raw}")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await send_error_local("invalid_json", "Invalid JSON payload")
                continue

            msg_type = msg.get("type")
            req_id = msg.get("id")

            if msg_type == "hello":
                proto_min = int(msg.get("proto_min", PROTOCOL_VERSION))
                proto_max = int(msg.get("proto_max", PROTOCOL_VERSION))
                if proto_min > PROTOCOL_VERSION or proto_max < PROTOCOL_VERSION:
                    await send_error_local(
                        "unsupported_proto", "Protocol version not supported", req_id
                    )
                    continue
                await send_json_local(
                    {
                        "type": "welcome",
                        "id": req_id,
                        "ts_ms": now_ts_ms(),
                        "proto": PROTOCOL_VERSION,
                        "server": {"name": "dashb", "version": "0.1.0"},
                        "capabilities": {
                            "auth": "basic" if username and password else "none",
                            "tls": False,
                            "max_subscriptions": MAX_SUBSCRIPTIONS,
                            "min_interval_ms": MIN_INTERVAL_MS,
                            "max_interval_ms": MAX_INTERVAL_MS,
                        },
                    }
                )
                await send_json_local(
                    probe_info.build_server_info_payload(SUPPORTED_METRICS)
                )
                continue

            if msg_type == "ping":
                await send_json_local(
                    {"type": "pong", "id": req_id, "ts_ms": now_ts_ms()}
                )
                continue

            if msg_type == "subscribe":
                subs = msg.get("subscriptions", [])
                if not isinstance(subs, list):
                    await send_error_local(
                        "invalid_request", "subscriptions must be a list", req_id
                    )
                    continue

                accepted: List[Dict[str, Any]] = []
                rejected: List[Dict[str, str]] = []

                if len(subs) > MAX_SUBSCRIPTIONS:
                    await send_error_local(
                        "too_many_subscriptions",
                        "subscription count exceeds limit",
                        req_id,
                    )
                    continue

                for sub in subs:
                    metric = sub.get("metric")
                    interval = sub.get("interval_ms", MIN_INTERVAL_MS)
                    parsed = parse_metric(metric)
                    if not parsed:
                        rejected.append({"metric": metric, "reason": "not_available"})
                        continue
                    if not isinstance(interval, (int, float)) or interval <= 0:
                        rejected.append(
                            {"metric": metric, "reason": "invalid_interval"}
                        )
                        continue
                    clamped = max(MIN_INTERVAL_MS, min(int(interval), MAX_INTERVAL_MS))
                    accepted.append({"metric": metric, "interval_ms": clamped})
                    state["subscriptions"].add(metric)
                    probe_registry.subscribe(
                        metric=parsed["base"],
                        params=parsed["params"],
                        interval_ms=clamped,
                        client_id=client_id,
                        send=send_json_local,
                    )

                await send_json_local(
                    {
                        "type": "subscribed",
                        "id": req_id,
                        "ts_ms": now_ts_ms(),
                        "accepted": accepted,
                        "rejected": rejected,
                    }
                )
                continue

            if msg_type == "unsubscribe":
                metrics = msg.get("metrics", [])
                if not isinstance(metrics, list):
                    await send_error_local(
                        "invalid_request", "metrics must be a list", req_id
                    )
                    continue

                removed: List[str] = []
                for metric in metrics:
                    parsed = parse_metric(metric)
                    if not parsed:
                        continue
                    if metric in state["subscriptions"]:
                        state["subscriptions"].remove(metric)
                    probe_registry.unsubscribe(
                        metric=parsed["base"],
                        params=parsed["params"],
                        client_id=client_id,
                    )
                    removed.append(metric)

                await send_json_local(
                    {
                        "type": "unsubscribed",
                        "id": req_id,
                        "ts_ms": now_ts_ms(),
                        "removed": removed,
                    }
                )
                continue

            await send_error_local(
                "unknown_type", f"Unknown message type: {msg_type}", req_id
            )
    finally:
        probe_registry.unsubscribe_client(client_id)
        client_pool.pop(client_id, None)
        logger.debug(f"Client {client_id} disconnected")


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8080))

    # basic auth
    username = os.getenv("USERNAME", None)
    password = os.getenv("PASSWORD", None)

    logger.info(f"Static files root: {WWWROOT}")
    logger.info(f"Starting server...")

    config = Config()
    config.accesslog = logger
    config.access_log_format = '%(h)s "%(r)s" %(s)s %(b)s'
    config.errorlog = logger
    config.bind = [f"{host}:{port}"]

    # Handle graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(serve(app, config))
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
    finally:
        # Clean up tasks
        tasks = asyncio.all_tasks(loop=loop)
        for task in tasks:
            task.cancel()

        # Windows-specific proactor cleanup
        if hasattr(loop, "_proactor"):
            loop._proactor.close()
        loop.close()
