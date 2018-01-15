"""This module encapsulates the pyodine system state into a runlevel scheme."""

import asyncio
import enum
from functools import partial
import logging
from typing import Awaitable, List  # pylint: disable=unused-import
from . import procedures as proc
from . import daemons, subsystems
from .lock_buddy import LockStatus
from .. import constants as cs
from ..globals import GLOBALS as GL
from ..drivers.ecdl_mopa import LaserState
from ..util import asyncio_tools as tools

LOGGER = logging.getLogger('runlevels')  # type: logging.Logger


class REQUEST:  # pylint: disable=too-few-public-methods
    """Those control variables are set directly from other modules.

    They even __need__ to be defined from other modules, as they're invalid on
    import.
    """
    liftoff = None  # type: bool
    """Did the rocket lift off yet?"""
    microg = None  # type: bool
    """Did the lift off phase complete yet?"""
    off = None  # type: bool
    """Is an (emergency?) shutdown requested?"""
    level = None  # type: Runlevel
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


async def get_level() -> Runlevel:
    """Determine current runlevel."""
    try:
        tec = await proc.get_tec_status()  # type: proc.TecStatus
    except proc.TecError:
        LOGGER.error("Couldn't get TEC status")
        LOGGER.debug("Couldn't get TEC status", exc_info=True)
        return Runlevel.UNDEFINED

    laser = GL.subs.laser.get_state()  # LaserState

    if tec == proc.TecStatus.OFF and laser == LaserState.OFF:
        return Runlevel.STANDBY

    if tec == proc.TecStatus.AMBIENT and laser == LaserState.OFF:
        return Runlevel.AMBIENT

    if tec == proc.TecStatus.HOT and laser == LaserState.ON:
        if daemons.is_running(daemons.Service.DRIFT_COMPENSATOR):
            return Runlevel.BALANCED

        if daemons.is_running(daemons.Service.LOCKER):
            return Runlevel.LOCK

        if daemons.is_running(daemons.Service.PRELOCKER):
            return Runlevel.PRELOCK

        return Runlevel.HOT

    return Runlevel.UNDEFINED


async def pursue_ambient() -> None:
    """Kick-off changes that get the system closer to Runlevel.AMBIENT."""
    LOGGER.debug('Pursuing "AMBIENT" runlevel.')
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.release_lock())
    jobs.append(proc.laser_power_down())
    jobs.append(proc.pursue_tec_ambient())
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def pursue_balanced() -> None:
    """Kick-off changes that get the system closer to Runlevel.BALANCED. """
    LOGGER.debug('Pursuing "BALANCED" runlevel.')
    if daemons.is_running(daemons.Service.LOCKER):
        if daemons.is_running(daemons.Service.DRIFT_COMPENSATOR):
            LOGGER.debug("Drift compensator is already running.")
        else:
            daemons.register(daemons.Service.DRIFT_COMPENSATOR,
                             GL.loop.create_task(proc.compensate_temp_drifts()))
    else:
        await pursue_lock()


async def pursue_hot() -> None:
    """Kick-off changes that get the system closer to Runlevel.HOT."""
    LOGGER.debug('Pursuing "HOT" runlevel.')
    daemons.cancel(daemons.Service.PRELOCKER)
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.pursue_tec_hot())
    jobs.append(proc.laser_power_up())
    jobs.append(proc.release_lock())
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def pursue_lock() -> None:
    """Kick-off changes that get the system closer to Runlevel.LOCK."""
    LOGGER.debug('Pursuing "LOCK" runlevel.')
    daemons.cancel(daemons.Service.DRIFT_COMPENSATOR)
    # Prelocker is cancelled in `pursue_runlevel()`.
    if daemons.is_running(daemons.Service.LOCKER):
        LOGGER.debug("Currently locked.  Doing nothing.")
        return
    daemons.register(daemons.Service.LOCKER,
                     GL.loop.create_task(_lock_runner()))
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.pursue_tec_hot())
    jobs.append(proc.laser_power_up())
    jobs.append(proc.release_lock())
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def pursue_prelock() -> None:
    """Kick-off changes that get the system closer to Runlevel.PRELOCK."""
    LOGGER.debug('Pursuing "PRELOCK" runlevel.')
    jobs = []  # type: List[Awaitable[None]]
    jobs.append(proc.pursue_tec_hot())
    jobs.append(proc.laser_power_up())
    jobs.append(proc.release_lock())

    # Try to invoke prelocker.  As with the other procedures above, this might
    # fail depending on the system state.  But as we don't know which try will
    # eventually succeed, we're registering our attempt with the daemons
    # registry.
    if not daemons.is_running(daemons.Service.PRELOCKER):
        daemons.register(daemons.Service.PRELOCKER,
                         GL.loop.create_task(_prelock_runner()))
        # NOTE: The daemon is cancelled upstream, in `pursue_runlevel()`.
    await asyncio.wait(jobs, timeout=cs.RUNLEVEL_PURSUE_KICKOFF_TIMEOUT)


