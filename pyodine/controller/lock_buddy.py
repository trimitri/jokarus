"""This module houses the LockBuddy class for analog lockbox management."""
import asyncio
import enum
import logging
from typing import Any, Awaitable, Callable, List, Optional, Union

import numpy as np

from . import feature_locator
from .. import constants as cs
from ..util import asyncio_tools as tools

LOGGER = logging.getLogger('pyodine.controller.lock_buddy')

ALLOWABLE_LOCK_IMBALANCE = .2
"""OK deviation of lockbox level from center position. In [0, .5].

See ``balance()`` below for details.
"""
MONITOR_INTERVAL = 22.
"""Check for lock imbalance every ~ seconds."""
MAX_JUMPS = 10
"""Jump ~ times before considering the pre-lock procedure failed."""
MATCH_QUALITY_THRESH = 0.7
"""How well does a sample have to fit the reference for us to even consider the
match valid?
"""
CONFIDENCE_THRESH = 0.6
"""How confident do we have to be to use and trust a match candidate? """
LOSS_CHECK_INTERVAL = 0.3
"""Check if the lock was lost every ~ seconds."""
LOSS_THRESH = 0.005
"""A lockbox this close to the edge of range of motion is considered lost.

Given as a relative value [0, .5[, (.01 = 1%).
"""

# 300 MHz will always put at least two features in range. TODO: Use more brain.
PRELOCK_SCAN_RANGE = 300.0

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
    a_1 = 200.  # FIXME put real value here (see script)
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

class LockError(RuntimeError):
    """Something went wrong in trying to achieve a lock."""
    pass

class _SnowblindError(LockError):
    """In search for a feature, we found nothing but an empty void.

    This is a common problem with MTS spectra, as they are very "clean" and
    have long sections where they're simply == 0.

    This Error is marked private, as it's not going to rise out of the class.
    """
    pass

class _RivalryError(LockError):
    """We wanted one match but found many and no particular one sticks out.

    If there are many features in the spectrum that all look the same, then
    using only a very small sample and trying to find its position can lead to
    multiple nearly identical hits. This just happened.

    This Error is marked private, as it's not going to rise out of the class.
    """
    pass


