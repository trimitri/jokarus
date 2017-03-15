"""A simple websocket server.
"""

import asyncio
import websockets
import logging

LOGGER = logging.getLogger("pyodine.transport.websocket_server")


class WebsocketServer:

    def __init__(self, port: int=56320):
        """Mustn't be run alone. Be sure to await the async_init() coroutine
        afterwards.
        The default port number is inspired by the 56(32)-0 iodine hyperfine
        transition. If you want to use lower port numbers, the OS will probably
        ask you for superuser privileges.
        """
        self.port = port
        self.subscribers = set()
        LOGGER.info("Creating JsonWs instance. Do call the async_init() fcn.")

    async def async_init(self) -> None:
        asyncio.ensure_future(websockets.serve(self._register_subscriber,
                                               'localhost', self.port))

    async def publish(self, data: str) -> None:
        LOGGER.debug("Trying to publish: " + data)
        if len(self.subscribers) > 0:

            # Send data to every subscriber.
            await asyncio.wait([ws.send(data) for ws in self.subscribers])
        else:
            LOGGER.debug("Won't publish as there are "
                         "no subscribers connected.")

    async def _create_loopback(self, socket, path):
        while True:
            LOGGER.debug("Waiting for incoming connection.")
            received_msg = await socket.recv()
            await socket.send(received_msg)

    async def _register_subscriber(self, socket, path):
        self.subscribers.add(socket)
        LOGGER.info("Subscribed client. %d connected clients.",
                    len(self.subscribers))
        try:
            while True:

                # To keep the server running without having to poll, we wait
                # for commands sent by the client. We don't expect any commands
                # though, and if there is one, we ignore it.
                await socket.recv()
        except (websockets.exceptions.ConnectionClosed, ConnectionError):
            self.subscribers.remove(socket)
            LOGGER.info("Unsubscribed client. %d clients left.",
                        len(self.subscribers))
