"""The pyodine logging system.

Mainly consisting of
- stderr (usually passed to systemd logging)
- application debug log
- logging of measurements

This acts like a singleton class. It does all the initialization on import and
the module's methods will act on module-level ("static") variables.
"""

import logging
import logging.handlers

PROGRAM_LOG_FNAME = 'log/pyodine.log'

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

_WRITE_TO_DISK = logging.handlers.TimedRotatingFileHandler(
    PROGRAM_LOG_FNAME, when='s', interval=3600)

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
    # FIXME: do some actual checks here.
    return True
