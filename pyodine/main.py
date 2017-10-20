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


def init_locker(subs: subsystems.Subsystems) -> lock_buddy.LockBuddy:
    """Initialize the frequency prelock and lock system."""

    ##
    # Tuning by Temperature of the Micro-Optical Bench
    ##

    def get_miob_temp() -> float:
        try:
            temp = subs.get_temp_setpt(subsystems.TecUnit.MIOB)
        except ConnectionError:
            return float('nan')
        return (temp - 20) / 10

    def set_miob_temp(value: float) -> None:
        temp = 10 * value + 20
        subs.set_temp(subsystems.TecUnit.MIOB, temp)

    # FIXME: provide estimates of tuning characteristic (#122)
    miob_temp = lock_buddy.Tuner(scale=50, granularity=.01, delay=60,
                                 getter=get_miob_temp, setter=set_miob_temp,
                                 name="MiOB temp")

    ##
    # Tuning by Diode Current
    ##

    # Based on the FBH preliminary spec sheet we assume a usable MO current
    # tuning range of 60 to 160 mA. In those 100mA of movement, the laser spans
    # about 7600 MHz.
    #
    # The granularity however is quite bad, as 125μA is the smallest step
    # possible. This yields 0.125mA / 100mA = 1.25e-3 for granularity.
    #
    # The delay for MO tuning originates mostly in the websocket protocol and
    # the Menlo firmware and is estimated to be about a second.
    #
    # The setter and getter methods project the mA values like 0 = 60mA,
    # 1 = 160mA.
    def mo_getter() -> float:
        return (subs.laser.get_mo_current() - 60) / 100

    def mo_setter(arb_units: float) -> None:
        subs.laser.set_mo_current(arb_units * 100 + 60)

    mo_current = lock_buddy.Tuner(scale=7600, granularity=1.25e-3, delay=1,
                                  getter=mo_getter, setter=mo_setter,
                                  name="MO current")

    ##
    # Tuning by Modulation Ramp Offset
    ##

    # The diode driver modulation port does about 1mA/V. As we have a 10V range
    # of motion for our ramp offset, and the Laser does about 74MHz/mA, this
    # leads to 740MHz of tuning range.
    def ramp_getter() -> float:
        return (subs.get_ramp_offset() + 5) / 10

    def ramp_setter(value: float) -> None:
        subs.set_ramp_offset(value * 10 + 5)

    ramp_offset = lock_buddy.Tuner(scale=740, granularity=3.05e-4, delay=0.2,
                                   getter=ramp_getter, setter=ramp_setter,
                                   name="ramp offset")

    # Log all acquired signals.
    def on_new_signal(data: np.ndarray) -> None:
        """Logs the received array as base64 string."""
        data_type = str(data.dtype)
        shape = str(data.shape)
        values = base64.b64encode(data).decode()  # base64-encoded str()
        logger.log_quantity(
            'spectroscopy_signal', data_type + '\t' + shape + '\t' + values)


    # Assemble the actual lock buddy using the tuners above.
    def nu_locked() -> bool:
        try:
            return subs.nu_locked()
        except ConnectionError:
            logging.warning("Couldn't fetch actual frequency lockbox state. "
                            'Assuming "Not Locked".')
            return False

    locker = lock_buddy.LockBuddy(
        lock=lambda: subs.switch_lock('nu', True),
        unlock=lambda: subs.switch_lock('nu', False),
        locked=nu_locked,
        scanner=subs.fetch_scan,
        scanner_range=700.,  # FIXME measure correct scaling coefficient.
        tuners=[miob_temp, mo_current, ramp_offset],
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
    face.start_publishing_regularly(readings_interval=0.5, flags_interval=1,
                                    setup_interval=5, signal_interval=0,
                                    status_update_interval=5)

    handler = instruction_handler.InstructionHandler(subs, face, locker)
    face.register_on_receive_callback(handler.handle_instruction)
    face.register_timer_handler(handler.handle_timer_command)

    # Start a asyncio-capable interactive python console on port 8000 as a
    # backdoor, practically providing a powerful CLI to Pyodine.
    open_backdoor({'subs': subs, 'face': face, 'locker': locker})

    await asyncio_tools.watch_loop(
        lambda: LOGGER.warning("Event loop overload!"),
        lambda: LOGGER.debug("Event loop is healthy."))

    while True:  # Shouldn't reach this.
        LOGGER.error("Dropped to emergency loop keep-alive.")
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
