"""The pyodine logging system.

Mainly consisting of
- stderr (usually passed to systemd logging)
- application debug log
- logging of measurements

This acts like a singleton class. It does all the initialization on import and
the module's methods will act on module-level ("static") variables.
"""

import logging
from logging.handlers import TimedRotatingFileHandler

PROGRAM_LOG_FNAME = 'log/pyodine.log'  # Log program/debug messages here.
QTY_LOG_FNAME = 'log/pyodine.log'  # Log readings ("quantities") here.

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


def log_quantity(id: str, time: float, value: float) -> None:
    """Append "value" to the logfile of given name.

    :param id: This distinguishes logfiles from each other.
    :param time: Unix time of when the passed "value" was measured.
    :param value: Value to log. None is fine as well.
    """
    logger = _get_logger(id)


def _get_logger(name: str) -> Logger:
    name = str(name)
    if not name.isidentifier():
        raise ValueError("Invalid log ID \"%s\"Only letters, numbers and _ "
                         "allowed for log IDs.", name)
    global _loggers
    try:
        logger = _loggers[name]
    except KeyError:
        # FIXME
        pass

    return logger
