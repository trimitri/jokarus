"""This module houses the LockBuddy class for analog lockbox management."""
from typing import Callable, List
import logging

import numpy as np


LOGGER = logging.getLogger('pyodine.controller.lock_buddy')

# To make the code more readable, we differentiate between numbers that
# represent the lock system's tunable quantity (e.g. frequency) and all other
# numbers that occur in the code.
Unit = float  # One "LockBuddy unit" (e.g. MHz of frequency)

class Tuner:
    """A means of tuning a control system's tunable quantity.

    As there are often multiple such means means, we provide a unified
    interface for such "knobs" here. All tuners linearize and scale their
    respective ranges of motion to [0, 1] in order to keep the usage of a
    multi-variable control system straightforward and easy to read.
    """
    def __init__(self, scale: Unit, granularity: float, delay: float,
                 getter: Callable[[], float],
                 setter: Callable[[float], None]) -> None:
        """A tuner must scale it's full range of motion [0, 1] interval.

        :param scale: (Approximate) number of "LockBuddy units" that fit into
                    the controllers [0, 1] range. The range is expected to be
                    linearized.
        :param granularity: Smallest step that will make an actual difference
                    in the controlled system. This must be given relative to
                    the linearized [0, 1] range.
        :param delay: Delay in seconds between control input and actual effect
                    on the controlled quantity.
        :param getter: Callback used to get current knob position. Must use the
                    the linearized [0, 1] range.
        :param setter: Callback used to command control input. Must accept the
                    linearized [0, 1] range.
        """
        if not scale > 0:
            raise ValueError("Provide scale >0")
        if not granularity > 0 or not granularity < 1:
            raise ValueError("Provide granularity in ]0, 1[ interval.")
        if not delay >= 0:
            raise ValueError("Provide delay in seconds.")
        if not callable(getter) or not callable(setter):
            raise TypeError("Provide callable getter and setter.")

        self.scale = float(scale)
        self.granularity = float(granularity)
        self.delay = float(delay)
        self._setter = setter
        self._getter = getter

    @property
    def value(self) -> float:
        return self._getter()

    @value.setter
    def value(self, value: float) -> None:
        self._setter(value)


class LockBuddy:
    """Provide management and helper functions for closed-loop locks."""

    def __init__(self, lock: Callable[[], None],
                 unlock: Callable[[], None],
                 locked: Callable[[], bool],
                 scanner: Callable[[float], np.ndarray],
                 tuners: List[Tuner]) -> None:
        """
        :param lock: Callback that engages the hardware lock. No params.
        :param unlock: Callback that disengages the hardware lock. No params.
        :param locked: Callback indicating if the hardware lock is engaged. No
                    params.
        :param scanner: Callback acquiring a signal for prelock. Is passed one
                    float parameter in [0, 1] to set the relative scan range.
        :param tuner_coarse: A Tuner object that provides control over the
                    tunable quantity.
        :param tuner_medium: See tuner_coarse.
        :param tuner_fine: See tuner_coarse.
        """

        for name, callback in (("lock", lock), ("unlock", unlock),
                               ("scanner", scanner), ("locked", locked)):
            if not callable(callback):
                raise TypeError('Callback "%s" is not callable.', name)

        self.prelock_running = False  # The prelock algorithm is running.
        self.recent_signal = np.empty(0)  # The most recent signal acquired.
        self.range = 1.  # The range used for acquiring .recent_signal

        self._scanner = scanner
        self._lock = lock
        self._unlock = unlock
        self._locked = locked

        # Make sure the fastest tuner is listed first.
        self._tuners = sorted(tuners, key=lambda t: t.delay)

    @property
    def lock_engaged(self) -> bool:
        return self._locked()

    def acquire_signal(self, rel_range: float = None) -> np.ndarray:
        """Run one scan and store the result. Lock must be disengaged.

        :param rel_range: The scan amplitude in ]0, 1]. The last used amplitude
                    is used again if `None` is given.
        :raises RuntimeError: Lock was not disengaged before.
        :raises ValueError: Range is out of ]0, 1].
        """
        # To avoid inadvertent lock losses, we only allow scanning if the lock
        # is currently disengaged.
        if self.lock_engaged:
            raise RuntimeError("Disengage lock before acquiring signals.")
        if not rel_range:
            rel_range = self.range
        else:
            self.range = rel_range

        self.recent_signal = self._scanner(rel_range)
        return self.recent_signal

    def prelock(self, threshold: float, autolock: bool = True,
                proximity_callback: Callable[[], None] = lambda: None) -> None:
        """Start the prelock algorithm and get as close as possible to target.

        As soon as we can reasonable assume to be closer than `threshold` to
        the target value, `proximity_callback` is fired. If `autolock` is set
        to true, the closed-loop lock is engaged as well.

        If the lock is currently engaged, it is going to be disengaged.
        """
        pass
