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

from .controller import interfaces
from .controller import subsystems
from .controller import instruction_handler


async def main():
    logger.info("Running Pyodine...")

    subs = subsystems.Subsystems()
    await subs.init_async()

    face = interfaces.Interfaces(subs, start_serial_server=True)
    await face.init_async()
    face.start_publishing_regularly(flags_interval=1.1)

    handler = instruction_handler.InstructionHandler(subs, face)
    face.on_receive(handler.handle_instruction)

    while True:
        await asyncio.sleep(1)
        # data = daq.scan_ramp(min_val=-3, max_val=2)
        # print(data)

# Only execute if run as main program (not on import). This also holds when the
# recommended way of running this program (see above) is used.
if __name__ == '__main__':
    logger = logging.getLogger('pyodine.main')
    logging.basicConfig(level=logging.INFO)

    loop = asyncio.get_event_loop()
    # loop.set_debug(True)

    # Schedule main program for running and start central event loop.
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting.")
