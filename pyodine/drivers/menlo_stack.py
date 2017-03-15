"""An interface wrapper to the Menlo stack websocket.

This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.
"""

import logging     # DEBUG, INFO, WARN, ERROR etc.
import time        # To keep track of when replies came in.
import asyncio     # A native python module needed for websockets.
import websockets

LOGGER = logging.getLogger('pyodine.drivers.menlo_stack')
ROTATE_N = 16  # Keep log of received values smaller than this.
DEFAULT_URL = 'ws://menlostack:8000'

# Constants specific to the published Menlo interface.

LASER_NODES = [3, 4, 5, 6]  # node IDs of laser units 1 through 4
LOCKBOX_NODES = [1, 2]      # node IDs of lockboxes 1 and 2
ADC_NODE = 16               # node ID of the analog-digital converter
MUC_NODE = 255              # node ID of the embedded system

# Provide dictionaries for the service IDs.
LASER_SVC_GET = {256: "LD temperature setpoint (found by trying)",
                 257: "TEC current setpoint",
                 272: "meas. LD temperature",
                 273: "Unknown 01 (???)",
                 274: "meas. TEC current",
                 275: "meas. LD current",
                 288: "temp OK status flag"}
LASER_SVC_SET = {1: "TEC temperature",
                 2: "enable TEC, active HIGH",
                 3: "LD current",
                 5: "enable LD, active HIGH"}
LOCKBOX_SVC_GET = {272: "lockbox monitor",
                   273: "P monitor"}
LOCKBOX_SVC_SET = {0: "disable lock",
                   1: "disable I1",
                   2: "disable I2",
                   3: "activate ramp",
                   4: "offset in value",
                   5: "level",
                   6: "ramp value"}
ADC_SVC_GET = {0: "ADC channel 0",
               1: "ADC channel 1",
               2: "ADC channel 2",
               3: "ADC channel 3",
               4: "ADC channel 4",
               5: "ADC channel 5",
               6: "ADC channel 6",
               7: "ADC channel 7",
               8: "ADC temp 0",
               9: "ADC temp 1",
               10: "ADC temp 2",
               11: "ADC temp 3",
               12: "ADC temp 4",
               13: "ADC temp 5",
               14: "ADC temp 6",
               15: "ADC temp 7"}
ADC_SVC_SET = {}  # ADC has no input channels
MUC_SVC_GET = {1: "system time?"}


