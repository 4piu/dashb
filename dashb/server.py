import asyncio
import json
import logging
import logging.config
import os
from pathlib import Path
from quart import Quart, websocket, send_file, jsonify
from hypercorn.config import Config
from hypercorn.asyncio import serve

WWWROOT = Path(__file__).parent / "wwwroot"

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


@app.route("/")
@app.route("/<path:path>")
async def static_serve(path="index.html"):
    NOT_FOUND_ERROR = {"error": "Not Found"}
    file_path = WWWROOT / path
    if not file_path.exists():
        return jsonify(NOT_FOUND_ERROR), 404
    if file_path.is_dir():
        file_path /= "index.html"
        if not file_path.exists():
            return jsonify(NOT_FOUND_ERROR), 404
    return await send_file(file_path)


@app.websocket("/ws")
async def ws_handle():
    while True:
        msg = await websocket.receive()
        if msg == "close":
            await websocket.close()
            break
        else:
            try:
                msg_json = json.loads(msg)
                """
                Example JSON:
                {
                    "action": "subscribe",
                    "functions": [
                        "hw.cpu.percent": {
                            "interval": 1000,
                            "kwargs": {
                                "percpu": false
                            }
                        },
                        "hw.memory.virtual": {
                            "interval": 3000
                        }
                    ]
                }
                """
                logger.debug(f"Received: {msg_json}")
                if msg_json.get("action") == "subscribe":
                    await websocket.send("OK")
            except json.JSONDecodeError:
                await websocket.send("Invalid JSON")
                continue


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8080))

    logger.info(f"Starting server...")

    config = Config()
    config.accesslog = logger
    config.access_log_format = '%(h)s "%(r)s" %(s)s %(b)s'
    config.errorlog = logger
    config.bind = [f"{host}:{port}"]
    asyncio.run(serve(app, config))
