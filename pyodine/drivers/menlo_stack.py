"""An interface wrapper to the Menlo stack websocket.

This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.
"""

import logging     # DEBUG, INFO, WARN, ERROR etc.
import asyncio     # A native python module needed for websockets.
import websockets

logger = logging.getLogger('pyodine.drivers.menlo_stack')


class MenloStack:
    """Provides an interface to the Menlo electronics stack."""

    LASER_NODES = {1: '3', 2: '4', 3: '5', 4: '6'}
    LOCKBOX_NODES = {1: '1', 2: '2'}
    ADC_NODE = 16
    LASER_SERVICES = {'set_temperature': '1',
                      'set_ld_current': '2',
                      'enable_diode': '5',
                      'diode_temp': '272',
                      'tec_current': '274',
                      'diode_current': '275',
                      'temp_ok': '288'}
    LOCKBOX_SERVICES = {'disable': '0',
                        '?1': '1',
                        '?2': '2',
                        'ramp_enable': '3',
                        '?4': '4',
                        '?5': '5',
                        '?6': '6',
                        '?272': '272',
                        '?273': '273'}

    def __init__(self, url: str='ws://menlostack:8000'):
        """Establish a websocket connection with the Menlo stack controller.
        """
        self.conn = websockets.connect(url)

    # Laser Diode Driver Control.

    def laser_enable(self, enable: bool=True, unit: int=1) -> None:
        pass

    def laser_set_current(self, current: float, unit: int=1) -> None:
        """Sets the laser diode current setpoint."""
        pass

    def laser_get_current(self, unit: int=1) -> float:
        """Gets the actual laser diode current."""
        pass

    def laser_set_temperature(self, temp: float, unit: int=1) -> None:
        pass

    def laser_get_temperature(self, unit: int=1) -> float:
        pass

    def laser_get_peltier_current(self, unit: int=1) -> float:
        pass

    def laser_is_temp_ok(self, unit: int=1) -> bool:
        pass

    # Lockbox Control

    def lockbox_enable(self, enable: bool=True, unit: int=1) -> None:
        pass

    # Private Methods

    def _send_command(self, node: int, service: int, value: str) -> None:
        message = str(node) + ':0:' + str(service) + ':' + str(value)
        self._send_string(message)

    def _send_string(self, message: str) -> None:
        pass


if __name__ == '__main__':

    async def hello_menlo() -> None:
        async with websockets.connect('ws://menlostack:8000') as ws:
            while True:
                print(await ws.recv())

    asyncio.get_event_loop().run_until_complete(hello_menlo())
