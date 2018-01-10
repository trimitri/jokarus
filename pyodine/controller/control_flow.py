"""This module provides predefined sequences. Methods never throw exceptions.

It includes power-on, reset and teardown procedures as well as running actual
experiments, such as establishing and monitoring locks.
It is assured and imperative that no methods of this class do ever throw
exceptions. A return status of type .ReturnState is provided to detect errors.
"""
import asyncio
import base64
import enum
from functools import partial
import logging
from typing import Any, Dict, List
import numpy as np
import aioconsole
from . import lock_buddy, subsystems
from .. import constants as cs
from .. import logger
from ..util import asyncio_tools as tools

LOGGER = logging.getLogger('control_flow')

MO_STANDARD_CURRENT = 100.
"""The default MO current, MO has to be lasing at that current."""
PA_IDLE_CURRENT = 250.
"""Safe current for PA, that allows switching MO on or off."""
PA_STANDARD_CURRENT = 1500.
"""The working current to use on the power amplifier."""
NTC_CALCULATION_ERR = 0.1
"""How far will the NTC temperature readout be apart from the value that was
set as target, assuming perfectly controlled plant. This is only due to NTC
calculations and DAC/ADC errors, not related to the actual plant and
controller!
"""

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

class ReturnState(enum.IntEnum):
    SUCCESS = 0
    FAIL = 1

class TecError(RuntimeError):
    """Something went wrong with the thermoelectric cooling subsystem."""
    pass

class TecStatusError(RuntimeError):
    """The system is in the wront `TecStatus`."""
    pass


