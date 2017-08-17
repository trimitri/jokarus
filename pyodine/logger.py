"""The pyodine logging system.

Mainly consisting of
- stderr (usually passed to systemd logging)
- application debug log
- logging of measurements

This acts like a singleton class. It does all the initialization on import and
the module's methods will act on module-level ("static") variables.
"""

import logging

_root_logger = logging.getLogger()

# We need to set the root logger to DEBUG in order to filter down below.
_root_logger.level = logging.DEBUG
_root_logger.name = 'pyodine'

# Write everything to a log file, starting a new file every hour.
_write_to_disk = logging.handlers.TimedRotatingFileHandler(
    'log/pyodine.log', when='s', interval=3600)

# Start a new file every time pyodine is run.
_write_to_disk.doRollover()
_write_to_disk.formatter = logging.Formatter(
    "{asctime} {name} {levelname} - {message} "
    "[{module}.{funcName}]", style='{')
_root_logger.addHandler(_write_to_disk)

# Write everything of priority INFO and up to stderr.
stderr = logging.StreamHandler()
stderr.setLevel(logging.INFO)
stderr.formatter = logging.Formatter(
    "{levelname:<7} {message} "
    "[{module}:{lineno}] ({name})", style='{')
_root_logger.addHandler(stderr)
