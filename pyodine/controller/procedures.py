"""This module provides predefined sequences. Methods never throw exceptions.

It includes power-on, reset and teardown procedures as well as running actual
experiments, such as establishing and monitoring locks.
"""
import asyncio
import base64
import enum
from functools import partial
import logging
import time
from typing import Any, Dict, List, NamedTuple

import aioconsole

from . import lock_buddy, subsystems
from ..pyodine_globals import GLOBALS as GL
from .. import constants as cs
from .. import logger
from ..util import asyncio_tools as tools
from ..drivers.ecdl_mopa import LaserState

LOGGER = logging.getLogger('procedures')

class TecStatus(enum.IntEnum):
    """Status of the thermoelectric cooling subsystem."""

    UNDEFINED = 10
    """Everything that is not covered by the other cases (e.g. "off")."""

    AMBIENT = 20
    """MiOB and SHG TECs are on and set to ambient temperature. VHBG is off.

    Note that the system may change from AMBIENT to UNDEFINED whenever the housing
    temperature changes.
    """

    HEATING = 30
    """Ramp target temperatures lie within working range, but not HOT.

    This also checks for actually running ramps, so this will most definitely
    lead to HOT.  VHBG is not checked at all.
    """

    HOT = 40
    """All actual object temperatures and ramp targets are in working range.

    This checks for VHBG as well. All TECs are on. The laser must not run in
    any state except this one.
    """

    OFF = 50
    """All TECs are off.  Object temps are unknown due to inferior hardware."""

PrelockResult = NamedTuple('PrelockResult', [('time', float),
                                             ('signal', cs.DopplerLine)])
"""Information about a completed prelock run."""

class StateError(RuntimeError):
    """Something is unsafe or not possible in the current system state."""
    pass
class TecError(RuntimeError):
    """Something went wrong with the thermoelectric cooling subsystem."""
    pass
class TecStatusError(RuntimeError):
    """The system is in the wrong `TecStatus` for this action."""
    pass


async def compensate_temp_drifts() -> None:
    """Keep the MO current in the center of its range of motion.

    .. NOTE::
        This will only work on an engaged lock.  It may thus fail if the lock
        is relocking *just now*.

    :param loop: Event loop to use for scheduling.
    :raises LockError: Lock wasn't engaged initially.
    """
    async def balancer() -> None:
        """Balance now once, if necessary."""
        current = subsystems.Tuners.MO
        mo_imbalance = cs.SpecMhz(
            cs.LOCK_SFG_FACTOR * (await current.get() - 0.5) * current.scale)
        if abs(mo_imbalance) > cs.PRELOCK_TUNING_PRECISION:
            LOGGER.info("Tuning MiOB by %s MHz to balance MO current.", mo_imbalance)
            await GL.locker.tune(mo_imbalance, subsystems.Tuners.MIOB)

    async def condition() -> bool:
        """Does balancing still make sense?"""
        return await GL.locker.get_lock_status() == lock_buddy.LockStatus.ON_LINE

    if not await condition():
        LOGGER.debug("Can only compensate running locks. Aborting.")
        return

    await tools.repeat_task(balancer, period=0.6, do_continue=condition)
    LOGGER.warning("Stopped temp drift compensator, as lock is %s.",
                   await GL.locker.get_lock_status())


async def engage_lock() -> None:
    """Run the timed procedure needed to engage the frequency lock."""
    LOGGER.info("proc.engage_lock")
    GL.subs.switch_pii_ramp(False)
    GL.subs.switch_lock(True)
    await asyncio.sleep(cs.LOCKBOX_P_TO_I_DELAY)
    GL.subs.switch_integrator(2, True)
    await asyncio.sleep(cs.LOCKBOX_I_TO_I_DELAY)
    GL.subs.switch_integrator(1, True)
    await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)