class MenloStack:
    """Provides an interface to the Menlo electronics stack."""

    # Laser Diode Driver Control.

    def __init__(self):
        """This does not do anything. Make sure to await the init() coro!"""

    async def init_async(self, url: str=DEFAULT_URL) -> None:
        """This replaces the default constructor.

        Be sure to await this coroutine before using the class.
        """
        self._init_buffers()
        self._connection = await websockets.connect(url)
        asyncio.ensure_future(self._listen_to_socket())

    def get_laser_current(self, unit: int=1) -> float:
        """Gets the actual laser diode current."""

        # Do a reverse dictionary lookup to get the service ID.
        try:
            service_index = list(LASER_SVC_GET.values()).index('diode_current')
        except ValueError:
            LOGGER.error("Service 'diode_current' not specified.")
            return None
        service_id = list(LASER_SVC_GET.keys())[service_index]
        buffer = self._buffers[LASER_NODES[unit-1]][service_id]
        return self._get_latest_entry(buffer)[0]

    async def set_temp(self, osc_supply_unit_no: int, temp: float):
        node = 2 + osc_supply_unit_no
        if node in LASER_NODES:
            await self._send_command(node, 1, str(int(temp)))
        else:
            LOGGER.warning("Oscillator Supply unit index out of range."
                           "Refusing to set temperature setpoing.")

    def get_adc_voltage(self, channel: int) -> tuple:
        if channel in ADC_SVC_GET.keys():
            return self._get_latest_entry(self._buffers[16][channel])
        else:
            LOGGER.warning("ADC channel index out of bounds. Returning dummy.")
            return (float('nan'), '')

    # Private Methods

    def _init_buffers(self) -> None:
        """Create empty buffers to store received quantities in."""

        # Create one buffer for each receiving service of each connected module
        # using nested dict comprehensions.
        # The finished dict will look as follows:
        #   {
        #      node_id1: {svc_id1: [], svc_id2: [], etc.},
        #      node_id2: {svc_id1: [], svc_id2: [], etc.},
        #      etc.
        #   }
        # Each of the contained empty lists will eventually hold received data
        # in tuples: [(value1, time1), (value2, time2), etc.]

        # First, create a tree of buffers for each module.
        laser_buffers = {
            node_id: {svc_id: [] for svc_id in LASER_SVC_GET}
            for node_id in LASER_NODES}
        lockbox_buffers = {
            node_id: {svc_id: [] for svc_id in LOCKBOX_SVC_GET}
            for node_id in LOCKBOX_NODES}
        adc_buffers = {ADC_NODE: {svc_id: [] for svc_id in ADC_SVC_GET}}
        muc_buffers = {MUC_NODE: {svc_id: [] for svc_id in MUC_SVC_GET}}

        # Merge dictionaries into one, as "node" is a unique key.
        self._buffers = {}
        self._buffers.update(laser_buffers)
        self._buffers.update(lockbox_buffers)
        self._buffers.update(adc_buffers)
        self._buffers.update(muc_buffers)

    async def _send_command(self, node: int, service: int, value: str) -> None:
        message = str(node) + ':0:' + str(service) + ':' + str(value)
        LOGGER.debug("Sending message %d:%d:%s ...", node, service, value)
        await self._connection.send(message)
        LOGGER.debug("Sent message %d:%d:%s", node, service, value)

    def _store_reply(self, node: int, service: int, value: str) -> None:
        buffer = None

        # If we try to access an nonexistent service, the corresponding buffer
        # doesnt exist. That's why we need to try.
        try:
            buffer = self._buffers[node][service]
        except KeyError:
            pass  # buffer = None

        if isinstance(buffer, list):
            if len(buffer) == 0:
                LOGGER.info("Service %d:%d (%s) alive. First value: %s",
                            node, service, self._name_service(node, service),
                            value)
            self._rotate_log(self._buffers[node][service], value)
        else:
            LOGGER.warning(("Combination of node id %s and service id %s "
                            "doesn't resolve into a documented quantity."),
                           node, service)

    async def _listen_to_socket(self) -> None:
        while True:
            message = await self._connection.recv()
            # message = await self._mock_reply()
            self._parse_reply(message)

    @staticmethod
    async def _mock_reply() -> str:
        await asyncio.sleep(.002)  # Simulate websocket wait.
        replies = ["5:288:0", "3:274:1488", "3:275:-12", "5:272:-29",
                   "5:274:-39", "5:275:-56", "5:274:-65",
                   "255:1:1481101784.216184", "4:288:0", "4:272:-2",
                   "5:272:-427", "4:274:1488", "4:275:0", "5:272:-34",
                   "6:288:0", "6:272:-9", "6:274:1490",
                   "255:1:1481101784.716533"]
        import random
        return replies[random.randint(0, len(replies) - 1)]

    def _parse_reply(self, received_string: str) -> None:
        LOGGER.debug("Parsing reply '%s'", received_string)

        # Some responses contain a packed set of single values. Those are
        # concatenated using the '@' token.
        responses = received_string.split('@')

        for resp in responses:
            parts = resp.split(":")
            self._store_reply(int(parts[0]), int(parts[1]), parts[2])

    @staticmethod
    def _rotate_log(log_list: list, value) -> None:
        log_list.insert(0, (value, time.time()))

        # Shave of some elements in case the list got too long. Be careful to
        # not use any statement here that creates a new list. Such as
        #     list = list[0:foo_end]
        # which does NOT work, as it doesn't modify the passed-by-reference
        # list.
        del(log_list[ROTATE_N:])

    @staticmethod
    def _get_latest_entry(buffer: list) -> tuple:
        """Returns the latest tuple of time and value from given buffer."""
        if len(buffer) > 0:
            return buffer[0]
        else:
            LOGGER.warning('Returning a dummy, as the given buffer is empty.')
            return (float('nan'), '')

    @staticmethod
    def _name_service(node: int, service: int) -> str:
        if node in LASER_NODES:
            if service in LASER_SVC_GET.keys():
                return LASER_SVC_GET[service]
        elif node in LOCKBOX_NODES:
            if service in LOCKBOX_SVC_GET.keys():
                return LOCKBOX_SVC_GET[service]
        elif node == 16:  # ADC
            if service in ADC_SVC_GET.keys():
                return ADC_SVC_GET[service]
        elif node == 255:  # MUC
            if service in MUC_SVC_GET.keys():
                return MUC_SVC_GET[service]

        # Unknown combination of Node and Service.
        LOGGER.warning("Tried to name unknown service %d:%d.", node, service)
        return "unknown service"
