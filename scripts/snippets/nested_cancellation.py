"""How do CancelledError exceptions get passed up?"""

import asyncio


async def wrapper(what):
    try:
        await what()
        print('foo')
    except asyncio.CancelledError:
        print("Wrapper for {} got cancelled.".format(what))
        raise


async def thingy():
    try:
        print("Thingy is running.")
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        print("Thingy got cancelled.")
        raise


async def cancellor(what, wait=1):
    await asyncio.sleep(wait)
    what.cancel()


def tester():
    loop = asyncio.get_event_loop()
    worker = loop.create_task(wrapper(thingy))
    canceller = loop.create_task(cancellor(worker, 1))
    loop.run_until_complete(asyncio.gather(worker, canceller))


tester()
