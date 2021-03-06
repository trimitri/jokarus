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
import os
import re
from typing import Dict, List, Union  # pylint: disable=unused-import

from .util import asyncio_tools as tools

PRIMARY_LOG_LOCATION = 'log/'
"""The main log location. Must be writable or creatable.

OSError will be raised if this isn't writeable or createable.
"""
SECONDARY_LOG_LOCATION = '/media/sdcard/pyodine_log/'
"""The location of the redundant logs.

If this isn't writeable or createable, a non-fatal Error will be displayed.
"""
PROGRAM_LOG_DIR = 'messages/'  # Log program/debug messages here.
PROGRAM_LOG_FILE = 'pyodine.log'  # Log program/debug messages here.
QTY_LOG_DIR = 'quantities/'  # Log readings ("quantities") here.
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
_VALID_LOG_LOCATIONS = []  # type: List[str]
"""List of writeable logging directories to use."""

def init() -> None:
    """Call this on first import. Don't call it again later.

    This sets up the default loggers and logging locations.
    """
    global _is_inited
    if _is_inited:
        raise RuntimeError('This is a "singleton module". Only init() once.')
    _is_inited = True

    root_logger = logging.getLogger()
    # We need to default to DEBUG in order to be able to filter downstream.
    root_logger.level = logging.DEBUG
    root_logger.name = 'pyodine'

    # Log to files in two separate locations.

    _setup_log_dir(PRIMARY_LOG_LOCATION)  # Will raise if primary logging can't work.
    _VALID_LOG_LOCATIONS.append(PRIMARY_LOG_LOCATION)
    try:
        _setup_log_dir(SECONDARY_LOG_LOCATION)
    except OSError:
        logging.error("Can't set up secondary log location!")
    else:
        _VALID_LOG_LOCATIONS.append(SECONDARY_LOG_LOCATION)
    # We need to specify 3600 seconds here instead of one hour, to force
    # detailed file name suffixes for manual log rotation.  This may lead to
    # problems if the program is started/stopped multiple times per second.
    writers = [TimedRotatingFileHandler(directory + PROGRAM_LOG_DIR + PROGRAM_LOG_FILE,
                                        when='s', interval=3600)
               for directory in _VALID_LOG_LOCATIONS]
    for writer in writers:
        writer.doRollover()  # Start a new file every time pyodine is run.
        writer.formatter = logging.Formatter(
            "{asctime} {name} {levelname} - {message} [{module}.{funcName}]",
            style='{')

    buffers = [MemoryHandler(200, target=writer) for writer in writers]

    for log_buffer in buffers:
        root_logger.addHandler(log_buffer)

    # Log to stderr.

    stderr = logging.StreamHandler()
    stderr.setLevel(logging.INFO)
    stderr.formatter = logging.Formatter(
        "{levelname:<7} {message} "
        "[{module}:{lineno}] ({name})", style='{')
    root_logger.addHandler(stderr)


def log_quantity(qty_id: str, value: Union[float, str], time: float = None) -> None:
    """Append "value" to the logfile of given name.

    :param id: This distinguishes logfiles from each other.
    :param time: Unix time of when the passed "value" was measured. If passed,
                this will be printed in addition to the current time.
    :param value: Value to log. None is fine as well.
    """
    logger = _get_qty_logger(qty_id)
    if time:
        logger.info('%s\t%s', time, value)
    else:
        logger.info('%s', value)


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
    if not seconds > .5:
        raise ValueError("Choose a flushing interval larger than 0.5s.")
    asyncio.ensure_future(tools.repeat_task(flush_to_disk, seconds))


def start_new_files() -> None:
    """Start new log files now. Don't wait for the usual period."""
    global _LOGGERS
    # Act the root logger and our quantity loggers.
    loggers = [logging.getLogger()] + list(_LOGGERS.values())
    handlers = [h for l in loggers for h in l.handlers
                if isinstance(h, TimedRotatingFileHandler)]
    for handler in handlers:
        handler.doRollover()


def ellipsicate(message: str, max_length: int = 40, strip: bool = True) -> str:
    """Return a shortened version of a string if it exceeds max_length.

    This will turn 'bizbazfrobnicator' into "biz ... tor".
    """
    msg = re.sub(r'\s+', ' ', str(message))  # only allow ' ' for whitespace
    if strip:
        msg = msg.strip()
    if len(msg) <= max_length:
        return msg
    snip_length = int((max_length - 5) / 2)  # ellipsis padded with spaces
    return str(msg[:snip_length] + ' ... ' + msg[-snip_length:])


def _get_qty_logger(name: str) -> logging.Logger:
    name = str(name)
    if not name.isidentifier():
        raise ValueError("Invalid log ID \"{}\". Only valid python "
                         "identifiers are allowed for log IDs.".format(name))

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
        writers = [TimedRotatingFileHandler(directory + QTY_LOG_DIR + str(name) + '.log',
                                            when='s', interval=3600)
                   for directory in _VALID_LOG_LOCATIONS]
        for writer in writers:
            writer.formatter = logging.Formatter("{asctime}\t{message}", style='{')
            # Start a new file for each pyodine run.
            writer.doRollover()

        # Buffer file writes to keep I/O down. We will flush the buffer at
        # given time intervals. If that flushing should fail, however, we'll
        # flush at 100 entries (which is about 4kB of data).
        buffers = [MemoryHandler(100, target=writer) for writer in writers]

        logger = logging.getLogger(logger_name)
        for log_buffer in buffers:
            logger.addHandler(log_buffer)
        logger.propagate = False  # Don't pass messages to root logger.
        _LOGGERS[logger_name] = logger

        return logger


def _setup_log_dir(path: str) -> None:
    """Check / prepare the passed folder to accept log files.

    Needs to exist and be writable, basically.

    :raises OSError: Didn't succeed.
    """
    log_dirs = [path + sub for sub in [PROGRAM_LOG_DIR, QTY_LOG_DIR]]
    for directory in log_dirs:
        os.makedirs(directory, exist_ok=True)  # Raises OSError
        if not os.access(directory, os.W_OK):
            raise OSError("Couldn't write log location {}.".format(directory))
