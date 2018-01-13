"""This module encapsulates the pyodine system state into a runlevel scheme."""

import asyncio
import enum
import logging
from typing import Awaitable, List  # pylint: disable=unused-import
from . import procedures as proc
from . import daemons, subsystems
from .subsystems import Subsystems
from .lock_buddy import LockBuddy, LockStatus
from .. import constants as cs
from ..drivers.ecdl_mopa import LaserState
from ..util import asyncio_tools

LOGGER = logging.getLogger('runlevels')  # type: logging.Logger


class GLOBALS:
    """Those control variables are set directly from other modules.

    They even __need__ to be defined from other modules, as they're invalid on
    import.
    """
    loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop
    """The event loop used for scheduling background tasks.

    This can be (re-)set externally, but as it will usually be the main thread
    that is importing this module first, it is set to the default event loop
    running in the import thread at import time.
    """

    liftoff = None  # type: bool
    """Did the rocket lift off yet?"""
    microg = None  # type: bool
    """Did the lift off phase complete yet?"""
    off = None  # type: bool
    """Is an (emergency?) shutdown requested?"""
    requested_level = None  # type: Runlevel
    """Which runlevel should the system pursue?"""


class Runlevel(enum.IntEnum):
    """The incremental pyodine system state.

    There are eight possible states (including "undefined") which conveniently
    projects onto a three-bit state register.
    """
    UNDEFINED = 0  # 0 0 0
    """Not clearly in one of the other states.

    The system could currently be transitioning.  This can not be used to
    request a runstate.
    """
    SHUTDOWN = 1  # 1 0 0
    """The system is ordered to prepare for physical power-off.

    Even when requested, the system will never report being in this state.  It
    will just keep on maintaining a state as safe as possible for power-off.
    """
    STANDBY = 2  # 0 1 0
    """The system is on stand by and ready.

    Cold subsystems tests have been conducted sucessfully.  System is
    reasonably safe to switch off, although the specific measures being done
    for `SHUTDOWN` are omitted.
    """
    AMBIENT = 3  # 1 1 0
    """System is thermalized to ambient temperatures and ready to heat up.

    Although the system will eventually report being `AMBIENT` on reaching this
    level, due to changing ambient temperatures it is necessary to keep
    actively pursuing this level.  The system may drop to `UNDEFINED`
    occasionally if such drifts happen.
    """
    HOT = 4  # 0 0 1
    """All components are brought to their working temperature. Light is on!

    For tunable components (MiOB!) the full tuning range is considered valid.

    The laser is running at it's working point.  Delaying the laser power-up
    procedure until the `PRELOCK` level would lead to laser-induced temperature
    drifts at the beginning of that level.
    """
    PRELOCK = 5  # 1 0 1
    """The correct spectral line was found; system is ready to lock."""
    LOCK = 6  # 0 1 1
    """The system is locked on (the correct) HFS line."""
    BALANCED = 7  # 1 1 1
    """The working point is aligned, tuners have maximum range of motion. """


async def get_level(subs: Subsystems, locker: LockBuddy) -> Runlevel:
    """Determine current runlevel."""
    tec = await proc.get_tec_status(subs)  # type: proc.TecStatus
    laser = subs.laser.get_state()  # LaserState
    lock = await locker.get_lock_status()  # LockStatus

    if tec == proc.TecStatus.OFF and laser == LaserState.OFF:
        return Runlevel.STANDBY
    if tec == proc.TecStatus.AMBIENT and laser == LaserState.OFF:
        return Runlevel.AMBIENT
    if tec == proc.TecStatus.HOT and laser == LaserState.ON:
        return Runlevel.HOT

    # TODO: Check for "PRELOCK" runlevel.

    if (tec == proc.TecStatus.HOT and laser == LaserState.ON
            and lock == LockStatus.ON_LINE):
        if daemons.is_running(daemons.Service.DRIFT_COMPENSATOR):
            return Runlevel.BALANCED
        return Runlevel.LOCK

    return Runlevel.UNDEFINED