async def get_tec_status() -> TecStatus:
    """Analyze the current TEC subsystem status.

    side effect
        This will initialize all temp. ramps on units that are active but have
        an undefined ramp state.

    :raises TecError: Couldn't get ambient temperatures.
    """
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    tec = subsystems.TecUnit
    temps = await GL.subs.get_aux_temps(dont_log=True)
    try:
        ambient = _get_ambient_temps(temps)
    except ConnectionError as err:
        raise TecError("Couldn't get ambient temps.") from err
    except ValueError as err:
        raise TecError("Ambient temps out of range.") from err
    assert all([ambient[tec.SHGA], ambient[tec.SHGB], ambient[tec.MIOB]])

    is_on = {}  # type: Dict[subsystems.TecUnit, bool]
    ramp_on = {}  # type: Dict[subsystems.TecUnit, bool]
    obj_temp = {}  # type: Dict[subsystems.TecUnit, float]
    raw_setpt = {}  # type: Dict[subsystems.TecUnit, float]
    ramp_setpt = {}  # type: Dict[subsystems.TecUnit, float]
    for unit in tec:
        is_on[unit] = GL.subs.is_tec_enabled(unit)
        ramp_on[unit] = GL.subs.is_temp_ramp_enabled(unit)
        obj_temp[unit] = GL.subs.get_temp(unit)
        raw_setpt[unit] = GL.subs.get_temp_setpt(unit)
        ramp_setpt[unit] = GL.subs.get_temp_ramp_target(unit)

    if not any(is_on.values()):
        return TecStatus.OFF

    LOGGER.debug("Not OFF")

    if not all([is_on[unit] for unit in [tec.SHGA, tec.SHGB, tec.MIOB]]):
        # Unexpected number of TECs are active.
        return TecStatus.UNDEFINED

    # If we just launched pyodine and connected to an already running system,
    # it may well be that everything is fine and the only thing left to do is
    # to initialize the temp ramps, which we will do here.
    for unit in tec:
        if is_on[unit]:
            if not ramp_setpt[unit]:
                GL.subs.set_temp(unit, raw_setpt[unit])
                await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
                GL.subs.switch_temp_ramp(unit, True)

    LOGGER.debug("Base TECs OK, ramps on and set..")


    # Check for legit "HOT" state.  We always do all the checks as it's cheap
    # and easier to read.
    legit = True
    # VHBG
    legit = is_on[tec.VHBG]
    for temp in [obj_temp[tec.VHBG], raw_setpt[tec.VHBG]]:
        if _is_hot_vhbg(temp):
            LOGGER.debug("VHBG temps OK.")
        else:
            legit = False
            LOGGER.debug("VHBG temps NOT OK.")

    # MiOB
    for temp in [obj_temp[tec.MIOB], raw_setpt[tec.MIOB]]:
        if _is_hot_miob(temp):
            LOGGER.debug("MIOB temps OK.")
        else:
            legit = False
            LOGGER.debug("MIOB temps NOT OK.")

    # SHGs
    for temp in [obj_temp[tec.SHGA], raw_setpt[tec.SHGA],
                 obj_temp[tec.SHGB], raw_setpt[tec.SHGB]]:
        if _is_hot_shg(temp):
            LOGGER.debug("SHG temps OK.")
        else:
            legit = False
            LOGGER.debug("SHG temps NOT OK.")
    if legit:
        return TecStatus.HOT

    LOGGER.debug("Not legit HOT")

    # Check for "HEATING" state.
    if all([_is_hot_shg(ramp_setpt[tec.SHGA]), is_on[tec.SHGA],
            _is_hot_shg(ramp_setpt[tec.SHGB]), is_on[tec.SHGB],
            _is_hot_miob(ramp_setpt[tec.MIOB]), is_on[tec.MIOB]]):
        return TecStatus.HEATING

    LOGGER.debug("not HEATING")

    # Check for "AMBIENT" state.
    # MiOB and SHG TECs are all on (is checked above).
    if is_on[tec.VHBG]:
        return TecStatus.UNDEFINED
    for unit in [tec.SHGA, tec.SHGB, tec.MIOB]:
        for temp in obj_temp[unit], ramp_setpt[unit], raw_setpt[unit]:
            if abs(temp - ambient[unit]) > cs.TEMP_GENERAL_ERROR:
                return TecStatus.UNDEFINED

    return TecStatus.AMBIENT
    # pylint: enable=too-many-return-statements
    # pylint: enable=too-many-branches


