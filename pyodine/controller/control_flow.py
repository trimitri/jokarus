"""This module provides predefined sequences. Methods never throw exceptions.

It includes power-on, reset and teardown procedures as well as running actual
experiments, such as establishing and monitoring locks.
It is assured and imperative that no methods of this class do ever throw
exceptions. A return status of type .ReturnState is provided to detect errors.
"""
import enum
import logging
from .subsystems import Subsystems

LOGGER = logging.getLogger('pyodine.controller.subsystems')
LOGGER.setLevel(logging.DEBUG)


class ReturnState(enum.IntEnum):
    SUCCESS = 0
    FAIL = 1


def initialize_rf_chain(subs: Subsystems) -> ReturnState:
    """Setup the RF sources for heterodyne detection.

    This provides EOM, AOM and mixer with the correct driving signals.
    """
    LOGGER.info("Initializing RF chain.")
    try:
        subs.switch_rf_clock_source('internal')  # FIXME: use dedicated OCXO
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
