"""A python wrapper for the MCC linux driver."""

import numpy as np
import ctypes as ct


class MccDaq:
    """A stateful wrapper around the MCC DAQ device."""

    def __init__(self):
        self._daq = ct.CDLL('pyodine/drivers/mcc_daq/libmccdaq.so')
        self._daq.OpenConnection()

    def scan_ramp(self) -> np.ndarray:
        channels = np.array([10, 11, 12], dtype='uint8')
        samples = 500
        frequency = 500
        response = np.zeros([samples, len(channels)])
        self._daq.TriangleOnce()
        self._daq.SampleChannelsAt10V(channels.ctypes.data,
                                      ct.c_uint(len(channels)),
                                      ct.c_uint(samples),
                                      ct.c_double(frequency),
                                      response.ctypes.data)
        return(response)