async def pursue_tec_hot() -> None:
    """Get the system closer to `TecStatus.HOT` state.

    If the system is anything but TecStatus.HOT, HEATING or AMBIENT, take a
    detour through pursuing AMBIENT first.
    """
    status = await get_tec_status()
    if status == TecStatus.HOT:
        LOGGER.debug("System is hot, nothing to do.")
        return
    if status in (TecStatus.UNDEFINED, TecStatus.OFF):
        await pursue_tec_ambient()
        return
    if status in (TecStatus.HEATING, TecStatus.AMBIENT):
        LOGGER.info("System is %s. Running `heat_up()`...", status)

    # VHBG plays a special role, as it can only be heated after the MiOB
    # finishes.
    vhbg = subsystems.TecUnit.VHBG
    GL.subs.set_temp(vhbg, cs.VHBG_WORKING_TEMP)
    # If it's running, that's fine. If not, it doesn't do anything.

    if GL.subs.is_tec_enabled(vhbg):
        GL.subs.switch_temp_ramp(vhbg, True)
    else:
        miob_temp = GL.subs.get_temp(subsystems.TecUnit.MIOB)
        if _is_hot_miob(miob_temp):
            LOGGER.info("Heating VHBG...")
            GL.subs.set_temp(vhbg, miob_temp, bypass_ramp=True)
            await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
            GL.subs.switch_tec_by_id(vhbg, True)
            await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
            GL.subs.switch_temp_ramp(vhbg, True)
        else:
            LOGGER.warning("Can't heat VHBG, as MiOB is not yet in working range.")

    # The others are simple, as get_tec_status() has checked everything before.
    miob_target = (cs.MIOB_TEMP_TUNING_RANGE[0] + cs.MIOB_TEMP_TUNING_RANGE[1]) / 2
    GL.subs.set_temp(subsystems.TecUnit.MIOB, miob_target)
    GL.subs.set_temp(subsystems.TecUnit.SHGA, cs.SHGA_WORKING_TEMP)
    GL.subs.set_temp(subsystems.TecUnit.SHGB, cs.SHGB_WORKING_TEMP)


def init_locker() -> lock_buddy.LockBuddy:
    """Initialize the frequency prelock and lock system."""

    # Store tuners as "globals" (into subsystems) for other modules to use.
    subsystems.Tuners.MO = _spawn_current_tuner()
    subsystems.Tuners.MIOB = _spawn_miob_tuner()

    # The lockbox itself has to be wrapped like a Tuner, as it does
    # effectively tune the laser. All values associated with setting stuff can
    # be ignored though ("1"'s and lambda below).
    lock = cs.LOCKBOX_RANGE_mV
    lock_range = lock[1] - lock[0]
    def lockbox_getter() -> float:
        return (lock[1] - GL.subs.get_lockbox_level()) / lock_range

    lockbox = lock_buddy.Tuner(
        scale=cs.LaserMhz(abs(lock_range * cs.LOCKBOX_MHz_mV)),
        granularity=.42,  # not used
        delay=42,  # not used
        getter=lockbox_getter,
        setter=lambda _: None,  # not used
        name="Lockbox")

    # Log and publish all acquired signals.
    async def on_new_signal(data: cs.SpecScan) -> None:
        """Logs the received array as base64 string and publishes."""

        await GL.face.publish_error_signal(data)

        data_type = str(data.dtype)
        shape = str(data.shape)
        values = base64.b64encode(data).decode()  # base64-encoded str()
        logger.log_quantity(
            'spectroscopy_signal', data_type + '\t' + shape + '\t' + values)


    def nu_locked() -> lock_buddy.LockboxState:
        """What state is the lockbox in?

        :raises ConnectionError: State cannot be determined (yet).
        """
        if (GL.subs.nu_locked()
                and GL.subs.lockbox_integrators_enabled()
                and not GL.subs.is_lockbox_ramp_enabled()):
            return lock_buddy.LockboxState.ENGAGED
        if (not GL.subs.nu_locked()
                and GL.subs.lockbox_integrators_disabled()
                and GL.subs.is_lockbox_ramp_enabled()):
            return lock_buddy.LockboxState.DISENGAGED
        return lock_buddy.LockboxState.DEGRADED

    # Assemble the actual lock buddy using the tuners above.
    GL.locker = lock_buddy.LockBuddy(
        lock=engage_lock,
        unlock=release_lock,
        locked=nu_locked,
        lockbox=lockbox,
        scanner=GL.subs.fetch_scan,
        scanner_range=cs.LaserMhz(700),  # FIXME measure correct scaling coefficient.
        on_new_signal=on_new_signal)
    return GL.locker


