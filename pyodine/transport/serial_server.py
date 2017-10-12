"""Imitate the .websocket_server functionality using RS232 instead of TCP/IP.
"""
import logging
from typing import Callable

import serial

from .decoder import Decoder
from .. import logger

LOGGER = logging.getLogger("serial_server")


class SerialServer:
    """A server that listens on and sends through a serial port."""

    def __init__(self, device: str,
                 received_msg_callback: Callable[[str], None] = None,
                 baudrate: int = 19200) -> None:
        try:
            self._dev = serial.Serial(port=device, baudrate=baudrate)
        except (FileNotFoundError, serial.SerialException):
            LOGGER.error("Failed to open serial connection for serving.")
            raise ConnectionError("Starting serial connection for server "
                                  "failed.")
        self._rcv_callback = received_msg_callback
        LOGGER.info("Creating instance. Do call the async_init() fcn.")

    def publish(self, data: str) -> None:
        """Send the given string over the serial interface."""
        bytestream = data.encode()
        n_bytes = len(bytestream)
        n_transmitted_bytes = self._dev.write(bytestream)
        if n_transmitted_bytes == n_bytes:
            LOGGER.debug("Sent message: %s", logger.ellipsicate(data))
        else:
            LOGGER.warning("Error transmitting Message: %s",
                           logger.ellipsicate(data))

    def serve(self) -> None:
        """Start listening. This blocks indefinitely. Use threading."""
        LOGGER.info("Listening on port %s", self._dev.port)
        collector = Decoder()
        while True:
            # Receive data. This will block until some data is received.
            # This will avoid busy waiting.
            data = self._dev.read(1)
            data += self._dev.read(self._dev.in_waiting)
            collector.feed(data)
            if collector.n_pending() > 0:
                messages = collector.harvest()
                for msg in messages:
                    LOGGER.debug("Received message: %s", msg)
                    if callable(self._rcv_callback):
                        self._rcv_callback(msg)
