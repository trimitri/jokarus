"""Check if asyncio chooses correct loop type and doesn't eat up CPU."""
import asyncio

from ..util import asyncio_tools

if __name__ == '__main__':
    LOOP = asyncio.get_event_loop()
# LOOP.set_debug(True)
    LOOP.run_until_complete(asyncio_tools.watch_loop(
        lambda: print("Delay!"), lambda: print("OK")))
