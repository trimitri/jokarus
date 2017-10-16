"""Communication with the TEXUS flight signals.

Provides callbacks for start and stop of specific flight phases, etc.
"""
import asyncio
from collections import namedtuple
import logging
from typing import Callable, Dict
import serial

from ..util import asyncio_tools

LOGGER = logging.getLogger('pyodine.transport.texus_relay')
LEGAL_SETTERS = ['jok1', 'jok2', 'jok3', 'jok4']
POLLING_INTERVAL = .63  # Poll for changing TEXUS flags every ~ seconds.
TimerState = namedtuple('TimerState', ['liftoff', 'microg', 'tex1', 'tex2',
                                       'tex3', 'tex4', 'tex5', 'tex6'])


class TexusRelay:
    """Manage the data lines representing TEXUS and experiment state."""

    def __init__(self, port_1: str, port_2: str,
                 on_state_change: Callable[[TimerState], None] = lambda s: None) -> None:
        try:
            self._port1 = serial.Serial(str(port_1))
            self._port2 = serial.Serial(str(port_2))
        except (FileNotFoundError, serial.SerialException):
            raise ConnectionError("Couldn't open serial ports assigned to "
                                  "TEXUS relay.")
        self._on_change = on_state_change

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
    def timer_state(self) -> TimerState:
        return TimerState(self.liftoff, self.microg, self.tex1, self.tex2,
                          self.tex3, self.tex4, self.tex5, self.tex6)

    async def poll_for_change(self):
        """Start polling the incoming timer wires for change indefinitely.

        This will (async) block.
        """
        old_state = self.timer_state
        while True:
            await asyncio.sleep(POLLING_INTERVAL)
            new_state = self.timer_state
            if new_state != old_state:
                asyncio_tools.call_callback(self._on_change, new_state)
                old_state = new_state
