"""Some tools for recurrent I/O tasks."""

import asyncio
import inspect
import logging
import time
from typing import Any, Awaitable, Callable, Union

LOGGER = logging.getLogger('asyncio_tools')

async def poll_resource(indicator: Callable[[], bool],
                        delay: Union[float, int],
                        prober: Callable[[], Union[None, Awaitable[None]]] = lambda: None,
                        on_connect: Callable[[], None] = lambda: None,
                        on_disconnect: Callable[[], None] = lambda: None,
                        name: str = '',
                        continuous: bool = False) -> None:
    """Wait for/periodically probe/check/monitor a resource.

    This will check bool(`indicator`), and if False, call `probe` after `delay`
    seconds. This will repeat until `indicator` is true in which case it will
    either standby (if `continuous` is True) or stop.

    As this will dispatch a worker task, it does not raise on faulty callbacks
    but uses logging.exception() instead.

    :param indicator: A function returning something coercible to bool that
                indicates if there is currently a connection. This gets called
                quite often and should ideally be cheap.
    :param delay: How long to wait after probing before checking `indicator`
                again. Just sleeping for this time in case no `indicator` is
                given.
    :param probe: Function to be called to "try again". This accepts coroutine
                functions returning "oneshot"-type coroutines as well. If
                passed, this should trigger some kind of reconnection attempt.
                This will only be called while the connection is dead. A dying
                connection that was live before connection should be
                recognizable by using `indicator` alone.
    :param on_connect: If passed, this is called whenever `indicator` became
                True after a period of False-ness.
    :param continuous: Tick this, if you want to keep on monitoring even after
                a connection has been established. Otherwise the coroutine will
                end at that point (default).
    :raises TypeError: Supplied callback `probe` or `on_connect` is not
                callable.
    """
    for my_name, callback in (("prober", prober), ("on_connect", on_connect),
                              ("on_disconnect", on_disconnect)):
        if not callable(callback):
            raise TypeError('Callback "%s" is not callable.', my_name)

    probe_is_async = inspect.iscoroutinefunction(prober)

    # This outer loop will only run more than once if the user wants us to keep
    # observing a currently healthy connection.
    while True:
        if not indicator():
            LOGGER.info("Trying to connect connect %s.", name)
            while not indicator():
                LOGGER.debug("Resource %s is still offline.", name)
                try:
                    if probe_is_async:
                        await prober()
                    else:
                        prober()
                except Exception:  # pylint: disable=broad-except
                    # It doesn't make a lot of sense to raise here, as this is
                    # a worker process.
                    LOGGER.exception("'prober()' callback raised an exception:")
                await asyncio.sleep(float(delay))
            try:
                on_connect()  # Notify the caller.
            except Exception:  # pylint: disable=broad-except
                # It doesn't make a lot of sense to raise here, as this is
                # a worker process.
                LOGGER.exception("'on_connect()' callback raised an exception:")
            LOGGER.info("Resource %s is now available.", name)
        if not continuous:
            LOGGER.info("Stopped polling of resource %s.", name)
            break
        if not indicator():  # There was a connection, but it got lost.
            try:
                on_disconnect()
            except Exception:  # pylint: disable=broad-except
                # It doesn't make a lot of sense to raise here, as this is
                # a worker process.
                LOGGER.exception("'on_disconnect()' callback raised an exception:")

            LOGGER.info("Resource %s became unavailable.", name)
        await asyncio.sleep(float(delay))

async def repeat_task(
        coro: Callable[[], Awaitable[None]], period: float,
        do_continue: Callable[[], bool] = lambda: True,
        reps: int = 0, min_wait_time: float = 0.1) -> None:
    """Repeat a task at given time intervals forever or ``reps`` times.

    :param coro: The coroutine object (not coroutine function!) to await
    """
    async def do_stuff():
        """Run one loop iteration."""
        start = time.time()
        await coro()  # Do things the caller wants to be done.
        remaining_wait_time = period - (time.time() - start)
        if remaining_wait_time > 0:
            await asyncio.sleep(remaining_wait_time)
        elif min_wait_time > 0:
            await asyncio.sleep(min_wait_time)

    if reps > 0:  # Do `reps` repetitions at max.
        for _ in range(reps):
            if not do_continue():
                break
            await do_stuff()
    else:  # Run forever.
        while do_continue():
            await do_stuff()

async def watch_loop(on_delay: Callable[[], Any],
                     on_ok: Callable[[], Any] = lambda: None,
                     stop: Callable[[], bool] = lambda: False,
                     interval: float = 5,
                     max_load_factor: float = 1.2) -> None:
    """Monitor the performance/fill state of an asyncio loop.

    :param on_delay: Callback called when loop suffers more delay than
                ``max_load_factor``.
    :param on_ok: Called if it doesn't.
    :param stop: Watchdog is cancelled as soon as this callback returns True.
    :param interval: Use that many seconds as checking interval.
    :param max_load_factor: Each time ``asyncio.sleep(foo)`` takes longer than
                foo * ``max_load_factor``, ``on_delay()`` is fired.
    """
    def call_callback(callback: Callable[[], Any]):
        try:
            return callback()
        except Exception:  # It might raise hell. # pylint: disable=broad-except
            LOGGER.exception("""Error calling callback "%s"!""", callback.__name__)

    while not call_callback(stop):
        before = time.time()
        await asyncio.sleep(interval)
        if time.time() - before > interval * max_load_factor:
            call_callback(on_delay)
        else:
            call_callback(on_ok)