async def laser_power_up() -> None:
    """Switch on the laser.

    After running this, the laser power may be adjusted through the PA current,
    the frequency through MO current.

    :raises ConnectionError: Lighting up failed.
    """
    state = GL.subs.laser.get_state()
    if state == LaserState.ON:
        LOGGER.debug("Laser is already ON. Doing nothing.")
        return
    if state == LaserState.UNDEFINED:
        LOGGER.error("Laser was UNDEFINED switching off instead of on.")
        await laser_power_down()
        return

    try:
        await _ensure_system_is(TecStatus.HOT)
    except TecStatusError:
        LOGGER.debug("couldn't power up laser:", exc_info=True)
        return
    LOGGER.info("Powering up laser...")
    GL.subs.switch_ld(subsystems.LdDriver.MASTER_OSCILLATOR, True)
    GL.subs.switch_ld(subsystems.LdDriver.POWER_AMPLIFIER, True)
    GL.subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, cs.MILAS_PA_IDLE)
    await asyncio.sleep(cs.MENLO_CURRENT_DRIVER_REALIZATION_WAIT)
    mo_working_point = (cs.LD_MO_TUNING_RANGE[0] + cs.LD_MO_TUNING_RANGE[1]) / 2
    GL.subs.set_current(subsystems.LdDriver.MASTER_OSCILLATOR, mo_working_point)
    await asyncio.sleep(cs.MENLO_CURRENT_DRIVER_REALIZATION_WAIT)
    GL.subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, cs.MILAS_PA_WORKING_POINT)

    if GL.subs.laser.get_state() != LaserState.ON:
        raise ConnectionError("Failed to switch on Laser.")


async def laser_power_down() -> None:
    """Shut down and switch off laser.

    :raises ConnectionError: Failed to switch off laser.
    """
    if GL.subs.laser.get_state() == LaserState.OFF:
        LOGGER.info("Laser is already OFF. Doing nothing.")
        return
    LOGGER.info("Powering down laser...")
    GL.subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, cs.MILAS_PA_IDLE)
    await asyncio.sleep(cs.MENLO_CURRENT_DRIVER_REALIZATION_WAIT)
    GL.subs.switch_ld(subsystems.LdDriver.MASTER_OSCILLATOR, False)
    await asyncio.sleep(cs.MENLO_CURRENT_DRIVER_REALIZATION_WAIT)
    GL.subs.switch_ld(subsystems.LdDriver.POWER_AMPLIFIER, False)
    await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)

    if GL.subs.laser.get_state() != LaserState.OFF:
        raise ConnectionError("Failed to switch off Laser.")


def open_backdoor(injected_locals: Dict[str, Any]) -> None:
    """Provide a python interpreter capable of probing the system state."""

    # Provide a custom factory to allow for `locals` injection.
    def console_factory(streams: Any = None) -> aioconsole.AsynchronousConsole:
        return aioconsole.AsynchronousConsole(locals=injected_locals,
                                              streams=streams)
    asyncio.ensure_future(
        aioconsole.start_interactive_server(factory=console_factory))


async def prelock(prelock_tuner: lock_buddy.Tuner) -> PrelockResult:
    """Run the pre-lock algorithm."""
    await _ensure_system_is(TecStatus.HOT)
    _ensure_laser_is(LaserState.ON)
    await _ensure_lock_is(lock_buddy.LockStatus.OFF)

    dip = await GL.locker.doppler_search(
        prelock_tuner, judge=partial(GL.locker.is_correct_line, prelock_tuner, reset=True))
    for attempt in range(cs.PRELOCK_TUNING_ATTEMPTS):
        error = cs.SpecMhz(dip.distance - cs.PRELOCK_DIST_SWEET_SPOT_TO_DIP)
        if abs(error) < cs.PRELOCK_TUNING_PRECISION:
            LOGGER.info("Took %s jumps to align dip.", attempt)
            break
        await GL.locker.tune(error, prelock_tuner)
        dip = await GL.locker.doppler_sweep()
    else:
        raise lock_buddy.DriftError("Unable to center doppler line.")
    return PrelockResult(time=time.time(), signal=dip)


async def pursue_tec_ambient() -> None:
    """Do what can be done right now to get system to ambient temperature.

    This can be used to cool down before switching off or to arm the TEC system
    before heating up.

    When cooling down, this must be called at least twice.  It is thus
    recommended to call it "watchdog style" until `get_tec_status()` returns
    "AMBIENT".
    """
    _ensure_laser_is(LaserState.OFF)
    status = await get_tec_status()
    if status == TecStatus.AMBIENT:
        LOGGER.debug("Refusing to run `tec_standby()`, as system is AMBIENT already.")
        return

    ambient = _get_ambient_temps(await GL.subs.get_aux_temps())
    await _set_to_ambient(subsystems.TecUnit.SHGA, ambient)
    await _set_to_ambient(subsystems.TecUnit.SHGB, ambient)

    # If VHBG is live, we can't do anything but cool it down first.  If it's
    # dead, we act on MiOB.
    if GL.subs.is_tec_enabled(subsystems.TecUnit.VHBG):
        await _land_vhbg()
    else:
        await _set_to_ambient(subsystems.TecUnit.MIOB, ambient)


