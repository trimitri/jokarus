"""This module provides utility class for running temperature ramps.

This is necessary, if a temperature controller does not include the feature to
set a limit to the temperature gradient.
"""
from typing import Callable
import inspect
import logging
import math

LOGGER = logging.getLogger("pyodine.controller.temperature_ramp")
LOGGER.setLevel(logging.DEBUG)


class TemperatureRamp:
    """A stateful executor for a limited-gradient temperature ramp."""

    # Pylint doesn't recognize typing's subscriptable metaclasses.
    # pylint: disable=unsubscriptable-object
    def __init__(self, get_temp_callback: Callable[[], float],
                 set_temp_callback: Callable[[float], None]) -> None:

        # Check and store getter callback.
        sig = inspect.signature(get_temp_callback)
        if sig.return_annotation is float and not sig.parameters:
            self._get_temp = get_temp_callback
        else:
            raise TypeError("Provide a type-annotated callback of proper"
                            "signature.", get_temp_callback)

        # Check and store setter callback.
        sig = inspect.signature(set_temp_callback)
        param_types = list(sig.parameters.values())
        if len(param_types) == 1 and param_types[0] is float:
            self._set_temp = set_temp_callback
        else:
            raise TypeError("Provide a type-annotated callback of proper"
                            "signature.", set_temp_callback)

        self._target = None  # type: float # Target temperature
        self._max_grad = 1. / 60.  # Maximum temperature gradient (1K/min)
        self._current_setpt = None  # type: float # Current internal setpoint

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

    def start_ramp(self) -> None:
        """Start pediodically setting the temp. setpoint."""
        LOGGER.debug("Starting to ramp temperature.")
        # TODO: implement!

    def pause_ramp(self) -> None:
        """Stop setting new temp. setpoints, stay at current value."""
        LOGGER.debug("Pausing temperature ramp, staying at %s.",
                     self._current_setpt)
        # TODO: implement!
