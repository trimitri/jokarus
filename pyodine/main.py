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
from . import pyodine_globals
GL = pyodine_globals.GLOBALS
from .controller import (daemons, interfaces, instruction_handler, procedures,
                         runlevels, subsystems)
from .util import asyncio_tools as tools
from .util import git_adapter


async def main() -> None:
    """Start the pyodine server."""
    LOGGER.info("Running Pyodine...")

    GL.subs = subsystems.Subsystems()
    GL.locker = procedures.init_locker()
    GL.face = interfaces.Interfaces(start_ws_server=True, start_serial_server=True)
    await GL.face.init_async()
    await GL.face.start_publishing_regularly(
        readings_interval=.8, flags_interval=1.3, setup_interval=3.1,
        signal_interval=4, status_update_interval=0, aux_temps_interval=6.9)
    handler = instruction_handler.InstructionHandler()
    GL.face.register_on_receive_callback(handler.handle_instruction)
    GL.face.register_timer_handler(handler.handle_timer_command)
    # await pyodine_globals.systems_online()


    # Start a asyncio-capable interactive python console on port 8000 as a
    # backdoor, practically providing a CLI to Pyodine.
    procedures.open_backdoor({'cs': cs,
                              'daemons': daemons,
                              'gl': pyodine_globals,
                              'GL': GL,
                              'proc': procedures,
                              'run': runlevels,
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
    GL.loop = LOOP

    logger.log_quantity('git_revision',
                        tools.safe_call(git_adapter.get_revision))

    logger.start_flushing_regularly(7)  # Write data to disk every 7 seconds.
    try:
        # Schedule main program for running and start central event loop.
        LOOP.run_until_complete(main())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received. Exiting.")
