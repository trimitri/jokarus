"""A service that passes data between a serial connection and a websocket.
"""
import asyncio
import serial
import logging
from ..transport.websocket_server import WebsocketServer
from ..transport.decoder import Decoder

LOGGER = logging.getLogger('pyodine.gui.serial_websocket')


class SerialWebsocket():

    def __init__(self, ws_port: int, serial_device: str) -> None:
        """Do also run async_init()."""
        LOGGER.debug("Creating instance...")
        self._ws_port = ws_port
        self._serial = serial.Serial(port=serial_device, baudrate=19200)
        self._ws_server = None  # type: WebsocketServer
        LOGGER.debug("Created instance.")

    async def async_init(self):
        self._ws_server = WebsocketServer(
                port=self._ws_port, received_msg_callback=self._forward_reply)
        await self._ws_server.async_init()

    def start_server(self):
        LOGGER.info("Starting server.")
        asyncio.ensure_future(self._server())

    def _forward_reply(self, message: str):
        bytestream = message.encode()
        n_bytes = len(bytestream)
        n_transmitted_bytes = self._serial.write(bytestream)
        if (n_transmitted_bytes == n_bytes):
            LOGGER.debug("Transmitted Message: %s ... %s",
                         message[:11], message[-11:])
        else:
            LOGGER.warning("Error transmitting Message.")

    async def _server(self):
        collector = Decoder()
        while True:
            if (self._serial.in_waiting > 0):
                data = self._serial.read(1)
                data += self._serial.read(self._serial.in_waiting)
                collector.feed(data)
                if collector.n_pending() > 0:
                    messages = collector.harvest()
                    for msg in messages:
                        LOGGER.debug("Forwarding message: %s ... %s",
                                     msg[:11], msg[-10:])
                        asyncio.ensure_future(self._ws_server.publish(msg))
            else:
                await asyncio.sleep(0.1)  # OPTIMIZE: Do this elegantly.


async def launch():
    ws = SerialWebsocket(ws_port=56321, serial_device='/dev/ttyUSB0')
    await ws.async_init()
    ws.start_server()

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    asyncio.ensure_future(launch())
    loop = asyncio.get_event_loop()
    loop.run_forever()
