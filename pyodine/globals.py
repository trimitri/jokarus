"""Provide a centralized place of access to global objects."""

import asyncio

from .controller import lock_buddy, subsystems  # pylint: disable=unused-import

class GLOBALS:  # pylint: disable=too-few-public-methods
    """Stuff that would otherwise get passed around throughout pyodine.

    Passing stuff around is usually the better practice, but in this case all
    those objects are only existing at most once throughout the whole program
    lifetime.
    """
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
