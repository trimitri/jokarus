"""Extract information from various spectroscopy signals."""

from typing import Optional
import numpy as np

from .. import constants as cs

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

    # Due to the nature of the hack around the DAQ asynchronicity, time (read:
    # sample index) is an unsafe base to rely calculations on.  We use the
    # amplitude of the loopback-ed ramp instead.
    # First, we extract the full ramp from the data.
    start = find_first_max(ramp, cs.DAQ_MIN_RAMP_AMPLITUDE)
    stop = find_first_max(ramp, cs.DAQ_MIN_RAMP_AMPLITUDE, start=len(ramp),
                          reverse=True)
    span = stop - start

    # Then we further trim off values that _are_ actual readings but that we
    # believe to be unreliable.
    shave_marks = (cs.DAQ_LOG_RAMP_TRIM_FACTORS if log
                   else cs.DAQ_ERR_RAMP_TRIM_FACTORS)
    lower = start + (shave_marks[1] * span)
    upper = stop - (shave_marks[0] * span)

    return data[:, lower:upper]

def find_first_max(series: np.ndarray, min_height: float, start: int = 0,
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
