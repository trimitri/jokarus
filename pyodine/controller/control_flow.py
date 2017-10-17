"""This module provides predefined sequences. Methods never throw exceptions.

It includes power-on, reset and teardown procedures as well as running actual
experiments, such as establishing and monitoring locks.
It is assured and imperative that no methods of this class do ever throw
exceptions. A return status of type .ReturnState is provided to detect errors.
"""
import asyncio
import enum
import logging
from . import subsystems

LOGGER = logging.getLogger('pyodine.controller.subsystems')

NTC_CALCULATION_ERR = 0.1
"""How far will the NTC temperature readout be apart from the value that was
set as target, assuming perfectly controlled plant. This is only due to NTC
calculations and DAC/ADC errors, not related to the actual plant and
controller!
"""


class ReturnState(enum.IntEnum):
    SUCCESS = 0
    FAIL = 1


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


def is_hot(subs: subsystems.Subsystems) -> bool:
    """If this returns True, heat_up() will have no effect."""
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


def heat_up(subs: subsystems.Subsystems) -> None:
    """Ramp temperatures of all controlled components to their target value.

    If the temperature control is currently active for all those components,
    nothing happens, even if the current temperatures differs from the target
    temperatures that would have been set. This is to avoid overriding manual
    settings.
    """
    pass  # FIXME


# TODO Consider moving this to subsystems module.
async def laser_power_up(subs: subsystems.Subsystems) -> ReturnState:
    """Switch on or reset the laser.

    After running this, the laser power may be adjusted through the PA current,
    the frequency through MO current.
    """
    try:
        subs.power_up_pa()

        # Before trying to switch on the MO, we need to wait for the PA current
        # to settle and be read.
        asyncio.sleep(1)

        subs.power_up_mo()
    except subsystems.SubsystemError:
        LOGGER.exception("There was a critical error in one of the subsystems.")
        return ReturnState.FAIL
    return ReturnState.SUCCESS
