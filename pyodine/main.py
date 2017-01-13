"""Run this by invoking ``python3 -m pyodine.main`` from the parent directory.

It launches the lab control software and sets up the Pyodine server.
(not yet ;)

The reason for not making this script executable is to keep the import
statements as clean and unambiguous as possible: Relative imports are used for
local modules, absolute imports for global ones. This should be the pythonic
way as discussed in PEP328.
"""
import logging
import time
# from .drivers import dds9_control
from .drivers import menlo_stack

# Only execute if run as main program (not on import). This also holds when the
# recommended way of running this program (see above) is used.
if __name__ == '__main__':
    logger = logging.getLogger('pyodine.main')
    logging.basicConfig(level=logging.DEBUG)
    logger.info("Running Pyodine...")

    menlo = menlo_stack.MenloStack()
    print("Doing other stuff")
    while True:
        time.sleep(2)
        print("Still doing stuff")
