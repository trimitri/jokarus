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


class CallbackError(RuntimeError):
    """There was an error executing one of the callbacks.

    As the callback functions are supposed to not raise any exceptions, this is
    most definitely an indicator for a necessary subsystem reset.
    """
    pass


class EcdlMopa:  # pylint: disable=too-many-instance-attributes
    """A wrapper for the two current drivers needed for a MOPA laser.

    It makes sure that all requested currents stay within the non-trivial MOPA
    operation envelope.

    This class does not, however, make sure that the requested currents are
    actually reached. As the provided callbacks are not allowed to throw any
    exceptions, it is up to the user to check for success of their request.
    This decision was made because it takes time to evaluate the success of
    setting a current.

    All methods may raise a ecdl_mopa.CallbackError if there is a problem
    executing a callback. Mutators (incl. en/disable!) may additionally raise
    a ValueError in case the current operating regime forbids the requested
    action.
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

    def get_mo_current(self) -> float:
        """The master oscillator laser diode current in milliamps."""
        try:
            return self._get_mo_current()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error while executing get_mo_current_callback.")
            raise CallbackError("Callback provided to %s raised an exception!",
                                __name__)

        # Is never reached.
        return float('nan')

    def set_mo_current(self, milliamps: float) -> None:
        """Set the current setpoint for the master oscillator laser diode.

        :raises ValueError: The given value must not be applied in the current
                            operating regime.
        :raises CallbackError:
        """
        try:  # type check
            current = float(milliamps)
        except (TypeError, ValueError):
            LOGGER.error("Couldn't parse passed current. Doing nothing.")
            return

        # NOTE: The following conditions are all formulated in a way that
        # ensures failure in case of NaN/inf occurrences.

        # Don't exceed maximum diode rating.
        if not current < self._spec.mo_max:
            raise ValueError("Requested current exceeds specified maximum "
                             "current for master oscillator.")

        # Don't dump (more) energy into the PA if it is not transparent.
        # Use "not" flavour of conditions to make sure that Nan/Inf lead to
        # failure.
        if (current != 0 and
                not self.get_pa_current() >= self._spec.pa_transparency):
            raise ValueError("Refusing to increase MO current, as PA is not "
                             "transparent.")

        # Don't decrease MO current below lasing level if PA is in a regime
        # allowing backfire. Otherwise powerful backfire resulting from
        # spontaneous emission might occur.
        if (not current >= self._spec.mo_seed_threshold
                and not self.get_pa_current() < self._spec.pa_backfire):
            raise ValueError("Refusing to decrease MO current below seeding "
                             "level, as PA is in a backfire regime.")

        # If we got here, everything should be alright. Try to actually set the
        # new current.
        try:
            self._set_mo_current(current)
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error excecuting get_mo_callback:")
            raise CallbackError("Callback provided to %s raised an exception!",
                                __name__)

    def get_pa_current(self) -> float:
        """The laser power amplifier current in milliamps."""
        try:
            return self._get_pa_current()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error while executing get_pa_current_callback.")
            raise CallbackError("Callback provided to %s raised an exception!",
                                __name__)

        # We never get here.
        return float('nan')

    def set_pa_current(self, milliamps: float) -> None:
        """Set the current setpoint for the laser power amplifier.

        :raises ValueError: The given value must not be applied in the current
                            operating regime.
        :raises CallbackError:
        """
        try:  # type check
            current = float(milliamps)
        except (TypeError, ValueError):
            LOGGER.error("Couldn't parse passed current. Doing nothing.")
            return

        # NOTE: The following conditions are all formulated in a way that
        # ensures failure in case of NaN/inf occurrences.

        # Don't exceed maximum diode rating.
        if not current <= self._spec.pa_max:
            raise ValueError("Requested current exceeds specified maximum "
                             "current for power amplifier.")

        # Don't go below PA transparency current while MO is seeding. This
        # avoids dumping energy into the PA.
        if (not current >= self._spec.pa_transparency and
                not self.get_mo_current() < self._spec.mo_seed_threshold):
            raise ValueError("Refusing to go below PA transparency current, "
                             "as MO is still seeding.")

        # Don't increase PA current to backfire-prone current levels if MO is
        # not seeding. Otherwise powerful backfire resulting from spontaneous
        # emission might occur and damage internal components.
        if (not current < self._spec.pa_backfire and
                not self.get_mo_current() >= self._spec.mo_seed_threshold):
            raise ValueError("Refusing to enter backfire-prone PA current "
                             "range, as mo is not seeding.")

        # If we got here, everything should be alright. Try to actually set the
        # new current.
        try:
            self._set_pa_current(current)
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error excecuting get_mo_callback:")
            raise CallbackError("Callback provided to %s raised an exception!",
                                __name__)

    def disable_mo(self, force: bool = False) -> None:
        """Switch off master oscillator if safe. Use force to skip checks.

        :raises ValueError: Turning off MO not allowable in current regime.
                            This is only raised if "force" is not used.
        :raises CallbackError:
        """
        if not force:
            self.set_mo_current(0)

        # Zeroing the current is allowable in the current regime or was forced.
        # Switch off now.
        try:
            self._disable_mo()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error excecuting disable_mo_callback:")
            raise CallbackError("Callback provided to %s raised an exception!",
                                __name__)

    def disable_pa(self, force: bool = False) -> None:
        """Switch off power amplifier if safe. Use force to skip checks.
        """
        if not force:
            self.set_pa_current(0)

        # Zeroing the current is allowable in the current regime or was forced.
        # Switch off now.
        try:
            self._disable_pa()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error excecuting disable_pa_callback.")
            raise RuntimeError("Failed to execute callback.")

    def enable_mo(self, force: bool = False) -> None:
        """Switch on master oscillator (setting it to 0 mA).

        Use "force" to skip all sanity checks and switch it on. This skips
        setting the current to 0 mA!

        :raises ValueError: Current regime doesn't allow setting MO to 0 mA. Is
                            only raised if "force" is not used.
        :raises CallbackError:
        """
        if not force:
            self.set_mo_current(0)

        try:
            self._enable_mo()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error while executing enable_mo_callback.")
            raise CallbackError("Callback provided to %s raised an exception!",
                                __name__)

    def enable_pa(self, force: bool = False) -> None:
        """Switch on power amplifier (setting it to 0 mA).

        Use "force" to skip all sanity checks and switch it on. This skips
        setting the current to 0 mA!

        :raises ValueError: Current regime doesn't allow setting PA to 0 mA. Is
                            only raised if "force" is not used.
        :raises CallbackError:
        """
        if not force:
            self.set_pa_current(0)

        try:
            self._enable_pa()
        except:  # pylint: disable=bare-except
            LOGGER.exception("Error while executing enable_pa_callback.")
            raise CallbackError("Callback provided to %s raised an exception!",
                                __name__)
