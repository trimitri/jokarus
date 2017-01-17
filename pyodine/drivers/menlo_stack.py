"""An interface wrapper to the Menlo stack websocket.
This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.
"""

import logging     # DEBUG, INFO, WARN, ERROR etc.
import time        # To keep track of when replies came in.
import asyncio     # A native python module needed for websockets.
import websockets
logger = logging.getLogger('pyodine.drivers.menlo_stack')

# Constants specific to the published Menlo interface.

LASER_NODES = [3, 4, 5, 6]  # node IDs of laser units 1 through 4
LOCKBOX_NODES = [1, 2]      # node IDs of lockboxes 1 and 2
ADC_NODE = 16               # node ID of the analog-digital converter
MUC_NODE = 255              # node ID of the embedded system
LASER_SERVICES = {'set_temperature': 1,
                  'set_ld_current': 2,
                  'enable_diode': 5,
                  'diode_temp': 272,
                  'tec_current': 274,
                  'diode_current': 275,
                  'temp_ok': '288'}
LOCKBOX_SERVICES = {'disable': 0,
                    '?1': 1,
                    '?2': 2,
                    'ramp_enable': 3,
                    '?4': 4,
                    '?5': 5,
                    '?6': 6,
                    '?272': 272,
                    '?273': 273}
MUC_SERVICES = {'time': 1}

ROTATE_N = 10  # Keep log of received values smaller than this.


class MenloStack:
    """Provides an interface to the Menlo electronics stack."""

    ##############
    # Properties #
    ##############

    @property
    def muc_times(self) -> list:
        return self._muc_times

    ####################
    # Instance Methods #
    ####################

    # Laser Diode Driver Control.

    def __init__(self, url: str="ws://menlostack:8000"):
        """Establish a websocket connection with the Menlo stack controller.
        """
        self._ws = websockets.connect(url)

        # Create buffers for saving received system parameters.

        # Laser drivers
        self._diode_temps = []     # laser diode temperature
        self._tec_currents = []    # Peltier currents
        self._diode_currents = []  # laser diode current
        self._laser_drv_ok = []    # "OK" flag of the laser driver

        # Embedded System
        self._muc_times = []       # MUC system time

        # Setup concurrent execution
        asyncio.ensure_future(self._listen_to_socket())

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

    def _parse_reply(self, received_string: str) -> tuple:
        logger.debug("Parsing reply " + received_string)
        parts = received_string.split(":")
        return parts[0], parts[1], parts[2]  # node, service, value

    def _store_reply(self, node: int, service: int, value: str) -> None:
        if node in LASER_NODES:
            unit = LASER_NODES.index(node)
            self._store_laser_param(unit, service, value)

        elif node in LOCKBOX_NODES:
            unit = LOCKBOX_NODES.index(node)
            self._store_lockbox_param(unit, service, value)

        elif node == ADC_NODE:
            self._store_adc_param(service, value)

        elif node == MUC_NODE:
            self._store_muc_param(service, value)

        else:
            logger.warning("Unknown node ID.")

    def _store_laser_param(self, unit: int, service: int, value: str) -> None:
        pass

    def _store_muc_param(self, service, value) -> None:
        if service in MUC_SERVICES.values():
            if service == MUC_SERVICES["time"]:
                self.add_to_rotating_log(self._muc_times, (value, time.time()))
        else:
            logger.warning("Unknown MUC service ID {}".format(service))

    # asyncio

    async def _listen_to_socket(self) -> None:
        while True:
            # message = await self._ws.recv()
            # self._parse_reply(message)
            await asyncio.sleep(2.3)
            logger.debug("Doing stuff in MenloStack.")

    @staticmethod
    async def _mock_reply():
        pass  # TODO

    ##################
    # Static Methods #
    ##################

    @staticmethod
    def add_to_rotating_log(log_list: list, value) -> None:
        log_list.insert(0, value)

        # Shave of some elements if list gets too long.
        if len(log_list) > ROTATE_N:
            log_list = log_list[0:ROTATE_N-1]


if __name__ == '__main__':

    async def hello_menlo() -> None:
        async with websockets.connect('ws://menlostack:8000') as ws:
            while True:
                print(await ws.recv())

    asyncio.get_event_loop().run_until_complete(hello_menlo())
