"""This module provides predefined sequences. Methods never throw exceptions.

It includes power-on, reset and teardown procedures as well as running actual
experiments, such as establishing and monitoring locks.
It is assured and imperative that no methods of this class do ever throw
exceptions. A return status of type .ReturnState is provided to detect errors.
"""
import asyncio
import enum
import logging
from .subsystems import Subsystems, SubsystemError

LOGGER = logging.getLogger('pyodine.controller.subsystems')
LOGGER.setLevel(logging.DEBUG)


class ReturnState(enum.IntEnum):
    SUCCESS = 0
    FAIL = 1


def initialize_rf_chain(subs: Subsystems) -> ReturnState:
    """Setup the RF sources for heterodyne detection.

    This provides EOM, AOM and mixer with the correct driving signals.
    """
    LOGGER.info("Initializing RF chain...")
    try:
        subs.switch_rf_clock_source('external')
        subs.set_aom_amplitude(1)
        subs.set_aom_frequency(150)  # 150 MHz offset
        subs.set_eom_amplitude(1)
        subs.set_eom_frequency(0.300)  # 300 kHz sidebands
        subs.set_mixer_amplitude(1)
        subs.set_mixer_phase(0)

    # By design of this class, no method may ever throw anything.
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Initializing RF chain failed.")
        return ReturnState.FAIL

    LOGGER.info("Successfully initialized RF chain.")
    return ReturnState.SUCCESS


def hot_start(subs: Subsystems) -> ReturnState:
    """Reset all fast subsystems.

    General cold-start procedures, such as temperature control, are assumed to
    have been completed before.
    """
    fate = initialize_rf_chain(subs)
    if fate != ReturnState.SUCCESS:
        return fate

    return ReturnState.SUCCESS


# TODO Consider moving this to subsystems module.
async def laser_power_up(subs: Subsystems) -> ReturnState:
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
    except SubsystemError as err:
        LOGGER.error("There was a critical error in one of the subsystems "
                     "(%s). Trying to reset.")
        subs.reset_subsystems(err)
        return ReturnState.FAIL

    return ReturnState.SUCCESS
