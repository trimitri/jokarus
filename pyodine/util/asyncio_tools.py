"""Some tools for recurrent I/O tasks."""

import asyncio
import inspect
import logging
from typing import Awaitable, Callable, Union

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
