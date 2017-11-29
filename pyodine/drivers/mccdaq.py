"""A python wrapper for the MCC linux driver."""

import ctypes as ct
from enum import IntEnum
import logging
import threading
from typing import List, Tuple

import numpy as np

DISALLOW_NAIVE_LOCKING = True
"""Error instead of blocking when trying to make requests to a busy device."""

MAX_AOUT_SAMPLES = 2560
LOGGER = logging.getLogger('pyodine.drivers.mccdaq')

class DaqChannel(IntEnum):
    """The DAQ features 16 analog input in single-ended mode."""
    C_0 = 0
    C_1 = 1
    C_2 = 2
    C_3 = 3
    C_4 = 4
    C_5 = 5
    C_6 = 6
    C_7 = 7
    C_8 = 8
    C_9 = 9
    C_10 = 10
    C_11 = 11
    C_12 = 12
    C_13 = 13
    C_14 = 14
    C_15 = 15

class RampShape(IntEnum):
    """Possible ways to ramp the frequency"""
    DESCENT = 1  # downward slope
    ASCENT = 2  # upward slope
    DIP = 3  # combination of 1 and 2, in that order

class InputRange(IntEnum):
    """The DAQ can use different input attenuations when sampling."""
    PM_1V = 1    # +/- 1 volt (= 2V max. amplitude)
    PM_2V = 2    # +/- 2 volt (= 4V max. amplitude)
    PM_5V = 5    # +/- 5 volt (= 10V max. amplitude)
    PM_10V = 10  # +/- 10 volt (= 20V max. amplitude)


class MccDaq:
    """A stateful wrapper around the MCC DAQ device."""

    def __init__(self) -> None:
        """Construnctor shouldn't block and is not thread safe."""
        self._daq = ct.CDLL('pyodine/drivers/mcc_daq/libmccdaq.so')
        state = self._daq.OpenConnection()
        if state == 1:  # 'kConnectionError in error types enum in C'
            raise ConnectionError("Couldn't connect to DAQ.")
        if not state == 0:
            raise ConnectionError("Unexpected error while trying to connect "
                                  "to DAQ.")
        self._offset = 0.0  # Offset voltage the ramp centers around.

        # As main methods of this class are blocking, they are likely to be
        # executed in a threaded environment.  We thus need to provide a mutex
        # lock for the device.
        self._lock = threading.Lock()

    @property
    def ramp_offset(self) -> float:
        return self._offset

    @ramp_offset.setter
    def ramp_offset(self, volts: float) -> None:
        if volts <= 5 and volts >= -5:
            self._offset = volts
        else: raise ValueError("Ramp value out of bounds [-5, 5]")

    @property
    def is_busy(self) -> bool:
        """Is the device currently blocked?

        :returns bool: True: Unusual wait times are to be expected when using the
                    device now.  False: OK to use.
        """
        if self._lock.acquire(False):
            self._lock.release()
            return False
        return True

    def fetch_scan(self, amplitude: float, time: float,
                   channels: List[Tuple[DaqChannel, InputRange]],
                   shape: RampShape = RampShape.DESCENT) -> np.ndarray:
        """Scan the output voltage once and read the inputs during that time.

        The ramp will center around the current `offset` voltage, thus only an
        amplitude is given.

        :param amplitude: Peak-peak amplitude of the generated ramp.
        :param time: Approx time it takes from ramp maximum to ramp minimum.
        :param channels: Which output channels to log during sweep?
        :returns: A two-dimensional array of values read. Those are raw uint16,
                    as received from the device's 16-bit ADC chip.
        :raises BlockingIOError: The DAQ is currently busy.
        """
        # TODO:
        # - Try reading at higher sample rate than writing
        # - Validate `channels`
        if not amplitude <= 10 or not amplitude > 0:
            raise ValueError("Passed amplitude {} not in ]0, 10].".format(amplitude))
        if not time > 0:
            raise ValueError("Passed time {} not in ]0, inf[.".format(time))
        if not isinstance(shape, RampShape):
            raise TypeError("Invalid ramp shape passed. Use provided enum.")

        # We choose to block the mutex quite early to avoid two calls being
        # prepared at the same time in a threaded environment.
        if DISALLOW_NAIVE_LOCKING and self.is_busy:
            raise BlockingIOError("DAQ is busy.")
        n_samples = MAX_AOUT_SAMPLES

        # Allocate some memory for the C library to save it's result in.
        response = np.empty([n_samples, len(channels)], dtype=np.uint16)

        # CAUTION: Beware of the python optimizer/garbage collector!  When
        # inlining the two variables below, Python clears the memory before
        # the C library starts to access it, leading to unexpected
        # behaviour of the C code.
        chan = np.array([c[0] for c in channels], dtype='uint8')
        gain = np.array([c[1] for c in channels], dtype='uint8')
        with self._lock:
            ret = self._daq.FetchScan(
                ct.c_double(float(self._offset)),
                ct.c_double(amplitude),
                ct.c_double(time),
                ct.c_uint(n_samples),
                chan.ctypes.data,  # channels; See note above!
                gain.ctypes.data,  # gains; See note above!
                ct.c_uint(len(channels)),
                ct.c_int(int(shape)),
                response.ctypes.data)
        if ret != 0:
            raise ConnectionError(
                "Failed to fetch scan. `FetchScan()` returned {}".format(ret))
        return response

    def sample_channels(self, channels: List[Tuple[DaqChannel, InputRange]],
                        n_samples: int = 1, frequency: float = 1000) -> np.ndarray:
        """Sample analog input channels.

        :param channels: Which output channels to log during sweep?
        :returns: A two-dimensional array of values read. Those are raw uint16,
                    as received from the device's 16-bit ADC chip.
        :raises BlockingIOError: The device is currently blocked.
        :raises ConnectionError: DAQ's playing tricks...
        """
        if DISALLOW_NAIVE_LOCKING and self.is_busy:
            raise BlockingIOError("DAQ is busy.")

        # Allocate some memory for the C library to save it's result in.
        response = np.empty([n_samples, len(channels)], dtype=np.uint16)

        # CAUTION: Beware of the python optimizer/garbage collector! When
        # inlining the two variables below, Python clears the memory before the
        # C library starts to access it, leading to unexpected behaviour of the
        # C code.
        chan = np.array([c[0] for c in channels], dtype='uint8')
        gain = np.array([c[1] for c in channels], dtype='uint8')
        with self._lock:
            ret = self._daq.SampleChannels(
                ct.c_uint(n_samples),
                ct.c_double(frequency),
                chan.ctypes.data,  # channels; See note above!
                gain.ctypes.data,  # gains; See note above!
                ct.c_uint(len(channels)),
                response.ctypes.data)
        if ret != 0:
            raise ConnectionError("Failed to sample channels. "
                                  "`SampleChannels()` returned {}".format(ret))
        return response

    def ping(self) -> bool:
        """The DAQ talks to us and seems healthy."""
        try:
            with self._lock:
                return self._daq.Ping() == 0
        except:  # Who knows what it might raise... # pylint: disable=bare-except
            LOGGER.exception("DAQ got sick.")
        return False
