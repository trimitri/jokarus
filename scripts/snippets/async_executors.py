"""Test module for asyncio + Executors"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import time

# EXECUTOR = ProcessPoolExecutor()
EXECUTOR = ThreadPoolExecutor(thread_name_prefix="foothread")
LOOP = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop


def busy_wait(seconds):
    now = time.time()
    while time.time() < now + seconds:
        pass


def print_a():
    times = 1
    while True:
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
    while True:
        await asyncio.sleep(1)
        print("Event loop still alive. async time: {} Time slip: {}".format(
            asyncio.get_event_loop().time(),
            time.time() - asyncio.get_event_loop().time() - initial_slip))


if __name__ == '__main__':
    asyncio.ensure_future(LOOP.run_in_executor(EXECUTOR, print_a))
    asyncio.ensure_future(LOOP.run_in_executor(EXECUTOR, print_b))
    asyncio.ensure_future(LOOP.run_in_executor(EXECUTOR, print_c))
    LOOP.run_until_complete(do_nothing())

    raise RuntimeError("You shouldn't have come here.")
