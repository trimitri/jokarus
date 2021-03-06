"""``QueueingSerialServer`` is a subclass of ``serial_server.SerialServer``."""
import asyncio
import functools
from typing import Any, Callable

from . import serial_server
from ..util import asyncio_tools


class QueueingSerialServer(serial_server.SerialServer):
    """A queuing, asynchronous extension of serial_server.py

    Caller must be calling from a running asyncio loop.
    """

    def __init__(self, device: str,
                 received_msg_callback: Callable[[str], None] = None,
                 baudrate: int = 19200) -> None:
        super().__init__(device, received_msg_callback, baudrate)
        self.uplink_blocked = False
        """Is the serial connection currently sending data?"""
        self._loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop
        self._queue = asyncio_tools.DeDupQueue()
        """The de-duplicating queue used to store send requests."""

    async def async_serve(self) -> None:
        """Like ``.serve()``, but non blocking. Instead await'ing forever.

        This runs the actual server in a threaded executor."""
        self._loop.run_in_executor(None, self.serve)
        serial_server.LOGGER.debug("Started queueing serial server.")

    def queue_for_publication(self, data: str, species: Any) -> None:
        """Notify the server of the intent to publish ``data`` asap.

        This will not guarantee, that the data is sent over the interface right
        now, as other transmissions might currently be happening.  This will
        neither guarantee, that ``data`` is sent at all: If newer messages of
        the same ``species`` arrive while waiting for the next free
        transmission slot, those will be transferred instead.

        :param data: The message to be sent.
        :param species: An identification as to which type of news this is.
                    Important for deciding which messages to discard (see
                    above).
        """
        self._queue.enqueue(data, species)
        if not self.uplink_blocked:
            asyncio.ensure_future(self._process_queue())
        else:
            serial_server.LOGGER.debug("Uplink blocked.")
        serial_server.LOGGER.debug("Scheduled a %s specimen for publication.",
                                   species)

    async def _process_queue(self) -> None:
        """Start to publish the accumulated queue of messages.

        This may well run forever and keep the RS232 link blocked the whole
        time as long as the requests for publication come in faster than what
        the link can handle.
        """
        if not self._queue.queue:
            return
        n_published = 0
        try:
            serial_server.LOGGER.debug("Publishing queue...")
            self.uplink_blocked = True
            while True:
                await self._loop.run_in_executor(None, functools.partial(
                    super().publish, self._queue.pop()))
                n_published += 1
        except IndexError:
            self.uplink_blocked = False
            serial_server.LOGGER.debug("Published %s elements in a row.",
                                       n_published)
