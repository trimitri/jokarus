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
        ramp, error, log = data
    except ValueError:
        ramp, error = data

    # Due to the nature of the hack around the DAQ asynchronicity, time (read:
    # sample index) is an unsafe base to rely calculations on.  We use the
    # amplitude of the loopback-ed ramp instead.
    shave_marks = (cs.DAQ_LOG_RAMP_TRIM_FACTORS if log
                   else cs.DAQ_ERR_RAMP_TRIM_FACTORS)
    ramp_max, ramp_min = ramp.max(), ramp.min()
    span = ramp_max - ramp_min
    # Calculate ramp values between which we expect reliable data.
    upper = ramp_max - (shave_marks[0] * span)
    lower = ramp_min + (shave_marks[1] * span)
    # Find the indices at which those values are.  This is a little tricky, as
    # due to the Z shape of the ramp, both values are passed twice.

