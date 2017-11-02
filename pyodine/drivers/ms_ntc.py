"""Providing some conversion for working with the MS NTC board.

The MS (Matthias Schoch) NTC conversion boards preloads some thermistors in
order to have their resistance read out by means of an ADC.
"""
from typing import List
import numpy as np
from ..util import ntc_temp

NTC_CONVERTER = None  # type: ntc_temp.NtcTemp

def to_resistances(adc_readings: List[int]) -> List[float]:
    """
    Convert given ADC readings to resistance values.

    Gives wrong results outside of [2kΩ, 30kΩ].

    :param adc_readings: The readings as received from MCC DAQ device at 5V
                gain setting.
    :returns: List of resistances in ohms.
    """
    # This was obtained through calibrating the MS board with some test
    # resistors and fitting with a fourth-degree polynomial. Mind the limits
    # stated in the docstring.
    coeffs = [5.72362631e-12, -9.89646008e-07, 6.42572230e-02, -1.85840325e+03, 2.02210773e+07]
    return np.polyval(coeffs, adc_readings).tolist()


def to_temperatures(adc_readings: List[int]) -> List[float]:
    """
    Convert given ADC readings to temperatures.

    Gives wrong results outside of [2kΩ, 30kΩ].

    :param adc_readings: The readings as received from MCC DAQ device at 5V
                gain setting.
    :returns: List of temperatures in degrees celsius.
    """
    global NTC_CONVERTER
    if not NTC_CONVERTER:
        NTC_CONVERTER = ntc_temp.NtcTemp()

    return [NTC_CONVERTER.to_temp(ohms) for ohms in to_resistances(adc_readings)]
