import asyncio
import base64
import json
import logging
import logging.config
import os
from pathlib import Path
import uuid
from quart import (
    Quart,
    copy_current_websocket_context,
    request,
    websocket,
    send_file,
)
from hypercorn.config import Config
from hypercorn.asyncio import serve

from probe import Functions
from task import Task

WWWROOT = Path(__file__).parent.parent / "wwwroot"
MAX_CLIENTS = 3

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


# Basic auth check function
def check_basic_auth(auth_header):
    if not username or not password:
        logger.warning("Username or password not set")
        return True  # If username and password are not set, allow access.

    if not auth_header or not auth_header.startswith("Basic "):
        return False

    try:
        decoded_auth = base64.b64decode(auth_header[6:]).decode("utf-8")
        auth_username, auth_password = decoded_auth.split(":", 1)
        return auth_username == username and auth_password == password
    except Exception:
        return False


# Middleware for basic auth
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
async def static_serve(path="index.html"):
    file_path = WWWROOT / path
    if not file_path.exists():
        return "Not found", 404
    if file_path.is_dir():
        file_path /= "index.html"
        if not file_path.exists():
            return "Not found", 404
    return await send_file(file_path)


client_pool = {}


@app.websocket("/ws")
async def ws_handle():
    if not check_basic_auth(websocket.headers.get("Authorization")):
        await websocket.accept()
        await websocket.send(json.dumps({"error": "Unauthorized"}))
        await websocket.close()
        return

    await websocket.accept()

    # limit clients
    if len(client_pool) >= MAX_CLIENTS:
        await websocket.send("Too many clients")
        await websocket.close()
        return

    client_id = str(uuid.uuid4())
    task_pool = []
    client_pool[client_id] = {
        "task_pool": task_pool,
    }
    logger.debug(f"Client {client_id} connected")

    try:
        while True:
            msg = await websocket.receive()
            logger.debug(f"Received: {msg}")
            try:
                msg_json = json.loads(msg)
                """
                Example JSON:
                {
                    "action": "subscribe",
                    "functions": [
                        {
                            "func": "hw.cpu.percent",
                            "interval": 1,
                            "args": [],
                            "kwargs": {
                                "interval": 0.5,
                                "percpu": true
                            }
                        },
                        {
                            "func": "hw.memory.virtual",
                            "interval": 3
                        }
                    ]
                }
                """
            except json.JSONDecodeError:
                await websocket.send("Invalid JSON")
                continue

            if msg_json.get("action") == "subscribe":
                # if client is already subscribed, stop previous tasks
                for task in task_pool:
                    task.stop()
                task_pool.clear()

                for function in msg_json.get("functions", []):
                    func_id = function.get("func", None)
                    # check if function exists
                    if not func_id in Functions:
                        await websocket.send(f"Function {func_id} not found")
                        continue
                    interval = function.get("interval", None)
                    args = function.get("args", [])
                    kwargs = function.get("kwargs", {})

                    # check types and value
                    if interval and (
                        not isinstance(interval, (int, float)) or interval <= 0
                    ):
                        await websocket.send(f"Invalid interval for {func_id}")
                        continue
                    if not isinstance(args, list):
                        await websocket.send(f"Invalid args for {func_id}")
                        continue
                    if not isinstance(kwargs, dict):
                        await websocket.send(f"Invalid kwargs for {func_id}")
                        continue

                    # create tasks
                    async_loop = asyncio.get_running_loop()

                    @copy_current_websocket_context
                    def send_data(result, _func_id=func_id):
                        asyncio.run_coroutine_threadsafe(
                            websocket.send(json.dumps({_func_id: result})),
                            async_loop,
                        )

                    task = Task(
                        Functions[func_id],
                        args=args,
                        kwargs=kwargs,
                        interval=interval,
                        callback=send_data,
                    )
                    task_pool.append(task)
                    task.start()
                logger.debug(
                    f"Client {client_id} subscribed to {msg_json.get('functions', [])}"
                )
                await websocket.send("OK")
    except asyncio.CancelledError as e:
        logger.debug(f"Client {client_id} disconnected")
        for task in task_pool:
            task.stop()
        del client_pool[client_id]
        logger.debug(f"Client {client_id} tasks stopped")
        raise e


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
