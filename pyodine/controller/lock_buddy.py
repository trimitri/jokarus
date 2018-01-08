"""This module houses the LockBuddy class for analog lockbox management."""
import asyncio
import enum
import logging
import typing
from typing import Any, Awaitable, Callable, List, Optional, Tuple, Union

import numpy as np

from . import feature_locator
from .. import constants as cs
from ..constants import DopplerLine, LaserMhz, SpecMhz
from ..util import asyncio_tools as tools
from ..analysis import signals

LOGGER = logging.getLogger('pyodine.controller.lock_buddy')

MAX_JUMPS = 10
"""Jump ~ times before considering the pre-lock procedure failed."""

MATCH_QUALITY_THRESH = 0.7
"""How well does a sample have to fit the reference for us to even consider the
match valid?
"""
CONFIDENCE_THRESH = 0.6
"""How confident do we have to be to use and trust a match candidate? """

BALANCE_AT = [.2, .8]
"""To maintain a high tuning precision, the tuners are balanced from time to
time. Those are the thresholds beyond which a tuner is regarded as imbalanced.
It's an array [low, high] with 0 < low < high < 1.
"""

class LockError(RuntimeError):
    """Something went wrong in trying to achieve a lock."""
    pass
class SnowblindError(LockError):
    """In search for a feature, we found nothing but an empty void.

    This is a common problem with MTS spectra, as they are very "clean" and
    have long sections where they're simply == 0.

    This Error is marked private, as it's not going to rise out of the class.
    """
    pass
class DriftError(LockError):
    """System behaves in an unstable manner, possibly due to drifts."""
    pass
class _RivalryError(LockError):
    """We wanted one match but found many and no particular one sticks out.

    If there are many features in the spectrum that all look the same, then
    using only a very small sample and trying to find its position can lead to
    multiple nearly identical hits. This just happened.

    This Error is marked private, as it's not going to rise out of the class.
    """
    pass

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
class LockStatus(enum.IntEnum):
    """Asessment of the current lock situation."""
    ON_LINE = 0
    """We're likely locked to a feature."""
    RAIL = 1
    """The lockbox has railed."""
    OFF = 2
    """The lockbox is not completely engaged."""
    DEGRADED = 3
    """The lockbox is neither completely engaged nor properly switched off."""
class LockboxState(enum.IntEnum):
    """Possible states a software-configurable lockbox could be in."""
    ENGAGED = 0
    """The lockbox and all it's control stages are engaged."""
    DISENGAGED = 1
    """The lockbox and all it's control stages are disengaged."""
    DEGRADED = 2
    """The lockbox is neither completely engaged nor properly switched off."""
TunersState = typing.NamedTuple('TunersState', [('speed', float), ('value', float)])
"""State for a set of tuners.

Is currently only implemented for single tuners, not for sets of.
"""


