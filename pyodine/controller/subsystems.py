"""The Subsystems class manages the connection to internal subsystems.

This is an interface to the actual things connected to each port of each
subsystem.
"""
from typing import Dict, List, Tuple
from ..drivers import menlo_stack
# from ..drivers import mccdaq
# from ..drivers import dds9control

# Define some custom types.
DataPoint = Tuple[float, str]  # Measurement time (float), value (str)
Buffer = List[DataPoint]


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

    def reset_daq(self) -> None:
        pass  # FIXME

    def reset_dds(self) -> None:
        pass  # FIXME

    async def set_mo_temp(self, temp: float) -> None:
        await self._menlo.set_temp(1, temp)

    def get_full_set_of_readings(self) -> Dict[str, Buffer]:
        data = {}  # type: Dict[str, Buffer]

        # ADC readings
        for channel in range(8):
            data['adc' + str(channel)] = self._menlo.get_adc_voltage(channel)

        # TEC controller temperature readings
        for unit in [1, 2, 3, 4]:
            data['temp'+str(unit)] = self._menlo.get_temperature(unit)

        # Oscillator Supplies
        data['mo_temp'] = self._menlo.get_temperature(1)
        data['mo_current'] = self._menlo.get_diode_current(1)
        data['mo_tec_current'] = self._menlo.get_tec_current(1)
        data['mo_temp_set'] = self._menlo.get_temp_setpoint(1)

        data['pa_temp'] = self._menlo.get_temperature(2)
        data['pa_current'] = self._menlo.get_diode_current(2)
        data['pa_tec_current'] = self._menlo.get_tec_current(2)
        data['pa_temp_set'] = self._menlo.get_temp_setpoint(2)

        return data
