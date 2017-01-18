"""An interface wrapper to the Menlo stack websocket.
This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.
"""

import logging     # DEBUG, INFO, WARN, ERROR etc.
import time        # To keep track of when replies came in.
import asyncio     # A native python module needed for websockets.
import websockets

LOGGER = logging.getLogger('pyodine.drivers.menlo_stack')
ROTATE_N = 10  # Keep log of received values smaller than this.

# Constants specific to the published Menlo interface.

LASER_NODES = [3, 4, 5, 6]  # node IDs of laser units 1 through 4
LOCKBOX_NODES = [1, 2]      # node IDs of lockboxes 1 and 2
ADC_NODE = 16               # node ID of the analog-digital converter
MUC_NODE = 255              # node ID of the embedded system

# Provide dictionaries for the service IDs.
LASER_SVC_GET = {272: 'diode_temp',
                 274: 'tec_current',
                 275: 'diode_current',
                 288: 'temp_ok'}
LASER_SVC_SET = {1: 'diode_temp',
                 2: 'diode_current',
                 3: 'enable_diode'}
LOCKBOX_SVC_GET = {272: "not well documented (Lockbox Monitor)",  # FIXME
                   273: "not well documented (P Monitor)"}  # FIXME
LOCKBOX_SVC_SET = {0: 'disable',
                   1: '?1',
                   2: '?2',
                   3: 'ramp_enable',
                   4: '?4',
                   5: '?5',
                   6: '?6'}
ADC_SVC_GET = {}
ADC_SVC_SET = {}
MUC_SVC_GET = {1: 'time'}


class MenloStack:
    """Provides an interface to the Menlo electronics stack."""

    # Laser Diode Driver Control.

    def __init__(self, url: str="ws://menlostack:8000"):
        """Establish a websocket connection with the Menlo stack controller.
        """
        self._ws = websockets.connect(url)

        # Create one buffer for each receiving service of each laser driver
        # using a nested double dict comprehension.
        # Then do the same for the lockboxes.
        # The finished dicts will look as follows:
        #   {
        #      node_id1: {svc_id1: [], svc_id2: [], etc.},
        #      node_id2: {svc_id1: [], svc_id2: [], etc.},
        #      etc.
        #   }
        # Each of the contained empty lists will eventually hold received data
        # in tuples: [(value1, time1), (value2, time2), etc.]
        self._laser_buffers = {
            node_id: {svc_id: [] for svc_id in LASER_SVC_GET}
            for node_id in LASER_NODES}
        self._lockbox_buffers = {
            node_id: {svc_id: [] for svc_id in LOCKBOX_SVC_GET}
            for node_id in LOCKBOX_NODES}
        self._adc_buffers = {svc_id: [] for svc_id in ADC_SVC_GET}
        self._muc_buffers = {svc_id: [] for svc_id in MUC_SVC_GET}

        # Schedule background tasks to run in central asyncio event loop.

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

    def _send_command(self, node: int, service: int, value: str) -> None:
        message = str(node) + ':0:' + str(service) + ':' + str(value)
        self._send_string(message)

    def _send_string(self, message: str) -> None:
        pass

    @staticmethod
    def _parse_reply(received_string: str) -> tuple:
        LOGGER.debug("Parsing reply '%s'", received_string)
        parts = received_string.split(":")
        return(int(parts[0]), int(parts[1]), parts[2])  # node, service, value

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
            LOGGER.warning("Unknown node ID.")

    def _store_laser_param(self, unit: int, service: int, value: str) -> None:
        LOGGER.debug("Storing Laser %s param %s as %s.", unit, service, value)
        if service in LASER_SVC_GET:
            pass  # TODO
        else:
            LOGGER.error("Unknown laser controller service id (%s).", service)

    def _store_lockbox_param(self,
                             unit: int, service: int, value: str) -> None:
        LOGGER.debug("Storing Lockbox %s param %s as %s.", unit, service,
                     value)
        # TODO

    def _store_adc_param(self, service: int, value: str) -> None:
        LOGGER.debug("Storing ADC param %s as %s.", service, value)
        # TODO

    def _store_muc_param(self, service, value) -> None:
        LOGGER.debug("Storing MUC param %s as %s.", service, value)
        # TODO

    async def _listen_to_socket(self) -> None:
        while True:
            # message = await self._ws.recv()
            message = await self._mock_reply()
            self._store_reply(*self._parse_reply(message))

    @staticmethod
    async def _mock_reply() -> str:
        await asyncio.sleep(.2)  # Simulate websocket wait.
        replies = ["5:288:0", "3:274:1488", "3:275:-12", "5:272:-29",
                   "5:274:-39", "5:275:-56", "5:274:-65",
                   "255:1:1481101784.216184", "4:288:0", "4:272:-2",
                   "5:272:-427", "4:274:1488", "4:275:0", "5:272:-34",
                   "6:288:0", "6:272:-9", "6:274:1490",
                   "255:1:1481101784.716533"]
        import random
        return replies[random.randint(0, len(replies) - 1)]

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
        async with websockets.connect('ws://menlostack:8000') as sckt:
            while True:
                print(await sckt.recv())

    asyncio.get_event_loop().run_until_complete(hello_menlo())
