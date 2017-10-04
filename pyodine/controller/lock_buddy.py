"""This module houses the LockBuddy class for analog lockbox management."""
import asyncio
import enum
from typing import Any, Callable, List
import logging

import numpy as np

from . import feature_locator

LOGGER = logging.getLogger('pyodine.controller.lock_buddy')

# How many times to jump before considering the pre-lock procedure failed?
MAX_JUMPS = 10

"""To maintain a high tuning precision, the tuners are balanced from time to
time. Those are the thresholds beyond which a tuner is regarded as imbalanced.
It's an array [low, high] with 0 < low < high < 1.
"""
BALANCE_AT = [.2, .8]

"""Don't use tuners slower than that many seconds during prelock phase."""
PRELOCK_SPEED_CONSTRAINT = 1.

"""To make the code more readable, we differentiate between numbers that
represent the lock system's tunable quantity (e.g. frequency) and all other
numbers that occur in the code."""
QtyUnit = float

class Line(enum.Enum):
    """A map of where in the spectrum to find the target transitions."""
    # The first line's position depends on how much padding is added to the
    # reference left of the first line. All positions are in MHz.
    a_1 = 500.  # FIXME put real value here (ask Klaus)
    a_2 = a_1 + 259.698
    a_3 = a_1 + 285.511
    a_4 = a_1 + 286.220
    a_5 = a_1 + 311.366
    a_6 = a_1 + 401.478
    a_7 = a_1 + 416.994
    a_8 = a_1 + 439.626
    a_9 = a_1 + 455.343
    a_10 = a_1 + 571.542
    a_11 = a_1 + 698.055
    a_12 = a_1 + 702.754
    a_13 = a_1 + 726.030
    a_14 = a_1 + 732.207
    a_15 = a_1 + 857.954


class Tuner:
    """A means of tuning a control system's tunable quantity.

    As there are often multiple such means means, we provide a unified
    interface for such "knobs" here. All tuners linearize and scale their
    respective ranges of motion to [0, 1] in order to keep the usage of a
    multi-variable control system straightforward and easy to read.
    """
    def __init__(self, scale: QtyUnit, granularity: float, delay: float,
                 getter: Callable[[], float], setter: Callable[[float], None],
                 name: str = "") -> None:
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

        self.delay = float(delay)
        self.granularity = float(granularity)
        self.name = name
        self.scale = float(scale)
        self._setter = setter
        self._getter = getter

    def get(self) -> float:
        """Get the current actual value.

        :returns: The actual current tuner value. Doesn't necessarily match set
                    value.
        :raises RuntimeError: The callback provided as getter raised something.
        """
        try:
            return self._getter()
        except Exception as err:
            raise RuntimeError("Error executing getter callback.") from err

    def set(self, value: float) -> None:
        """Order the value to be set to ``value``.

        :param value: The value to be set. Needs to be in [0, 1] interval.

        :raises RuntimeError: The callback provided as setter raised something.
        :raises ValueError: ``value`` is not in [0, 1] interval.
        """
        if not value >= 0 or not value <= 1:
            raise ValueError("Tuners only accept values in the [0, 1] range. %s was passed.",
                             value)
        try:
            self._setter(value)
        except Exception as err:
            raise RuntimeError("Error executing setter callback.") from err


