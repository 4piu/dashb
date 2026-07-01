import asyncio
import base64
import hashlib
import hmac
import json
import logging
import logging.config
import math
import os
import time
import uuid
from typing import Any, Dict, Optional, Set

from quart import Quart, jsonify, request, send_file, websocket
from hypercorn.config import Config
from hypercorn.asyncio import serve
from dashb.probe import build_metric_catalog, lhm
from dashb.scheduler import ProbeRegistry
from dashb.theme import (
    default_webroot,
    default_theme_root,
    discover_themes,
    find_theme,
    resolve_theme_asset,
    resolve_webroot_asset,
)
from dashb.server_constants import (
    PROTOCOL_VERSION,
    MIN_INTERVAL_MS,
    MAX_INTERVAL_MS,
    MAX_SUBSCRIPTIONS,
    MAX_CLIENTS,
)

WEBROOT = default_webroot()
THEME_ROOT = default_theme_root(WEBROOT)

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
AUTH_COOKIE_NAME = "dashb_auth"


def auth_enabled() -> bool:
    return bool(username and password)


def check_basic_auth(auth_header: Optional[str]) -> bool:
    """Return True if authorized or auth disabled, False otherwise."""
    if not auth_enabled():
        return True  # Auth disabled

    if not auth_header or not auth_header.startswith("Basic "):
        return False

    try:
        decoded_auth = base64.b64decode(auth_header[6:]).decode("utf-8")
        auth_username, auth_password = decoded_auth.split(":", 1)
        return auth_username == username and auth_password == password
    except Exception:
        return False


