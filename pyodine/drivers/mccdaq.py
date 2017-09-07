"""A python wrapper for the MCC linux driver."""

import ctypes as ct
from enum import IntEnum
import logging
from typing import List

import numpy as np

MAX_BULK_TRANSFER = 2560
LOGGER = logging.getLogger('pyodine.drivers.mccdaq')

class RampShape(IntEnum):
    """Possible ways to ramp the frequency"""
    DESCENT = 1  # downward slope
    ASCENT = 2  # upward slope
    DIP = 3  # combination of 1 and 2, in that order


class MccDaq:
    """A stateful wrapper around the MCC DAQ device."""

    def __init__(self):
        self._daq = ct.CDLL('pyodine/drivers/mcc_daq/libmccdaq.so')
        state = self._daq.OpenConnection()
        if state == 1:  # 'kConnectionError in error types enum in C'
            raise ConnectionError("Couldn't connect to DAQ.")
        if not state == 0:
            raise ConnectionError("Unexpected error while trying to connect "
                                  "to DAQ.")
        self._offset = 0.0  # Offset voltage the ramp centers around.

    @property
    def ramp_offset(self) -> float:
        return self._offset

    @ramp_offset.setter
    def ramp_offset(self, volts: float) -> None:
        if volts <= 5 and volts >= -5:
            self._offset = volts
        else: raise ValueError("Ramp value out of bounds [-5, 5]")

    def fetch_scan(self, amplitude: float, time: float, channels: List[int],
                   shape: RampShape = RampShape.DESCENT) -> np.ndarray:
        """Scan the output voltage once and read the inputs during that time.

        The ramp will center around the current `offset` voltage, thus only an
        amplitude is given.

        :param amplitude: Peak-peak amplitude of the generated ramp.
        :param time: Approx time it takes from ramp maximum to ramp minimum.
        :param channels: Which output channels to log during sweep?
        :returns: A two-dimensional array of values read.
        """
        # TODO:
        # - Try reading at higher sample rate than writing
        if not amplitude <= 10 or not amplitude > 0:
            raise ValueError("Passed amplitude {} not in ]0, 1].".format(amplitude))
        if not time > 0:
            raise ValueError("Passed time {} not in ]0, inf[.".format(time))
        for chan in channels:
            if not chan >= 1 or not chan <= 32:
                raise ValueError("DAQ only features channels 1 to 32.")
        if not isinstance(shape, RampShape):
            raise TypeError("Invalid ramp shape passed. Use provided enum.")

        # channel setting to be passed to DAQ
        chan = np.array(channels, dtype='uint8')

        n_samples = int(MAX_BULK_TRANSFER / len(channels))
        if n_samples % 8 != 0:  # Make sure we're at a nice sample count.
            n_samples = n_samples + 8 - (n_samples % 8)

        response = np.zeros([n_samples, len(channels)])

        ret = self._daq.FetchScan(
            ct.c_double(float(self._offset)),
            ct.c_double(amplitude),
            ct.c_double(time),
            ct.c_uint(n_samples),
            ct.c_int(int(shape)),
            response.ctypes.data)
        if ret != 0:
            raise ConnectionError(
                "Failed to fetch scan. `FetchScan()` returned {}".format(ret))
        return response

    def ping(self) -> bool:
        """The DAQ talks to us and seems healthy."""
        try:
            return self._daq.Ping() == 0
        except:  # Who knows what it might raise... # pylint: disable=bare-except
            LOGGER.exception("DAQ got sick.")
        return False
