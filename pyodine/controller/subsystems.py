"""The Subsystems class manages the connection to internal subsystems.

This is an interface to the actual things connected to each port of each
subsystem.
"""
import json
from ..drivers import menlo_stack
# from ..drivers import mccdaq
# from ..drivers import dds9control


class Subsystems:

    def __init__(self):
        self._menlo = None  # type: menlo_stack.MenloStack
        # self._dds = None
        # self._daq = None
        pass

    async def init_async(self):
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

    def get_full_set_of_readings(self) -> str:
        data = {}

        # ADC readings
        for channel in range(8):
            data['adc' + str(channel)] = self._menlo.get_adc_voltage(channel)

        # TEC controller temperature readings
        for unit in [1, 2, 3, 4]:
            data['temp'+str(unit)] = self._menlo.get_temperature(unit)

        data['mo_temperature'] = self._menlo.get_temperature(1)
        data['mo_diode_current'] = self._menlo.get_diode_current(1)
        data['mo_tec_current'] = self._menlo.get_tec_current(1)

        message = {'data': data,
                   'type': 'readings'}
        return json.dumps(message)
