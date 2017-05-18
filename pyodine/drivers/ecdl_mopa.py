"""A generic driver for the combined current drivers of an ECDL.

As a "Master Oscillator"-"Power Amplifier" setup does not allow for arbitrary
combinations of MO and PA current which is why the fitness of every state
change must be checked before it is applied.
"""
# Diode current in mA at which the amplifier becomes transparent

import collections
import logging
from typing import Callable

LOGGER = logging.getLogger('ecdl_mopa')

MopaSpec = collections.namedtuple('MopaSpec', [
    'mo_max',
    'mo_seed_threshold',
    'pa_max',
    'pa_transparency',
    'pa_backfire'])


MILAS = MopaSpec(mo_max=200, mo_seed_threshold=50,
                 pa_max=1500, pa_transparency=200, pa_backfire=300)


class EcdlMopa:  # pylint: disable=too-many-instance-attributes
    """A wrapper for the two current drivers needed for a MOPA laser.

    It makes sure that all requested currents stay within the non-trivial MOPA
    operation envelope.
    """
    def __init__(self,  # pylint: disable=too-many-arguments
                 # pylint: disable=unsubscriptable-object
                 get_mo_callback: Callable[[], float],
                 set_mo_callback: Callable[[float], None],
                 get_pa_callback: Callable[[], float],
                 set_pa_callback: Callable[[float], None],
                 enable_mo_callback: Callable[[], None],
                 disable_mo_callback: Callable[[], None],
                 enable_pa_callback: Callable[[], None],
                 disable_pa_callback: Callable[[], None],
                 # pylint: enable=unsubscriptable-object
                 laser_specification: MopaSpec = MILAS) -> None:
        self._spec = laser_specification
        self._get_mo_current = get_mo_callback
        self._set_mo_current = set_mo_callback
        self._get_pa_current = get_pa_callback
        self._set_pa_current = set_pa_callback
        self._enable_mo = enable_mo_callback
        self._disable_mo = disable_mo_callback
        self._enable_pa = enable_pa_callback
        self._disable_pa = disable_pa_callback

    @property
    def mo_current(self) -> float:
        """The master oscillator laser diode current in milliamps."""
        try:
            return self._get_mo_current()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error while executing get_mo_current_callback.")
        return float('nan')

    @mo_current.setter
    def mo_current(self, milliamps: float) -> None:
        try:
            current = float(milliamps)
        except (TypeError, ValueError):
            LOGGER.error("Couldn't parse passed current.")
            return

        # FIXME: Check all if's for NaN/inf safety

        # Don't exceed maximum diode rating.
        if current > self._spec.mo_max:
            LOGGER.warning("Requested current exceeds specified maximum "
                           "current for master oscillator.")
            return

        # Don't dump (more) energy into the PA if it is not transparent.
        if current > 0 and self.pa_current < self._spec.pa_transparency:
            LOGGER.warning("Refusing to increase MO current, as PA is not "
                           "transparent.")
            return

        # Don't decrease MO current below lasing level if PA is in a regime
        # allowing backfire. Otherwise powerful backfire resulting from
        # spontaneous emission might occur.
        if (current < self._spec.mo_seed_threshold
                and self.pa_current >= self._spec.pa_backfire):
            LOGGER.warning("Refusing to decrease MO current below seeding "
                           "level, as PA is in a backfire regime.")
            return

        # If we got here, everything should be alright. Try to actually set the
        # new current.
        try:
            self._set_mo_current(current)
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error excecuting get_mo_callback.")

    @property
    def pa_current(self) -> float:
        """The laser power amplifier current in milliamps."""
        try:
            return self._get_pa_current()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error while executing get_pa_current_callback.")
        return float('nan')

    @pa_current.setter
    def pa_current(self, milliamps: float) -> None:
        pass  # FIXME

    def pa_disable(self, force: bool = False) -> None:
        """Switch off power amplifier if safe. Use force to skip checks.
        """
        if self.mo_current < self._spec.mo_seed_threshold or force:
            try:
                self._disable_pa()

            # We use the ultimate exception catcher here, as we're dealing
            # with a generally unknown callback.
            except:  # pylint: disable=bare-except
                LOGGER.exception("Error while executing disable_pa_callback.")
        else:
            LOGGER.error("Can not disable PA, as MO is running above seed "
                         "threshold and would dump into PA otherwise.")
            LOGGER.info("Consider using \"force\" attribute if something went "
                        "wrong and PA needs to be switched off regardless.")

    def mo_disable(self, force: bool = False) -> None:
        """Switch off master oscillator if safe. Use force to skip checks.
        """
        if self.pa_current < self._spec.pa_backfire or force:
            try:
                self._disable_mo()

            # We use the ultimate exception catcher here, as we're dealing
            # with a generally unknown callback.
            except:  # pylint: disable=bare-except
                LOGGER.exception("Error while executing disable_mo_callback.")
        else:
            LOGGER.error("Can not disable PA, as MO is running above seed "
                         "threshold and would dump into PA otherwise.")
            LOGGER.info("Consider using \"force\" attribute if something went "
                        "wrong and PA needs to be switched off regardless.")
