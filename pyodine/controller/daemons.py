"""A registry of notable asyncio tasks."""

import asyncio
import enum
from typing import Dict  # pylint: disable=unused-import


class Service(enum.IntEnum):
    """Major pyodine daemons."""
    DRIFT_COMPENSATOR = 10
    """Temperature drift compensator on a running lock (procedures.py). """
    LOCKER = 20
    """Maintains a running lock.  Includes relocker and simple balancer."""
    PRELOCKER = 30
    """Prelock-maintainer that doesn't actually lock. """


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


def cancel(service: Service) -> bool:
    """Cancel given task (if it was running).

    :returns: Task was running.
    :raises ValueError: Unknown `service`.
    """
    try:
        return TASKS[service].cancel() if TASKS[service] is not None else False
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
