"""This module provides utility class for running temperature ramps.

This is necessary, if a temperature controller does not include the feature to
set a limit to the temperature gradient.
"""
import asyncio
import logging
import math
import time
from typing import Callable

from .. import constants as cs
from ..globals import GLOBALS as GL
from ..util import asyncio_tools as tools


class TemperatureRamp:
    """A stateful executor for a limited-gradient temperature ramp."""

    def __init__(self, get_temp_callback: Callable[[], float],
                 get_temp_setpt_callback: Callable[[], float],
                 set_temp_callback: Callable[[float], None],
                 name: str) -> None:

        self.name = name
        """What object is this ramp assigned to?"""
        self.maximum_gradient = None  # type: float
        """Maximum allowable temperature gradient in kelvin per second."""

        # As there tend to be multiple instances of this class, we keep a
        # separate, named logger for each of them.
        self.logger = logging.getLogger("pyodine.controller.temperature_ramp ("
                                        + self.name + ")")

        # None of these are checked for sanity here, as asyncio_tools.safe_call
        # will be used.
        self._get_temp = get_temp_callback
        self._get_temp_set = get_temp_setpt_callback
        self._set_temp = set_temp_callback

        self._target = None  # type: float  # current target temperature

        async def dummy():
            return
        self._task = GL.loop.create_task(dummy())  # type: asyncio.Task

        # Current transitional setpoint (in deg. Celsius).
        self._current_setpt = None  # type: float

        # Previous transitional setpoint (in deg. Celsius).
        self._prev_setpt = None  # type: float

        self._keep_running = False
        self._last_update = time.time()

    @property
    def target_temperature(self) -> float:
        """The final temperature the object should reach."""
        return self._target

    @target_temperature.setter
    def target_temperature(self, target: float) -> None:
        if isinstance(target, float) and math.isfinite(target):
            self._target = target
            self.logger.debug("Setting target temperature to %s.", target)
        else:
            self.logger.error("Please provide a finite target temperature.")

    @property
    def is_running(self) -> bool:
        """Is the temperature control currently running?"""
        return self._keep_running

    @property
    def temperature(self) -> float:
        return tools.safe_call(self._get_temp)

    def start_ramp(self) -> None:
        """Start/resume pediodically setting the temp. setpoint."""

        # Ensure prerequisites.
        if self._keep_running:
            self.logger.debug("%s ramp is already running. Ignoring.", self.name)
            return
        if self._target is None or not math.isfinite(self._target):
            self.logger.error(
                "Set target temperature before starting ramp %s", self.name)
            return

        if not self._task.done():
            raise RuntimeError("Ramp is running although it shouldn't be.")

        self.logger.debug("Starting to ramp temperature.")

        self._keep_running = True  # Is used to cancel _task gracefully.
        self._init_ramp()
        GL.loop.create_task(tools.repeat_task(
            self._update_transitional_setpoint, cs.TEMP_RAMP_UPDATE_INTERVAL,
            do_continue=lambda: self._keep_running))

    def pause_ramp(self) -> None:
        """Stop setting new temp. setpoints, stay at current value."""
        self.logger.debug("Pausing temperature ramp, staying at %s.",
                          self._current_setpt)

        # Reset the instance state to the same state as if the ramp wouldn't
        # have been started yet.  This makes sure that the resume procedure has
        # to check for actual current system state.
        self._keep_running = False
        self._current_setpt = None
        self._prev_setpt = None

    def _update_transitional_setpoint(self) -> None:
        """Set a new intermediate setpoint if the thermal load is following.
        """
        # Exit prematurely if we're there already.
        if self._current_setpt == self._target:
            self.logger.debug("Current setpoint equals target temperature.")
            return

        # Are we close enough to the current setpoint to continue?
        if abs(self.temperature - self._current_setpt) < cs.TEMP_GENERAL_ERROR:
            self._set_next_setpoint()
        else:
            # Don't do anything and wait until next invocation for the object
            # temperature to settle.
            self.logger.warning(
                "Thermal load didn't follow ramp. Delaying ramp continuation "
                "by %s seconds. (is: %s, want: %s)", cs.TEMP_RAMP_UPDATE_INTERVAL,
                self.temperature, self._current_setpt)

    def _set_next_setpoint(self) -> None:
        # Just set the next point, assuming that sanity test have been run.
        if not self.maximum_gradient > 0:
            raise ValueError("Invalid temperature gradient "
                             "({}) was set.".format(repr(self.maximum_gradient)))

        passed_time = time.time() - self._last_update
        if passed_time >= 2 * cs.TEMP_RAMP_UPDATE_INTERVAL:
            self.logger.debug("Restarting retired ramp.")
            passed_time = cs.TEMP_RAMP_UPDATE_INTERVAL
        # Calculate a candidate for next transitional setpoint.
        sign = -1 if self._target < self._current_setpt else 1
        next_setpt = self._current_setpt \
                     + (passed_time * sign * self.maximum_gradient)

        # Prevent overshoot and set target temperature directly instead.
        if ((self._prev_setpt - self._target) * (next_setpt - self._target)
                < 0):
            next_setpt = self._target
            self.logger.info("Reached target temperature.")

        # Advance time.
        self._prev_setpt = self._current_setpt
        self._current_setpt = next_setpt

        # Actually set the new temperature in hardware.
        self._last_update = time.time()
        tools.safe_call(self._set_temp, self._current_setpt)
        self.logger.debug("Setpoint new: %s, old: %s.",
                          self._current_setpt, self._prev_setpt)

    def _init_ramp(self) -> None:
        # Initialize internal ramp parameters to allow the iterative update
        # method to work.

        self._current_setpt = tools.safe_call(self._get_temp_set)
        self._prev_setpt = self._current_setpt
