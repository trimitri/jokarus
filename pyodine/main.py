"""Run this by invoking ``python3 -m pyodine.main`` from the parent directory.

It launches the lab control software and sets up the Pyodine server.

The reason for not making this script executable is to keep the import
statements as clean and unambiguous as possible: Relative imports are used for
local modules, absolute imports for global ones. This should be the pythonic
way as discussed in PEP328.
"""
import asyncio
import base64
import logging
from typing import Dict, Any

import aioconsole
import numpy as np

from . import logger
from . import constants as cs
from .controller import (interfaces, instruction_handler, lock_buddy, subsystems)
from .util import asyncio_tools


def open_backdoor(injected_locals: Dict[str, Any]) -> None:
    """Provide a python interpreter capable of probing the system state."""

    # Provide a custom factory to allow for `locals` injection.
    def console_factory(streams: Any = None) -> aioconsole.AsynchronousConsole:
        return aioconsole.AsynchronousConsole(locals=injected_locals,
                                              streams=streams)
    asyncio.ensure_future(
        aioconsole.start_interactive_server(factory=console_factory))

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
        scale=abs(abs_range * cs.MIOB_MHz_K),
        granularity=cs.TEC_GRANULARITY_K / abs_range,
        delay=90,
        getter=get_miob_temp,
        setter=set_miob_temp,
        name="MiOB temp")

def _spawn_current_tuner(subs: subsystems.Subsystems) -> lock_buddy.Tuner:
    """Get a tuner that utilizes the MO current for frequency tuning."""
    mo_rng = cs.LD_MO_TUNING_RANGE
    def mo_getter() -> float:
        return (mo_rng[1] - subs.laser.get_mo_current()) / (mo_rng[1] - mo_rng[0])

    def mo_setter(value: float) -> None:
        subs.laser.set_mo_current(mo_rng[1] - (value * (mo_rng[1] - mo_rng[0])))

    return lock_buddy.Tuner(
        scale=abs((mo_rng[1] - mo_rng[0]) * cs.LD_MO_MHz_mA),
        granularity=abs(cs.LD_MO_GRANULARITY_mA / (mo_rng[1] - mo_rng[0])),
        delay=cs.LD_MO_DELAY_s,
        getter=mo_getter,
        setter=mo_setter,
        name="MO current")

def _spawn_ramp_tuner(subs: subsystems.Subsystems) -> lock_buddy.Tuner:
    """Get a tuner that utilizes the ramp offset for frequency tuning."""
    ramp = cs.DAQ_RAMP_OFFSET_RANGE_V
    ramp_range = ramp[1] - ramp[0]
    def ramp_getter() -> float:
        return (ramp[1] - subs.get_ramp_offset()) / ramp_range

    def ramp_setter(value: float) -> None:
        subs.set_ramp_offset(ramp[1] - ramp_range * value)

    return lock_buddy.Tuner(
        scale=abs(cs.DAQ_MHz_V * ramp_range),
        granularity=cs.DAQ_GRANULARITY_V / ramp_range,
        delay=cs.DAQ_DELAY_s,
        getter=ramp_getter,
        setter=ramp_setter,
        name="ramp offset")

def init_locker(subs: subsystems.Subsystems) -> lock_buddy.LockBuddy:
    """Initialize the frequency prelock and lock system."""


    # The lockbox itself has to be wrapped like a Tuner as well, as it does
    # effectively tune the laser. All values associated with setting stuff can
    # be ignored though ("1"'s and lambda below).
    lock = cs.LOCKBOX_RANGE_mV
    lock_range = lock[1] - lock[0]
    def lockbox_getter() -> float:
        return (lock[1] - subs.get_lockbox_level()) / lock_range

    lockbox = lock_buddy.Tuner(
        scale=abs(lock_range * cs.LOCKBOX_MHz_mV),
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


    def nu_locked() -> bool:
        try:
            return subs.nu_locked()
        except ConnectionError:
            logging.warning("Couldn't fetch actual frequency lockbox state. "
                            'Assuming "Locked".')
            return True

    # Assemble the actual lock buddy using the tuners above.
    locker = lock_buddy.LockBuddy(
        lock=lambda: subs.switch_lock(True),
        unlock=lambda: subs.switch_lock(False),
        locked=nu_locked,
        lockbox=lockbox,
        scanner=subs.fetch_scan,
        scanner_range=700.,  # FIXME measure correct scaling coefficient.
        tuners=[_spawn_miob_tuner(subs), _spawn_current_tuner(subs), _spawn_ramp_tuner(subs)],
        on_new_signal=on_new_signal)
    return locker


async def main() -> None:
    """Start the pyodine server."""
    LOGGER.info("Running Pyodine...")

    subs = subsystems.Subsystems()
    locker = init_locker(subs)
    face = interfaces.Interfaces(subs, locker, start_ws_server=True,
                                 start_serial_server=True)
    await face.init_async()
    face.start_publishing_regularly(readings_interval=.8, flags_interval=1.3,
                                    setup_interval=3.1, signal_interval=4,
                                    status_update_interval=0)

    handler = instruction_handler.InstructionHandler(subs, face, locker)
    face.register_on_receive_callback(handler.handle_instruction)
    face.register_timer_handler(handler.handle_timer_command)

    # Start a asyncio-capable interactive python console on port 8000 as a
    # backdoor, practically providing a powerful CLI to Pyodine.
    open_backdoor({'cs': cs,
                   'face': face,
                   'flow': handler._flow,
                   'locker': locker,
                   'subs': subs})

    await asyncio_tools.watch_loop(
        lambda: LOGGER.warning("Event loop overload!"),
        lambda: LOGGER.debug("Event loop is healthy."))

    LOGGER.error("Dropped to emergency loop keep-alive.")
    while True:  # Shouldn't reach this.
        await asyncio.sleep(10)


# Only execute if run as main program (not on import). This also holds when the
# recommended way of running this program (see above) is used.
if __name__ == '__main__':
    logger.init()
    LOGGER = logging.getLogger('pyodine.main')

    LOOP = asyncio.get_event_loop()
    # event_loop.set_debug(True)

    if not logger.is_ok:
        # FIXME: make sure this doesn't fire unexpectedly (#123)
        raise OSError("Failed to set up logging.")

    logger.start_flushing_regularly(7)  # Write data to disk every 7 seconds.
    try:
        # Schedule main program for running and start central event loop.
        LOOP.run_until_complete(main())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received. Exiting.")
