"""Communication with the TEXUS flight signals.

Provides callbacks for start and stop of specific flight phases, etc.
"""
import logging
import random

LOGGER = logging.getLogger('pyodine.transport.texus_relay')
LEGAL_SETTERS = ['jok1', 'jok2', 'jok3', 'jok4']


class TexusRelay:

    def __init__(self):
        self._jok1 = self._rand_bool()  # FIXME
        self._jok2 = self._rand_bool()  # FIXME
        self._jok3 = self._rand_bool()  # FIXME
        self._jok4 = self._rand_bool()  # FIXME

    def get_full_set(self) -> dict:
        ret = {'jok1': self.jok1,
               'jok2': self.jok2,
               'jok3': self.jok3,
               'jok4': self.jok4,
               'liftoff': self.liftoff,
               'microg': self.microg}
        return ret

    def _get_fake_set(self) -> dict:  # TODO remove when not neede anymore.
        obj = {'liftoff': self._rand_bool(),
               'microg': self._rand_bool(),
               'jok1': self._rand_bool(),
               'jok2': self._rand_bool()}
        return obj

    @property
    def liftoff(self) -> bool:
        return self._rand_bool()  # FIXME

    @property
    def microg(self) -> bool:
        return self._rand_bool()  # FIXME

    @property
    def jok1(self) -> bool:
        return self._jok1  # FIXME Query serial pin.

    @jok1.setter
    def jok1(self, value: bool) -> None:
        LOGGER.info("Setting jok1 to %s", value)
        self._jok1 = value  # FIXME Set serial pin.

    @property
    def jok2(self) -> bool:
        return self._jok2  # FIXME Query serial pin.

    @jok2.setter
    def jok2(self, value: bool) -> None:
        LOGGER.info("Setting jok2 to %s", value)
        self._jok2 = value  # FIXME Set serial pin.

    @property
    def jok3(self) -> bool:
        return self._jok3  # FIXME Query serial pin.

    @jok3.setter
    def jok3(self, value: bool) -> None:
        LOGGER.info("Setting jok3 to %s", value)
        self._jok3 = value  # FIXME Set serial pin.

    @property
    def jok4(self) -> bool:
        return self._jok4  # FIXME Query serial pin.

    @jok4.setter
    def jok4(self, value: bool) -> None:
        LOGGER.info("Setting jok4 to %s", value)
        self._jok4 = value  # FIXME Set serial pin.

    @staticmethod
    def _rand_bool() -> bool:
        return random.randint(0, 1) == 1