class Tuner:
    """A means of tuning a control system's tunable quantity.

    As there are often multiple such means means, we provide a unified
    interface for such "knobs" here. All tuners linearize and scale their
    respective ranges of motion to [0, 1]. A setting of 1 must produce the
    highest possible quantity, 0 the lowest.
    """
    def __init__(self, scale: QtyUnit, granularity: float, delay: float,
                 getter: Callable[[], Union[float, Awaitable[float]]],
                 setter: Callable[[float], Union[None, Awaitable[None]]],
                 name: str = "") -> None:
        """A tuner must scale it's full range of motion [0, 1] interval.

        :param scale: (Approximate) number of "LockBuddy units" that fit into
                    the controllers [0, 1] range. Must be >0. The range is
                    expected to be linearized.
        :param granularity: Smallest step that will make an actual difference
                    in the controlled system. This must be given relative to
                    the linearized [0, 1] range.
        :param delay: Delay in seconds between control input and actual effect
                    on the controlled quantity.
        :param getter: Callback used to get current knob position. Must use the
                    the linearized [0, 1] range. May be a coroutine function.
        :param setter: Callback used to command control input. Must accept the
                    linearized [0, 1] range. May be a coroutine function.
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

    async def get(self) -> float:
        """Get the current actual value.

        :returns: The actual current tuner value. This doesn't necessarily
                    match the set value.
        :raises RuntimeError: The callback provided as getter raised something.
        """
        return await tools.safe_async_call(self._getter)

    async def set(self, value: float) -> None:
        """Set the value to ``value``. Includes wait time.

        :param value: The value to be set. Needs to be in [0, 1] interval.

        :raises RuntimeError: The callback provided as setter raised something.
        :raises ValueError: ``value`` is not in [0, 1] interval.
        """
        if not value >= 0 or not value <= 1:
            raise ValueError("Tuners only accept values in the [0, 1] range. "
                             "{} was passed.".format(value))
        await tools.safe_async_call(self._setter, value)
        await asyncio.sleep(self.delay)


class LockBuddy:
    """Provide management and helper functions for closed-loop locks."""

    def __init__(self, lock: Callable[[], None],
                 unlock: Callable[[], None],
                 locked: Callable[[], bool],
                 scanner: Callable[[float], Awaitable[np.ndarray]],
                 scanner_range: QtyUnit,
                 tuners: List[Tuner],
                 lockbox: Tuner,
                 on_new_signal: Callable[
                     [np.ndarray], Optional[Awaitable[None]]]=lambda _: None) -> None:
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
                    ``scanner(1.)`` span? Has to be a coroutine, as it will
                    always take considerable time to fetch a signal.
        :param tuners: A list of Tuner objects that provide control over the
                    tunable quantity.
        :param lockbox: A "read-only" tuner providing the current lockbox state
                    as well as it's scale. This is needed for balancing during
                    prolonged locks. The Tuner's .set() is not used.
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
        self._lockbox = lockbox  # type: Tuner
        self._locked = locked
        self._on_new_signal = on_new_signal
        self._prelock_running = False  # The prelock algorithm is running.
        self._scanner = scanner  # type: Callable[[float], Awaitable[np.ndarray]]
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

    async def acquire_signal(self, rel_range: float = None) -> np.ndarray:
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
            self.recent_signal = await self._scanner(rel_range)
        except Exception as err:  # We don't know anything about the callback.
            raise RuntimeError('"scanner" Callback raised an exception.') from err

        await tools.safe_async_call(self._on_new_signal, self.recent_signal)
        return self.recent_signal

    async def balance(self) -> None:
        """Adjust available tuners to keep lockbox well within range of motion.

        :raises RuntimeError: Lock is not engaged, thus there's nothing to
                    balance.
        """
        if not self.lock_engaged:
            raise RuntimeError("Lock is not running.")
        imbalance = .5 - await self._lockbox.get()
        if abs(imbalance) <= ALLOWABLE_LOCK_IMBALANCE:
            LOGGER.debug("No need to balance lock.")
            return
        LOGGER.info("Imbalance is %s", imbalance)
        distance = imbalance * self._lockbox.scale
        LOGGER.info("Balancing lock by %s units.", distance)
        await self.tune(distance)

    async def is_lock_lost(self) -> bool:
        """Has the lockbox railed, indicating lock loss?

        :returns: The lock is likely to have been lost.
        :raises RuntimeError: The lock isn't running at all.
        """
        if not self.lock_engaged:
            LOGGER.warning("Lock isn't running, assuming loss of lock.")
            return True
        level = await self._lockbox.get()
        return abs(1 - level) <= LOSS_THRESH or level <= LOSS_THRESH

    async def monitor(self, when_lost: Callable[[], Optional[Awaitable[None]]]) -> None:
        """Watch an engaged lock and compensate for drifts. Runs forever.

        :param when_lost:
        :raises RuntimeError: The lock isn't running.
        """
        if not self.lock_engaged:
            raise RuntimeError("Lock is not running.")
        LOGGER.info("Starting to track lock.")
        imbalance_poller = tools.repeat_task(self.balance, MONITOR_INTERVAL,
                                             self._locked)
        lock_loss_poller = tools.poll_resource(self.is_lock_lost, LOSS_CHECK_INTERVAL,
                                               on_connect=when_lost, name="Loss of lock")
        _, pending = await asyncio.wait([imbalance_poller, lock_loss_poller],
                                        return_when=asyncio.FIRST_COMPLETED)
        # Most of the time, the second poller will abort itself soon after the
        # first one, as both check the same break condition.  In case the lock
        # gets re-enabled swiftly after a loss and before the next iteration of
        # the imbalance poller, we need to make sure however, that the other
        # poller doesn't keep running in the background.
        for future in pending:
            future.cancel()
        LOGGER.info("Stopped monitoring lock, as the lock was disabled.")

    async def start_prelock(self, threshold: QtyUnit, target_position: QtyUnit,
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
        async def iterate() -> bool:
            """Do one iteration of the pre-lock loop.

            This will do one jump if we're still too far from our target
            transition. If we're close already, this returns True and does not
            jump.

            :returns: Did we arrive at a distance closer than ``threshold``?

            :raises RuntimeError: None of the tuners where able to compensate
                        for the measured detuning. Maybe check overall system
                        setup or consider raising ``PRELOCK_SPEED_CONSTRAINT``.
            :raises _SnowblindError: There was no usable feature in
                        the scanned range. Consider raising the scan range.
            :raises _RivalryError: Couldn't decide for a match, as
                        options are too similar. Consider raising the scan
                        range.
            """
            await self.acquire_signal(current_range)
            match_candidates = self._locator.locate_sample(
                self.recent_signal, current_range * self._scanner_range)
            best_match = self._pick_match(match_candidates)  # raises!
            detuning = target_position - best_match  # Sign already flipped for jumping.
            if abs(detuning) < threshold:
                return True
            LOGGER.debug("Jumping by %s units.", detuning)
            try:
                await self.tune(detuning, PRELOCK_SPEED_CONSTRAINT)
            except ValueError as err:
                raise RuntimeError("Requested more than tuners could deliver.") from err
            return False

        current_range = PRELOCK_SCAN_RANGE / self._scanner_range
        self._prelock_running = True
        self.cancel_prelock = False
        n_tries = 0
        while not self.cancel_prelock:
            n_tries += 1
            if max_tries > 0 and n_tries > max_tries:
                raise RuntimeError("Couldn't reach requested proximity in %s tries",
                                   max_tries)
            if await iterate():  # raises!
                LOGGER.info("Acquired pre-lock after %s iterations.", n_tries)
                tools.safe_call(proximity_callback)
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
        LOGGER.debug("Tuning 2 * %s MHz...", delta)
        delta /= cs.LOCK_SFG_FACTOR
        # We won't tune if delta is smaller than any of the available
        # granularities.
        if not abs(delta) >= self.min_step:
            LOGGER.warning("Can't tune this fine %s %s. Ignoring.", delta, self.min_step)
            return
        tuners = [t for t in self._tuners
                  if speed_constraint == 0 or t.delay < speed_constraint]
        if not tuners:
            raise ValueError("Speed constraint of {} disqualifies all tuners"
                             .format(speed_constraint))

        LOGGER.debug("%s tuners left.", len(tuners))

        # Try using a single tuner first. The tuners are sorted by ascending
        # granularity, so more coarse tuners are only used if the finer tuners
        # can't provide the needed range of motion.
        for index, tuner in enumerate(tuners):
            # Skip this tuner if it doesn't have enough range left to jump by
            # ``delta``.
            state = await tuner.get()
            target = state + (delta / tuner.scale)
            LOGGER.debug("state: %s, delta: %s, delta / scale: %s", state,
                         delta, delta / tuner.scale)
            LOGGER.debug("Target of %s would be %s.", tuner.name, target)
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
            compensation = .0
            if index > 0:
                LOGGER.debug("Checking for necessity of compensation.")
                for skipped_tuner in tuners[:index]:
                    state = await skipped_tuner.get()
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
                            await skipped_tuner.set(0.5)
                            LOGGER.debug("Balanced %s.", skipped_tuner.name)
                        else:
                            LOGGER.debug("Couldn't balance %s due to insufficient headroom in %s.",
                                         skipped_tuner.name, tuner.name)
                    else:
                        LOGGER.debug("Imbalance wasn't the reason to skip %s.",
                                     skipped_tuner.name)
            LOGGER.debug("Setting tuner %s to %s (was %s).", tuner.name, target + compensation, state)
            await tuner.set(target + compensation)
            if compensation > 0:
                LOGGER.debug("Introduced carry-over from balancing. Expect degraded performance.")
            LOGGER.debug("Tuned %s by %s units.", tuner.name, delta)
            return
        raise ValueError("Could't fulfill tuning request by means of a single tuner.")

        # Can we reach the desired jump by combining tuners?  This would only
        # be important if all available tuners have a similar range of motion.
        # In our case, however, the MiOB temperature has such a vast range,
        # that combining tuners will never be necessary.
        # FEATURE

    @staticmethod
    def _pick_match(candidates: List[List[float]], near: QtyUnit = None) -> QtyUnit:
        """Evaluate a list of match candidates and pick the correct one.

        This won't always work. If no match or too many too similar matches are
        found, this will raise.

        :param candidates: The list of matches as received from
                    `FeatureLocator`'s ``locate_sample()``.
        :param near: A bias indicating where we think we are. If this is
                    specified, out of the *acceptable* matches, the one closest
                    to ``near`` is returned.
        :returns: The position of the hopefully correct match (in quantity
                    units).

        :raises _SnowblindError: The provided candidates didn't include any
                    decent match or the list was empty.
        :raises _RivalryError: The matches were to similar to determine the
                    correct one.
        """
        candy = [c for c in candidates if c[1] > MATCH_QUALITY_THRESH]
        if not candy:
            raise _SnowblindError("No candidates have sufficient match quality.")
        if near:
            # Prefer matches close the anticipated position.
            candy.sort(key=lambda c: abs(c[1] - near))
        for candidate in candy:
            if candidate[2] > CONFIDENCE_THRESH:
                return candidate[0]

        # We couldn't determine the correct match. Why?
        if len(candidates) == 1:
            raise _SnowblindError(
                "There was only one match proposed and this match was of "
                "poor quality and is probably not a real hit.")
        raise _RivalryError("There were suitable matches, but they're too "
                            "similar.")
