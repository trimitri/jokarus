"""Run this by invoking ``python3 -m pyodine.main`` from the parent directory.

It launches the lab control software and sets up the Pyodine server.
(not yet ;)

The reason for not making this script executable is to keep the import
statements as clean and unambiguous as possible: Relative imports are used for
local modules, absolute imports for global ones. This should be the pythonic
way as discussed in PEP328.
"""
import logging
import asyncio

# from .drivers import dds9_control
from .drivers import menlo_stack


async def main():
    logger.info("Running Pyodine...")

    menlo = menlo_stack.MenloStack()

    while True:
        await asyncio.sleep(2)
        print(menlo.get_laser_current())
        print("Still doing stuff")


# Only execute if run as main program (not on import). This also holds when the
# recommended way of running this program (see above) is used.
if __name__ == '__main__':
    logger = logging.getLogger('pyodine.main')
    logging.basicConfig(level=logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.set_debug(True)

    # Schedule main program for running and start central event loop.
    loop.run_until_complete(main())
