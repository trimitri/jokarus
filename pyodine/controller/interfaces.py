"""The Interfaces class manages external communication.

It may set up downlinks to clients, regularly send data to them and deal with
control requests they might transmit.
"""
import asyncio
import logging
from ..transport.websocket_server import WebsocketServer
from ..transport.serial_server import SerialServer
from ..controller.subsystems import Subsystems

LOGGER = logging.getLogger("pyodine.controller.interfaces")


class Interfaces:

    def __init__(self, start_ws_server: bool=True,
                 start_serial_server: bool=False):
        self._use_ws = start_ws_server
        self._use_rs232 = start_serial_server
        self._ws = None  # type: WebsocketServer
        self._rs232 = None  # type: SerialServer

    async def init_async(self):
        if self._use_ws:
            self._ws = WebsocketServer()
            await self._ws.async_init()
        if self._use_rs232:
            self._rs232 = SerialServer(device='/dev/ttyUSB0')
            await self._rs232.async_init()

    def start_publishing(self, subsystem_controller: Subsystems,
                         interval: float=1.0):

        async def serve_data():
            while True:
                data = subsystem_controller.get_full_set_of_readings()
                if self._use_rs232:
                    self._rs232.publish(data)
                if self._use_ws:
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
                data = '{"some_voltage": ["'
                data += str(value) + '", ' + str(time.time()) + ']}'
                await self._ws.publish(data)
                await asyncio.sleep(.5)

        asyncio.ensure_future(serve_data())
