"""Provides a class NtcTemp that does NTC Ohms to °C conversion.

This is a class as the conversion is somewhat stateful, depending on the a, b
and c parameters of the Steinhart-Hart equation.
"""
from math import log, sqrt, exp


class NtcTemp:
    """
    Implements the Steinhart-Hart equation for NTC thermistors.

    Converts resistance to temperature (Kelvin) like:

    1/T = a + b * ln(R) + c * (ln(R))^3

    Converts temperature to resistance like:

        * R = exp( (y - x/2)^(1/3) - (y + x/2)^(1/3) )
        * x = 1/C * (a - 1/T)
        * y = sqrt( (b/(3*c))^3 + (x/2)^2)
    """

    def __init__(self,
                 coeff_a: float = 2.109e-3,
                 coeff_b: float = 7.979e-5,
                 coeff_c: float = 6.535e-7,
                 use_celsius: bool = True) -> None:
        self._a = coeff_a
        self._b = coeff_b
        self._c = coeff_c
        self._ref = 273.15 if use_celsius else 0  # Ref. point of Kelvin scale

    def to_temp(self, ohms: float) -> float:
        try:
            temp = 1 / \
                (self._a + self._b * log(ohms) + self._c * (log(ohms))**3)
        except (ValueError, TypeError, ArithmeticError):
            raise ValueError("Error converting resistance to temperature.")
        else:
            return temp - self._ref

    def to_resistance(self, temperature: float) -> float:
        try:
            temp = temperature + self._ref
            x = 1/self._c * (self._a - 1/temp)
            y = sqrt((self._b/3/self._c)**3 + (x/2)**2)
            resistance = exp((y - x/2)**(1/3) - (y + x/2)**(1/3))
        except (ValueError, TypeError, ArithmeticError):
            raise ValueError("Error converting temperature to resistance.")
        else:
            return resistance
