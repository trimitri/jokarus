"""The Interfaces class manages external communication.

It may set up downlinks to clients, regularly send data to them and deal with
control requests they might transmit.
"""
import asyncio
import logging
from ..transport import websocket_server
from ..controller.subsystems import Subsystems

LOGGER = logging.getLogger("pyodine.controller.interfaces")


class Interfaces:

    def __init__(self):
        self._ws = None

    async def init_async(self):
        self._ws = websocket_server.WebsocketServer(port=56320)
        await self._ws.async_init()

    def start_publishing(self, subsystem_controller: Subsystems,
                         interval: float=1.0):

        async def serve_data():
            while True:
                data = subsystem_controller.get_full_set_of_readings()
                await self._ws.publish(data)
                await asyncio.sleep(interval)

        asyncio.ensure_future(serve_data())
