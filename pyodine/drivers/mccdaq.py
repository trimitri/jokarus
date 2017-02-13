"""A python wrapper for the MCC linux driver."""

import numpy as np
import ctypes as ct

MAX_BULK_TRANSFER = 2560

class MccDaq:
    """A stateful wrapper around the MCC DAQ device."""

    def __init__(self):
        self._daq = ct.CDLL('pyodine/drivers/mcc_daq/libmccdaq.so')
        self._daq.OpenConnection()

    def scan_ramp(self, min_val: float=-10, max_val: float=10,
                  gate_time: float=1,
                  channels: list=[10, 11, 12]) -> np.ndarray:

        chan = np.array(channels, dtype='uint8')
        samples = MAX_BULK_TRANSFER
        frequency = MAX_BULK_TRANSFER / gate_time

        response = np.zeros([samples, len(chan)])
        self._daq.TriangleOnce(ct.c_double(gate_time),
                               ct.c_double(min_val), ct.c_double(max_val))
        self._daq.SampleChannelsAt10V(chan.ctypes.data,
                                      ct.c_uint(len(chan)),
                                      ct.c_uint(samples),
                                      ct.c_double(frequency),
                                      response.ctypes.data)
        return(response)
