"""Extract data from the pyodine log files.

Not tested in Python < 3.5.
Don't use features > Python 3.5.
"""

import io
import logging
import pandas as pd

from .. import constants as cs


def get_last_line(file_name: str,
                  max_line_length: int = cs.DAQ_MAX_SPEC_SCAN_BYTES) -> str:
    """Return the last line of given newline-terminated file.

    Relies on readlines() to determine line boundaries.

    :param file_name: Path to file for `open()`
    :param max_line_length: The lines expected must not be longer than this
                many bytes.
    :raises IndexError: No lines could be read at all.
    """
    with open(file_name, mode='rb') as handle:
        try:
            handle.seek(-2 * int(max_line_length) - 1, io.SEEK_END)
        except OSError:
            logging.debug("File is shorter than max_line_length.")
        last_lines = handle.readlines()
        if len(last_lines) < 2:
            logging.warning("Could not get more than one line. "
                            "Line integrity is not guaranteed.")
        return last_lines[-1].decode()


def get_nth_line(file_name: str, line_no: int) -> str:
    """Return the given line of an input file.

    :param line_no: Which line of the input file to return? Starts at 1!

    :raises ValueError: line_no is too large for a small file or < 1.
    """
    if line_no < 1:
        raise ValueError(""""line_no" starts at 1.""")

    with open(file_name) as file:
        for row, content in enumerate(file):
            # This does look like an inefficient loop where we could simply use
            # indexing.  But it is not. Direct indexing of lines in a file is
            # not possible, as the file needs to be read in completely anyway
            # to find out where newlines are.
            if row == line_no - 1:  # Line numbers start at 1.
                return content

        raise ValueError("File doesn't have {} rows.".format(line_no))


def parse_qty_log(file_name: str) -> pd.Series:
    """Parse a pyodine log file into a Pandas object."""
    try:
        data = pd.read_table(
            file_name, header=None, index_col=0, names=['time', 'value'],
            squeeze=True, parse_dates=True)  # type: pd.Series
    except IndexError:
        # Names like above can only be assigned only if it the quantity is a
        # scalar value.
        data = pd.read_table(file_name, header=None, index_col=0, squeeze=True,
                             parse_dates=True)
    return data
