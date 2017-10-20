"""A simple websocket server.

It manages a list of subscribers to whom it can publish data.
It can forward received messages to a callback handler.
"""
import asyncio
import logging
from typing import Callable
import websockets

from .. import logger

LOGGER = logging.getLogger("pyodine.transport.websocket_server")

# The websockets' protocol logger dumps every message sent and reiceived when
# set to DEBUG. We thus degrade to INFO.
logging.getLogger('websockets.protocol').setLevel(logging.INFO)


class WebsocketServer:
    """Sets up a listening WebSocket server on given TCP port.

    This class loosely follows the publish/subscribe pattern, while also
    allowing clients to send messages.
    """

    def __init__(self, port: int,
                 on_msg_receive: Callable[[str], None] = None,
                 on_client_connect: Callable[[], None] = None) -> None:
        """Mustn't be run alone. Be sure to await the async_init() coroutine
        afterwards.
        The default port number is inspired by the 56(32)-0 iodine hyperfine
        transition. If you want to use lower port numbers, the OS will probably
        ask you for superuser privileges.
        """
        # pylint: disable=unsubscriptable-object

        self.port = port
        self.subscribers = set()  # type: set
        self._rcv_callback = on_msg_receive
        self._client_connected_callback = on_client_connect
        LOGGER.info("Creating instance. Do call the async_init() fcn.")

    async def async_init(self) -> None:
        """This must be awaited after instantiation."""
        LOGGER.info("async_init() called.")
        LOGGER.info("Starting server on port %d.", self.port)
        asyncio.ensure_future(websockets.serve(
            lambda ws, _: self._register_subscriber(ws), port=self.port))

    async def publish(self, data: str) -> None:
        if self.subscribers:
            # Send data to every subscriber.
            await asyncio.wait([ws.send(data) for ws in self.subscribers])
            LOGGER.debug("Published: %s", logger.ellipsicate(data))
        else:
            LOGGER.debug("Won't publish as there are no subscribers "
                         "connected.")

    async def _create_loopback(
            self, socket: websockets.protocol.WebSocketCommonProtocol) -> None:
        while True:
            LOGGER.debug("Waiting for incoming connection.")
            received_msg = await socket.recv()
            await socket.send(received_msg)

    async def _register_subscriber(
            self, socket: websockets.protocol.WebSocketCommonProtocol) -> None:
        """Register a subscriber.

        This also launches a task that maintains the connection to them.
        """
        self.subscribers.add(socket)
        if callable(self._client_connected_callback):
            self._client_connected_callback()
        LOGGER.info("Subscribed a client. There are %d connected clients.",
                    len(self.subscribers))
        try:
            while True:

                # To keep the server running without having to poll, we wait
                # for commands sent by the client. We don't expect any commands
                # though, and if there is one, we ignore it.
                message = await socket.recv()
                if callable(self._rcv_callback):
                    self._rcv_callback(message)
                LOGGER.debug("Received message: %s", message)
        except (websockets.exceptions.ConnectionClosed, ConnectionError,
                AssertionError):
            self.subscribers.remove(socket)
            LOGGER.info("Unsubscribed a client. %d clients left.",
                        len(self.subscribers))
