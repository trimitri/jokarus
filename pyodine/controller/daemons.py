"""A registry of notable asyncio tasks."""

import asyncio
import enum
from typing import Dict  # pylint: disable=unused-import


class Service(enum.IntEnum):
    """Major pyodine daemons."""
    DRIFT_COMPENSATOR = 10
    """Temperature drift compensator on a running lock (procedures.py). """
    PRELOCKER = 20
    """Prelock and lock and basic lock maintenance algorithm.

    If this is running, the system is locked (at least should be).
    """
    BALANCER = 30
    """Adjusts the MiOB temperature in a running lock to allow the MO current
    tuner to stay in the center of it's range of motion.
    """


TASKS = {}  # type: Dict[Service, asyncio.Task]
for serv in Service:
    TASKS[serv] = None


def is_running(service: Service) -> bool:
    """Is the given pyodine daemon currently running?

    :raises ValueError: Unknown `service`.
    """
    try:
        return bool(TASKS[service]) and not TASKS[service].done()
    except KeyError:
        raise ValueError("Unknown service type.")


def register(service: Service, task: asyncio.Task) -> None:
    """Register an externally started task.

    :raises ValueError: Unknown `service`.
    """
    try:
        TASKS[service] = task
    except KeyError:
        raise ValueError("Unknown service type.")
