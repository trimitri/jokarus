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

from .drivers import menlo_stack
# from .drivers import mccdaq
from .transport import websocket_server


async def main():
    logger.info("Running Pyodine...")

    # MenloStack() is mostly async and hence needs external initialization.
    menlo = menlo_stack.MenloStack()
    await menlo.init()

    ws_transport = websocket_server.WebsocketServer(port=56320)
    await ws_transport.async_init()

    # daq = mccdaq.MccDaq()

    while True:
        await asyncio.sleep(5)
        await ws_transport.publish('some data')
        # print("Still alive")
        # data = daq.scan_ramp(min_val=-3, max_val=2)
        # print(data)
        await menlo._send_command(16, 1, "20")

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
