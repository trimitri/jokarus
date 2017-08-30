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
        self.offset = 0.0  # Offset voltage the ramp centers around.

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

    def scan_once(self, amplitude: float, time: float, channels: list) -> np.ndarray:
        """Scan the output voltage once and read the inputs during that time.

        The ramp will center around the current `offset` voltage, thus only an
        amplitude is given.

        :param amplitude: Peak-peak amplitude of the generated ramp.
        :param time: Approx time it takes from ramp maximum to ramp minimum.
        :param channels: Which output channels to log during sweep?
        :returns: A two-dimensional array of values read.
        """

        # TODO:
        # - Get return size from C
        # - Try reading at higher sample rate than writing

        chan = np.array(channels, dtype='uint8')
        samples = int(MAX_BULK_TRANSFER / 2)

        response = np.zeros([samples, len(chan)])

        # To emulate synchronous I/O operation, we first schedule the output
        # part and then immediately start reading.
        offset = ct.c_double(0)
        ampl = ct.c_double(amplitude)
        duration = ct.c_double(time)
        signal_type = ct.c_int(0)
        self._daq.FetchScan(offset, ampl, duration, signal_type,
                            response.ctypes.data)
        # self._daq.TriangleOnce(ct.c_double(gate_time),
        #                        ct.c_double(min_val),
        #                        ct.c_double(max_val))
        # self._daq.SampleChannelsAt10V(chan.ctypes.data,
        #                               ct.c_uint(len(chan)),
        #                               ct.c_uint(samples),
        #                               ct.c_double(frequency),
        #                               response.ctypes.data)
        return response

    def ping(self) -> bool:
        """The DAQ talks to us and seems healthy."""
        try:
            return self._daq.Ping() == 0
        except:  # Who knows what it might raise... # pylint: disable=bare-except
            LOGGER.exception("DAQ got sick.")
        return False
