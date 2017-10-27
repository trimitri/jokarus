"""This module provides predefined sequences. Methods never throw exceptions.

It includes power-on, reset and teardown procedures as well as running actual
experiments, such as establishing and monitoring locks.
It is assured and imperative that no methods of this class do ever throw
exceptions. A return status of type .ReturnState is provided to detect errors.
"""
import asyncio
import enum
import logging
from . import lock_buddy, subsystems

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
AMBIENT_TEMP = 23.  # FIXME use NTC readings!


class ReturnState(enum.IntEnum):
    SUCCESS = 0
    FAIL = 1


async def cool_down(subs: subsystems.Subsystems) -> None:
    """Get the system to a state where it can be physically switched off."""
    LOGGER.info("Cooling down components...")
    for unit in subsystems.TecUnit:
        if subs.is_tec_enabled(unit):
            subs.set_temp(unit, AMBIENT_TEMP)  # ramp target temp
            subs.switch_temp_ramp(unit, True)
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
        if not subs.is_tec_enabled(unit):
            subs.set_temp(unit, AMBIENT_TEMP, True)  # actual setpoint
            subs.set_temp(unit, AMBIENT_TEMP, False)  # ramp target temp
            # Wait for the temp. setpoint to arrive at actual TEC controller.
            await asyncio.sleep(.5)
            subs.switch_tec_by_id(unit, True)
            await asyncio.sleep(3)  # Allow three seconds for thermalization.
            subs.set_temp(unit, target_temps[unit])
            subs.switch_temp_ramp(unit, True)
        else:
            LOGGER.warning("Skipping %s TEC, as it was already active.")


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
    await asyncio.sleep(.5)
    subs.set_current(subsystems.LdDriver.MASTER_OSCILLATOR, MO_STANDARD_CURRENT)
    await asyncio.sleep(.5)
    subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, PA_STANDARD_CURRENT)


async def laser_power_down(subs: subsystems.Subsystems) -> None:
    """Shut down and switch off laser.

    :raises RuntimerError: Failed to switch off laser.
    """
    LOGGER.info("Powering down laser...")
    subs.set_current(subsystems.LdDriver.POWER_AMPLIFIER, PA_IDLE_CURRENT)
    await asyncio.sleep(.5)
    subs.switch_ld(subsystems.LdDriver.MASTER_OSCILLATOR, False)
    await asyncio.sleep(.5)
    subs.switch_ld(subsystems.LdDriver.POWER_AMPLIFIER, False)


async def prelock_and_lock(locker: lock_buddy.LockBuddy) -> None:
    """Run the pre-lock algorithm and engage the frequency lock.

    :raises lock_buddy.LockError: A lock couldn't be established.
    """
    LOGGER.info("prelock_and_lock() called.")  # TODO Invoke prelock algorithm.
    return
    await locker.start_prelock(
        threshold=0.5, target_position=lock_buddy.Line.a_1,
        proximity_callback=lambda: LOGGER.info("Yeah!"))



async def unlock(_: lock_buddy.LockBuddy) -> None:
    """Release the laser from frequency lock."""
    LOGGER.info("unlock() called.")  # TODO Implement unlock procedure.
