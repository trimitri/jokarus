"""Run this by invoking ``python3 -m pyodine.main`` from the parent directory.

It launches the lab control software and sets up the Pyodine server.
(not yet ;-)

The reason for not making this script executable is to keep the import
statements as clean and unambiguous as possible: Relative imports are used for
local modules, absolute imports for global ones. This should be the pythonic
way as discussed in PEP328.
"""
import logging
import asyncio
from .controller import interfaces, subsystems, instruction_handler
from .controller import control_flow as flow


def configure_logging():
    """Set up general parameters of the logging system."""
    logging.basicConfig(level=logging.INFO)
    root_logger = logging.getLogger()
    write_to_disk = logging.FileHandler('log/pyodine.log', mode='w')
    root_logger.addHandler(write_to_disk)
    # TODO: add timestamps, rotation, etc.


async def main():
    """Start the pyodine server."""
    LOGGER.info("Running Pyodine...")

    subs = subsystems.Subsystems()
    await subs.init_async()

    face = interfaces.Interfaces(subs, start_serial_server=True)
    await face.init_async()
    face.start_publishing_regularly(
        readings_interval=2, flags_interval=13, status_update_interval=19)

    handler = instruction_handler.InstructionHandler(subs, face)
    face.register_on_receive_callback(handler.handle_instruction)

    flow.hot_start(subs)

    while True:
        await asyncio.sleep(1)

# Only execute if run as main program (not on import). This also holds when the
# recommended way of running this program (see above) is used.
if __name__ == '__main__':
    configure_logging()
    LOGGER = logging.getLogger('pyodine.main')

    event_loop = asyncio.get_event_loop()
    # event_loop.set_debug(True)

    # Schedule main program for running and start central event loop.
    try:
        event_loop.run_until_complete(main())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received. Exiting.")
