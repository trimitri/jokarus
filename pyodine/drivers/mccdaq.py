"""A python wrapper for the MCC linux driver."""

import numpy as np
import ctypes as ct

daq = ct.CDLL('mcc_daq/libmccdaq.so')
channels = np.array([10, 11, 12], dtype='uint8')
samples = 500
frequency = 500
response = np.zeros([samples, len(channels)])
daq.OpenConnection()
daq.TriangleOnce()
daq.SampleChannelsAt10V(channels.ctypes.data, ct.c_uint(len(channels)),
                        ct.c_uint(samples), ct.c_double(frequency),
                        response.ctypes.data)
print(response[0])
