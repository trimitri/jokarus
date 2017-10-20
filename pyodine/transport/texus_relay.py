"""Communication with the TEXUS flight signals.

Provides callbacks for start and stop of specific flight phases, etc.
"""
import asyncio
import enum
import logging
from typing import Awaitable, Callable, Dict, List, Union
import serial

from ..util import asyncio_tools

LOGGER = logging.getLogger('pyodine.transport.texus_relay')
LEGAL_SETTERS = ['jok1', 'jok2', 'jok3', 'jok4']
POLLING_INTERVAL = .63  # Poll for changing TEXUS flags every ~ seconds.
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


class TexusRelay:
    """Manage the data lines representing TEXUS and experiment state."""

    def __init__(self, port_1: str, port_2: str) -> None:
        try:
            self._port1 = serial.Serial(str(port_1))
            self._port2 = serial.Serial(str(port_2))
        except (FileNotFoundError, serial.SerialException):
            raise ConnectionError("Couldn't open serial ports assigned to "
                                  "TEXUS relay.")

    def get_full_set(self) -> Dict[str, bool]:
        """Return a Dict of all signal lines."""
        ret = {'liftoff': self.liftoff,
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
        return ret

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

    @property
    def timer_state(self) -> List[bool]:
        """The current state of all TEXUS timer wires.

        :returns: A list indexable by ``.TimerWire``.
        """
        return [self.liftoff, self.tex1, self.tex2, self.tex3,
                self.tex4, self.tex5, self.tex6, self.microg]

    async def poll_for_change(
            self,
            on_state_change: Callable[[TimerWire, List[bool]],
                                      Union[None, Awaitable[None]]] = lambda *_: None) -> None:  # pylint: disable=bad-whitespace
        """Start polling the incoming timer wires for change indefinitely.

        This will (async) block.
        """
        old_state = self.timer_state
        while True:
            await asyncio.sleep(POLLING_INTERVAL)
            new_state = self.timer_state
            for wire in TimerWire:
                if new_state[wire] != old_state[wire]:
                    await asyncio_tools.safe_async_call(on_state_change, wire,
                                                        new_state)
            old_state = new_state