async def compensate_temp_drifts(locker: lock_buddy.LockBuddy) -> None:
    """Keep the MO current in the center of its range of motion.

    NOTE: This will only work on an engaged lock.  It may thus fail if the lock
    is relocking _just now_.

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
            await locker.tune(mo_imbalance, subsystems.Tuners.MIOB)

    async def condition() -> bool:
        """Does balancing still make sense?"""
        return await locker.get_lock_status() == lock_buddy.LockStatus.ON_LINE

    if not await condition():
        raise lock_buddy.LockError("Can only compensate running locks.")

    await tools.repeat_task(balancer, period=0.6, do_continue=condition)
    LOGGER.warning("Stopped temp drift compensator, as lock is %s.",
                   await locker.get_lock_status())


async def cool_down(subs: subsystems.Subsystems) -> None:
    """Get the system to a state where it can be physically switched off."""
    LOGGER.info("Cooling down components...")
    for unit in subsystems.TecUnit:
        if subs.is_tec_enabled(unit):
            # subs.set_temp(unit, AMBIENT_TEMP)  # ramp target temp
            # subs.switch_temp_ramp(unit, True)
            pass
        else:
            LOGGER.warning("Skipping %s on cooldown, as TEC was disabled.",
                           unit)


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


async def _set_to_ambient(subs: subsystems.Subsystems, unit: subsystems.TecUnit,
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
    is_tec_on = subs.is_tec_enabled(unit)
    if is_tec_on:
        LOGGER.info("Ramping %s to ambient.", unit)
        subs.set_temp(unit, ambient[unit])
        await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
    else:
        LOGGER.info("Arming %s.", unit)
        subs.set_temp(unit, ambient[unit], bypass_ramp=True)
        subs.set_temp(unit, ambient[unit])  # Init temp ramp.
        await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
        if abs(subs.get_temp_setpt(unit) - ambient[unit]) < cs.TEMP_ALLOWABLE_SETTER_ERROR:
            subs.switch_tec_by_id(unit, True)
            await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
        else:
            raise ConnectionError("Failed to set {} temperature.".format(unit))
    subs.switch_temp_ramp(unit, True)


async def get_tec_status(subs: subsystems.Subsystems, temps: List[float] = None) -> TecStatus:
    """Analyze the current TEC subsystem status.

    :raises TecError: Couldn't get ambient temperatures.
    """
    # pylint: disable=too-many-return-statements
    # pylint: disable=too-many-branches
    tec = subsystems.TecUnit
    temps = temps if temps else await subs.get_aux_temps(dont_log=True)
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
        is_on[unit] = subs.is_tec_enabled(unit)
        ramp_on[unit] = subs.is_temp_ramp_enabled(unit)
        obj_temp[unit] = subs.get_temp(unit)
        raw_setpt[unit] = subs.get_temp_setpt(unit)
        ramp_setpt[unit] = subs.get_temp_ramp_target(unit)

    if not any(is_on.values()):
        return TecStatus.OFF

    LOGGER.info("Not OFF")

    if not all([is_on[unit] and ramp_on[unit] and ramp_setpt[unit] for unit
                in [tec.SHGA, tec.SHGB, tec.MIOB]]):
        # Unexpected number of TECs are active.
        return TecStatus.UNDEFINED

    LOGGER.info("Base TECs OK, ramps on and set..")


    # Check for legit "HOT" state.  We always do all the checks as it's cheap
    # and easier to read.
    legit = True
    # VHBG
    legit = is_on[tec.VHBG]
    for temp in [obj_temp[tec.VHBG], raw_setpt[tec.VHBG], ramp_setpt[tec.VHBG]]:
        if _is_hot_vhbg(temp):
            LOGGER.info("VHBG temps OK.")
        else:
            legit = False
            LOGGER.info("VHBG temps NOT OK.")

    # MiOB
    for temp in [obj_temp[tec.MIOB], raw_setpt[tec.MIOB], ramp_setpt[tec.MIOB]]:
        if _is_hot_miob(temp):
            LOGGER.info("MIOB temps OK.")
        else:
            legit = False
            LOGGER.info("MIOB temps NOT OK.")

    # SHGs
    for temp in [obj_temp[tec.SHGA], raw_setpt[tec.SHGA], ramp_setpt[tec.SHGA],
                 obj_temp[tec.SHGB], raw_setpt[tec.SHGB], ramp_setpt[tec.SHGB]]:
        if _is_hot_shg(temp):
            LOGGER.info("SHG temps OK.")
        else:
            legit = False
            LOGGER.info("SHG temps NOT OK.")
    if legit:
        return TecStatus.HOT

    LOGGER.info("Not legit HOT")

    # Check for "HEATING" state.
    if all([_is_hot_shg(ramp_setpt[tec.SHGA]), is_on[tec.SHGA],
            _is_hot_shg(ramp_setpt[tec.SHGB]), is_on[tec.SHGB],
            _is_hot_miob(ramp_setpt[tec.MIOB]), is_on[tec.MIOB]]):
        return TecStatus.HEATING

    LOGGER.info("not HEATING")

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


async def heat_up(subs: subsystems.Subsystems) -> None:
    """Ramp temperatures of all controlled  components to their target value.

    Raises if system is not TecStatus.AMBIENT.

    :raises TecStatusError: System was not TecStatus.AMBIENT.
    """
    status = await get_tec_status(subs)
    if status == TecStatus.HOT:
        LOGGER.info("System is hot, nothing to do.")
        return
    if status in (TecStatus.UNDEFINED, TecStatus.OFF):
        raise TecStatusError("TEC subsystem is undefined or off. Can't heat.")
    if status in (TecStatus.HEATING, TecStatus.AMBIENT):
        LOGGER.info("System is %s. Running `heat_up()`...", status)

    # VHBG plays a special role, as it can only be heated after the MiOB
    # finishes.
    vhbg = subsystems.TecUnit.VHBG
    subs.set_temp(vhbg, cs.VHBG_WORKING_TEMP)
    if subs.is_tec_enabled(vhbg):
        subs.switch_temp_ramp(vhbg, True)
    else:
        miob_temp = subs.get_temp(subsystems.TecUnit.MIOB)
        if _is_hot_miob(miob_temp):
            LOGGER.info("Heating VHBG...")
            subs.set_temp(vhbg, miob_temp, bypass_ramp=True)
            await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
            subs.switch_tec_by_id(vhbg, True)
            await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)
            subs.switch_temp_ramp(vhbg, True)
        else:
            LOGGER.warning("Can't heat VHBG, as MiOB is not yet in working range.")

    # The others are simple, as get_tec_status() has checked everything before.
    miob_target = (cs.MIOB_TEMP_TUNING_RANGE[0] + cs.MIOB_TEMP_TUNING_RANGE[1]) / 2
    subs.set_temp(subsystems.TecUnit.MIOB, miob_target)
    subs.set_temp(subsystems.TecUnit.SHGA, cs.SHGA_WORKING_TEMP)
    subs.set_temp(subsystems.TecUnit.SHGB, cs.SHGB_WORKING_TEMP)


def initialize_rf_chain(subs: subsystems.Subsystems) -> ReturnState:
    """Setup the RF sources for heterodyne detection.

    This provides EOM, AOM and mixer with the correct driving signals.
    """
    try:
        subs.switch_rf_clock_source('external')
        subs.set_aom_amplitude(0.32)  # Don't produce high harmonics in amp.
        subs.set_aom_frequency(150)  # 150 MHz offset

        # Choose the lowest possible RF amplifiert input amplitude that still
        # leads to maximum RF power at output. If the input amplitude is set
        # too high, there will be strong sidebands in output.
        subs.set_eom_amplitude(.4)

        # This also sets the mixer frequency accordingly.
        subs.set_eom_frequency(0.300)

        subs.set_mixer_amplitude(1)
        subs.set_mixer_phase(0)

    # By design of this class, no method may ever throw anything.
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Initializing RF chain failed.")
        return ReturnState.FAIL

    LOGGER.info("Successfully initialized RF chain.")
    return ReturnState.SUCCESS


def init_locker(subs: subsystems.Subsystems) -> lock_buddy.LockBuddy:
    """Initialize the frequency prelock and lock system."""

    # Store tuners as "globals" (into subsystems) for other modules to use.
    subsystems.Tuners.MO = _spawn_current_tuner(subs)
    subsystems.Tuners.MIOB = _spawn_miob_tuner(subs)

    # The lockbox itself has to be wrapped like a Tuner, as it does
    # effectively tune the laser. All values associated with setting stuff can
    # be ignored though ("1"'s and lambda below).
    lock = cs.LOCKBOX_RANGE_mV
    lock_range = lock[1] - lock[0]
    def lockbox_getter() -> float:
        return (lock[1] - subs.get_lockbox_level()) / lock_range

    lockbox = lock_buddy.Tuner(
        scale=cs.LaserMhz(abs(lock_range * cs.LOCKBOX_MHz_mV)),
        granularity=.42,  # not used
        delay=42,  # not used
        getter=lockbox_getter,
        setter=lambda _: None,  # not used
        name="Lockbox")

    # Log all acquired signals.
    def on_new_signal(data: np.ndarray) -> None:
        """Logs the received array as base64 string."""
        data_type = str(data.dtype)
        shape = str(data.shape)
        values = base64.b64encode(data).decode()  # base64-encoded str()
        logger.log_quantity(
            'spectroscopy_signal', data_type + '\t' + shape + '\t' + values)


    def nu_locked() -> lock_buddy.LockboxState:
        """What state is the lockbox in?"""
        if (subs.nu_locked()
                and subs.lockbox_integrators_enabled()
                and not subs.is_lockbox_ramp_enabled()):
            return lock_buddy.LockboxState.ENGAGED
        if (not subs.nu_locked()
                and subs.lockbox_integrators_disabled()
                and subs.is_lockbox_ramp_enabled()):
            return lock_buddy.LockboxState.DISENGAGED
        return lock_buddy.LockboxState.DEGRADED

    # Assemble the actual lock buddy using the tuners above.
    locker = lock_buddy.LockBuddy(
        lock=partial(engage_lock, subs),
        unlock=partial(release_lock, subs),
        locked=nu_locked,
        lockbox=lockbox,
        scanner=subs.fetch_scan,
        scanner_range=cs.LaserMhz(700),  # FIXME measure correct scaling coefficient.
        on_new_signal=on_new_signal)
    return locker


async def laser_power_up(subs: subsystems.Subsystems) -> None:
    """Switch on the laser.

    After running this, the laser power may be adjusted through the PA current,
    the frequency through MO current.

    :raises RuntimeError: Failed to power up laser.
    """
    LOGGER.info("Powering up laser...")
    for unit in subsystems.TecUnit:
        if not subs.is_tec_enabled(unit):
            raise RuntimeError("At least one TEC controller is not enabled.")
    subs.switch_ld(subsystems.LdDriver.MASTER_OSCILLATOR, True)
    subs.switch_ld(subsystems.LdDriver.POWER_AMPLIFIER, True)
    subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, PA_IDLE_CURRENT)
    await asyncio.sleep(3)
    subs.set_current(subsystems.LdDriver.MASTER_OSCILLATOR, MO_STANDARD_CURRENT)
    await asyncio.sleep(3)
    subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, PA_STANDARD_CURRENT)


async def laser_power_down(subs: subsystems.Subsystems) -> None:
    """Shut down and switch off laser.

    :raises RuntimerError: Failed to switch off laser.
    """
    LOGGER.info("Powering down laser...")
    subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, PA_IDLE_CURRENT)
    await asyncio.sleep(3)
    subs.switch_ld(subsystems.LdDriver.MASTER_OSCILLATOR, False)
    await asyncio.sleep(3)
    subs.switch_ld(subsystems.LdDriver.POWER_AMPLIFIER, False)


async def prelock_and_lock(locker: lock_buddy.LockBuddy,
                           prelock_tuner: lock_buddy.Tuner) -> asyncio.Task:
    """Run the pre-lock algorithm and engage the frequency lock.

    :raises lock_buddy.LockError: A lock couldn't be established.
    """
    dip = await locker.doppler_search(
        prelock_tuner, judge=partial(locker.is_correct_line, prelock_tuner, reset=True))
    for attempt in range(cs.PRELOCK_TUNING_ATTEMPTS):
        error = cs.SpecMhz(dip.distance - cs.PRELOCK_DIST_SWEET_SPOT_TO_DIP)
        if abs(error) < cs.PRELOCK_TUNING_PRECISION:
            LOGGER.info("Took %s jumps to align dip.", attempt)
            break
        await locker.tune(error, prelock_tuner)
        dip = await locker.doppler_sweep()
    else:
        raise lock_buddy.DriftError("Unable to center doppler line.")
    return locker.engage_and_maintain()


async def engage_lock(subs: subsystems.Subsystems) -> None:
    """Run the timed procedure needed to engage the frequency lock."""
    subs.switch_pii_ramp(False)
    subs.switch_lock(True)
    await asyncio.sleep(cs.LOCKBOX_P_TO_I_DELAY)
    subs.switch_integrator(2, True)
    await asyncio.sleep(cs.LOCKBOX_I_TO_I_DELAY)
    subs.switch_integrator(1, True)
    await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)


def open_backdoor(injected_locals: Dict[str, Any]) -> None:
    """Provide a python interpreter capable of probing the system state."""

    # Provide a custom factory to allow for `locals` injection.
    def console_factory(streams: Any = None) -> aioconsole.AsynchronousConsole:
        return aioconsole.AsynchronousConsole(locals=injected_locals,
                                              streams=streams)
    asyncio.ensure_future(
        aioconsole.start_interactive_server(factory=console_factory))


async def release_lock(subs: subsystems.Subsystems) -> None:
    """Release the laser from frequency lock."""
    subs.switch_lock(False)
    subs.switch_pii_ramp(True)
    subs.switch_integrator(1, False)
    subs.switch_integrator(2, False)
    await asyncio.sleep(cs.MENLO_MINIMUM_WAIT)


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


def _spawn_miob_tuner(subs: subsystems.Subsystems) -> lock_buddy.Tuner:
    """Get a tuner that utilizes the MiOB temperature for frequency tuning."""
    def get_miob_temp() -> float:
        """Normalized temperature of the micro-optical bench."""
        # This might raise a ConnectionError, but we don't catch here to
        # prevent the locker from going rogue with some NaNs.
        temp = subs.get_temp_setpt(subsystems.TecUnit.MIOB)
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
        subs.set_temp(subsystems.TecUnit.MIOB, temp)

    abs_range = cs.MIOB_TEMP_TUNING_RANGE[1] - cs.MIOB_TEMP_TUNING_RANGE[0]
    return lock_buddy.Tuner(
        scale=cs.LaserMhz(abs(abs_range * cs.MIOB_MHz_K)),
        granularity=cs.TEC_GRANULARITY_K / abs_range,
        delay=90,
        getter=get_miob_temp,
        setter=set_miob_temp,
        name="MiOB temp")


def _spawn_current_tuner(subs: subsystems.Subsystems) -> lock_buddy.Tuner:
    """Get a tuner that utilizes the MO current for frequency tuning."""
    mo_rng = cs.LD_MO_TUNING_RANGE
    def mo_getter() -> float:
        """Returns the normalized MO current setpoint."""
        setpoint = subs.get_ld_current_setpt(subsystems.LdDriver.MASTER_OSCILLATOR)
        normalized = (mo_rng[1] - setpoint) / (mo_rng[1] - mo_rng[0])
        LOGGER.debug("Got %s for current setpoint (normalized %s).", setpoint, normalized)
        return normalized

    def mo_setter(value: float) -> None:
        """Set MO current based on normalized `value`."""
        current = mo_rng[1] - (value * (mo_rng[1] - mo_rng[0]))
        LOGGER.debug("Setting MO current to %s mA (%s normalized).", current, value)
        subs.laser.set_mo_current(current)

    return lock_buddy.Tuner(
        scale=cs.LaserMhz(abs((mo_rng[1] - mo_rng[0]) * cs.LD_MO_MHz_mA)),
        granularity=abs(cs.LD_MO_GRANULARITY_mA / (mo_rng[1] - mo_rng[0])),
        delay=cs.LD_MO_DELAY_s,
        getter=mo_getter,
        setter=mo_setter,
        name="MO current")
