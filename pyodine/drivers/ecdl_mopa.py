"""A generic driver for the combined current drivers of an ECDL MOPA.

A "Master Oscillator"-"Power Amplifier" setup does not allow for arbitrary
combinations of MO and PA current which is why the fitness of every state
change must be checked before it is applied.
"""
import enum
import collections
import logging
from typing import Callable

LOGGER = logging.getLogger('ecdl_mopa')

MopaSpec = collections.namedtuple(
    'MopaSpec', ['mo_max', 'mo_seed', 'pa_max', 'pa_transparency', 'pa_backfire'])
"""A set of current limits describing a particular MOPA laser.

The members obviously can't be set arbitrarily.  Choosing sensible settings is
left to the informed user. All settings are in milliamps:

`mo_max`
    The MO current must never exceed this many mA.
`mo_seed`
    At this current, the MO lases enough to safely seed the PA.  The PA may
    thus be used in its full range only as long as the MO runs above this
    threshold.
`pa_max`
    The PA current must never exceed this many mA.
`pa_transparency`
    At this current, the PA is "transparent enough" (i.e. it actually amplifies
    instead of absorbing) to receive the full MO power.
`pa_backfire`
    Below this current, ASE from the _unseeded_ PA is weak enough to not damage
    any internal laser component whatsoever.
"""

class LaserState(enum.IntEnum):
    """The current running state of the laser."""
    ON = 10
    """MO and PA are running in a proper regime."""
    OFF = 20
    """MO and PA are both near zero current ("off")."""
    UNDEFINED = 30
    """Something is weird or currently transitioning."""

