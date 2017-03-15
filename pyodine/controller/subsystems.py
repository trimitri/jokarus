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
        self._menlo = None
        self._dds = None
        self._daq = None

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

    def get_some_voltage(self) -> tuple:
        return self._menlo.get_adc_voltage(0)

    def get_full_set_of_readings(self) -> str:
        data = {'some_voltage': self.get_some_voltage()}
        return json.dumps(data)
