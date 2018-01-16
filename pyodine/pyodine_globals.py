"""Provide a centralized place of access to global objects."""

import asyncio
import logging
import typing

from .util import asyncio_tools as tools
from . import constants as cs

LOGGER = logging.getLogger("pyodine_globals")

if typing.TYPE_CHECKING:
    # For the type annotations below to work, we need these "unneeded" imports.
    # The type annotations, on the other hand, are crucial for mypy and jedi to
    # work.  And if we don't hide those imports during a normal run, there are
    # cyclic imports.
    from .controller import interfaces, lock_buddy, subsystems

class GLOBALS:  # pylint: disable=too-few-public-methods
    """Stuff that would otherwise get passed around throughout pyodine.

    Passing stuff around is usually the better practice, but in this case all
    those objects are only existing at most once throughout the whole program
    lifetime.
    """
    face = None  # type: interfaces.Interfaces
    """The interfaces management object."""
    loop = asyncio.get_event_loop()  # type: asyncio.AbstractEventLoop
    """The event loop used for scheduling background tasks.

    This can be (re-)set externally, but as it will usually be the main thread
    that is importing this module first, it is set to the default event loop
    running in the import thread at import time.
    """
    subs = None  # type: subsystems.Subsystems
    """The subsystems controller."""
    locker = None  # type: lock_buddy.LockBuddy
    """The lock controller."""

async def systems_online(timeout: float = cs.SYSTEMS_INIT_TIMOUT) -> None:
    """Wait until all systems are online and raise a TimeoutError on failure.

    :raises TimeoutError: Not all systems are online, even after waiting.
    """
    def check() -> bool:
        return all([GLOBALS.face, GLOBALS.face.has_texus(),
                    GLOBALS.locker,
                    GLOBALS.subs, GLOBALS.subs.laser, GLOBALS.subs.has_menlo()])
    if check():
        return
    await asyncio.wait_for(  # raises TimeoutError
        tools.poll_resource(check, .5), timeout, loop=GLOBALS.loop)
    LOGGER.info("Subsystems are now online.")
