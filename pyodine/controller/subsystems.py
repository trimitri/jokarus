"""The Subsystems class manages the connection to internal subsystems.

This is an interface to the actual things connected to each port of each
subsystem.
"""
import logging
from typing import Dict, List, Tuple
from ..drivers import menlo_stack
# from ..drivers import mccdaq
# from ..drivers import dds9control

LOGGER = logging.getLogger("pyodine.controller.subsystems")
LOGGER.setLevel(logging.DEBUG)

# Define some custom types.
DataPoint = Tuple[float, str]  # Measurement time (float), value (str)
Buffer = List[DataPoint]
OSC_UNITS = {'mo': 1, 'pa': 2}


class Subsystems:

    def __init__(self) -> None:
        self._menlo = None  # type: menlo_stack.MenloStack
        # self._dds = None
        # self._daq = None

    async def init_async(self) -> None:
        await self.initialize_all()

    async def initialize_all(self) -> None:
        await self.reset_menlo()
        self.reset_daq()
        self.reset_dds()

    async def reset_menlo(self) -> None:
        if self._menlo is menlo_stack.MenloStack:
            del self._menlo

        self._menlo = menlo_stack.MenloStack()
        await self._menlo.init_async()

    async def refresh_status(self) -> None:
        await self._menlo.request_full_status()

    def reset_daq(self) -> None:
        pass  # FIXME

    def reset_dds(self) -> None:
        pass  # FIXME

    def set_current(self, unit_name: str, milliamps: float) -> None:
        LOGGER.debug("Setting diode current of unit %s to %s mA",
                     unit_name, milliamps)
        if (unit_name in OSC_UNITS
                and type(milliamps) is float
                and milliamps > 0):
            self._menlo.set_current(OSC_UNITS[unit_name], milliamps)
        else:
            LOGGER.error("Illegal setting for diode current.")

    def set_temp(self, unit_name, celsius: float) -> None:
        LOGGER.debug("Setting temp. of unit %s to %s°C", unit_name, celsius)
        if unit_name in OSC_UNITS and type(celsius) is float:
            self._menlo.set_temp(OSC_UNITS[unit_name], celsius)
        else:
            LOGGER.error("Illegal setting for temperature setpoint.")

    def switch_tec(self, unit_name: str, on: bool) -> None:
        if unit_name in OSC_UNITS:
            if type(on) is bool:
                self._menlo.switch_tec(OSC_UNITS[unit_name], on)

    def switch_ld(self, unit_name: str, on: bool) -> None:
        if unit_name in OSC_UNITS:
            if type(on) is bool:
                self._menlo.switch_ld(OSC_UNITS[unit_name], on)

    def get_full_set_of_readings(self) -> Dict[str, Buffer]:
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
        data['mo_temp_set'] = self._menlo.get_temp_setpoint(1)
        # data['mo_temp_ok'] = self._menlo.is_temp_ok(1)
        data['mo_tec_current'] = self._menlo.get_tec_current(1)

        data['pa_enabled'] = self._menlo.is_current_driver_enabled(2)
        data['pa_current'] = self._menlo.get_diode_current(2)
        data['pa_current_set'] = self._menlo.get_diode_current_setpoint(2)
        data['pa_tec_enabled'] = self._menlo.is_tec_enabled(2)
        data['pa_temp'] = self._menlo.get_temperature(2)
        data['pa_temp_set'] = self._menlo.get_temp_setpoint(2)
        # data['pa_temp_ok'] = self._menlo.is_temp_ok(2)
        data['pa_tec_current'] = self._menlo.get_tec_current(2)

        return data
