import asyncio
import logging
import os
from pathlib import Path
from aiohttp import web

WWWROOT = Path("static")

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s :: %(levelname)s :: %(message)s"
)
logger = logging.getLogger(__name__)


@web.middleware
async def static_serve(request, handler):
    if request.path.startswith("/ws"):
        return await handler(request)

    relative_file_path = Path(request.path).relative_to("/")  # remove root '/'
    file_path = WWWROOT / relative_file_path  # rebase into static dir
    if not file_path.exists():
        return web.HTTPNotFound()
    if file_path.is_dir():
        file_path /= "index.html"
        if not file_path.exists():
            return web.HTTPNotFound()
    return web.FileResponse(file_path)


async def ws_handle(request):
    """Handle the WebSocket connection."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            if msg.data == "close":
                await ws.close()
            else:
                await ws.send_str(f"Received: {msg.data}")
        elif msg.type == web.WSMsgType.ERROR:
            logger.error(f"ws connection closed with exception {ws.exception()}")
    return ws


if __name__ == "__main__":
    # print all environment vars
    # env_vars = "\n".join([f"{k}={v}" for k, v in os.environ.items()])
    # logger.debug(f"Environment variables:\n{env_vars}")
    # read config from environment vars
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8080))

    app = web.Application(middlewares=[static_serve])
    app.router.add_get("/ws", ws_handle)
    logger.info(f"Starting server at {host}:{port}")
    web.run_app(app, host=host, port=port)
