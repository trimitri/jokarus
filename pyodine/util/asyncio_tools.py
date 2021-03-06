"""Some tools for recurrent I/O tasks."""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, List, Optional, Tuple, Union  # pylint: disable=unused-import

LOGGER = logging.getLogger('asyncio_tools')


def safe_call(callback: Callable, *args: Any, **kwargs: Any) -> Any:
    """Try to call a callback and catch everything that might be raised.

    This passes on additional arguments to the callee, just like
    functools.partial.

    :param callback: The function to call. May expect arbitrary combination of
                arguments, as long as they are passed to me. It's return value
                is returned if the call succeeds.
    """
    try:
        rval = callback(*args, **kwargs)
    except Exception:  # It might raise hell. # pylint: disable=broad-except
        LOGGER.exception("""Error calling callback "%s"!""", callback.__name__)
    if asyncio.iscoroutine(rval):
        LOGGER.error("Callback %s returned a coroutine.  This is very "
                     "likely to be a mistake.", callback.__name__)
        LOGGER.info("Consider using safe_async_call() for async calls.")
    return rval


async def async_call(callback: Callable, *args: Any, **kwargs: Any) -> Any:
    """Call it like it's async.

    This returns a coroutine object no matter if ``callback`` is a coroutine
    function or not. It passes on additional arguments to the callee, just
    like functools.partial does.

    **Disclaimer on false-positive coroutine function detection**

    Note that, if callback returns a coroutine despite not being a coroutine
    function, the returned coroutine will be awaited instead of returned
    anyway.  Thus anything that returns a coroutine is indifferently treated
    like a coroutine function by this method.

    :param callback: The function to call. May expect arbitrary combination of
                arguments. It's return value is returned if the call succeeds.
                Can be a regular or a coroutine function.
    :raises Exception: Whatever the challback might raise.
    """
    rval = callback(*args, **kwargs)
    if asyncio.iscoroutine(rval):
        return await rval
    return rval


async def safe_async_call(callback: Callable, *args: Any, **kwargs: Any) -> Any:
    """Call it like it's async and catch everything that might be raised.

    This returns a coroutine object no matter if ``callback`` is a coroutine
    function or not. It passes on additional arguments to the callee, just
    like functools.partial does.

    **Disclaimer on false-positive coroutine function detection**

    Note that, if callback returns a coroutine despite not being a coroutine
    function, the returned coroutine will be awaited instead of returned
    anyway.  Thus anything that returns a coroutine is indifferently treated
    like a coroutine function by this method.

    :param callback: The function to call. May expect arbitrary combination of
                arguments. It's return value is returned if the call succeeds.
                Can be a regular or a coroutine function.
    """
    try:
        return await async_call(callback, *args, **kwargs)
    except Exception:  # It might raise hell. # pylint: disable=broad-except
        LOGGER.error("Error calling callback {}!".format(callback.__name__))
        LOGGER.debug("Exception info:", exc_info=True)


async def poll_resource(indicator: Callable[[], Union[bool, Awaitable[bool]]],
                        delay: Union[float, int],
                        prober: Callable[[], Optional[Awaitable[None]]] = lambda: None,
                        on_connect: Callable[[], Optional[Awaitable[None]]] = lambda: None,
                        on_disconnect: Callable[[], Optional[Awaitable[None]]] = lambda: None,
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
            raise TypeError('Callback {} is not callable.'.format(repr(my_name)))

    # This outer loop will only run more than once if the user wants us to keep
    # observing a currently healthy connection.
    while True:
        if not await safe_async_call(indicator):
            LOGGER.info("Trying to connect connect %s.", name)
            while not await safe_async_call(indicator):
                LOGGER.debug("Resource %s is still offline.", name)
                await safe_async_call(prober)
                await asyncio.sleep(delay)
            await safe_async_call(on_connect)  # Notify the caller.
            LOGGER.info("Resource %s is now available.", name)
        if not continuous:
            LOGGER.info("Stopped polling of resource %s.", name)
            break
        if not indicator():  # There was a connection, but it got lost.
            await safe_async_call(on_disconnect)
            LOGGER.info("Resource %s became unavailable.", name)
        await asyncio.sleep(float(delay))


async def repeat_task(
        coro: Callable[[], Any],
        period: float = 0,
        do_continue: Callable[[], Union[bool, Awaitable[bool]]] = lambda: True,
        reps: int = 0, min_wait_time: float = 0.1) -> None:
    """Repeat a task at given time intervals forever or ``reps`` times.

    **Disclaimer on false-positive coroutine function detection**

    Note that, if coro returns a coroutine despite not being a coroutine
    function, the returned coroutine will be awaited instead of returned
    anyway.  Thus anything that returns a coroutine is indifferently treated
    like a coroutine function by this method.

    :param coro: The coroutine object (not coroutine function!) to await
    """
    async def run_once() -> None:
        """Run one loop iteration."""
        start = time.time()
        await async_call(coro)
        remaining_wait_time = period - (time.time() - start)
        if remaining_wait_time > 0:
            await asyncio.sleep(remaining_wait_time)
        elif min_wait_time > 0:
            await asyncio.sleep(min_wait_time)

    if reps > 0:  # Do `reps` repetitions at max.
        for _ in range(reps):
            if not await async_call(do_continue):
                break
            await run_once()
    else:  # Run forever.
        while await async_call(do_continue):
            await run_once()


def static_variable(variable_name: str,
                    initial_value: Any) -> Callable[[Callable], Callable]:
    """A decorator to add a static variable to a function."""
    def decorator(function):
        setattr(function, variable_name, initial_value)
        return function
    return decorator


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
    while not safe_call(stop):
        before = time.time()
        await asyncio.sleep(interval)
        if time.time() - before > interval * max_load_factor:
            safe_call(on_delay)
        else:
            safe_call(on_ok)


class DeDupQueue:
    """A deduplicating FIFO queue.

    When a specimen is enqueued of whose species there currently is an element
    in the queue, the existing element is replaced by the new element without
    changing the queue order.
    """
    def __init__(self) -> None:
        self.queue = []  # type: List[Tuple[Any, Any]]
        """List of tuples like (specimen, species).

        The last item is returned first.
        """

    def enqueue(self, specimen: Any, species: Any) -> None:
        """Enqueue an element or update an existing specimen.

        :param specimen: The actual item to store. Can be of any type.
        :param species: The identifying info to use when comparing to other
                    items. Needs to == to existing element's species. Can be of
                    any type.
        """
        for index, item in enumerate(self.queue):
            if item[1] == species:
                self.queue[index] = (specimen, species)
                break
        else:
            self.queue.insert(0, (specimen, species))

    def pop(self) -> Any:
        """Retrieve the most urgent element and remove it from the queue.

        ``if not bool(self.queue)``, this will throw.

        :raises IndexError: Queue is empty. Checkable by ``bool(self.queue)``.
        """
        return self.queue.pop()[0]  # Raises if queue is empty.
