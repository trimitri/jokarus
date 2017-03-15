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

from .interfaces import websocket_server
from .controller import subsystems


async def main():
    logger.info("Running Pyodine...")

    subs = subsystems.Subsystems()
    await subs.init_async()

    ws_transport = websocket_server.WebsocketServer(port=56320)
    await ws_transport.async_init()

    asyncio.ensure_future(subs.set_mo_temp(42.4))

    while True:
        await asyncio.sleep(.2)
        await ws_transport.publish('some data')
        print(subs.get_full_set_of_readings() + "\n")
        # print("Still alive")
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
