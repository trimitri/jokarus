"""Extract information from various spectroscopy signals."""

import ast
import base64
import logging
from typing import NamedTuple
import numpy as np
from scipy import signal

from . import logs
from .. import constants as cs

LOGGER = logging.getLogger('signals')


SpecScan = NamedTuple('SpecScan', [
    ('ramp', np.ndarray), ('error', np.ndarray), ('trans', np.ndarray)])


def decode_daq_scan(log_file: str, row: int = None) -> SpecScan:
    """Read the latest archived DAQ scan from the log file.

    :param log_file: Path to log file.
    :param row: Which line of the input file to use? Starts at 1!
    :returns: A SpecScan tuple read from the original data.
    """
    line = (logs.get_last_line(log_file) if row is None
            else logs.get_nth_line(log_file, row))

    _, dtype, shape, base64_data = line.strip().split('\t')
    shape = ast.literal_eval(shape)
    assert isinstance(shape, tuple) and len(shape) == 2
    data = base64.b64decode(base64_data, validate=True)
    values = np.frombuffer(data, dtype=dtype).reshape(shape).transpose()
    return SpecScan(values[0], values[1], values[2])


def format_daq_scan(data: SpecScan) -> SpecScan:
    """Scale ramp value to be in MHz and sort data by ramp value.

    This procedure is not idempotent!  Only call this once on a given data set.
    """
    ramp = data.ramp / 2**16 * 20 - 10  # ramp values in volts
    ramp *= cs.LOCKBOX_MHz_mV * cs.LOCK_SFG_FACTOR * 1000  # ramp values in MHz

    error = data.error / 2**16 * 2 - 1
    trans = data.trans / 2**16 * 10 - 5

    # We only touched the ramp values, the rest gets returned as-is. The whole
    # scan is sorted by ramp value, however.
    sorted_idx = ramp.argsort()
    return SpecScan(ramp[sorted_idx], error[sorted_idx], trans[sorted_idx])


def locate_doppler_line(data: np.ndarray,
                        min_depth: float = cs.SPEC_MIN_LOG_DIP_DEPTH,
                        preprocess_data: bool = True) -> cs.DopplerLine:
    """Locate a line in the "log" photodiode signal.

    This method basically returns the location of the absolute minimum of the
    data, given that the distance of this minimum compared to the maximum is
    reasonably large.  Otherwise it will raise.  As we sample quite evenly, we
    don't need to consider the x values here and just work by indices instead.

    :param signal: The one-dimensional numpy array to search in.
    :param min_depth: How deep has a dip in the "log" photodiode signal to be
                to be considered valid?  In Volts.
    :param preprocess_data: Expect raw data coming from DAQ and preprocess it.
                If set to False, data must have been trimmed and formatted
                before.
    :raises ValueError: Didn't find a line.
    :returns: The directional distance of the dip minimum from current spectral
                position in SpecMHz and the dip depth in Volts.
    """
    assert len(data.shape) == 2 and data.shape[0] == 3
    if preprocess_data:
        data = format_daq_scan(trim_daq_scan(data))
    ramp = data[0]
    log = data[2]
    smooth = signal.savgol_filter(log, cs.DAQ_LOG_SIGNAL_SMOOTHING_WINDOW_WIDTH, 3)
    argmin, argmax = np.argmin(smooth), np.argmax(smooth)
    depth = smooth[argmax] - smooth[argmin]
    if depth > min_depth:
        return cs.DopplerLine(distance=cs.SpecMhz(ramp[argmin]), depth=depth)
    raise ValueError("Didn't find a dip.")


def trim_daq_scan(scan: SpecScan, ignore_trans: bool = False) -> SpecScan:
    """Extract and return the reliable part of a full DAQ scan.

    As the DAQ uses a Z-shaped signal for ramp scanning, there is mostly
    useless data at the beginning and end of the scan.  This data is trimmed
    off.

    :param ignore_trans: Choose trim factors that leave more data, even if it
                means that the total transmission data contains distorted
                regions.  Set to True if you're only interested in the error
                signal.

    .. CAUTION::
        As opposed to common trimming, this procedure is not idempotent!  Only
        call this once for a given data set.

    :returns: Array in which all columns are equally stripped from the useless
                values at the start and end.
    """

    # Due to the nature of the hack around the DAQ asynchronicity, time (read:
    # sample index) is an unsafe base to rely calculations on.  We use the
    # amplitude of the loopback-ed ramp instead.
    # First, we extract the full ramp from the data.
    start = find_flank(scan.ramp, cs.DAQ_MIN_RAMP_AMPLITUDE)
    stop = find_flank(-scan.ramp, cs.DAQ_MIN_RAMP_AMPLITUDE,
                      start=len(scan.ramp) - 1, reverse=True)
    span = stop - start

    # Then we further trim off values that _are_ actual readings but that we
    # believe to be unreliable.  This is due to some apparent DAQ readout
    # dynamics that we haven't analyzed any further.
    shave_marks = (cs.DAQ_ERR_RAMP_TRIM_FACTORS if ignore_trans
                   else cs.DAQ_LOG_RAMP_TRIM_FACTORS)
    lower = int(start + (shave_marks[1] * span))
    upper = int(stop - (shave_marks[0] * span))

    return SpecScan(scan.ramp[lower:upper], scan.error[lower:upper],
                    scan.trans[lower:upper])


def find_flank(series: np.ndarray, min_height: float, start: int = 0,
               reverse: bool = False, plunge_depth: float = 0.9,
               trigger_level: float = 0.9) -> int:
    """Find the first flank that occurs after ``start`` and return its index.

    :param series: The one-dimensional numpy array to search in.
    :param min_height: Don't consider anything less tall than this a flank.
    :param start: Start searching at this index.  Defaults to 0, thus it must
                be specified when ``reverse`` ing.
    :param reverse: Walk backwards from ``start`` in searching a flank.
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

    def build_range(origin: int, backwards: bool = False) -> range:
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