async def pursue_runlevel() -> None:
    """Kick off changes getting the system closer to the requested runlevel.

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
    level = REQUEST.level
    LOGGER.debug("pursue_runlevel(%s) called.", level)

    # This avoids having to add these lines to all the pursue_  functions().
    if level != Runlevel.PRELOCK:
        daemons.cancel(daemons.Service.PRELOCKER)
    if level != Runlevel.BALANCED:
        daemons.cancel(daemons.Service.DRIFT_COMPENSATOR)


    if level == Runlevel.UNDEFINED:
        LOGGER.warning("Runlevel `UNDEFINED` must not be requested.")
    elif level == Runlevel.SHUTDOWN:
        await pursue_standby()  # TODO: flush files etc.
    elif level == Runlevel.STANDBY:
        await pursue_standby()
    elif level == Runlevel.AMBIENT:
        await pursue_ambient()
    elif level == Runlevel.HOT:
        await pursue_hot()
    elif level == Runlevel.PRELOCK:
        await pursue_prelock()
    elif level == Runlevel.LOCK:
        await pursue_lock()
    elif level == Runlevel.BALANCED:
        await pursue_balanced()
    else:
        raise ValueError("Unknown runlevel {}.".format(repr(level)))


async def pursue_standby() -> None:
    """Kick-off changes that get the system closer to Runlevel.STANDBY."""
    LOGGER.debug('Pursuing "STANDBY" runlevel.')
    current = await get_level()
    if current == Runlevel.STANDBY:
        LOGGER.debug("Already on STANDBY.")
        return
    if current == Runlevel.AMBIENT:
        LOGGER.debug("System is AMBIENT, going to STANDBY now.")
        await proc.tec_off()
    else:
        await pursue_ambient()


async def start_runner() -> None:
    """Start continuously synchronizing system state with requested state.

    :raises RuntimerError: Globals weren't fully set.
    """
    _validate_request()  # raises
    await tools.repeat_task(pursue_runlevel, min_wait_time=cs.RUNLEVEL_REFRESH_INTERVAL)


async def _lock_runner() -> None:
    """The continuous lock maintenance runner.

    This will start prelock again, if lock is lost.
    """
    if await GL.locker.get_lock_status() != LockStatus.ON_LINE:
        LOGGER.info("Running prelock for lock.")
        await proc.prelock(subsystems.Tuners.MO)  # raises on failure
        LOGGER.info("Engaging lock.")
        await GL.locker.engage_and_maintain()
        LOGGER.info("Failed lock.")


async def _prelock_runner() -> None:
    """The continuous prelock-only runner."""
    # Repeat prelock process some seconds after it has completed.
    await tools.repeat_task(partial(proc.prelock, subsystems.Tuners.MO),
                            min_wait_time=cs.PRELOCK_REST_PERIOD)


def _validate_request() -> None:
    """Make sure all the globals are set.  They are not set on import."""
    for setting in [REQUEST.liftoff, REQUEST.microg, REQUEST.off, REQUEST.level]:
        if setting is None:
            raise RuntimeError("`runlevels.py` doesn't know the system state.")
