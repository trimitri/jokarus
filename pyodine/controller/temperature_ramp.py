"""This module provides utility class for running temperature ramps.

This is necessary, if a temperature controller does not include the feature to
set a limit to the temperature gradient.
"""
from typing import Callable
import math
import logging

LOGGER = logging.getLogger("pyodine.controller.temperature_ramp")
LOGGER.setLevel(logging.DEBUG)  # TODO: remove


class TemperatureRamp:
    """A stateful executor for a limited-gradient temperature ramp."""

    def __init__(self, get_temp_callback: Callable[[], float],
                 set_temp_callback: Callable[[float], None],
                 is_temp_ok_callback: Callable[[], bool] = None) -> None:
        self._get_temp = get_temp_callback
        self._set_temp = set_temp_callback
        self._is_temp_ok = is_temp_ok_callback
        self._target = None  # type: float # Target temperature
        self._max_grad = 1. / 60.  # Maximum temperature gradient

    @property
    def target_temperature(self) -> float:
        """The final temperature the object should reach."""
        return self._target

    @target_temperature.setter
    def target_temperature(self, target: float) -> None:
        """The final temperature the object should reach."""
        if type(target) is float and math.isfinite(target):
            self._target = target
        else:
            LOGGER.error("Please provide a finite target temperature.")

    def start_ramp(self) -> None:
        pass

    def pause_ramp(self) -> None:
        pass
