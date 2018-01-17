"""A service that passes data between a serial connection and a websocket.
"""
import asyncio
import logging
import serial
from ..transport.websocket_server import WebsocketServer
from ..transport.decoder import Decoder
from .. import logger

WS_PORT = 56320
BAUDRATE = 19200
LOGGER = logging.getLogger('pyodine.gui.serial_websocket')


class SerialWebsocket():

    def __init__(self, ws_port: int, serial_device: str) -> None:
        """Do also run async_init()."""
        LOGGER.debug("Creating instance...")
        self._ws_port = ws_port
        self._serial = serial.Serial(port=serial_device, baudrate=BAUDRATE)
        self._ws_server = None  # type: WebsocketServer
        LOGGER.info("Created Serial<->Websocket server. Do call "
                    ".async_init().")

    async def async_init(self):
        self._ws_server = WebsocketServer(port=self._ws_port,
                                          on_msg_receive=self._forward_reply)
        await self._ws_server.async_init()
        LOGGER.info("async_init() called.")

    def start_server(self):
        LOGGER.info("Starting server...")
        asyncio.ensure_future(self._server())

    def _forward_reply(self, message: str):
        bytestream = message.encode()
        n_bytes = len(bytestream)
        n_transmitted_bytes = self._serial.write(bytestream)
        if n_transmitted_bytes == n_bytes:
            LOGGER.info("To RS232: %s", logger.ellipsicate(message))
            LOGGER.debug("To RS232: %s", message)
        else:
            LOGGER.warning("Error transmitting Message.")

    async def _server(self):
        LOGGER.info("Server started.")
        collector = Decoder()
        while True:
            if self._serial.in_waiting > 0:
                data = self._serial.read(1)
                data += self._serial.read(self._serial.in_waiting)
                collector.feed(data)
                if collector.n_pending() > 0:
                    messages = collector.harvest()
                    for msg in messages:
                        LOGGER.info("To WS: %s", logger.ellipsicate(msg))
                        LOGGER.debug("To WS: %s", msg)
                        asyncio.ensure_future(self._ws_server.publish(msg))
            else:
                await asyncio.sleep(0.1)  # OPTIMIZE: Do this elegantly.


async def launch():
    socket = SerialWebsocket(ws_port=WS_PORT, serial_device='/dev/ttyUSB0')
    await socket.async_init()
    socket.start_server()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    asyncio.ensure_future(launch())
    LOOP = asyncio.get_event_loop()
    LOOP.run_forever()