class CallbackError(RuntimeError):
    """There was an error executing one of the callbacks."""
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
    def __init__(self, get_mo_callback: Callable[[], float],
                 set_mo_callback: Callable[[float], None],
                 get_pa_callback: Callable[[], float],
                 set_pa_callback: Callable[[float], None],
                 enable_mo_callback: Callable[[], None],
                 disable_mo_callback: Callable[[], None],
                 enable_pa_callback: Callable[[], None],
                 disable_pa_callback: Callable[[], None],
                 is_mo_enabled: Callable[[], bool],
                 is_pa_enabled: Callable[[], bool],
                 laser_specification: MopaSpec) -> None:
        self._spec = laser_specification
        self._get_mo_current = get_mo_callback
        self._set_mo_current = set_mo_callback
        self._get_pa_current = get_pa_callback
        self._set_pa_current = set_pa_callback
        self._enable_mo = enable_mo_callback
        self._disable_mo = disable_mo_callback
        self._enable_pa = enable_pa_callback
        self._disable_pa = disable_pa_callback
        self._is_mo_on = is_mo_enabled
        self._is_pa_on = is_pa_enabled

    @property
    def pa_powerup_current(self) -> float:
        """A current between transparency and backfire thresholds."""
        return self._spec.pa_transparency + \
            0.3 * (self._spec.pa_backfire - self._spec.pa_transparency)

    @property
    def mo_powerup_current(self) -> float:
        """A current above seeding threshold."""
        candidate = 1.3 * self._spec.mo_seed
        if candidate < self._spec.mo_max:
            return candidate
        return self._spec.mo_max

    def get_mo_current(self) -> float:
        """The master oscillator laser diode current in milliamps.

        :raises CallbackError: Some exception occured in callback function.
        """
        try:
            return self._get_mo_current()
        except Exception as err:  # pylint: disable=bare-except
            raise CallbackError("Error executing get_mo_current_callback.") from err

    def set_mo_current(self, milliamps: float) -> None:
        """Set the current setpoint for the master oscillator laser diode.

        :raises ValueError: The given value must not be applied in the current
                            operating regime.
        :raises CallbackError: Some exception occured in callback function.
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
        if (current != 0 and
                not self.get_pa_current() >= self._spec.pa_transparency):
            raise ValueError("Refusing to set nonzero MO current, as PA is "
                             "operating below transparency threshold.")

        # Don't decrease MO current below lasing level if PA is in a regime
        # allowing backfire. Otherwise powerful backfire resulting from
        # spontaneous emission might occur.
        if (not current >= self._spec.mo_seed
                and not self.get_pa_current() < self._spec.pa_backfire):
            raise ValueError("Refusing to decrease MO current below seeding "
                             "level, as PA is in a backfire regime.")

        # If we got here, everything should be alright. Try to actually set the
        # new current.
        try:
            self._set_mo_current(current)
        except Exception as err:
            raise CallbackError("Error executing set_mo_current_callback.") from err

    def get_pa_current(self) -> float:
        """The laser power amplifier current in milliamps.

        :raises CallbackError: Some exception occured in callback function.
        """
        try:
            return self._get_pa_current()
        except Exception as err:
            raise CallbackError("Error executing get_pa_current_callback.") from err

    def set_pa_current(self, milliamps: float) -> None:
        """Set the current setpoint for the laser power amplifier.

        :raises ValueError: The given value must not be applied in the current
                            operating regime.
        :raises CallbackError: Some exception occured in callback function.
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
                not self.get_mo_current() < self._spec.mo_seed):
            raise ValueError("Refusing to go below PA transparency current, "
                             "as MO is still seeding.")

        # Don't increase PA current to backfire-prone current levels if MO is
        # not seeding. Otherwise powerful backfire resulting from spontaneous
        # emission might occur and damage internal components.
        if (not current < self._spec.pa_backfire and
                not self.get_mo_current() >= self._spec.mo_seed):
            raise ValueError("Refusing to enter backfire-prone PA current "
                             "range, as mo is not seeding.")

        # If we got here, everything should be alright. Try to actually set the
        # new current.
        try:
            self._set_pa_current(current)
        except Exception as err:
            raise CallbackError("Error executing set_pa_current_callback.") from err

    def disable_mo(self, force: bool = False) -> None:
        """Switch off master oscillator if safe. Use force to skip checks.

        :raises ValueError: Turning off MO not allowable in current regime.
                            This is only raised if "force" is not used.
        """
        if not force:
            self.set_mo_current(0)  # raises ValueError if not allowable
        self._disable_mo()

    def disable_pa(self, force: bool = False) -> None:
        """Switch off power amplifier if safe. Use force to skip checks.

        :raises ValueError: Turning off PA not allowable in current regime.
                            This is only raised if "force" is not used.
        """
        if not force:
            self.set_pa_current(0)  # raises ValueError if not allowable
        self._disable_pa()

    def enable_mo(self, force: bool = False) -> None:
        """Switch on master oscillator (setting it to 0 mA).

        Use "force" to skip all sanity checks and switch it on. This skips
        setting the current to 0 mA!

        :raises ValueError: Current regime doesn't allow setting MO to 0 mA. Is
                            only raised if "force" is not used.
        """
        if not force:
            self.set_mo_current(0)  # raises ValueError if not allowable
        self._enable_mo()

    def enable_pa(self, force: bool = False) -> None:
        """Switch on power amplifier (setting it to 0 mA).

        Use "force" to skip all sanity checks and switch it on. This skips
        setting the current to 0 mA!

        :raises ValueError: Current regime doesn't allow setting PA to 0 mA. Is
                            only raised if "force" is not used.
        """
        if not force:
            self.set_pa_current(0)  # raises ValueError if not allowable
        self._enable_pa()

    def get_state(self) -> LaserState:
        """Identify the laser's current state."""
        if not self._is_mo_on() and not self._is_pa_on():
            return LaserState.OFF
        mo_current = self.get_mo_current()
        pa_current = self.get_pa_current()
        if all([self._is_mo_on(), self._is_pa_on(),
                mo_current > self._spec.mo_seed,
                mo_current < self._spec.mo_max,
                pa_current > self._spec.pa_transparency,
                pa_current < self._spec.pa_max]):
            return LaserState.ON
        return LaserState.UNDEFINED
