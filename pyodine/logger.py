"""The pyodine logging system.

Mainly consisting of
- stderr (usually passed to systemd logging)
- application debug log
- logging of measurements

This acts like a singleton class. It does all the initialization on import and
the module's methods will act on module-level ("static") variables.
"""

import logging
from logging.handlers import TimedRotatingFileHandler, MemoryHandler
from typing import Dict  # pylint: disable=unused-import

PROGRAM_LOG_FNAME = 'log/messages/pyodine.log'  # Log program/debug messages here.
QTY_LOG_FNAME = 'log/quantities/'  # Log readings ("quantities") here.
# We need to avoid name clashes with existing loggers.
QTY_LOGGER_PREFIX = 'qty_logger.'

_LOGGERS = dict()  # type: Dict[logging.Logger]

#
# Setup root logger.
#

_ROOT_LOGGER = logging.getLogger()

# We need to default to DEBUG in order to be able to filter downstream.
_ROOT_LOGGER.level = logging.DEBUG
_ROOT_LOGGER.name = 'pyodine'

#
# Log to disk.
#

_WRITE_TO_DISK = TimedRotatingFileHandler(PROGRAM_LOG_FNAME, when='s',
                                          interval=3600)

# Start a new file every time pyodine is run.
_WRITE_TO_DISK.doRollover()
_WRITE_TO_DISK.formatter = logging.Formatter(
    "{asctime} {name} {levelname} - {message} [{module}.{funcName}]",
    style='{')
_ROOT_LOGGER.addHandler(_WRITE_TO_DISK)

#
# Log to stderr.
#

_STDERR = logging.StreamHandler()
_STDERR.setLevel(logging.INFO)
_STDERR.formatter = logging.Formatter(
    "{levelname:<7} {message} "
    "[{module}:{lineno}] ({name})", style='{')
_ROOT_LOGGER.addHandler(_STDERR)


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
