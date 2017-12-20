"""How does cancelling Tasks in asyncio work?"""

import asyncio
import aiomonitor


async def worker(what) -> None:
    try:
        while True:
            print("working {}".format(what))
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        print("{} got cancelled!".format(what))


async def cancellor(what, wait=1) -> None:
    await asyncio.sleep(wait)
    what.cancel()


def main() -> None:
    print('running...')
    loop = asyncio.get_event_loop()
    task1 = loop.create_task(worker('one'))
    task2 = loop.create_task(worker('two'))
    loop.create_task(cancellor(task1))
    with aiomonitor.start_monitor(
        loop=loop, locals={'loop':loop, 'task1':task1, 'task2':task2}):
        loop.run_forever()


main()
