"""Sends JSON-formatted data as a websocket server.
"""

import asyncio
import websockets
import logging

LOGGER = logging.getLogger("pyodine.transport.json_ws")


class JsonWs:

    def __init__(self, port: int=80):
        self.port = port
        LOGGER.info("Creating JsonWs instance. Do call the async_init() fcn.")

    async def async_init(self):
        asyncio.ensure_future(websockets.serve(self.loopback, 'localhost',
                                               self.port))

    async def send(self, data: str):
        await self.socket.send(data)

    async def loopback(self, socket, path):
        self.socket = socket
        while True:
            LOGGER.debug("Waiting for incoming connection.")
            received_msg = await socket.recv()
            await socket.send(received_msg)
