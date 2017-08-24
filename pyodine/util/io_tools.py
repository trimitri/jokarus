"""Some tools for recurrent I/O tasks."""

import asyncio
import inspect
from typing import Awaitable, Callable, Union


async def poll_resource(indicator: Union[Callable[[], bool], bool],
                        delay: Union[float, int],
                        prober: Callable[[], Union[None, Awaitable[None]]] = lambda: None,
                        on_connect: Callable[[], None] = lambda: None,
                        on_disconnect: Callable[[], None] = lambda: None,
                        continuous: bool = False) -> None:
    """Wait for/periodically probe/check/monitor a resource.

    This will check bool(`indicator`), and if False, call `probe` after `delay`
    seconds. This will repeat until `indicator` is true in which case it will
    either standby (if `continuous` is True) or stop.

    :param indicator: Something coercible to bool or a function returning
                something coercible to bool that indicates if there is
                currently a connection. This gets called quite often and should
                ideally be cheap.
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
    for name, callback in (("prober", prober), ("on_connect", on_connect),
                           ("on_disconnect", on_disconnect)):
        if not callable(callback):
            raise TypeError('Callback "%s" is not callable.', name)

    indicate = lambda: indicator() if callable(indicator) else indicator
    probe_is_async = inspect.iscoroutinefunction(prober)

    # This outer loop will only run more than once if we are observing a
    # currently healthy connection.
    while True:
        if not indicate():
            # Try connecting until there is a connection.
            while not indicate():
                if probe_is_async:
                    await prober()
                else:
                    prober()
                await asyncio.sleep(float(delay))
            on_connect()  # Notify the caller.
        if not continuous:
            break
        if not indicate():  # There was a connection, but it got lost.
            on_disconnect()
        await asyncio.sleep(float(delay))
