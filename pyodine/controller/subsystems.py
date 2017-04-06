"""The Subsystems class manages the connection to internal subsystems.

This is an interface to the actual things connected to each port of each
subsystem.
"""
import logging
import time
from typing import Dict, List, Tuple, Union
from ..drivers import menlo_stack
from .temperature_ramp import TemperatureRamp
# from ..drivers import mccdaq
# from ..drivers import dds9control

LOGGER = logging.getLogger("pyodine.controller.subsystems")
LOGGER.setLevel(logging.DEBUG)

# Define some custom types.
MenloUnit = Union[float, int]
DataPoint = Tuple[float, MenloUnit]  # Measurement (time, reading)
Buffer = List[DataPoint]
OSC_UNITS = {'mo': 1, 'pa': 2}
PII_UNITS = {'nu': 1}


class Subsystems:
    """Provides a wrapper for all connected subsystems.
    Don't access the subsystems directly."""

    def __init__(self) -> None:
        self._menlo = None  # type: menlo_stack.MenloStack
        self._temp_ramps = dict()  # type: Dict[int, TemperatureRamp]
        self._init_temp_ramps()
        # self._dds = None
        # self._daq = None

    async def init_async(self) -> None:
        """Needs to be awaited after initialization.

        It makes sure that all subsystems are ready."""
        await self.reset_menlo()

    async def reset_menlo(self) -> None:
        """Reset the connection to the Menlo subsystem."""
        if self._menlo is menlo_stack.MenloStack:
            del self._menlo

        self._menlo = menlo_stack.MenloStack()
        await self._menlo.init_async()

    async def refresh_status(self) -> None:
        await self._menlo.request_full_status()

    def set_current(self, unit_name: str, milliamps: float) -> None:
        """Set diode current setpoint of given unit."""
        LOGGER.debug("Setting diode current of unit %s to %s mA",
                     unit_name, milliamps)
        if (unit_name in OSC_UNITS
                and isinstance(milliamps, float)
                and milliamps > 0):
            self._menlo.set_current(OSC_UNITS[unit_name], milliamps)
        else:
            LOGGER.error("Illegal setting for diode current.")

    def set_temp(self, unit_name, celsius: float,
                 bypass_ramp: bool = False) -> None:
        """Set the target temp. for the temperature ramp."""
        LOGGER.debug("Setting target temp. of unit %s to %s°C",
                     unit_name, celsius)
        if unit_name in OSC_UNITS and isinstance(celsius, float):
            if bypass_ramp:
                self._menlo.set_temp(OSC_UNITS[unit_name], celsius)
            else:
                ramp = self._temp_ramps[OSC_UNITS[unit_name]]
                ramp.target_temperature = celsius
        else:
            LOGGER.error("Illegal setting for temperature setpoint.")

    def switch_tec(self, unit_name: str, switch_on: bool) -> None:
        if unit_name in OSC_UNITS:
            if isinstance(switch_on, bool):
                self._menlo.switch_tec(OSC_UNITS[unit_name], switch_on)

    def switch_ld(self, unit_name: str, switch_on: bool) -> None:
        if unit_name in OSC_UNITS:
            if isinstance(switch_on, bool):
                self._menlo.switch_ld(OSC_UNITS[unit_name], switch_on)

    def get_full_set_of_readings(self) -> Dict[str, Buffer]:
        """Return a dict of all readings, ready to be sent to the client."""
        data = {}  # type: Dict[str, Buffer]

        # ADC readings
        for channel in range(8):
            data['adc' + str(channel)] = self._menlo.get_adc_voltage(channel)

        # TEC controller temperature readings
        for unit in [1, 2, 3, 4]:
            data['temp'+str(unit)] = self._menlo.get_temperature(unit)

        # Oscillator Supplies
        data['mo_enabled'] = self._menlo.is_current_driver_enabled(1)
        data['mo_current'] = self._menlo.get_diode_current(1)
        data['mo_current_set'] = self._menlo.get_diode_current_setpoint(1)
        data['mo_tec_enabled'] = self._menlo.is_tec_enabled(1)
        data['mo_temp'] = self._menlo.get_temperature(1)
        data['mo_temp_raw_set'] = self._menlo.get_temp_setpoint(1)
        data['mo_temp_set'] = self._wrap_into_buffer(
            self._temp_ramps[1].target_temperature)
        data['mo_temp_ramp_active'] = self._wrap_into_buffer(
            self._temp_ramps[1].is_running)
        data['mo_temp_ok'] = self._menlo.is_temp_ok(1)
        data['mo_tec_current'] = self._menlo.get_tec_current(1)

        # PII Controllers
        data['nu_lock_enabled'] = self._menlo.is_lock_enabled(1)
        data['nu_i1_enabled'] = self._menlo.is_integrator_enabled(1, 1)
        data['nu_i2_enabled'] = self._menlo.is_integrator_enabled(1, 2)
        data['nu_ramp_enabled'] = self._menlo.is_ramp_enabled(1)
        data['nu_prop'] = self._menlo.get_pii_prop_factor(1)
        data['nu_offset'] = self._menlo.get_pii_offset(1)
        data['nu_p_monitor'] = self._menlo.get_pii_monitor(1, p_only = True)
        data['nu_monitor'] = self._menlo.get_pii_monitor(1)

        return data

    def _init_temp_ramps(self) -> None:
        """Initialize one TemperatureRamp instance for every TEC controller."""
        for name, unit in OSC_UNITS.items():
            def getter() -> float:
                """Get the most recent temperature reading from MenloStack."""

                # We need to bind the loop variable "unit" to a local variable
                # here, e.g. using lambdas.
                temp_readings = self._menlo.get_temperature((lambda: unit)())
                if temp_readings:
                    return temp_readings[0][1]
                return float('nan')

            def setter(temp: float) -> None:
                # Same here (see above).
                self._menlo.set_temp((lambda: unit)(), temp)

            self._temp_ramps[unit] = TemperatureRamp(get_temp_callback=getter,
                                                     set_temp_callback=setter,
                                                     name=name)

    @staticmethod
    def _wrap_into_buffer(value: Union[MenloUnit, bool]) -> Buffer:
        if isinstance(value, bool):
            return [(time.time(), 1 if value else 0)]  # bool is no MenloUnit

        if isinstance(value, float):
            return [(time.time(), float(value))]  # float(): make mypy happy

        if isinstance(value, int):
            return [(time.time(), int(value))]  # int(): make mypy happy

        if value is None:
            # Don't throw an error here, as None might just be an indication
            # that there isn't any data available yet.
            return []

        LOGGER.error("Type %s is not convertible into a MenloUnit.",
                     type(value))
        return []