async def pursue_ambient(subs: Subsystems) -> None:
    """Kick-off changes that get the system closer to Runlevel.AMBIENT."""
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.release_lock(subs))
    jobs.append(proc.laser_power_down(subs))
    jobs.append(proc.pursue_tec_ambient(subs))
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def pursue_balanced(subs: Subsystems) -> None:
    await pursue_lock(subs)  # TODO Implement.


async def pursue_hot(subs: Subsystems) -> None:
    """Kick-off changes that get the system closer to Runlevel.HOT."""
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.pursue_tec_hot(subs))
    jobs.append(proc.laser_power_up(subs))
    jobs.append(proc.release_lock(subs))
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def pursue_lock(subs: Subsystems, locker: LockBuddy) -> None:
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.pursue_tec_hot(subs))
    jobs.append(proc.laser_power_up(subs))

    # Try to invoke prelocker.  As with the other procedures above, this might
    # fail depending on the system state.  But as we don't know which try will
    # eventually succeed, we're registering our attempt with the daemons
    # registry.
    if not daemons.is_running(daemons.Service.PRELOCKER):
        # FIXME review...
        prelocker = GLOBALS.loop.create_task(
            proc.prelock(subs, locker, subsystems.Tuners.MO))
        daemons.register(daemons.Service.PRELOCKER, prelocker)
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def pursue_standby(subs: Subsystems) -> None:
    """Kick-off changes that get the system closer to Runlevel.STANDBY."""
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.release_lock(subs))
    jobs.append(proc.laser_power_down(subs))
    if await proc.get_tec_status(subs) in [proc.TecStatus.AMBIENT, proc.TecStatus.OFF]:
        jobs.append(proc.tec_off(subs))
    else:
        jobs.append(proc.pursue_tec_ambient(subs))
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def request_runlevel(level: Runlevel, subs: Subsystems) -> None:
    """Send the system to runlevel `level` and return if it's there already.

    This can (and needs to be) called multiple times, usually until the desired
    runlevel is reached.

    This method might still raise errors, but it is of uttermost importance
    that the loop this is called in will catch anything, because if that loop
    fails, the system will be unresponsive to TEXUS runlevel requests.

    :param level: The level to aspire to.
    :returns: Is the system in the requested level right now?
    :raises ValueError: Unknown runlevel.
    :raises Exception: This might raise close to anything.  Be sure to catch
                it.  This would not usually be a good practice, but in this
                case, a stable program is preferrable to a debuggable one.
    """
    if level == Runlevel.UNDEFINED:
        LOGGER.warning("Runlevel `UNDEFINED` must not be requested.")
    elif level == Runlevel.SHUTDOWN:
        await pursue_standby(subs)  # TODO: flush files etc.
    elif level == Runlevel.STANDBY:
        await pursue_standby(subs)
    elif level == Runlevel.AMBIENT:
        await pursue_ambient(subs)
    elif level == Runlevel.HOT:
        await pursue_hot(subs)
    elif level == Runlevel.PRELOCK:
        await pursue_lock(subs)  # TODO: dedicated prelock stage
    elif level == Runlevel.LOCK:
        await pursue_lock(subs)
    elif level == Runlevel.BALANCED:
        await pursue_balanced(subs)
    else:
        raise ValueError("Unknown runlevel {}.".format(repr(level)))


def start_runner(subs: Subsystems) -> asyncio.Task:
    """Start continuously synchronizing system state with requested state.

    :raises RuntimerError: Globals weren't fully set.
    """
    validate_globals()  # raises
    async def iteration() -> None:
        await request_runlevel(GLOBALS.requested_level, subs)
    return GLOBALS.loop.create_task(
        asyncio_tools.repeat_task(iteration, cs.RUNLEVEL_REFRESH_INTERVAL))


def validate_globals() -> None:
    """Make sure all the globals are set.  They are not set on import."""
    for setting in [GLOBALS.liftoff, GLOBALS.microg, GLOBALS.off,
                    GLOBALS.requested_level]:
        if setting is None:
            raise RuntimeError("`runlevels.py` doesn't know the system state.")