async def release_lock() -> None:
    """Release the laser from frequency lock."""
    status = await GL.locker.get_lock_status()
    if status == lock_buddy.LockStatus.OFF:
        LOGGER.debug("Lock is off already, doing nothing.")
        return
    GL.subs.switch_lock(False)
    GL.subs.switch_pii_ramp(True)
    GL.subs.switch_integrator(1, False)
    GL.subs.switch_integrator(2, False)
    await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)


async def tec_off() -> None:
    """Switch off all temperature control if possible.

    This is only allowed, if the system is `TecStatus.AMBIENT`.
    """
    if await get_tec_status() == TecStatus.OFF:
        LOGGER.debug("""Won't "tec_off()", as system is OFF already.""")
        return
    try:
        await _ensure_system_is(TecStatus.AMBIENT)  # raises
    except TecStatusError:
        LOGGER.debug("""Can't "tec_off()", as system is not AMBIENT.""")
        return
    tecs = subsystems.TecUnit
    for unit in tecs.SHGA, tecs.SHGB, tecs.MIOB:
        GL.subs.switch_temp_ramp(unit, False)
        GL.subs.switch_tec_by_id(unit, False)

###############
##  private  ##
###############

def _ensure_laser_is(state: LaserState) -> None:
    """Ensure that Laser is off before doing automated TEC stuff.

    :raises StateError: Laser is not `LaserState.OFF`.
    """
    laser_state = GL.subs.laser.get_state()  # type: LaserState
    if laser_state != state:
        raise StateError("Won't do thing, as laser is {}.".format(repr(laser_state)))


async def _ensure_lock_is(status: lock_buddy.LockStatus) -> None:
    """Ensure that the lockbox status is `status` and raise otherwise.

    :raises StateError: Lockbox is not is not `status`.
    """
    lb_status = await GL.locker.get_lock_status()  # type: lock_buddy.LockStatus
    if lb_status != status:
        raise StateError("Lockbox is {}, refusing to do thing.".format(repr(lb_status)))


async def _ensure_system_is(status: TecStatus) -> None:
    """Ensure that the TEC subsystem status is `status` and raise otherwise.

    :raises TecStatusError: System is not `status`.
    """
    tec_status = await get_tec_status()  # type: TecStatus
    if tec_status != status:
        raise TecStatusError(
            "TEC system is {}, refusing to do thing.".format(repr(tec_status)))


def _get_ambient_temps(temps: List[float]) -> Dict[subsystems.TecUnit, float]:
    """Get (and judge) ambient temp readings for TEC operation.

    :returns: Dict of two temperatures to use for SHGs and MIOB. VHBG has no "ambient".
    :raises ConnectionError: Temperature readings are not consistent.
    :raises ValueError: At least one ambient temp is out of safe bounds for the
                respective component.
    """
    assert len(temps) == len(subsystems.AuxTemp)
    ambient = {}  # type: Dict[subsystems.TecUnit, float]

    # MiOB
    candidate = temps[subsystems.AuxTemp.HEATSINK_A]
    second = temps[subsystems.AuxTemp.HEATSINK_B]
    if abs(candidate - second) > cs.TEMP_LASER_TRAY_DELTA:
        raise ConnectionError("Erroneous laser tray temp reading {}.".format(candidate))
    if (candidate < cs.TEMP_HEATSINK_RANGE_LASER[0]
            or candidate > cs.TEMP_HEATSINK_RANGE_LASER[1]):
        raise ValueError("Laser tray temperature {} out of safe range.".format(candidate))
    ambient[subsystems.TecUnit.MIOB] = candidate

    # SHGs
    candidate = temps[subsystems.AuxTemp.SHG]
    second = temps[subsystems.AuxTemp.CELL]
    if abs(candidate - second) > cs.TEMP_SPEC_TRAY_DELTA:
        raise ConnectionError("Erroneous spec tray temp reading {}".format(candidate))
    if (candidate < cs.TEMP_HEATSINK_RANGE_SPEC[0]
            or candidate > cs.TEMP_HEATSINK_RANGE_SPEC[1]):
        raise ValueError("Spec tray temperature {} out of safe range.".format(candidate))
    ambient[subsystems.TecUnit.SHGA] = candidate
    ambient[subsystems.TecUnit.SHGB] = candidate

    return ambient