def auth_cookie_value() -> str:
    assert username is not None
    assert password is not None
    return hmac.new(
        password.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def check_auth_cookie(cookie_value: Optional[str]) -> bool:
    if not auth_enabled():
        return True
    if not cookie_value:
        return False
    return hmac.compare_digest(cookie_value, auth_cookie_value())


def parse_cookie_header(cookie_header: Optional[str]) -> dict[str, str]:
    if not cookie_header:
        return {}
    cookies = {}
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


@app.before_request
async def requires_auth():
    if not auth_enabled():
        return None
    if check_auth_cookie(request.cookies.get(AUTH_COOKIE_NAME)):
        return None
    if not check_basic_auth(request.headers.get("Authorization")):
        return (
            "Unauthorized",
            401,
            {"WWW-Authenticate": 'Basic realm="Login Required"'},
        )
    return None


@app.after_request
async def set_auth_cookie(response):
    if auth_enabled() and check_basic_auth(request.headers.get("Authorization")):
        response.set_cookie(
            AUTH_COOKIE_NAME,
            auth_cookie_value(),
            httponly=True,
            samesite="Lax",
            secure=request.is_secure,
            max_age=60 * 60 * 24 * 30,
        )
    return response


@app.route("/")
async def theme_picker():
    index = resolve_webroot_asset(WEBROOT, "index.html")
    if not index:
        return "Theme selector not found. Build the web app first.", 404
    return await send_file(index)


@app.route("/api/themes")
async def api_themes():
    return jsonify([theme.to_api_dict() for theme in discover_themes(THEME_ROOT)])


@app.route("/theme/<theme_id>/")
async def theme_index(theme_id: str):
    theme = find_theme(theme_id, THEME_ROOT)
    if not theme:
        return "Theme not found", 404
    entry = resolve_theme_asset(theme, theme.entry)
    if not entry:
        return "Theme entry not found", 404
    return await send_file(entry)


@app.route("/theme/<theme_id>/<path:asset_path>")
async def theme_asset(theme_id: str, asset_path: str):
    theme = find_theme(theme_id, THEME_ROOT)
    if not theme:
        return "Theme not found", 404
    asset = resolve_theme_asset(theme, asset_path)
    if not asset:
        return "Not found", 404
    return await send_file(asset)


@app.route("/<path:asset_path>")
async def webroot_asset(asset_path: str):
    asset = resolve_webroot_asset(WEBROOT, asset_path)
    if not asset:
        return "Not found", 404
    return await send_file(asset)


def now_ts_ms() -> int:
    return int(time.time() * 1000)


def to_json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [to_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: to_json_safe(item) for key, item in value.items()}
    return value


active_client_ids: Set[str] = set()
metric_catalog = build_metric_catalog()
probe_registry = ProbeRegistry(metric_catalog)


class WebSocketSession:
    def __init__(self):
        self.client_id = str(uuid.uuid4())
        self.send_lock = asyncio.Lock()
        self.subscriptions: set[str] = set()
        # `quart.websocket` is a context-local proxy (werkzeug LocalProxy).
        # ProbeTask._run() is a single shared asyncio.Task per metric that
        # only gets created for the *first* subscriber, so its captured
        # context belongs to whichever client's request triggered that
        # creation. If a later client's send_json() ran there and used the
        # ambient `websocket` proxy, it would resolve to that first client's
        # connection instead of its own. Capture the concrete object now,
        # while still in this session's own request context, so sends always
        # target the right socket regardless of which task calls send_json().
        self._ws = websocket._get_current_object()

    async def run(self):
        active_client_ids.add(self.client_id)
        logger.debug(f"Client {self.client_id} connected")
        try:
            while True:
                await self.handle_raw_message(await websocket.receive())
        except asyncio.CancelledError:
            logger.debug(f"Client {self.client_id} websocket task cancelled")
            raise
        except Exception:
            logger.exception(f"Client {self.client_id} websocket session failed")
        finally:
            probe_registry.unsubscribe_client(self.client_id)
            active_client_ids.discard(self.client_id)
            logger.debug(f"Client {self.client_id} disconnected")

    async def send_json(self, message: Dict[str, Any]):
        async with self.send_lock:
            await self._ws.send(json.dumps(to_json_safe(message), allow_nan=False))

    async def send_error(
        self, code: str, message: str, req_id: Optional[str] = None
    ):
        await self.send_json(
            {
                "type": "error",
                "id": req_id,
                "ts_ms": now_ts_ms(),
                "code": code,
                "message": message,
            }
        )

    async def handle_raw_message(self, raw: str):
        logger.debug(f"Received: {raw}")
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await self.send_error("invalid_json", "Invalid JSON payload")
            return

        handlers = {
            "hello": self.handle_hello,
            "ping": self.handle_ping,
            "query": self.handle_query,
            "subscribe": self.handle_subscribe,
            "unsubscribe": self.handle_unsubscribe,
        }
        handler = handlers.get(message.get("type"))
        if not handler:
            await self.send_error(
                "unknown_type",
                f"Unknown message type: {message.get('type')}",
                message.get("id"),
            )
            return
        await handler(message)

    async def handle_hello(self, message: Dict[str, Any]):
        req_id = message.get("id")
        proto_min = int(message.get("proto_min", PROTOCOL_VERSION))
        proto_max = int(message.get("proto_max", PROTOCOL_VERSION))
        logger.debug(
            f"Client {self.client_id} hello proto_min={proto_min} proto_max={proto_max}"
        )
        if proto_min > PROTOCOL_VERSION or proto_max < PROTOCOL_VERSION:
            await self.send_error(
                "unsupported_proto", "Protocol version not supported", req_id
            )
            return

        await self.send_json(
            {
                "type": "welcome",
                "id": req_id,
                "ts_ms": now_ts_ms(),
                "proto": PROTOCOL_VERSION,
                "server": {"name": "dashb", "version": "0.1.0"},
                "capabilities": {
                    "auth": "basic" if username and password else "none",
                    "tls": False,
                    "query": True,
                    "max_subscriptions": MAX_SUBSCRIPTIONS,
                    "min_interval_ms": MIN_INTERVAL_MS,
                    "max_interval_ms": MAX_INTERVAL_MS,
                },
            }
        )
        await self.send_json(
            {
                "type": "server_info",
                "ts_ms": now_ts_ms(),
                "metrics": metric_catalog.as_payload(),
            }
        )
        logger.debug(
            f"Client {self.client_id} server_info metrics={len(metric_catalog.metrics)}"
        )

    async def handle_ping(self, message: Dict[str, Any]):
        await self.send_json(
            {"type": "pong", "id": message.get("id"), "ts_ms": now_ts_ms()}
        )

    async def handle_query(self, message: Dict[str, Any]):
        req_id = message.get("id")
        metrics = message.get("metrics", [])
        if not isinstance(metrics, list):
            await self.send_error("invalid_request", "metrics must be a list", req_id)
            return

        values = []
        rejected = []
        for metric in metrics:
            if not metric_catalog.has(metric):
                rejected.append({"metric": metric, "reason": "not_available"})
                continue
            try:
                value = await metric_catalog.collect(metric)
            except Exception as exc:
                logger.debug(f"Query failed for {metric}: {exc}")
                rejected.append({"metric": metric, "reason": "collection_failed"})
                continue
            values.append(
                {
                    "metric": metric,
                    "value": value,
                    "unit": metric_catalog.unit(metric),
                }
            )

        await self.send_json(
            {
                "type": "query_result",
                "id": req_id,
                "ts_ms": now_ts_ms(),
                "values": values,
                "rejected": rejected,
            }
        )
        logger.debug(
            f"Client {self.client_id} query_result values={len(values)} rejected={len(rejected)}"
        )

    async def handle_subscribe(self, message: Dict[str, Any]):
        req_id = message.get("id")
        subscriptions = message.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            await self.send_error(
                "invalid_request", "subscriptions must be a list", req_id
            )
            return
        if len(subscriptions) > MAX_SUBSCRIPTIONS:
            await self.send_error(
                "too_many_subscriptions",
                "subscription count exceeds limit",
                req_id,
            )
            return

        accepted = []
        rejected = []
        for subscription in subscriptions:
            metric = subscription.get("metric")
            interval = subscription.get("interval_ms", MIN_INTERVAL_MS)
            if not metric_catalog.has(metric):
                rejected.append({"metric": metric, "reason": "not_available"})
                continue
            if not metric_catalog.can_subscribe(metric):
                rejected.append({"metric": metric, "reason": "not_subscribable"})
                continue
            if not isinstance(interval, (int, float)) or interval <= 0:
                rejected.append({"metric": metric, "reason": "invalid_interval"})
                continue

            clamped = max(MIN_INTERVAL_MS, min(int(interval), MAX_INTERVAL_MS))
            accepted.append({"metric": metric, "interval_ms": clamped})
            self.subscriptions.add(metric)
            probe_registry.subscribe(
                metric=metric,
                interval_ms=clamped,
                client_id=self.client_id,
                send=self.send_json,
            )

        await self.send_json(
            {
                "type": "subscribed",
                "id": req_id,
                "ts_ms": now_ts_ms(),
                "accepted": accepted,
                "rejected": rejected,
            }
        )
        logger.debug(
            f"Client {self.client_id} subscribed accepted={len(accepted)} rejected={len(rejected)}"
        )

    async def handle_unsubscribe(self, message: Dict[str, Any]):
        req_id = message.get("id")
        metrics = message.get("metrics", [])
        if not isinstance(metrics, list):
            await self.send_error("invalid_request", "metrics must be a list", req_id)
            return

        removed = []
        for metric in metrics:
            if metric not in self.subscriptions:
                continue
            self.subscriptions.remove(metric)
            probe_registry.unsubscribe(metric=metric, client_id=self.client_id)
            removed.append(metric)

        await self.send_json(
            {
                "type": "unsubscribed",
                "id": req_id,
                "ts_ms": now_ts_ms(),
                "removed": removed,
            }
        )


@app.websocket("/ws")
async def ws_handle():
    await websocket.accept()
    session = WebSocketSession()

    cookies = parse_cookie_header(websocket.headers.get("Cookie"))
    if not (
        check_basic_auth(websocket.headers.get("Authorization"))
        or check_auth_cookie(cookies.get(AUTH_COOKIE_NAME))
    ):
        await session.send_error("unauthorized", "Unauthorized")
        await websocket.close(1008, "Unauthorized")
        return

    if len(active_client_ids) >= MAX_CLIENTS:
        await session.send_error("too_many_clients", "Too many clients connected")
        await websocket.close(1013, "Too many clients connected")
        return

    await session.run()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8080))

    # basic auth
    username = os.getenv("USERNAME", None)
    password = os.getenv("PASSWORD", None)

    logger.info(f"Web root: {WEBROOT}")
    logger.info(f"Theme root: {THEME_ROOT}")
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
        # Stop probe sampling tasks before the generic task-cancel sweep below,
        # since this also clears ProbeRegistry's bookkeeping (subscribers,
        # tasks dict) rather than just cancelling the asyncio.Task objects.
        probe_registry.shutdown()

        # Clean up tasks
        tasks = asyncio.all_tasks(loop=loop)
        for task in tasks:
            task.cancel()

        # Stop the LHM helper process/connection. An elevated helper runs
        # outside this process's tree (UAC elevation puts it under a
        # separate parent), so an explicit close is needed for a
        # deterministic, prompt shutdown on graceful stops.
        lhm.close()

        # Windows-specific proactor cleanup
        if hasattr(loop, "_proactor"):
            loop._proactor.close()
        loop.close()
