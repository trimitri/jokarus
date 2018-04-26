"""Provide a centralized place of access to global objects.

Some things are here to avoid circular dependencies, for example.
"""

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
    from .controller import interfaces, lock_buddy, runlevels, subsystems  # pylint: disable=unused-import


class REQUEST:  # pylint: disable=too-few-public-methods
    """The currently requested system state. Does not inquire!

    Those control variables are set directly from other modules.  They even
    __need__ to be defined from other modules, as they're invalid on
    import.
    """
    # The reason that this class was put here (it originally resided in
    # runlevels.py), was to resolve some circular dependency around the
    # runlevels module.
    # Placing this in texus_relay instead would be misleading, as the runlevel
    # might also be requested during manual operation (when TEXUS commands
    # are overridden).
    # Placing it in an own module would be possible and probably cleaner.
    is_override = False
    """Are the TEXUS timer commands overriden by manual control? """
    level = None  # type: runlevels.Runlevel
    """Which runlevel should the system pursue?"""
    liftoff = None  # type: bool
    """Did the rocket lift off yet?"""
    microg = None  # type: bool
    """Did the lift off phase complete yet?"""
    off = None  # type: bool
    """Is an (emergency?) shutdown requested?"""


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


def is_shaky() -> bool:
    """The system is most likely experiencing heavy vibration right now."""
    return REQUEST.liftoff and not REQUEST.microg


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
        tools.poll_resource(check, .5, name="all subsystems"), timeout, loop=GLOBALS.loop)
    LOGGER.info("Subsystems are now online.")


def validate_request() -> None:
    """Make sure all the REQUEST elements are set.  They are not set on import.

    :raises RuntimeError: At least one of the request elements wasn't set (yet).
    """
    for setting in [REQUEST.liftoff, REQUEST.microg, REQUEST.off, REQUEST.level]:
        if setting is None:
            raise RuntimeError("`runlevels.py` doesn't know the system state.")
