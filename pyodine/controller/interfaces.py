"""The Interfaces class manages external communication.

It may set up downlinks to clients, regularly send data to them and deal with
control requests they might transmit.
"""
import asyncio
import logging
from typing import Callable
from ..transport.websocket_server import WebsocketServer
from ..transport.serial_server import SerialServer
from ..transport import texus_relay
from ..transport import packer
from ..controller.subsystems import Subsystems

LOGGER = logging.getLogger("pyodine.controller.interfaces")


class Interfaces:

    def __init__(self, subsystem_controller: Subsystems,
                 start_ws_server: bool=True,
                 start_serial_server: bool=False,
                 on_receive: Callable[[str], None]=None):
        self._use_ws = start_ws_server
        self._use_rs232 = start_serial_server
        self._ws = None  # type: WebsocketServer
        self._rs232 = None  # type: SerialServer
        self._texus = None  # type: texus_relay.TexusRelay
        self._subs = subsystem_controller
        self._rcv_callback = on_receive

    async def init_async(self):

        # Websocket server
        if self._use_ws:
            self._ws = WebsocketServer(received_msg_callback=self._parse_reply)
            await self._ws.async_init()

        # Serial server
        if self._use_rs232:
            self._rs232 = SerialServer(device='/dev/ttyUSB0',
                                       received_msg_callback=self._parse_reply)
            await self._rs232.async_init()

        # TEXUS flags relay
        self._texus = texus_relay.TexusRelay()

    def start_publishing_regularly(self, readings_interval: float=1,
                                   flags_interval: float=10):

        async def serve_readings():
            while True:
                await self.publish_readings()
                await asyncio.sleep(readings_interval)

        async def serve_flags():
            while True:
                await self.publish_flags()
                await asyncio.sleep(flags_interval)

        asyncio.ensure_future(serve_readings())
        asyncio.ensure_future(serve_flags())

    async def publish_readings(self) -> None:
        data = self._subs.get_full_set_of_readings()
        await self._publish_message(packer.create_message(data, 'readings'))

    async def publish_flags(self) -> None:
        data = self._texus.get_full_set()
        await self._publish_message(packer.create_message(data, 'texus'))

    def set_flag(self, entity_id: str, value: bool) -> None:
        if entity_id in texus_relay.LEGAL_SETTERS and type(value) is bool:
            setattr(self._texus, entity_id, value)

    def on_receive(self, callback: Callable[[str], None]) -> None:
        self._rcv_callback = callback

    async def _publish_message(self, message: str) -> None:
        if self._use_rs232:
            self._rs232.publish(message)
        if self._use_ws:
            await self._ws.publish(message)

    def _parse_reply(self, message: str) -> None:
        if callable(self._rcv_callback):
            self._rcv_callback(message)
