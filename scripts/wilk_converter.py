"""Convert Rafal Wilk's approximation of the TEC temp. curve to ADC values and
back.

KEEP THIS in order to be able to evaluate old measurements.

As the setpoint is set through an DAC using different conversion factors than
the temperature reading ADC unit, you need to specify whether you're dealing
with a setpoint or with a temperature reading.
"""
import math


def to_counts(temp, is_setpoint: bool):
    factor = 27000 if is_setpoint else 1000
    a_0 = factor * -2.489
    a_1 = factor * 0.1717
    a_2 = factor * -0.0004352
    return int(round(a_0 + a_1 * temp + a_2 * temp**2))


def to_temp(counts, is_setpoint: bool):
    factor = 27000 if is_setpoint else 1000
    a_0 = factor * -2.489
    a_1 = factor * 0.1717
    a_2 = factor * -0.0004352
    return -a_1/(2*a_2) - math.sqrt((a_1/(2*a_2))**2 + (counts - a_0)/a_2)
