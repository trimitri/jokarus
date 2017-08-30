"""A python wrapper for the MCC linux driver."""

import ctypes as ct
import logging
import numpy as np

MAX_BULK_TRANSFER = 2560
LOGGER = logging.getLogger('pyodine.drivers.mccdaq')

class MccDaq:
    """A stateful wrapper around the MCC DAQ device."""

    def __init__(self):
        self._daq = ct.CDLL('pyodine/drivers/mcc_daq/libmccdaq.so')
        self._daq.OpenConnection()

    def scan_ramp(self, min_val: float = -10, max_val: float = 10,
                  gate_time: float = 1, channels: list = None) -> np.ndarray:
        """Scan the output voltage once and read the inputs during that time.

        :param min_val: Minimum output voltage
        :param max_val: Maximum output voltage
        :param duration: Time T = 1/f for the full frequency sweep
        :param channels: Which output channels to log during sweep?
        :returns: A two-dimensional array of values read.
        """

        chan = np.array(channels if channels else [10, 11, 12], dtype='uint8')
        samples = MAX_BULK_TRANSFER
        frequency = MAX_BULK_TRANSFER / gate_time

        response = np.zeros([samples, len(chan)])

        # To emulate synchronous I/O operation, we first schedule the output
        # part and then immediately start reading.
        self._daq.TriangleOnce(ct.c_double(gate_time),
                               ct.c_double(min_val),
                               ct.c_double(max_val))
        self._daq.SampleChannelsAt10V(chan.ctypes.data,
                                      ct.c_uint(len(chan)),
                                      ct.c_uint(samples),
                                      ct.c_double(frequency),
                                      response.ctypes.data)
        return response

    def ping(self) -> bool:
        """The DAQ talks to us and seems healthy."""
        try:
            return self._daq.Ping() == 0
        except:  # Who knows what it might raise... # pylint: disable=bare-except
            LOGGER.exception("DAQ got sick.")
        return False
