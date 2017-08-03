"""The Interfaces class manages external communication.

It may set up downlinks to clients, regularly send data to them and deal with
control requests they might transmit.
"""
# System Libraries
import asyncio
import logging
import time
from typing import Callable

# Own Stuff
from ..transport.websocket_server import WebsocketServer
from ..transport.serial_server import SerialServer
from ..transport import texus_relay
from ..transport import packer
from ..controller.subsystems import Subsystems

LOGGER = logging.getLogger("pyodine.controller.interfaces")
# LOGGER.setLevel(logging.DEBUG)
WS_PORT = 56320


class Interfaces:
    """This is how to talk to Pyodine.

    It sets up the services and reiceives instructions.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, subsystem_controller: Subsystems,
                 start_ws_server: bool = True,
                 start_serial_server: bool = False,
                 on_receive: Callable[[str], None] = None) -> None:
        # pylint: disable=unsubscriptable-object
        # Callable is in subscriptable, pylint fails to detect that.

        self._use_ws = start_ws_server
        self._use_rs232 = start_serial_server
        self._ws = None  # type: WebsocketServer
        self._rs232 = None  # type: SerialServer
        self._texus = None  # type: texus_relay.TexusRelay
        self._subs = subsystem_controller
        self._rcv_callback = on_receive

        # Keep track of when we sent the prev. publication to the clients.
        self._readings_published_at = None  # type: float

    async def init_async(self) -> None:
        """The class instance is ready to use only after I was awaited."""

        # Websocket server
        if self._use_ws:
            self._ws = WebsocketServer(
                port=WS_PORT, on_msg_receive=self._parse_reply,
                on_client_connect=self._on_client_connect)
            await self._ws.async_init()

        # Serial server
        if self._use_rs232:
            try:
                self._rs232 = SerialServer(
                    device='/dev/ttyUSB1',
                    received_msg_callback=self._parse_reply)
            except ConnectionError:
                LOGGER.error("Couldn't open serial port for serving. "
                             "Switching off serial server.")
                self._use_rs232 = False
            else:
                self._rs232.start_serving()

        # TEXUS flags relay
        LOGGER.info("Starting TEXUS relay...")
        try:
            self._texus = texus_relay.TexusRelay(port_1='/dev/ttyUSB0',
                                                 port_2='/dev/ttyUSB3')
        except ConnectionError:
            LOGGER.error("Error establishing TEXUS relay. Disabling.")
        else:
            LOGGER.info("Started TEXUS relay.")

    def start_publishing_regularly(self, readings_interval: float,
                                   flags_interval: float,
                                   setup_interval: float,
                                   status_update_interval: float) -> None:
        """Schedule asyncio tasks to publish data regularly.

        This includes the following types of data:

        - Readings: Measurements, mostly numerical, taken from various
          subsystems.
        - Setup Data: Things that don't usually change at runtime, such as RF
          stack setup.
        - Flags: The TEXUS flags as sent by the TEXUS flight computer. Those
          only change seldomly, usually once per experiment run.

        Please note that the given intervals will not be matched exactly, as
        the whole server runs on a single asyncio loop, putting "regular"
        updates into perspective ("cooperative multitasking").

        :param readings_interval: Readings are sent at roughly this interval
                    (in seconds). Set to zero to disable publishing readings.
        :param flags_interval: Flags are sent at roughly this interval (in
                    seconds). Set to zero to disable publishing flags.
        :param setup_interval: Setup data is sent at roughly this interval (in
                    seconds). Set to zero to disable publishing setup data.
        :param status_update_interval: Some subsystems do comprise params that
                    seldomly change. Those are consequently not periodically
                    communicated by those systems but only if they change.
                    However, they can also be inquired which is done at the
                    interval specified here.  Set to zero to never request
                    those params.
        """

        async def serve_readings():
            while True:
                await self.publish_readings()
                await asyncio.sleep(readings_interval)

        async def serve_flags():
            while True:
                await self.publish_flags()
                await asyncio.sleep(flags_interval)

        async def serve_setup_params():
            while True:
                await self.publish_setup_parameters()
                await asyncio.sleep(setup_interval)

        async def regularly_inquire_status():
            while True:
                await self._subs.refresh_status()
                await asyncio.sleep(status_update_interval)

        asyncio.ensure_future(serve_readings())
        asyncio.ensure_future(serve_flags())
        asyncio.ensure_future(serve_setup_params())
        asyncio.ensure_future(regularly_inquire_status())

    async def publish_readings(self) -> None:
        """Publish recent readings as received from subsystem controller."""

        # We need to use a transitional variable here to make sure that we
        # don't claim to have published newer readings than we actually did.
        prev = self._readings_published_at
        data = self._subs.get_full_set_of_readings(since=prev)
        await self._publish_message(packer.create_message(data, 'readings'))
        self._readings_published_at = time.time()

    async def publish_flags(self) -> None:
        if isinstance(self._texus, texus_relay.TexusRelay):
            data = self._texus.get_full_set()
            await self._publish_message(packer.create_message(data, 'texus'))

    async def publish_setup_parameters(self) -> None:
        """Publish all setup parameters over all open connections once."""
        LOGGER.debug("Scheduling setup parameter publication.")
        data = self._subs.get_setup_parameters()
        await self._publish_message(packer.create_message(data, 'setup'))

    def set_flag(self, entity_id: str, value: bool) -> None:
        if isinstance(self._texus, texus_relay.TexusRelay):
            if entity_id in texus_relay.LEGAL_SETTERS \
                    and isinstance(value, bool):
                setattr(self._texus, entity_id, value)

    def register_on_receive_callback(
            self, callback: Callable[[str], None]) -> None:
        """Provide a callback that is called each time a data packet arrives.

        The callback must take the data payload (string) as an argument.
        """
        # pylint: disable=unsubscriptable-object
        # Callable is indeed subscriptable, pylint fails to detect that.

        self._rcv_callback = callback

    async def _publish_message(self, message: str) -> None:
        if self._use_rs232:
            self._rs232.publish(message)
        if self._use_ws:
            await self._ws.publish(message)

    def _parse_reply(self, message: str) -> None:
        if callable(self._rcv_callback):
            self._rcv_callback(message)

    def _on_client_connect(self) -> None:
        """Is called everytime a new client connects to the TCP/IP interface.

        Attention: As there might be RS232 clients as well, this might not get
        called at all."""
        asyncio.ensure_future(self.publish_setup_parameters())
        asyncio.ensure_future(self.publish_readings())
        asyncio.ensure_future(self.publish_flags())
