"""Communication with the TEXUS flight signals.

Provides callbacks for start and stop of specific flight phases, etc.
"""
import logging
import random

LOGGER = logging.getLogger('pyodine.transport.texus_relay')


class TexusRelay:

    def get_full_set(self) -> dict:
        return self._get_fake_set()  # FIXME

    def _get_fake_set(self) -> dict:
        obj = {'liftoff': self._rand_bool(),
               'microg': self._rand_bool(),
               'jok1': self._rand_bool(),
               'jok2': self._rand_bool()}
        return obj

    @staticmethod
    def _rand_bool() -> bool:
        return random.randint(0,1) == 1

    @property
    def jok1(self) -> bool:
        pass  # FIXME Query serial pin.

    @jok1.setter
    def jok1(self, value: bool) -> None:
        LOGGER.info("Setting jok1 to %s", value)
        pass  # FIXME Set serial pin.