def _is_hot_shg(temp: float) -> bool:
    """Is `temp` a valid temperature for a "hot" SHG module?"""
    if not temp:
        return False
    mean_temp = (cs.SHGA_WORKING_TEMP + cs.SHGB_WORKING_TEMP) / 2
    return (temp > mean_temp - cs.TEMP_GENERAL_ERROR
            and temp < mean_temp + cs.TEMP_GENERAL_ERROR)


def _is_hot_vhbg(temp: float) -> bool:
    """Is `temp` a valid temperature for a "hot" VHBG?"""
    if not temp:
        return False
    return (temp > cs.VHBG_WORKING_TEMP - cs.TEMP_GENERAL_ERROR
            and temp < cs.VHBG_WORKING_TEMP + cs.TEMP_GENERAL_ERROR)


def _is_hot_miob(temp: float) -> bool:
    """Is `temp` a valid temperature for a "hot" MiOB?"""
    if not temp:
        return False
    return (temp > cs.MIOB_TEMP_TUNING_RANGE[0] - cs.TEMP_GENERAL_ERROR
            and temp < cs.MIOB_TEMP_TUNING_RANGE[1] + cs.TEMP_GENERAL_ERROR)


async def _land_vhbg() -> None:
    """Bring VHBG back to MiOB temperature or switch off if there already.

    Similar to the `_pursue...()` family of methods, this encapsulates a
    multi-step process and thus may need to be called multiple times to reach
    the desired effect.

    before (has not yet been called)
        VHBG TEC is on.  MiOB TEC is active.

    after (has been called until _is_vhbg_airborne() returns true)
        VHBG TEC is off.  MiOB TEC still active.
    """
    _ensure_laser_is(LaserState.OFF)
    vhbg = subsystems.TecUnit.VHBG
    miob = subsystems.TecUnit.MIOB
    if not GL.subs.is_tec_enabled(vhbg):
        LOGGER.info("""Refusing to "land" VHBG TEC, as it is off already.""")
        return

    if GL.subs.is_tec_enabled(miob):
        target_temp = GL.subs.get_temp(miob)
    else:
        target_temp = _get_ambient_temps(await GL.subs.get_aux_temps())[miob]

    if abs(GL.subs.get_temp(vhbg) - target_temp) < cs.TEMP_GENERAL_ERROR:
        LOGGER.info("VHBG temp. is close to MiOB. Switching off TEC.")
        GL.subs.switch_temp_ramp(vhbg, False)
        GL.subs.switch_tec_by_id(vhbg, False)
    else:
        LOGGER.info("Getting VHBG close to MiOB for shutdown...")
        GL.subs.set_temp(vhbg, target_temp)
        await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
        GL.subs.switch_temp_ramp(vhbg, True)


async def _launch_vhbg() -> None:
    """If MiOB is hot, start VHBG TEC and raise to target temp.

    Will do nothing if MiOB is anything but live.
    """
    _ensure_laser_is(LaserState.OFF)
    miob = subsystems.TecUnit.MIOB
    vhbg = subsystems.TecUnit.VHBG
    miob_temp = GL.subs.get_temp(miob)
    if not all([_is_hot_miob(temp) for temp
                in [miob_temp, GL.subs.get_temp_setpt(miob),
                    GL.subs.get_temp_ramp_target(miob)]]):
        LOGGER.warning("Refusing to detach VHBG, as MiOB isn't live.")
        return
    if not GL.subs.is_tec_enabled(vhbg):
        GL.subs.set_temp(vhbg, miob_temp, bypass_ramp=True)
        await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
        GL.subs.switch_tec_by_id(vhbg, True)
        await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
    GL.subs.set_temp(vhbg, cs.VHBG_WORKING_TEMP)
    GL.subs.switch_temp_ramp(vhbg, True)


