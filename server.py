import asyncio
from logging import Logger
from threading import Thread
from aiohttp import web


class WebServer:
    def __init__(self, logger: Logger):
        self._logger = logger
        self._server_thread = None
        self._loop = None
        self._server_task = None

    async def http_handle(self, request):
        """Handle the request and return a response."""
        return web.Response(text="Hello, aiohttp!")
    
    async def ws_handle(self, request):
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
                self._logger.error(f"ws connection closed with exception {ws.exception()}")
        return ws

    def start(self, host: str, port: int):
        """Start the aiohttp server in a separate thread."""
        if self._server_thread and self._server_thread.is_alive():
            self._logger.info("Server is already running.")
            return
        
        def run_server():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            app = web.Application()
            app.router.add_get("/", self.http_handle)
            app.router.add_get("/ws", self.ws_handle)

            self._server_task = self._loop.create_task(web._run_app(app, host=host, port=port))

            try:
                self._loop.run_forever()
            finally:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.close()
                
        self._server_thread = Thread(target=run_server, daemon=True)
        self._server_thread.start()
        self._logger.info(f"Server listening on {host}:{port}")

    def stop(self):
        """Stop the aiohttp server."""
        if not (self._loop and self._server_task):
            self._logger.info("Server is not running.")
            return
        self._loop.call_soon_threadsafe(self._server_task.cancel)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._server_thread.join()
        self._logger.info("Server stopped.")

