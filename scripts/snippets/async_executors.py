"""Test module for asyncio + Executors"""

import asyncio
import functools
import time

LOOP = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop

# This is a flag that gets passed around. We can't use a plain bool here, as it
# is immutable.
FOO = [False]

def busy_wait(seconds):
    now = time.time()
    while time.time() < now + seconds:
        pass


def print_a(magic_flag):
    """This one can be cancelled."""
    times = 1
    # We need to poll an external flag here, as -- due to this not being an
    # asyncio coroutine -- it is otherwise not cancellable!
    while not magic_flag[0]:
        print("A printed {} times.".format(times))
        times += 1
        busy_wait(1)


def print_b():
    times = 1
    while True:
        print("B printed {} times.".format(times))
        times += 1
        busy_wait(1)


def print_c():
    times = 1
    while True:
        print("C printed {} times.".format(times))
        times += 1
        busy_wait(1)


async def do_nothing():
    initial_slip = time.time() - asyncio.get_event_loop().time()

    async def dostuff():
        await asyncio.sleep(1)
        print("Event loop still alive. async time: {} Time slip: {}".format(
            asyncio.get_event_loop().time(),
            time.time() - asyncio.get_event_loop().time() - initial_slip))

    for i in range(5):
        await dostuff()
    FOO[0] = True
    while True:
        await dostuff()


if __name__ == '__main__':

    asyncio.ensure_future(LOOP.run_in_executor(None, functools.partial(print_a, FOO)))
    asyncio.ensure_future(LOOP.run_in_executor(None, print_b))
    asyncio.ensure_future(LOOP.run_in_executor(None, print_c))
    LOOP.run_until_complete(do_nothing())

    raise RuntimeError("You shouldn't have come here.")