async def _set_to_ambient(unit: subsystems.TecUnit,
                          ambient: Dict[subsystems.TecUnit, float]) -> None:
    """Set `unit` temperature to ambient temp.

    If the TEC is disabled, it will simply set it's raw temperature to the
    ambient temp.  If TEC is enabled and `ramp_down` is given, the temp. is
    ramped down.  If `ramp_down` and actual TEC state dont add up, a
    RuntimeError is raised.

    :raises ConnectionError: Couldn't get reliable values for ambient temp of
                `unit` or failed to set TEC setpoint.
    """
    # Check again, as time has passed.
    is_tec_on = GL.subs.is_tec_enabled(unit)
    if is_tec_on:
        LOGGER.info("Ramping %s to ambient.", unit)
        GL.subs.set_temp(unit, ambient[unit])
        await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
    else:
        LOGGER.info("Arming %s.", unit)
        GL.subs.set_temp(unit, ambient[unit], bypass_ramp=True)
        GL.subs.set_temp(unit, ambient[unit])  # Init temp ramp.
        await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
        if abs(GL.subs.get_temp_setpt(unit) - ambient[unit]) < cs.TEMP_ALLOWABLE_SETTER_ERROR:
            GL.subs.switch_tec_by_id(unit, True)
            await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
        else:
            raise ConnectionError("Failed to set {} temperature.".format(unit))
    GL.subs.switch_temp_ramp(unit, True)


def _spawn_current_tuner() -> lock_buddy.Tuner:
    """Get a tuner that utilizes the MO current for frequency tuning."""
    mo_rng = cs.LD_MO_TUNING_RANGE
    def mo_getter() -> float:
        """Returns the normalized MO current setpoint."""
        setpoint = GL.subs.get_ld_current_setpt(subsystems.LdDriver.MASTER_OSCILLATOR)
        normalized = (mo_rng[1] - setpoint) / (mo_rng[1] - mo_rng[0])
        LOGGER.debug("Got %s for current setpoint (normalized %s).", setpoint, normalized)
        return normalized

    def mo_setter(value: float) -> None:
        """Set MO current based on normalized `value`."""
        current = mo_rng[1] - (value * (mo_rng[1] - mo_rng[0]))
        LOGGER.debug("Setting MO current to %s mA (%s normalized).", current, value)
        GL.subs.laser.set_mo_current(current)

    return lock_buddy.Tuner(
        scale=cs.LaserMhz(abs((mo_rng[1] - mo_rng[0]) * cs.LD_MO_MHz_mA)),
        granularity=abs(cs.LD_MO_GRANULARITY_mA / (mo_rng[1] - mo_rng[0])),
        delay=cs.LD_MO_DELAY_s,
        getter=mo_getter,
        setter=mo_setter,
        name="MO current")


def _spawn_miob_tuner() -> lock_buddy.Tuner:
    """Get a tuner that utilizes the MiOB temperature for frequency tuning."""
    def get_miob_temp() -> float:
        """Normalized temperature of the micro-optical bench."""
        # This might raise a ConnectionError, but we don't catch here to
        # prevent the GL.locker from going rogue with some NaNs.
        temp = GL.subs.get_temp_setpt(subsystems.TecUnit.MIOB)
        low = cs.MIOB_TEMP_TUNING_RANGE[0]
        high = cs.MIOB_TEMP_TUNING_RANGE[1]

        if not temp > low or not temp < high:
            raise RuntimeError("MiOB temperature out of tuning range.")
        # The highest possible temperature must return 0, the lowest 1. This is
        # due to the negative thermal tuning coefficient of the MiLas.
        return (high - temp) / (high - low)

    def set_miob_temp(value: float) -> None:
        """Set normalized temperature of the micro-optical bench."""
        # The MiLas has a negative thermal tuning coefficient, which has us
        # reverse this.
        temp = cs.MIOB_TEMP_TUNING_RANGE[1] - \
               (value * (cs.MIOB_TEMP_TUNING_RANGE[1] - cs.MIOB_TEMP_TUNING_RANGE[0]))
        GL.subs.set_temp(subsystems.TecUnit.MIOB, temp)

    abs_range = cs.MIOB_TEMP_TUNING_RANGE[1] - cs.MIOB_TEMP_TUNING_RANGE[0]
    return lock_buddy.Tuner(
        scale=cs.LaserMhz(abs(abs_range * cs.MIOB_MHz_K)),
        granularity=cs.TEC_GRANULARITY_K / abs_range,
        delay=90,
        getter=get_miob_temp,
        setter=set_miob_temp,
        name="MiOB temp")
