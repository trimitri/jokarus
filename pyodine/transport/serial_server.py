"""Imitate the .websocket_server functionality using RS232 instead of TCP/IP.
"""
import asyncio
import serial
import logging
from typing import Callable

from .decoder import Decoder

LOGGER = logging.getLogger("pyodine.transport.serial_server")


class SerialServer:
    def __init__(self, device: str,
                 received_msg_callback: Callable[[str], None]=None,
                 baudrate: int=19200) -> None:
        self._dev = serial.Serial(port=device, baudrate=baudrate)
        self._rcv_callback = received_msg_callback
        LOGGER.info("Creating instance. Do call the async_init() fcn.")

    async def async_init(self) -> None:
        LOGGER.info("async_init() called. Starting server on dev %s",
                    self._dev.port)
        asyncio.ensure_future(self._serve())

    def publish(self, data: str) -> None:
        LOGGER.debug("Trying to publish: %s", data)
        bytestream = data.encode()
        n_bytes = len(bytestream)
        n_transmitted_bytes = self._dev.write(bytestream)
        if (n_transmitted_bytes == n_bytes):
            LOGGER.debug("Transmitted Message: %s", data)
        else:
            LOGGER.warning("Error transmitting Message.")

    async def _serve(self) -> None:
        collector = Decoder()

        while True:
            if (self._dev.in_waiting > 0):

                # Receive data
                data = self._dev.read(1)
                data += self._dev.read(self._dev.in_waiting)
                collector.feed(data)
                if collector.n_pending() > 0:
                    messages = collector.harvest()
                    for msg in messages:
                        LOGGER.debug("Received message: %s", msg)
                        if callable(self._rcv_callback):
                            self._rcv_callback(msg)
            else:
                await asyncio.sleep(0.1)  # OPTIMIZE: Do this elegantly.
