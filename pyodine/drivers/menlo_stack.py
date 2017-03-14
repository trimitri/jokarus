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

    def __init__(self):
        """This does not do anything. Make sure to await the init() coro!"""

        # We are not doing anything here. It is imperative the user awaits the
        # async init() coroutine by themselves.

    async def init(self, url: str=DEFAULT_URL) -> None:
        """This replaces the default constructor.

        Be sure to await this coroutine before using the class.
        """
        self._init_buffers()
        self._connection = await websockets.connect(url)
        asyncio.ensure_future(self._listen_to_socket())

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

    # def laser_enable(self, enable: bool=True, unit: int=1) -> None:
    #     pass

    # def laser_set_current(self, current: float, unit: int=1) -> None:
    #     """Sets the laser diode current setpoint."""
    #     pass

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

    # def laser_set_temperature(self, temp: float, unit: int=1) -> None:
    #     pass

    # def laser_get_temperature(self, unit: int=1) -> float:
    #     pass

    # def laser_get_peltier_current(self, unit: int=1) -> float:
    #     pass

    # def laser_is_temp_ok(self, unit: int=1) -> bool:
    #     pass

    # def lockbox_enable(self, enable: bool=True, unit: int=1) -> None:
    #     pass

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
                LOGGER.info("Service %d:%d alive. First value: %s",
                            node, service, value)
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
        if len(buffer) > 0:
            return buffer[0]
        else:
            LOGGER.warning('Returning "None", as the given buffer is empty.')
            return (None, None)