class LockBuddy:
    """Provide management and helper functions for closed-loop locks."""

    class _SnowblindError(RuntimeError):
        """In search for a feature, we found nothing but an empty void.

        This is a common problem with MTS spectra, as they are very "clean" and
        have long sections where they're simply == 0.
        """
        pass

    class _RivalryError(RuntimeError):
        """We wanted one match but found many and no particular one sticks out.

        If there are many features in the spectrum that all look the same, then
        using only a very small sample and trying to find its position can lead
        to multiple nearly identical hits. This just happened.
        """
        pass

    def __init__(self, lock: Callable[[], None],
                 unlock: Callable[[], None],
                 locked: Callable[[], bool],
                 scanner: Callable[[float], np.ndarray],
                 scanner_range: QtyUnit,
                 tuners: List[Tuner],
                 on_new_signal: Callable[[np.ndarray], None]=None) -> None:
        """
        :param lock: Callback that engages the hardware lock. No params.
        :param unlock: Callback that disengages the hardware lock. No params.
        :param locked: Callback indicating if the hardware lock is engaged. No
                    params.
        :param scanner: Callback acquiring a signal for prelock. Is passed one
                    float parameter in [0, 1] to set the relative scan range.
                    The callback should return a NumPy array of shape (n, m)
                    with:
                    - n: number of samples (usually ca. 1e3)
                    - m: number of readings per sample; must be >= 2 with the
                      first column containing the x values (tunable quantity!)
                      and all following columngs readings plotted against that
        :param scanner_range: How much quantity units does a call to
                    ``scanner(1.)`` span?
        :param tuners: A list of Tuner objects that provide control over the
                    tunable quantity.
        :param on_new_signal: Is called with every new signal acquired. It gets
                    passed the acquired data as np.ndarray.

        :raises TypeError: At least one callback is not callable.
        :raises ValueError: List of tuners is empty.
        """

        for name, callback in (("lock", lock), ("unlock", unlock),
                               ("scanner", scanner), ("locked", locked)):
            if not callable(callback):
                raise TypeError('Callback "%s" is not callable.', name)
        if not tuners:
            raise ValueError("No tuners passed.")

        self.cancel_prelock = False
        self.recent_signal = np.empty(0)  # The most recent signal acquired.
        self.range = 1.  # The range that was used for acquiring .recent_signal.

        self._locator = feature_locator.FeatureLocator()
        self._lock = lock
        self._locked = locked
        self._on_new_signal = on_new_signal
        self._prelock_running = False  # The prelock algorithm is running.
        self._scanner = scanner
        self._scanner_range = scanner_range
        self._unlock = unlock

        # Sort available tuners finest first.
        self._tuners = sorted(tuners, key=lambda t: t.granularity)

    @property
    def lock_engaged(self) -> bool:
        return self._locked()

    @property
    def min_step(self) -> QtyUnit:
        """The smallest step size (in quantity units) this class can use to do
        prelock and tuning. There is no use in trying to achieve results more
        precise than this for a given set of tuners.
        """
        return min([t.granularity * t.scale for t in self._tuners])

    @property
    def prelock_running(self) -> bool:
        return self._prelock_running


    def acquire_signal(self, rel_range: float = None) -> np.ndarray:
        """Run one scan and store the result. Lock must be disengaged.

        :param rel_range: The scan amplitude in ]0, 1]. The last used amplitude
                    is used again if `None` is given.
        :raises RuntimeError: Lock was not disengaged before.
        :raises RuntimeError: Callback threw an Exception.
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

        try:
            self.recent_signal = self._scanner(rel_range)
        except Exception as err:  # We don't know anything about the callback.
            raise RuntimeError('"scanner" Callback raised an exception.') from err

        # Notify user of new signal. Can be used for logging or monitoring.
        if callable(self._on_new_signal):
            try:
                self._on_new_signal(self.recent_signal)
            except Exception as err:  # We don't know anything about the callback.
                raise RuntimeError('"on_lock_engaged" Callback raised an exception.') from err

        return self.recent_signal

    def start_prelock(self, threshold: QtyUnit, target_position: QtyUnit,
                      proximity_callback: Callable[[], Any] = lambda: None,
                      max_tries: int = MAX_JUMPS) -> None:
        """Start the prelock algorithm and get as close as possible to target.


        As soon as we can reasonable assume to be closer than `threshold` to
        the target value, `proximity_callback` is fired.

        If the lock is currently engaged, it is going to be released!

        :param threshold: How close (in qty. units) to the target position is
                    considered close enough?
        :param target_position: How far (in qty. units) is the desired feature
                    from the left edge of the reference spectrum?
        :param proximity_callback: Must not require any arguments. Is called as
                    soon as the target has been reached, but after the
                    (optional) closed-loop lock has been engaged. Both events
                    might as well not happen if the system misbehaves.
        :param max_tries: Upper bound on iterations to use when trying to
                    undercut ``threshold``. When set to 0, this will let the
                    search run forever (even after possible success) and thus
                    lead to **blocking behaviour**, so don't do this in the
                    main thread.
        :raises RuntimeError: Desired ``threshold`` could not be undercut in
                    ``max_tries`` iterations.
        :raises RuntimeError: None of the tuners where able to compensate
                    for the measured detuning. Maybe check overall system
                    setup or consider raising ``PRELOCK_SPEED_CONSTRAINT``.
        """
        def iterate() -> bool:
            """Do one iteration of the pre-lock loop.

            This will do one jump if we're still too far from our target
            transition. If we're close already, this returns True and does not
            jump.

            :returns: Did we arrive at a distance closer than ``threshold``?

            :raises RuntimeError: None of the tuners where able to compensate
                        for the measured detuning. Maybe check overall system
                        setup or consider raising ``PRELOCK_SPEED_CONSTRAINT``.
            :raises LockBuddy._SnowblindError: There was no usable feature in
                        the scanned range. Consider raising the scan range.
            :raises LockBuddy._RivalryError: Couldn't decide for a match, as
                        options are too similar. Consider raising the scan
                        range.
            """
            self.acquire_signal(current_range)
            match_candidates = self._locator.locate_sample(
                self.recent_signal, current_range * self._scanner_range)
            # FIXME don't just use the first match blindly
            detuning = target_position - match_candidates[0][0]  # Sign already flipped for jumping.
            if abs(detuning) < threshold:
                return True
            LOGGER.debug("Jumping by %s units.", detuning)
            try:
                self.tune(detuning, PRELOCK_SPEED_CONSTRAINT)
            except ValueError as err:
                raise RuntimeError("Requested more than tuners could deliver.") from err
            return False

        static_range = 200.  # Use 200 MHz of range for now. # TODO be smart.
        current_range = static_range / self._scanner_range
        self._prelock_running = True
        self.cancel_prelock = False
        n_tries = 0
        while not self.cancel_prelock:
            n_tries += 1
            if max_tries > 0 and n_tries > max_tries:
                raise RuntimeError("Couldn't reach requested proximity in %s tries",
                                   max_tries)
            if iterate():  # raises!
                LOGGER.info("Acquired pre-lock after %s iterations.", n_tries)
                try:
                    proximity_callback()
                except Exception:  # Who knows what hell it might raise. # pylint: disable=broad-except
                    LOGGER.exception("Problem executing callback.")
                if max_tries > 0:
                    break

    async def tune(self, delta: QtyUnit, speed_constraint: float = 0) -> None:
        """Tune the system by ``delta`` quantity units and wait.

        This will choose the most appropriate tuner by itself, invoke it and
        then wait for as long as it usually takes the chosen tuner to reflect
        the change in the actual physical system.

        :param delta: The amount of quantity units to jump. Any float number
                    is legal input, although the system might reject bold
                    requests with a ValueError.
        :param speed_constraint: Don't use tuners that have delays larger than
                    this many seconds. Set to 0 to disable contraint (default).
        :raises ValueError: None of the available tuners can tune that far.
                    Note that availability of tuners is limited by
                    ``speed_constraint``.
        :raises ValueError: ``speed_constraint`` disqualifies all tuners.
        """
        # We won't tune if delta is smaller than any of the available
        # granularities.
        if not delta >= self.min_step:
            LOGGER.warning("Can't tune this fine. Ignoring.")
            return
        tuners = [t for t in self._tuners
                  if speed_constraint > 0 and t.delay < speed_constraint]
        if not tuners:
            raise ValueError("Speed constraint of {} disqualifies all tuners"
                             .format(speed_constraint))

        # Try using a single tuner first. The tuners are sorted by ascending
        # granularity, so more coarse tuners are only used if the finer tuners
        # can't provide the needed range of motion.
        for index, tuner in enumerate(tuners):
            # Skip this tuner if it doesn't have enough range left to jump by
            # ``delta``.
            target = tuner.get() + (delta / tuner.scale)
            if target < 0 or target > 1:
                LOGGER.debug("Skipping %s for insufficient range of motion.",
                             tuner.name)
                continue

            # We found a tuner that can do what we want. It might be, however,
            # that we arrived at a more coarse tuner than necessary just
            # because the finer tuners were maxed out. So instead of firing
            # this tuner straightaway, we will first check if that was the
            # case, and---if so---do a balancing operation.

            # Did we have to skip any of the finer tuners?
            if index > 0:
                compensation = .0
                for skipped_tuner in tuners[:index]:
                    state = skipped_tuner.get()
                    # Is the tuner imbalanced?
                    if state < BALANCE_AT[0] or state > BALANCE_AT[1]:
                        # How much compensation would be required
                        # downstream when resetting this tuner?
                        detuning = (state - 0.5) * skipped_tuner.scale
                        carry = detuning / tuner.scale

                        # Is there still room in the downstream tuner
                        # (``tuner``) to accommodate this compensation?
                        desired = target + compensation + carry
                        if desired >= 0 and desired <= 1:
                            compensation += carry
                            skipped_tuner.set(0.5)
                            await asyncio.sleep(skipped_tuner.delay)
                            LOGGER.debug("Balanced %s.", skipped_tuner.name)
                        else:
                            LOGGER.debug("Couldn't balance %s due to insufficient headroom in %s.",
                                         skipped_tuner.name, tuner.name)
                    else:
                        LOGGER.debug("Imbalance wasn't the reason to skip %s.",
                                     skipped_tuner.name)
            tuner.set(target + compensation)
            await asyncio.sleep(tuner.delay)
            if compensation > 0:
                LOGGER.debug("Introduced carry-over from balancing. Expect degraded performance.")
            LOGGER.debug("Tuned %s by %s units.", tuner.name, delta)
            return
        raise ValueError("Could't fulfill tuning request by means of a single tuner.")

        # Can we reach the desired jump by combining tuners?
        # TODO Try to use combined tuners. This would only be important if all
        # available tuners have a similar range of motion.
