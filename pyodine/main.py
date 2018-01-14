"""Run this by invoking ``python3 -m pyodine.main`` from the parent directory.

It launches the lab control software and sets up the Pyodine server.

The reason for not making this script executable is to keep the import
statements as clean and unambiguous as possible: Relative imports are used for
local modules, absolute imports for global ones. This should be the pythonic
way as discussed in PEP328.
"""
import asyncio
import logging

from . import logger
from . import constants as cs
from .controller import (interfaces, instruction_handler, lock_buddy,
                         procedures, runlevels, subsystems)
from .util import asyncio_tools as tools
from .util import git_adapter


class GLOBALS:  # pylint: disable=too-few-public-methods
    """Stuff that would otherwise get passed around throughout pyodine.

    Passing stuff around is usually the better practice, but in this case all
    those objects are only existing at most once throughout the whole program
    lifetime.
    """
    loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop
    """The event loop used for scheduling background tasks.

    This can be (re-)set externally, but as it will usually be the main thread
    that is importing this module first, it is set to the default event loop
    running in the import thread at import time.
    """
    subs = None  # type: subsystems.Subsystems
    """The subsystems controller."""
    locker = None  # type: lock_buddy.LockBuddy
    """The lock controller."""


async def main() -> None:
    """Start the pyodine server."""
    LOGGER.info("Running Pyodine...")

    GLOBALS.subs = subsystems.Subsystems()
    GLOBALS.locker = procedures.init_locker()
    face = interfaces.Interfaces(start_ws_server=True, start_serial_server=True)
    await face.init_async()
    face.start_publishing_regularly(
        readings_interval=.8, flags_interval=1.3, setup_interval=3.1,
        signal_interval=4, status_update_interval=0, aux_temps_interval=6.9)

    handler = instruction_handler.InstructionHandler(face)
    face.register_on_receive_callback(handler.handle_instruction)
    face.register_timer_handler(handler.handle_timer_command)

    # Start a asyncio-capable interactive python console on port 8000 as a
    # backdoor, practically providing a CLI to Pyodine.
    procedures.open_backdoor({'cs': cs,
                              'face': face,
                              'flow': procedures,
                              'locker': GLOBALS.locker,
                              'run': runlevels,
                              'subs': GLOBALS.subs,
                              'subsystems': subsystems,
                              'Tuners': subsystems.Tuners})

    await tools.watch_loop(
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
    GLOBALS.loop = LOOP

    logger.log_quantity('git_revision',
                        tools.safe_call(git_adapter.get_revision))

    logger.start_flushing_regularly(7)  # Write data to disk every 7 seconds.
    try:
        # Schedule main program for running and start central event loop.
        LOOP.run_until_complete(main())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received. Exiting.")
