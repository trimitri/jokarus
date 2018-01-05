"""Extract information from various spectroscopy signals."""

import ast
import base64
from typing import Optional
import numpy as np

from .. import constants as cs
from .. import logger

def decode_daq_scan(log_file: str) -> np.ndarray:
    """Read the latest archived DAQ scan from the log file.

    :param log_file: Path to log file.
    :returns: The raw data as initially read.
    """
    last_line = logger.get_last_line(log_file, max_line_length=2e5)
    _, dtype, shape, base64_data = last_line.decode().strip().split('\t')
    shape = ast.literal_eval(shape)
    assert isinstance(shape, tuple) and len(shape) == 2
    data = base64.b64decode(base64_data, validate=True)
    values = np.frombuffer(data, dtype=dtype).reshape(shape).transpose()
    return values


def format_daq_scan(data: np.ndarray) -> np.ndarray:
    """Scale ramp value to be in MHz and sort data by ramp value."""
    ramp = data[0]  # Ramp values are in ADC counts.
    ramp = ramp * 2**-16 * 20 - 10  # ramp values in volts
    ramp *= cs.LOCKBOX_MHz_mV * cs.LOCK_SFG_FACTOR * 1000  # ramp values in MHz

    # We only touched the ramp values, the rest gets returned as-is. The whole
    # scan is sorted by ramp value, however.
    return np.array([ramp, *data[1:]])[:, ramp.argsort()]


def locate_doppler_line() -> Optional[float]:
    pass


def trim_daq_scan(data: np.ndarray) -> np.ndarray:
    """Extract and return the reliable part of a full DAQ scan.

    As the DAQ uses a Z-shaped signal for ramp scanning, there is mostly
    useless data at the beginning and end of the scan.  This data is trimmed
    off.

    :raises ValueError: Data has an unexpected number of columns.  We expect
                three or two columns (ramp amplitude, error signal, <log
                port>).
    :returns: Array in which all columns are equally stripped from the useless
                values at the start and end.
    """
    try:  # Extract columns.
        ramp, _, log = data
    except ValueError:
        ramp, _ = data
        log = None

    # Due to the nature of the hack around the DAQ asynchronicity, time (read:
    # sample index) is an unsafe base to rely calculations on.  We use the
    # amplitude of the loopback-ed ramp instead.
    # First, we extract the full ramp from the data.
    start = find_flank(ramp, cs.DAQ_MIN_RAMP_AMPLITUDE)
    stop = find_flank(-ramp, cs.DAQ_MIN_RAMP_AMPLITUDE,
                      start=len(ramp) - 1, reverse=True)
    span = stop - start

    # Then we further trim off values that _are_ actual readings but that we
    # believe to be unreliable.
    shave_marks = (cs.DAQ_ERR_RAMP_TRIM_FACTORS if log is None
                   else cs.DAQ_LOG_RAMP_TRIM_FACTORS)
    lower = int(start + (shave_marks[1] * span))
    upper = int(stop - (shave_marks[0] * span))

    return data[:, lower:upper]


def find_flank(series: np.ndarray, min_height: float, start: int = 0,
               reverse: bool = False, plunge_depth: float = 0.9,
               trigger_level: float = 0.9) -> int:
    """Find the first flank that occurs after `start` and return its index.

    :param series: The one-dimensional numpy array to search in.
    :param min_height: Don't consider anything less tall than this a flank.
    :param start: Start searching at this index.  Defaults to 0, thus it must
                be specified when `reverse`ing.
    :param reverse: Walk backwards from `start` in searching a flank.
    :param plunge_depth: Only consider a maximum a maximum wenn we dropped at
                least this much of the (local_max - local_min) distance
                afterwards. This avoids finding spurious "maxima" in noise.
    :param trigger_level: When tracking back from the local maximum that was
                found to locate the actual flank, return the index at which the
                value reaches this much of the local max value.
    :raises AssertionError: The array was not one-dimensional.
    :raises ValueError: No flank has been found.
    :returns: Index, at which the flank has risen to its full amplitude.
    """
    assert len(series.shape) == 1  # Only accept one-dimensional arrays.

    def build_range(origin: int, backwards: bool = False):
        """Provide an iterator starting from a point to the left or right."""
        if backwards:
            return range(origin, -1, -1)
        return range(origin, len(series))

    span = build_range(start, reverse)
    candidate = span[0]
    last_max = series[candidate]
    last_min = series[candidate]
    for i in span[1:]:
        value = series[i]

        # Track maximum and minimum
        if value > last_max:
            candidate = i
            last_max = value
        elif value < last_min:
            last_min = value

        if (last_max - last_min > min_height
                and value < last_max - plunge_depth * (last_max - last_min)):
            break
    # Track back from the maximum that has been found to find the actual flank.
    for j in build_range(candidate, not reverse):
        if series[j] < last_max - trigger_level * (last_max - last_min):
            return j
    raise ValueError("No flank was found.")
