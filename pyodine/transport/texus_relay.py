"""Communication with the TEXUS flight signals.

Provides callbacks for start and stop of specific flight phases, etc.
"""
import asyncio
import enum
import logging
from typing import Awaitable, Callable, Dict, List, Optional
import serial

from .. import constants as cs
from .. import logger
from ..util import asyncio_tools
from ..pyodine_globals import GLOBALS as GL

LOGGER = logging.getLogger('texus_relay')
LEGAL_SETTERS = ['jok1', 'jok2', 'jok3', 'jok4']
class TimerWire(enum.IntEnum):
    """Indexing convention for texus timer signal wires."""
    LIFT_OFF = 0
    TEX_1 = 1
    TEX_2 = 2
    TEX_3 = 3
    TEX_4 = 4
    TEX_5 = 5
    TEX_6 = 6
    MICRO_G = 7

TimerState = List[bool]
"""The a full state reading of the TEXUS timer."""

class TexusRelay:
    """Manage the data lines representing TEXUS and experiment state."""

    def __init__(self, port_1: str, port_2: str) -> None:
        try:
            self._port1 = serial.Serial(str(port_1))
            self._port2 = serial.Serial(str(port_2))
        except (FileNotFoundError, serial.SerialException):
            raise ConnectionError("Couldn't open serial ports assigned to "
                                  "TEXUS relay.")
        self._recent_state = None  # type: List[bool]

    async def get_full_set(self) -> Dict[str, bool]:
        """Return a Dict of all signal lines.

        :raises ConnectionError: Serial didn't give us data.
        """
        def hw_blocking_call() -> Dict[str, bool]:
            """Get the data. This is prone to H/W blocking."""
            try:
                return {'liftoff': self.liftoff,
                        'microg': self.microg,
                        'tex1': self.tex1,
                        'tex2': self.tex2,
                        'tex3': self.tex3,
                        'tex4': self.tex4,
                        'tex5': self.tex5,
                        'tex6': self.tex6,
                        'jok1': self.jok1,
                        'jok2': self.jok2,
                        'jok3': self.jok3,
                        'jok4': self.jok4}
            except Exception as err:
                raise ConnectionError("Failed to get TEXUS flags.") from err

        return await GL.loop.run_in_executor(None, hw_blocking_call)

    @property
    def tex1(self) -> bool:
        return self._port1.getCD()

    @property
    def tex2(self) -> bool:
        return self._port1.getDSR()

    @property
    def tex3(self) -> bool:
        return self._port1.getCTS()

    @property
    def tex4(self) -> bool:
        return self._port1.getRI()

    @property
    def tex5(self) -> bool:
        return self._port2.getCD()

    @property
    def tex6(self) -> bool:
        return self._port2.getDSR()

    @property
    def microg(self) -> bool:
        return self._port2.getCTS()

    @property
    def liftoff(self) -> bool:
        return self._port2.getRI()

    @property
    def jok1(self) -> bool:
        return self._port1.dtr

    @jok1.setter
    def jok1(self, value: bool) -> None:
        LOGGER.info("Setting jok1 to %s", value)
        self._port1.dtr = value

    @property
    def jok2(self) -> bool:
        return self._port1.rts

    @jok2.setter
    def jok2(self, value: bool) -> None:
        LOGGER.info("Setting jok2 to %s", value)
        self._port1.rts = value

    @property
    def jok3(self) -> bool:
        return self._port2.dtr

    @jok3.setter
    def jok3(self, value: bool) -> None:
        LOGGER.info("Setting jok3 to %s", value)
        self._port2.dtr = value

    @property
    def jok4(self) -> bool:
        return self._port2.rts

    @jok4.setter
    def jok4(self, value: bool) -> None:
        LOGGER.info("Setting jok4 to %s", value)
        self._port2.rts = value

    async def get_timer_state(self) -> TimerState:
        """The current state of all TEXUS timer wires.

        :returns: A list indexable by ``.TimerWire``.
        """
        def get_state() -> List[bool]:
            """HW blocking call."""
            try:
                self._recent_state = [self.liftoff, self.tex1, self.tex2,
                                      self.tex3, self.tex4, self.tex5,
                                      self.tex6, self.microg]
            except Exception:  # likes to throw OSErrors...
                LOGGER.exception("Couldn't get timer state. Returning old one.")
            return self._recent_state

        return await GL.loop.run_in_executor(None, get_state)

    async def poll_timer(
            self,
            handler: Callable[[TimerState], Optional[Awaitable[None]]] = lambda *_: None) -> None:
        """Start polling the incoming timer wires indefinitely.

        This method blocks (async).
        """
        old_state = await self.get_timer_state()
        logger.log_quantity('texus_flags', str(old_state))

        while True:
            new_state = await self.get_timer_state()
            if new_state == old_state:
                await asyncio_tools.safe_async_call(handler, new_state)
            else:
                check_state = await self.get_timer_state()

                # Check the state again and only proceed if it didn't change.
                # As the signals will never be set and read at the exact same
                # time, it is possible that we read a request that is currently
                # in transition and thus possibly invalid and harmful.
                if check_state == new_state:
                    LOGGER.info("New TEXUS state: %s", new_state)
                    logger.log_quantity('texus_flags', str(new_state))
                    old_state = new_state
                    await asyncio_tools.safe_async_call(handler, new_state)
                else:
                    LOGGER.warning("New TEXUS request wasn't stable, waiting "
                                   "for next iteration.")
            await asyncio.sleep(cs.TEXUS_WIRE_POLLING_INTERVAL)
