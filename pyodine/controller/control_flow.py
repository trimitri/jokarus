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
from typing import Any, Dict
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


class ReturnState(enum.IntEnum):
    SUCCESS = 0
    FAIL = 1


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


async def heat_up(subs: subsystems.Subsystems) -> None:
    """Ramp temperatures of all controlled components to their target value.

    If the temperature control is currently active for all those components,
    nothing happens, even if the current temperatures differs from the target
    temperatures that would have been set. This is to avoid overriding manual
    settings.
    """
    if is_heating(subs):
        LOGGER.debug("""Won't "heat up", as TEC is already running.""")
        return
    LOGGER.info("Heating up systems...")
    target_temps = {subsystems.TecUnit.MIOB: 24.850, subsystems.TecUnit.VHBG: 24.856,
                    subsystems.TecUnit.SHGA: 40.95, subsystems.TecUnit.SHGB: 40.85}
    for unit in subsystems.TecUnit:
        pass
        # if not subs.is_tec_enabled(unit):
        #     subs.set_temp(unit, AMBIENT_TEMP, True)  # actual setpoint
        #     subs.set_temp(unit, AMBIENT_TEMP, False)  # ramp target temp
        #     # Wait for the temp. setpoint to arrive at actual TEC controller.
        #     await asyncio.sleep(.5)
        #     subs.switch_tec_by_id(unit, True)
        #     await asyncio.sleep(3)  # Allow three seconds for thermalization.
        #     subs.set_temp(unit, target_temps[unit])
        #     subs.switch_temp_ramp(unit, True)
        # else:
        #     LOGGER.warning("Skipping %s TEC, as it was already active.")


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


def is_heating(subs: subsystems.Subsystems) -> bool:
    """If this returns True, heat_up() will have no effect.

    The system is currently heating up or already at a stable temperature"""
    for unit in subsystems.TecUnit:
        if not subs.is_tec_enabled(unit):
            return False

        # The temperature ramp wasn't run at all or didn't finish yet. Even if
        # the temp. ramp finished just now, the actual system temperature might
        # still be somewhat off due to thermal inertia.  This however is
        # nothing that running ``heat_up()`` could fix and thus is not checked.
        if abs(subs.get_temp_setpt(unit) - subs.get_temp_ramp_target(unit)) > NTC_CALCULATION_ERR:
            return False
    return True


def is_hot(_: subsystems.Subsystems) -> bool:
    """All subsystems are stabilized to any temperature.

    If there has been no manual adjustment, this will be the temperatures set
    by heat_up().
    """
    pass  # TODO Implement is_hot().


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
