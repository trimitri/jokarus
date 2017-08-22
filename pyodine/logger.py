"""The pyodine logging system.

Mainly consisting of
- stderr (usually passed to systemd logging)
- application debug log
- logging of measurements

This acts like a singleton class. It does all the initialization on import and
the module's methods will act on module-level ("static") variables.
"""
import asyncio
import logging
from logging.handlers import (BufferingHandler, MemoryHandler,
                              TimedRotatingFileHandler)
from typing import Dict  # pylint: disable=unused-import

PROGRAM_LOG_FNAME = 'log/messages/pyodine.log'  # Log program/debug messages here.
QTY_LOG_FNAME = 'log/quantities/'  # Log readings ("quantities") here.
# We need to avoid name clashes with existing loggers.
QTY_LOGGER_PREFIX = 'qty_logger.'

# We will use these module-scope globals here to make our module behave like a
# singleton class. Pylint doesn't like that.
# pylint: disable=global-statement

_LOGGERS = {}  # type: Dict[str, logging.Logger]

# Those two are not constants but actually keep track of the current state of
# the loaded module. Pylint doesn't like that either.
# pylint: disable=invalid-name
_is_inited = False
_is_flushing = False  # A task for flushing buffers to disk is running.


def is_ok() -> bool:
    """Currently logging successfully."""
    # FIXME: do some actual checks here.
    return True


def log_quantity(qty_id: str, time: float, value: float) -> None:
    """Append "value" to the logfile of given name.

    :param id: This distinguishes logfiles from each other.
    :param time: Unix time of when the passed "value" was measured.
    :param value: Value to log. None is fine as well.
    """
    logger = _get_qty_logger(qty_id)
    logger.info('%s\t%s', time, value)


def flush_to_disk() -> None:
    """Flush all log entries from buffer memory to disk."""
    global _LOGGERS
    # Act the root logger and our quantity loggers.
    loggers = [logging.getLogger()] + list(_LOGGERS.values())
    handlers = [h for l in loggers for h in l.handlers
                if isinstance(h, BufferingHandler)]
    for handler in handlers:
        handler.flush()


def start_flushing_regularly(seconds: float) -> None:
    """Schedule regular flushing of the the buffered data to disk.

    This needs a running asyncio event loop to work. Make sure one is running,
    otherwise a warning is issued and the flushing is scheduled anyway.

    Specifying a long interval does not reliably avoid frequent writes, as the
    buffers will flush automatically if necessary to prevent overflow.

    :param seconds: Interval for flushing. See note on flushing interval above.
    """
    global _is_flushing
    if _is_flushing:
        logging.error("Flushing was already scheduled already. Ignoring.")
        return
    _is_flushing = True
    if seconds < 2:
        raise ValueError("Interval must be > 2 seconds to ensure asyncio flow.")

    if not asyncio.get_event_loop().is_running():
        logging.warning("Periodical disk flushing of logs might not work, as "
                        "no event loop is running. Scheduling anyway.")

    async def worker() -> None:
        while True:
            flush_to_disk()
            asyncio.sleep(float(seconds))
    asyncio.ensure_future(worker())


def start_new_files() -> None:
    """Start new log files now. Don't wait for the usual period."""
    global _LOGGERS
    # Act the root logger and our quantity loggers.
    loggers = [logging.getLogger()] + list(_LOGGERS.values())
    handlers = [h for l in loggers for h in l.handlers
                if isinstance(h, TimedRotatingFileHandler)]
    for handler in handlers:
        handler.doRollover()


def _get_qty_logger(name: str) -> logging.Logger:
    name = str(name)
    if not name.isidentifier():
        raise ValueError("Invalid log ID \"%s\". Only valid python "
                         "identifiers are allowed for log IDs.", name)

    logger_name = QTY_LOGGER_PREFIX + name

    # Actually the logging class provides a singleton behaviour of Logger
    # objects. We keep our own list however, as we need some specific
    # configuration and handlers attached.
    global _LOGGERS
    try:
        return _LOGGERS[logger_name]
    except KeyError:
        # Create the logger.

        # We need to specify 3600 seconds here instead of one hour, to force
        # detailed file name suffixes for manual log rotation.
        file_handler = TimedRotatingFileHandler(
            QTY_LOG_FNAME + str(name) + '.log', when='s', interval=3600)
        file_handler.formatter = logging.Formatter("{asctime}\t{message}",
                                                   style='{')
        # Start a new file for each pyodine run.
        file_handler.doRollover()

        # Buffer file writes to keep I/O down. We will flush the buffer at
        # given time intervals. If that flushing should fail, however, we'll
        # flush at 100 entries (which is about 4kB of data).
        buffer = MemoryHandler(100, target=file_handler)

        logger = logging.getLogger(logger_name)
        logger.addHandler(buffer)
        logger.propagate = False  # Don't pass messages to root logger.
        _LOGGERS[logger_name] = logger

        return logger


def _init() -> None:
    global _is_inited
    if _is_inited:
        logging.error("Logger module initializes automatically. Don't do it.")
        return
    _is_inited = True

    root_logger = logging.getLogger()
    # We need to default to DEBUG in order to be able to filter downstream.
    root_logger.level = logging.DEBUG
    root_logger.name = 'pyodine'

    # Log to file.

    # We need to specify 3600 seconds here instead of one hour, to force
    # detailed file name suffixes for manual log rotation.
    write_to_disk = TimedRotatingFileHandler(PROGRAM_LOG_FNAME, when='s',
                                             interval=3600)
    # Start a new file every time pyodine is run.
    write_to_disk.doRollover()
    write_to_disk.formatter = logging.Formatter(
        "{asctime} {name} {levelname} - {message} [{module}.{funcName}]",
        style='{')

    buffer = MemoryHandler(200, target=write_to_disk)

    root_logger.addHandler(buffer)

    # Log to stderr.

    stderr = logging.StreamHandler()
    stderr.setLevel(logging.INFO)
    stderr.formatter = logging.Formatter(
        "{levelname:<7} {message} "
        "[{module}:{lineno}] ({name})", style='{')
    root_logger.addHandler(stderr)


# Initializing a module at import time can be slow. However, as the logger
# module is the very first and most important module of pyodine, we do that
# here:
_init()
