"""A helper class wrapping ATI's non-standard NTC assumptions.

As stated in the plots in their TEC5V6A-D thermoelectric cooling controller
datasheet, ATI assumes seldomly-seen Steinhart-Hart coefficients for their
temperature calculations. This leads to wrong temperature readings when relying
on the provided U(T) plot alone.

This module aims to provide an accurate ohms reading from the aforementioned
chips by means of polynomial approximations obtained by reverse-engineering
their plots.
"""
import logging
import numpy as np

LOGGER = logging.getLogger('ati_tec')


def tempsp_to_ohms(volts: float) -> float:
    """Converts a ATI temp. setpoint voltage to actual Ohms in NTC resistance.

    :param tempsp: The voltage read on the controllers temp_sp pin
    :raises TypeError: Converting the given voltage to a float failed.
    :raises ValueError: Voltage is out of the TEC Chip's range.
    :returns: NTC resistance in Ohms
    """
    try:
        voltage = float(volts)
    except (TypeError, ValueError, ArithmeticError):
        LOGGER.exception()
        raise TypeError("Couldn't convert voltage to float")
    if voltage > 5 or voltage < 0:
        raise ValueError("Voltage has to be between zero and five volts.")

    c_4 = 2.32131941486   # * U^4
    c_3 = -53.7758974562  # * U³
    c_2 = 629.141287209   # * U²
    c_1 = -4474.03732095  # * U
    c_0 = 15601.7430608   # absolute term
    return float(np.polyval([c_4, c_3, c_2, c_1, c_0], voltage))


def ohms_to_tempsp(ohms: float) -> float:
    """Converts Ohms in NTC resistance to ATI TEC controller setpoint voltage.

    :param ohms: Measured NTC resistance
    :returns: Voltage to be applied to the controller's temp_sp pin
    :raises TypeError: Converting Ohms to float failed
    :raises ValueError: Resistance is too high/low for TEC chip
    """
    try:
        resistance = float(ohms)
    except (TypeError, ValueError, ArithmeticError):
        LOGGER.exception()
        raise TypeError("Couldn't convert resistance to float")

    sixth_order_coeffs = [9.96544974929286e-25, -6.48193814201448e-20,
                          1.83265994944409e-15, -2.95535304724271e-11,
                          3.03070724899164e-7, -0.00223020840250838,
                          10.2544735672273]
    voltage = float(np.polyval(sixth_order_coeffs, resistance))

    # We need to check voltage as well as resistance here, as for resistances
    # that are far out of the legal range, we might accidentially arrive at a
    # legal voltage (it's a sixth-order polynomial!).
    if voltage < 0 or voltage > 5 or resistance > 15800 or resistance < 3600:
        raise ValueError("Resistance out of TEC range.")
    return voltage