class Tuner:
    """A means of tuning a control system's tunable quantity.

    As there are often multiple such means means, we provide a unified
    interface for such "knobs" here. All tuners linearize and scale their
    respective ranges of motion to [0, 1]. A setting of 1 must produce the
    highest possible quantity, 0 the lowest.
    """
    def __init__(self, scale: LaserMhz, granularity: float, delay: float,
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
        self.scale = LaserMhz(scale)
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

    async def get_max_jumps(self) -> Tuple[LaserMhz, LaserMhz]:
        """How far can we tune up or down from the current working point?

        :returns: Tuple like (low, high).  Tuning by +high will have you end up
                    at the upper boundary of the tuning range.  Tuning by -low
                    goes to the lower end.
        """
        current = await self.get()
        high = (1 - current) * self.scale
        low = current * self.scale
        return (LaserMhz(low), LaserMhz(high))


class LockBuddy:
    """Provide management and helper functions for closed-loop locks."""

    def __init__(self, lock: Callable[[], Awaitable[None]],
                 unlock: Callable[[], Optional[Awaitable[None]]],
                 locked: Callable[[], Union[LockboxState, Awaitable[LockboxState]]],
                 scanner: Callable[[float], Awaitable[cs.SpecScan]],
                 scanner_range: LaserMhz,
                 tuners: List[Tuner],
                 lockbox: Tuner,
                 on_new_signal: Callable[
                     [cs.SpecScan], Optional[Awaitable[None]]]=lambda _: None) -> None:
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
                    passed the acquired data as cs.SpecScan.

        :raises TypeError: At least one callback is not callable.
        :raises ValueError: List of tuners is empty.
        """

        for name, callback in (("lock", lock), ("unlock", unlock),
                               ("scanner", scanner), ("locked", locked)):
            if not callable(callback):
                raise TypeError('Callback "{}" is not callable.'.format(name))
        if not tuners:
            raise ValueError("No tuners passed.")

        self.cancel_prelock = False
        self.recent_signal = np.empty(0)  # The most recent signal acquired.
        self.range = 1.  # The range that was used for acquiring .recent_signal.

        self._locator = feature_locator.FeatureLocator()
        self._lock = lock
        self._lockbox = lockbox  # type: Tuner
        self._locked = locked
        self._loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop
        self._on_new_signal = on_new_signal
        self._prelock_running = False  # The prelock algorithm is running.
        self._scanner = scanner  # type: Callable[[float], Awaitable[cs.SpecScan]]
        self._scanner_range = scanner_range
        self._unlock = unlock

        # Sort available tuners finest first.
        self._tuners = sorted(tuners, key=lambda t: t.granularity)

    @property
    def min_step(self) -> LaserMhz:
        """The smallest step size (in quantity units) this class can use to do
        prelock and tuning. There is no use in trying to achieve results more
        precise than this for a given set of tuners.
        """
        return min([LaserMhz(t.granularity * t.scale) for t in self._tuners])

    @property
    def prelock_running(self) -> bool:
        return self._prelock_running

    async def acquire_signal(self, rel_range: float = None) -> cs.SpecScan:
        """Run one scan and store the result. Lock must be disengaged.

        :param rel_range: The scan amplitude in ]0, 1]. The last used amplitude
                    is used again if `None` is given.
        :raises RuntimeError: Lock was not disengaged before.
        :raises RuntimeError: Callback threw an Exception.
        :raises ValueError: Range is out of ]0, 1].
        """

        # To avoid inadvertent lock losses, we only allow scanning if the lock
        # is currently disengaged.
        if not await self.get_lock_status() == LockStatus.OFF:
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

    async def balance(self, equilibrium: float = 0.5) -> None:
        """Adjust available tuners to keep lockbox well within range of motion.

        :param equilibrium: Where should a perfectly balanced lockbox be
                    resting? This should be given with respect to the [0, 1]
                    lockbox control range interval.  Thus, the obvious (and
                    default) choice is 0.5.
        :raises RuntimeError: Lock is not on line.
        """
        status = await self.get_lock_status()
        if not status == LockStatus.ON_LINE:
            raise RuntimeError("Lock is {}. Refusing to balance.".format(status))

        imbalance = await self._lockbox.get() - equilibrium
        LOGGER.debug("Imbalance is %s of %s", imbalance, cs.LOCKBOX_ALLOWABLE_IMBALANCE)
        if abs(imbalance) <= cs.LOCKBOX_ALLOWABLE_IMBALANCE:
            LOGGER.debug("No need to balance lock.")
            return
        # We need to manually tune the distance that is currently maintained by
        # the lockbox output.
        distance = imbalance * self._lockbox.scale
        LOGGER.info("Balancing lock by %s units.", distance)
        await self.tune(SpecMhz(cs.LOCK_SFG_FACTOR * distance))

    async def doppler_sweep(self) -> Optional[cs.DopplerLine]:
        """Do one scan and see if there's a doppler line nearby.

        :returns: Distance to doppler line and its depth if there is a line,
                    None otherwise.
        """
        signal = await self.acquire_signal()
        try:
            return signals.locate_doppler_line(signal.transpose())
        except ValueError:
            LOGGER.debug("Didn't find a line.")
            return None

    async def doppler_search(
            self, speed_constraint: float = cs.PRELOCK_TUNER_SPEED_CONSTRAINT,
            judge: Callable[[cs.DopplerLine], Union[Awaitable[bool], bool]] = lambda _: True,
            step_size: SpecMhz = cs.PRELOCK_STEP_SIZE,
            max_range: LaserMhz = cs.PRELOCK_MAX_RANGE) -> cs.DopplerLine:
        """Search for a doppler-broadened line around current working point.

        :param speed_constraint: When tuning away from the initial working
                    point, don't use tuners that take longer than ~ seconds for
                    a jump.
        :param judge: A coroutine function that is able to say if the line it
                    got passed is the line we're searching for.  If this method
                    doesn't evaluate True, we keep searching as if no line was
                    found. This must not detune the system or if it does, undo
                    what it has done afterwards.
        :param step_size: When searching, spectral sample points will be spaced
                    this far from each other.
        :param max_range: Don't deviate further than ~ LaserMhz from initial
                    working point.  Useful in avoiding to graze through
                    multiple mode hops.
        :returns: The distance of the found line from the last active search
                    position in MHz.
        :raises ValueError: The inputs don't make sense.
        :raises SnowblindError: Didn't find a line.  Staying at last active
                    search position.  TODO: Go back where we came from.
        """
        red, blue = await self.get_max_range(speed_constraint)
        reach = (max_range if max_range
                 else cs.LOCK_SFG_FACTOR * min(max_range, max(red, blue)))
        LOGGER.debug("red: %s, blue: %s, reach: %s", red, blue, reach)

        if not red > step_size and not blue > step_size:
            raise ValueError("Not enough tuning range for that step size in "
                             "either direction.")
        if not red > step_size or not blue > step_size:
            LOGGER.warning("Edge of tuning range. Can only search in one direction.")
        if max_range:
            if max_range < step_size:
                raise ValueError("Choose bigger range for this step size.")
            if max_range > red or max_range > blue:
                LOGGER.warning("Can't search requested range in both directions.")

        # Zig-zag back and forth, gradually extending the distance to the
        # origin.
        alternate = True       # search zig-zag
        relative_position = SpecMhz(0) # distance to origin
        sign = +1              # zig or zag?
        counter = 1            # how far to jump with next zig resp. zag
        dip = await self.doppler_sweep()  # type: DopplerLine
        step = step_size
        old_tuners_state = await self.get_tuners_state(speed_constraint)
        while True:
            try:
                LOGGER.debug("Target is %s + %s = %s",
                             relative_position, step, relative_position + step)
                if abs(relative_position + step) > reach:
                    LOGGER.debug("Would exceed reach.")
                    raise ValueError
                LOGGER.debug("Is in reach. Tuning by %s.", step)
                await self.tune(step, speed_constraint)  # also raises ValueError!
                relative_position = SpecMhz(relative_position + step)
            except ValueError:
                LOGGER.debug("Couldn't tune.")
                if alternate:
                    # We hit a boundary in one direction.  If we still didn't
                    # find a line, we'll now search in the remaining direction
                    # as far as possible.
                    LOGGER.info("Switching to single-sided mode.")
                    alternate = False
                    step = SpecMhz(-1 * sign * step_size)
                    continue
                else:
                    # Even the single-sided search didn't turn anything out.
                    LOGGER.warning("Exiting single-sided mode. No match at all.")
                    break
            LOGGER.info("Searching at %s.", relative_position)
            dip = await self.doppler_sweep()
            if alternate:
                counter += 1
                sign *= -1
                step = SpecMhz(sign * counter * step_size)
            if isinstance(dip, DopplerLine):
                is_legal = await tools.async_call(judge, dip)
                LOGGER.info("Found %s, %s deep dip %s MHz from the starting position.",
                            'correct' if is_legal else 'incorrect',
                            dip.depth,
                            dip.distance + relative_position)
                if is_legal:
                    return dip

        await self.set_tuners_state(old_tuners_state)
        raise SnowblindError("Didn't find a doppler dip.")

    def engage_and_maintain(self, balance: bool = True,
                            relock: bool = True) -> asyncio.Task:
        """Engage the lock and maintain it long-term.

        :param balance: Watch the established lock for imbalance (see
                    `lock_balancer()` for details).
        :param relock: Watch the established lock for inadvertent lock losses.

        :raises LockError: The initial locking failed.

        :returns: A Task that can be used to cancel the maintenance services.
                    This task will only finish if something unexpected happens.
                    Thus, it can also be used to be notified of problems.
        """

        if not relock or not balance:
            # TODO Implement partial maintenance.
            raise NotImplementedError("Relocker and balancer are always active.")

        balancer = None  # type: asyncio.Task

        def launch_balancer() -> None:
            """Engage the balancer task in the background."""
            nonlocal balancer
            balancer = self._loop.create_task(self.start_balancer())

        async def runner() -> None:
            """The daemon that will be wrappen in a Task and returned.

            The relocker is easy to maintain.  It just runs continuously.  The
            balancer however, may fail during relock operations and thus needs
            to be restarted accordingly.

            This coroutine will only ever complete if something goes wrong or
            is cancelled.
            """
            await self._lock()
            try:
                launch_balancer()
                await self.start_relocker(on_lock_lost=balancer.cancel,
                                          on_lock_on=launch_balancer)
                balancer.cancel()
            except asyncio.CancelledError:
                LOGGER.info("Lock maintenance was cancelled.")
                balancer.cancel()
                raise

        return self._loop.create_task(runner())

    async def get_lock_status(self) -> LockStatus:
        """What status is the lock currently in?

        :returns: The current lock status.
        """
        state = await tools.safe_async_call(self._locked)
        if state == LockboxState.DISENGAGED:
            return LockStatus.OFF
        if state == LockboxState.DEGRADED:
            return LockStatus.DEGRADED
        if state == LockboxState.ENGAGED:
            level = await self._lockbox.get()
            if level < cs.LOCKBOX_RAIL_ZONE / 2 or level > 1 - (cs.LOCKBOX_RAIL_ZONE / 2):
                return LockStatus.RAIL
            return LockStatus.ON_LINE
        raise RuntimeError("Couldn't get lockbox state from callback.")

    async def get_max_range(self, speed_constraint: float = None) -> Tuple[LaserMhz, LaserMhz]:
        """How far can we tune up or down from the current working point?

        :returns: Tuple like (max_red_detuning, max_blue_detuning).
        :raises ValueError: `speed_constraint` disqualifies all tuners.
        """
        fast_tuners = self._filter_tuners(speed_constraint=speed_constraint)
        if fast_tuners:
            return await fast_tuners[0].get_max_jumps()
        raise ValueError("speed_constraint {} disqualifies all tuners.".format(speed_constraint))

    async def get_tuners_state(self, speed_constraint: float) -> TunersState:
        """Get the state of all involved tuners.

        :raises NotImplementedError: Filter leaves more than one tuner.
        """
        tuners = self._filter_tuners(speed_constraint)
        if len(tuners) > 1:
            raise NotImplementedError("State reset not implemented for multiple tuners.")
        return TunersState(value=await tuners[0].get(), speed=speed_constraint)

    async def set_tuners_state(self, state: TunersState) -> None:
        """Set the state of all involved tuners to `state`.

        :raises NotImplementedError: Would affect more than one tuner.
        """
        LOGGER.debug("Setting tuners state to %s.", state)
        tuners = self._filter_tuners(state.speed)
        if len(tuners) > 1:
            raise NotImplementedError("State reset not implemented for multiple tuners.")
        await tuners[0].set(state.value)

    async def is_correct_line(self, hint: DopplerLine = None, reset: bool = False) -> bool:
        """Are we close to the right line?

        :raises SnowblindError: We are not close to any line.
        :raises DriftError: Unable to center the dip well enough for
                    measurement.  We're possibly experiencing heavy drifts.
        """
        dip = hint if hint else await self.doppler_sweep()
        if not dip:
            raise SnowblindError("There is no line nearby.")
        state_before = await self.get_tuners_state(cs.PRELOCK_TUNER_SPEED_CONSTRAINT)
        try:
            for attempt in range(cs.PRELOCK_TUNING_ATTEMPTS):
                if abs(dip.distance) < cs.PRELOCK_TUNING_PRECISION:
                    LOGGER.info("Took %s attempts to center dip.", attempt)
                    break
                await self.tune(dip.distance, cs.PRELOCK_TUNER_SPEED_CONSTRAINT)
                dip = await self.doppler_sweep()
            else:
                raise DriftError("Unable to center doppler line.")
        finally:
            if reset:
                await self.set_tuners_state(state_before)
        return dip.depth < cs.PRELOCK_DIP_DECIDING_DEPTH

    async def start_balancer(self) -> None:
        """Watch a running lock and correct for occurring drifts."""
        status = await self.get_lock_status()
        if status != LockStatus.ON_LINE:
            raise RuntimeError("Lock is {}. Won't invoke balancer.".format(status))
        while True:
            status = await self.get_lock_status()
            if status == LockStatus.ON_LINE:
                await self.balance(cs.LOCKBOX_BALANCE_POINT)
            else:
                break
            await asyncio.sleep(cs.LOCKBOX_BALANCE_INTERVAL)
        LOGGER.warning("Lock balancer cancelled itself, as lock is %s.", status)

    async def start_prelock(self, threshold: SpecMhz, target_position: SpecMhz,
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
            :raises SnowblindError: There was no usable feature in
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
                await self.tune(SpecMhz(detuning), cs.PRELOCK_TUNER_SPEED_CONSTRAINT)
            except ValueError as err:
                raise RuntimeError("Requested more than tuners could deliver.") from err
            return False

        current_range = self._scanner_range
        self._prelock_running = True
        self.cancel_prelock = False
        n_tries = 0
        while not self.cancel_prelock:
            n_tries += 1
            if max_tries > 0 and n_tries > max_tries:
                raise RuntimeError("Couldn't reach requested proximity in "
                                   "{} tries".format(max_tries))
            if await iterate():  # raises!
                LOGGER.info("Acquired pre-lock after %s iterations.", n_tries)
                tools.safe_call(proximity_callback)
                if max_tries > 0:
                    break

    async def start_relocker(
            self, on_lock_lost: Callable[[], Any] = lambda: None,
            on_lock_on: Callable[[], Any] = lambda: None) -> None:
        """Supervise a running lock and relock whenever it gets lost.

        :param on_lock_lost: Will be called as soon as a lock rail event is
                    registered.
        :param on_lock_on: Will be called when the relock process was completed
                    after a lock loss.
        :raises RuntimeError: No sound lock to start on.
        """
        status = await self.get_lock_status()
        if status != LockStatus.ON_LINE:
            raise RuntimeError("Lock is {}. Can't invoke relocker.".format(status))

        async def relock() -> None:
            await self._unlock()
            await self._lock()

        while True:
            problem = await self.watchdog()
            if problem == LockStatus.RAIL:
                LOGGER.info("Lock was lost.  Relocking.")
                await tools.safe_async_call(on_lock_lost)
                # If this task gets cancelled during a relock attempt, make
                # sure that we end up with a locked system:
                await asyncio.shield(relock())
                await tools.safe_async_call(on_lock_on)
            else:
                break
        LOGGER.warning("Relocker is exiting due to Lock being %s.", problem)

    async def tune(self, distance: SpecMhz, speed_constraint: float = 0) -> None:
        """Tune the system by ``distance`` quantity units and wait.

        This will choose the most appropriate tuner by itself, invoke it and
        then wait for as long as it usually takes the chosen tuner to reflect
        the change in the actual physical system.

        :param distance: The amount of quantity units to jump. Any float number
                    is legal input, although the system might reject bold
                    requests with a ValueError.
        :param speed_constraint: Don't use tuners that have delays larger than
                    this many seconds. Set to 0 to disable contraint (default).
        :raises ValueError: None of the available tuners can tune that far.
                    Note that availability of tuners is limited by
                    ``speed_constraint``.
        :raises ValueError: ``speed_constraint`` disqualifies all tuners.
        """
        LOGGER.debug("Tuning %s/%s MHz...", distance, cs.LOCK_SFG_FACTOR)
        delta = LaserMhz(distance / cs.LOCK_SFG_FACTOR)
        # We won't tune if delta is smaller than any of the available
        # granularities.
        if not abs(delta) >= self.min_step:
            LOGGER.warning("Can't tune this fine %s %s. Ignoring.", delta, self.min_step)
            return
        tuners = self._filter_tuners(speed_constraint=speed_constraint)
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
                    local_state = await skipped_tuner.get()
                    # Is the tuner imbalanced?
                    if local_state < BALANCE_AT[0] or local_state > BALANCE_AT[1]:
                        # How much compensation would be required
                        # downstream when resetting this tuner?
                        detuning = (local_state - 0.5) * skipped_tuner.scale
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
            LOGGER.debug("Setting tuner %s to %s (was %s).",
                         tuner.name, target + compensation, state)
            if compensation > 0:
                LOGGER.debug("Introduced carry-over from balancing. Expect degraded performance.")
            await tuner.set(target + compensation)
            LOGGER.debug("Tuned %s by %s units.", tuner.name, delta)
            return
        raise ValueError("Could't fulfill tuning request by means of a single tuner.")

    async def watchdog(self) -> LockStatus:
        """Watch an engaged lock and return as soon as something goes wrong.

        :raises RuntimeError: The lock wasn't on line when the dog was let out.
        :returns: The new status. Most definitely not `LockStatus.ON_LINE`.
        """
        status = await self.get_lock_status()
        if status != LockStatus.ON_LINE:
            raise RuntimeError("Lock is {}. Refusing to start watchdog.".format(status))
        LOGGER.info("Starting to track engaged lock.")
        async def check() -> bool:
            """Inquire current status and save it in scope."""
            nonlocal status
            status = await self.get_lock_status()
            return status != LockStatus.ON_LINE

        await tools.poll_resource(check, cs.LOCKBOX_RAIL_CHECK_INTERVAL,
                                  name="lock watchdog")
        # For the infinite lock, this will run forever.  Otherwise we return
        # the problem.
        return status


    @staticmethod
    def _pick_match(candidates: List[List[float]], near: SpecMhz = None) -> SpecMhz:
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

        :raises SnowblindError: The provided candidates didn't include any
                    decent match or the list was empty.
        :raises _RivalryError: The matches were to similar to determine the
                    correct one.
        """
        candy = [c for c in candidates if c[1] > MATCH_QUALITY_THRESH]
        if not candy:
            raise SnowblindError("No candidates have sufficient match quality.")
        if near:
            # Prefer matches close the anticipated position.
            candy.sort(key=lambda c: abs(c[1] - near))
        for candidate in candy:
            if candidate[2] > CONFIDENCE_THRESH:
                return SpecMhz(candidate[0])

        # We couldn't determine the correct match. Why?
        if len(candidates) == 1:
            raise SnowblindError(
                "There was only one match proposed and this match was of "
                "poor quality and is probably not a real hit.")
        raise _RivalryError("There were suitable matches, but they're too "
                            "similar.")

    def _filter_tuners(self, speed_constraint: float = None) -> List[Tuner]:
        """Filter tuners and return only the ones fast enough."""
        return [t for t in self._tuners
                if not speed_constraint or t.delay < speed_constraint]
