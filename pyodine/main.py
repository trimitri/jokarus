"""Run this by invoking ``python3 -m pyodine.main`` from the parent directory.

It launches the lab control software and sets up the Pyodine server.
(not yet ;-)

The reason for not making this script executable is to keep the import
statements as clean and unambiguous as possible: Relative imports are used for
local modules, absolute imports for global ones. This should be the pythonic
way as discussed in PEP328.
"""
import logging
import logging.handlers
import asyncio
from .controller import interfaces, subsystems, instruction_handler
from .controller import control_flow as flow


def configure_logging():
    """Set up general parameters of the logging system."""

    root_logger = logging.getLogger()

    # We need to set the root logger to DEBUG in order to filter down below.
    root_logger.level = logging.DEBUG
    root_logger.name = 'pyodine'

    # Write everything to a log file, starting a new file every hour.
    write_to_disk = logging.handlers.TimedRotatingFileHandler(
        'log/pyodine.log', when='s', interval=3600)
    write_to_disk.doRollover()  # Start a new file every time pyodine is run.
    write_to_disk.formatter = logging.Formatter(
        "{asctime} {name} {levelname} - {message} "
        "[{module}.{funcName}]", style='{')
    root_logger.addHandler(write_to_disk)

    # Write everything of priority INFO and up to stderr.
    stderr = logging.StreamHandler()
    stderr.setLevel(logging.INFO)
    stderr.formatter = logging.Formatter(
        "{levelname:<7} {message} "
        "[{module}:{lineno}] ({name})", style='{')
    root_logger.addHandler(stderr)


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

    await asyncio.sleep(10)
    while True:
        await asyncio.sleep(0.21)

        subs.set_temp('shga', 20, True)
        subs.set_temp('shgb', 20, True)
        subs.set_current('shga', 100)
        subs.set_current('shgb', 100)


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
