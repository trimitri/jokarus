"""The Interfaces class manages external communication.

It may set up downlinks to clients, regularly send data to them and deal with
control requests they might transmit.
"""
import asyncio
import base64
import logging
import time
from typing import Callable

import numpy as np

from ..transport.websocket_server import WebsocketServer
from ..transport.serial_server import SerialServer
from ..transport import texus_relay
from ..transport import packer
from ..controller import lock_buddy, subsystems

LOGGER = logging.getLogger("pyodine.controller.interfaces")
# LOGGER.setLevel(logging.DEBUG)
WS_PORT = 56320
MAX_SIGNAL_SAMPLES = 1024


class Interfaces:
    """This is how to talk to Pyodine.

    It sets up the services and receives instructions.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, subsystem_controller: subsystems.Subsystems,
                 locker: lock_buddy.LockBuddy,
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
        self._locker = locker
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
                                   signal_interval: float,
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

        async def serve_error_signal():
            while True:
                await self.publish_error_signal()
                await asyncio.sleep(signal_interval)

        async def serve_flags():
            while True:
                await self.publish_flags()
                await asyncio.sleep(flags_interval)

        async def serve_readings():
            while True:
                await self.publish_readings()
                await asyncio.sleep(readings_interval)

        async def serve_setup_params():
            while True:
                await self.publish_setup_parameters()
                await asyncio.sleep(setup_interval)

        async def regularly_inquire_status():
            while True:
                await self._subs.refresh_status()
                await asyncio.sleep(status_update_interval)

        asyncio.ensure_future(serve_error_signal())
        asyncio.ensure_future(serve_flags())
        asyncio.ensure_future(serve_readings())
        asyncio.ensure_future(serve_setup_params())
        asyncio.ensure_future(regularly_inquire_status())

    async def publish_error_signal(self) -> None:
        """Publish the most recently acquired error signal.

        As we need to be considerate about bandwidth and the data is only
        intended for display and backup logging, we will apply some
        compression.
        """
        raw_data = self._locker.last_signal

        # Check if a scan was already performed. Contrary to pyton lists, numpy
        # arrays don't always support bool().
        if not raw_data.any():
            LOGGER.warning("Couldn't publish signal as no signal was generated yet")
            return

        # Drop some values if this was a high-res scan.
        while raw_data.shape[0] > MAX_SIGNAL_SAMPLES:
            # Delete one third of the samples. That's not a very elegant way to
            # do it but it gets the job done in OK time.
            raw_data = np.delete(raw_data, np.arange(1, raw_data.size, 3),
                                 axis=0)

        # As the readings originally were 16-bit integers, we undo the
        # conversion here and transfer them as such.
        unscaled_data = (raw_data + 10.) / 20. * 2**16
        integer_data = np.rint(unscaled_data).astype('uint16')
        LOGGER.debug("Sending %s uint16 values.", integer_data.size)

        # Use base64 encoding, as it is common with browsers and saves further
        # bandwidth.
        data = base64.b64encode(integer_data.tobytes()).decode()
        payload = {'data': data}

        await self._publish_message(packer.create_message(payload, 'signal'))
        LOGGER.debug("Published error signal.")

    async def publish_flags(self) -> None:
        if isinstance(self._texus, texus_relay.TexusRelay):
            data = self._texus.get_full_set()
            await self._publish_message(packer.create_message(data, 'texus'))

    async def publish_readings(self) -> None:
        """Publish recent readings as received from subsystem controller."""

        # We need to use a transitional variable here to make sure that we
        # don't claim to have published newer readings than we actually did.
        prev = self._readings_published_at
        data = self._subs.get_full_set_of_readings(since=prev)
        await self._publish_message(packer.create_message(data, 'readings'))
        self._readings_published_at = time.time()

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
