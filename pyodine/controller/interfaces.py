"""The Interfaces class manages external communication.

It may set up downlinks to clients, regularly send data to them and deal with
control requests they might transmit.
"""
import asyncio
import logging
from ..transport import websocket_server
from ..controller import subsystems

LOGGER = logging.getLogger("pyodine.controller.interfaces")


class Interfaces:

    def __init__(self):
        self._ws = None

    async def init_async(self):
        self._ws = websocket_server.WebsocketServer()
        await self._ws.async_init()

    def start_publishing(self, subsystem_controller: subsystems.Subsystems,
                         interval: float=1.0):

        async def serve_data():
            while True:
                data = subsystem_controller.get_full_set_of_readings()
                await self._ws.publish(data)
                await asyncio.sleep(interval)

        asyncio.ensure_future(serve_data())

    def start_dummy_publishing(self):
        import random
        import time

        async def serve_data():
            value = 0
            while True:
                value += random.random() - .5
                data = '{"some_voltage": ["' + str(value) + '", ' + str(time.time()) + ']}'
                await self._ws.publish(data)
                await asyncio.sleep(.5)

        asyncio.ensure_future(serve_data())
