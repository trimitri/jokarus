"""Imitate the .websocket_server functionality using RS232 instead of TCP/IP.
"""
import asyncio
import serial
import logging
from typing import Callable

LOGGER = logging.getLogger("pyodine.transport.serial_server")


class SerialCollector:
    """Collect messages sent over RS232 until complete JSON string is formed.
    """

    MAX_CHUNKS = 100  # Max. number of messages to be combined into one.

    def __init__(self):
        self.max_n_chunks = 100
        self._rcv_buffer = b''
        self._n_chunks = 0

    def push(self, data: bytes) -> None:
        self._rcv_buffer += data
        self._n_chunks += 1

        if self._n_chunks > self.max_n_chunks:
            LOGGER.warning("Too many chunks in package. Resetting packager.")
            self._reset()

    def reset(self) -> None:
        self._rcv_buffer = b''
        self._n_chunks = 0

    def is_complete(self) -> bool:
        tester = self._rcv_buffer.decode(encoding='utf-8', errors='ignore')
        if tester[-4:] == '}\n\n\n':
            if tester[0] == '{':
                return True
            else:
                LOGGER.warning("Only received tail of a message. "
                               "Resetting collector.")
                self.reset()
        return False

    def harvest(self) -> str:
        """Returns the buffers content and empties it.

        You would usually call is_complete before."""
        result = self._rcv_buffer.decode(encoding='utf-8', errors='ignore')
        self.reset()
        return result


class SerialServer:
    def __init__(self, device: str,
                 received_msg_callback: Callable[[str], None]=None,
                 baudrate: int=19200):
        self._dev = serial.Serial(port=device, baudrate=baudrate)
        self._rcv_callback = received_msg_callback
        LOGGER.info("Creating instance. Do call the async_init() fcn.")

    async def async_init(self) -> None:
        LOGGER.info("async_init() called. Starting server on dev %s",
                    self._dev.port)
        asyncio.ensure_future(self._serve())

    def publish(self, data: str) -> None:
        LOGGER.debug("Trying to publish: %s", data)
        bytestream = (data + '\n\n\n').encode()
        n_bytes = len(bytestream)
        n_transmitted_bytes = self._dev.write(bytestream)
        if (n_transmitted_bytes == n_bytes):
            LOGGER.debug("Transmitted Message: %s", data)
        else:
            LOGGER.warning("Error transmitting Message.")

    async def _serve(self) -> None:
        packager = SerialCollector()

        while True:
            if (self._dev.in_waiting > 0):

                # Receive data
                data = self._dev.read(1)
                data += self._dev.read(self._dev.in_waiting)
                packager.push(data)
                if packager.is_complete():
                    message = packager.harvest()
                    LOGGER.debug("Received message: %s", message)
                    if callable(self._rcv_callback):
                        self._rcv_callback(message)
            else:
                await asyncio.sleep(0.1)  # OPTIMIZE: Do this elegantly.
