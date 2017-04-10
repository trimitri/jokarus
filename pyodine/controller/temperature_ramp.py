"""This module provides utility class for running temperature ramps.

This is necessary, if a temperature controller does not include the feature to
set a limit to the temperature gradient.
"""
import asyncio
import inspect
import logging
import math
import time
from typing import Callable

LOGGER = logging.getLogger("pyodine.controller.temperature_ramp")
LOGGER.setLevel(logging.DEBUG)

# The interval at which the transitional setpoint gets updated (in seconds). It
# is advisable to use some weird number here to make sure that asyncio tasks
# are evenly spaced in time.
UPDATE_INTERVAL = 11.73

# The distance (in Kelvin) between setpoint and temperature reading that is
# acceptable during normal operation of the ramp. Do not set this to zero, as
# it might significantly slow down operation or even impede it.
ACCEPTABLE_OFFSET = 1.0


# pylint: disable=too-many-instance-attributes
class TemperatureRamp:
    """A stateful executor for a limited-gradient temperature ramp."""

    # Pylint doesn't recognize typing's subscriptable metaclasses.
    # pylint: disable=unsubscriptable-object
    def __init__(self, get_temp_callback: Callable[[], float],
                 set_temp_callback: Callable[[float], None],
                 name: str) -> None:

        self.name = name  # descriptive name for this instance

        # Validate and store getter callback.
        sig = inspect.signature(get_temp_callback)
        if sig.return_annotation is float and not sig.parameters:
            self._get_temp = get_temp_callback
        else:
            raise TypeError("Provide a type-annotated callback of proper"
                            "signature.", get_temp_callback)

        # Validate and store setter callback.
        sig = inspect.signature(set_temp_callback)
        param_types = list(sig.parameters.values())
        if len(param_types) == 1 and param_types[0].annotation is float:
            self._set_temp = set_temp_callback
        else:
            raise TypeError("Provide a type-annotated callback of proper"
                            "signature.", set_temp_callback)

        self._target = None  # type: float # Target temperature
        self._max_grad = 1. / 60.  # Maximum temperature gradient (1K/min)

        # Current transitional setpoint (in deg. Celsius).
        self._current_setpt = None  # type: float

        # Previous transitional setpoint (in deg. Celsius).
        self._prev_setpt = None  # type: float

        # Last update of transitional setpoint was at that time (unix
        # timestamp).
        self._prev_time = None  # type: float

        self._keep_running = False  # Is used to break the loop when runnning.

    @property
    def target_temperature(self) -> float:
        """The final temperature the object should reach."""
        return self._target

    @target_temperature.setter
    def target_temperature(self, target: float) -> None:
        if isinstance(target, float) and math.isfinite(target):
            self._target = target
            LOGGER.debug("Setting target temperature to %s.", target)
        else:
            LOGGER.error("Please provide a finite target temperature.")

    @property
    def maximum_gradient(self) -> float:
        """The maximum thermal gradient to use (in Kelvin per second)."""
        return self._max_grad

    @maximum_gradient.setter
    def maximum_gradient(self, gradient: float) -> None:
        if math.isfinite(gradient) and gradient > 0:
            self._max_grad = gradient
            LOGGER.debug("Setting temp. gradient to %s.", gradient)
        else:
            LOGGER.error("Illegal value for temp. gradient: %s", gradient)

    @property
    def is_running(self) -> bool:
        """Is the temperature control currently running?"""
        return self._keep_running

    @property
    def temperature(self) -> float:
        return self._get_temp()

    def start_ramp(self) -> None:
        """Start/resume pediodically setting the temp. setpoint."""

        # Ensure prerequisites.
        if self._keep_running:
            LOGGER.warning("%s ramp is already running.", self.name)
            return
        if not math.isfinite(self._target):
            LOGGER.error(
                "Set target temperature before starting ramp %s", self.name)
            return

        LOGGER.debug("Starting to ramp temperature.")

        # Create a "runner" coroutine and then schedule it for running.
        async def run_ramp() -> None:
            while self._keep_running:
                self._update_transitional_setpoint()
                await asyncio.sleep(UPDATE_INTERVAL)
        self._keep_running = True
        asyncio.ensure_future(run_ramp())

    def pause_ramp(self) -> None:
        """Stop setting new temp. setpoints, stay at current value."""
        LOGGER.debug("Pausing temperature ramp, staying at %s.",
                     self._current_setpt)
        self._keep_running = False
        self._prev_setpt = None
        self._prev_time = None

    def _update_transitional_setpoint(self) -> None:
        """Set a new intermediate setpoint if the thermal load is following.
        """
        # Did we just start the ramping?
        if self._prev_setpt is None:
            self._init_ramp()

        # Exit prematurely if we're there already.
        if self._current_setpt == self._target:
            LOGGER.debug("Current setpoint equals target temperature.")
            return

        # Are we close enough to the current setpoint to continue?
        if abs(self._get_temp() - self._current_setpt) < ACCEPTABLE_OFFSET:
            self._set_next_setpoint()
        else:
            # Don't do anything and wait until next invocation for the object
            # temperature to settle.
            LOGGER.warning("Thermal load didn't follow ramp. Delaying ramp "
                           "continuation by %s seconds.", UPDATE_INTERVAL)

    def _set_next_setpoint(self) -> None:
        # Just set the next point, assuming that sanity test have been run.

	# Calculate a candidate for next transitional setpoint.
        now = time.time()
        sign = -1 if self._target < self._get_temp() else 1
        next_setpt = self._current_setpt + (
            (now - self._prev_time) * sign * self._max_grad)

        # Prevent overshoot and set target temperature directly instead.
        if ((self._prev_setpt - self._target) * (next_setpt - self._target)
                < 0):
            next_setpt = self._target
            LOGGER.info("Reached target temperature.")

        # Advance time.
        self._prev_setpt = self._current_setpt
        self._current_setpt = next_setpt
        self._prev_time = now

        # Actually set the new temperature in hardware.
        self._set_temp(self._current_setpt)
        LOGGER.debug("Setpoint new: %s, old: %s.",
                     self._current_setpt, self._prev_setpt)

    def _init_ramp(self) -> None:
        # Initialize internal ramp parameters to allow the iterative update
        # method to work.

        self._current_setpt = self._get_temp()
        self._prev_setpt = self._current_setpt

        # Set time back, so ramp does immediately start with a full step.
        self._prev_time = time.time() - UPDATE_INTERVAL
