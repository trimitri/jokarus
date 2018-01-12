"""This module encapsulates the pyodine system state into a runlevel scheme."""

import enum


class Runlevel(enum.IntEnum):
    """The incremental pyodine system state.

    There are eight possible states (including "undefined") which conveniently
    projects onto a three-bit state register.
    """
    UNDEFINED = 0
    """Not clearly in one of the other states.

    The system could currently be transitioning.  This can not be used to
    request a runstate.
    """
    SHUTDOWN = 1
    """The system is ordered to prepare for physical power-off.

    Even when requested, the system will never report being in this state.  It
    will just keep on maintaining a state as safe as possible for power-off.
    """
    STANDBY = 2
    """The system is on stand by and ready.

    Cold subsystems tests have been conducted sucessfully.  System is
    reasonably safe to switch off, although the specific measures being done
    for `SHUTDOWN` are omitted.
    """
    AMBIENT = 3
    """System is thermalized to ambient temperatures and ready to heat up.

    Although the system will eventually report being `AMBIENT` on reaching this
    level, due to changing ambient temperatures it is necessary to keep
    actively pursuing this level.  The system may drop to `UNDEFINED`
    occasionally if such drifts happen.
    """
    HOT = 4
    """All components are brought to their working temperature.

    For tunable components (MiOB!) the full tuning range is considered valid.
    """
    PRELOCK = 5
    """The correct spectral line was found; system is ready to lock."""
    LOCK = 6
    """The system is locked on (the correct) HFS line."""
    BALANCED = 7
    """The working point is aligned, tuners have maximum range of motion. """
