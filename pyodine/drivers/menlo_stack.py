"""An interface wrapper to the Menlo stack websocket.

This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.
"""

import asyncio     # Needed for websockets.
import logging
import math
import time        # To keep track of when replies came in.
from typing import Dict, List, Tuple, Union

import websockets

# Adjust as needed
ROTATE_N = 128  # Keep log of received values smaller than this.
DEFAULT_URL = 'ws://menlostack:8000'
TEC_CALIBRATION_TIME = 10.0

LOGGER = logging.getLogger('pyodine.drivers.menlo_stack')
LOGGER.setLevel(logging.INFO)

# Constants specific to the published Menlo interface.

LASER_NODES = [3, 4, 5, 6]  # node IDs of laser units 1 through 4
PII_NODES = [1, 2]      # node IDs of lockboxes 1 and 2
ADC_NODE = 16               # node ID of the analog-digital converter
MUC_NODE = 255              # node ID of the embedded system

# Provide dictionaries for the service IDs.
LASER_SVC_GET = {
    256: "temp setpoint",
    257: "LD current setpoint",
    272: "meas. LD temperature",
    273: "UNKNOWN 01",
    274: "meas. TEC current",
    275: "meas. LD current",
    288: "temp OK flag",
    304: "TEC enabled",
    305: "LD driver enabled"}
LASER_SVC_SET = {
    1: "TEC temperature",
    2: "enable TEC",
    3: "LD current",
    5: "enable LD",
    255: "update request"}
PII_SVC_GET = {
    256: "ramp offset",
    257: "level",
    258: "ramp value",
    272: "lockbox monitor",
    273: "P monitor",
    304: "lock disabled",
    305: "I1 disabled",
    306: "I2 disabled",
    307: "ramp active"}
PII_SVC_SET = {
    0: "disable lock",
    1: "disable I1",
    2: "disable I2",
    3: "activate ramp",
    4: "offset in value",
    5: "level",
    6: "ramp value",
    255: "update request"}
ADC_SVC_GET = {
    0: "ADC channel 0",
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
ADC_SVC_SET = {}  # type: Dict[int, str] # ADC has no input channels
MUC_SVC_GET = {1: "system time?"}

# Define some custom types.
MenloUnit = Union[float, int]
DataPoint = Tuple[float, MenloUnit]  # Measurement (time, reading)
Buffer = List[DataPoint]
Buffers = Dict[int, Dict[int, Buffer]]
Time = float  # Unix timestamp, as returned by time.time()


# pylint: disable=too-many-public-methods
# This is a driver for a lot of connected cards and thus needs a lot of
# methods.
class MenloStack:
    """Provides an interface to the Menlo electronics stack."""

    # Laser Diode Driver Control.

    def __init__(self) -> None:
        """This does not do anything. Make sure to await the init() coro!"""
        self._buffers = None  # type: Buffers
        self._connection = (
            None)  # type: websockets.client.WebSocketClientProtocol

        # Calibratable offsets for TEC current readings. Those are >> 0, thus
        # calibration is mandatory to get useful readings.
        self._tec_current_offsets = {unit: 0.0 for unit in range(1, 5)}

    async def init_async(self, url: str = DEFAULT_URL) -> None:
        """This replaces the default constructor.

        Be sure to await this coroutine before using the class.
        """
        self._init_buffers()
        self._connection = await websockets.connect(url)
        asyncio.ensure_future(self._listen_to_socket())
        await self.calibrate_tecs()

    async def calibrate_tec(self, unit_number: int) -> None:
        """Find zero-crossing of TEC current reading and compensate for it.

        TEC of given unit must be disabled.
        """
        node = unit_number + 2
        if node in LASER_NODES:

            # The user must disable the TEC themselves, as we don't want to be
            # responsible for possible effects.
            if not self.is_tec_enabled(unit_number):
                LOGGER.info("Calibrating TEC unit %s ...", unit_number)

                # Reset current calibration.
                self._tec_current_offsets[unit_number] = 0

                # Take uncalibrated readings and average them to get a new
                # calibration offset.
                now = time.time()
                await asyncio.sleep(TEC_CALIBRATION_TIME)
                readings = self.get_tec_current(unit_number, since=now - 10)
                if readings:
                    offset = sum([r for (t, r) in readings]) / len(readings)
                    self._tec_current_offsets[unit_number] = offset
                    LOGGER.info("Calibrated TEC unit %s like %s -> 0 by using "
                                "%s readings.",
                                unit_number, offset, len(readings))
                else:
                    LOGGER.error("Didn't receive any current readings to "
                                 "calibrate TEC unit %s against.", unit_number)
            else:
                LOGGER.error("Disable TEC %s before calibrating.", unit_number)
        else:
            LOGGER.error("There is no oscillator supply unit %s to calibrate "
                         "the TEC for.", unit_number)

    async def calibrate_tecs(self) -> None:
        """Calibrate zero-crossings of all TEC units' current readings."""
        tasks = [self.calibrate_tec(unit) for unit in range(1, 5)]
        await asyncio.wait(tasks, timeout=2 * TEC_CALIBRATION_TIME)

    def get_adc_voltage(self, channel: int, since: Time = None) -> Buffer:
        if channel in ADC_SVC_GET.keys():
            return self._get_latest(self._buffers[16][channel], since)

        LOGGER.warning("ADC channel index out of bounds. Returning dummy.")
        return self._dummy_point_series()

    def is_current_driver_enabled(self, unit_number: int) -> Buffer:
        return self._get_laser_prop(unit_number, 305)

    def is_tec_enabled(self, unit_number: int) -> Buffer:
        return self._get_laser_prop(unit_number, 304)

    def is_lock_enabled(self, unit_number: int) -> Buffer:
        return self._get_pii_prop(unit_number, 304)

    def is_integrator_enabled(self, unit_number: int, stage: int) -> Buffer:
        """Is the given unit's integrator stage "stage" shorted or not?
        0: It is shorted / disabled
        1: Enabled
        """
        if stage == 1:
            return self._get_pii_prop(unit_number, 305)
        if stage == 2:
            return self._get_pii_prop(unit_number, 306)
        LOGGER.error("Please choose integrator stage 1 or 2. Returning Dummy")
        return self._dummy_point_series()

    def is_ramp_enabled(self, unit_number: int) -> Buffer:
        return self._get_pii_prop(unit_number, 307)

    def get_pii_prop_factor(self, unit_number: int) -> Buffer:
        return self._get_pii_prop(unit_number, 257)

    def get_pii_offset(self, unit_number: int) -> Buffer:
        return self._get_pii_prop(unit_number, 256)

    def get_pii_monitor(self, unit_number: int, p_only: bool = False,
                        since: Time = None) -> Buffer:
        return self._get_pii_prop(unit_number, 273 if p_only else 272, since)

    def is_temp_ok(self, unit_number: int) -> Buffer:
        return self._get_laser_prop(unit_number, 288)

    def get_temperature(self, unit_number: int, since: Time = None) -> Buffer:
        return [(time, self._to_temperature(val))
                for (time, val)
                in self._get_laser_prop(unit_number, 272, since)]

    def get_temp_setpoint(self, unit_number: int) -> Buffer:
        return [(time, self._to_temperature(val, is_setpoint=True))
                for (time, val) in self._get_laser_prop(unit_number, 256)]

    def get_diode_current(self,
                          unit_number: int, since: Time = None) -> Buffer:
        return self._get_laser_prop(unit_number, 275, since)

    def get_diode_current_setpoint(self, unit_number: int,
                                   since: Time = None) -> Buffer:
        return [(time, val / 8.)
                for (time, val)
                in self._get_laser_prop(unit_number, 257, since)]

    def get_tec_current(self, unit_number: int, since: Time = None) -> Buffer:
        return [(time, val - self._tec_current_offsets[unit_number])
                for (time, val)
                in self._get_laser_prop(unit_number, 274, since=since)]

    def set_temp(self, unit_number: int, temp: float) -> None:
        node = 2 + unit_number
        if node in LASER_NODES:
            asyncio.ensure_future(
                self._send_command(node, 1, str(
                    self._from_temperature(temp, is_setpoint=True))))
        else:
            LOGGER.error("Oscillator Supply unit index out of range."
                         "Refusing to set temperature setpoint.")

    def set_current(self, unit_number: int, milliamps: float) -> None:
        node = 2 + unit_number
        if node in LASER_NODES:
            asyncio.ensure_future(
                self._send_command(node, 3, str(milliamps * 8)))
        else:
            LOGGER.error("Oscillator Supply unit index out of range."
                         "Refusing to set current setpoint.")

    def switch_tec(self, unit: int, on: bool) -> None:
        LOGGER.info("Switching TEC of unit %s %s.",
                    unit, "ON" if on else "OFF")
        if unit + 2 in LASER_NODES:
            asyncio.ensure_future(
                self._send_command(unit + 2, 2, 1 if on else 0))
        else:
            LOGGER.error("There is no oscillator supply unit %s", unit)

    def switch_ld(self, unit: int, on: bool) -> None:
        if unit + 2 in LASER_NODES:
            LOGGER.info("Switching current driver of unit %s %s.",
                        unit, "ON" if on else "OFF")
            asyncio.ensure_future(
                self._send_command(unit + 2, 5, 1 if on else 0))
        else:
            LOGGER.error("There is no oscillator supply unit %s", unit)

    def switch_ramp(self, unit: int, on: bool) -> None:
        """Switch the ramp generation of given PII unit on or off."""
        if unit in PII_NODES:
            LOGGER.info("Switching ramp generation of PII unit %s %s.",
                        unit, "ON" if on else "OFF")
            asyncio.ensure_future(
                self._send_command(unit, 3, 1 if on else 0))
        else:
            LOGGER.error("There is no PII unit %s", unit)

    ###################
    # Private Methods #
    ###################

    def _get_laser_prop(self, unit_number: int, service_id: int,
                        since: Time = None) -> Buffer:
        node_id = (unit_number + 2)
        if node_id in LASER_NODES:
            since = since if isinstance(since, float) else math.nan
            return self._get_latest(self._buffers[node_id][service_id], since)

        # else
        LOGGER.warning("There is no oscillator supply unit %d. "
                       "Returning dummy.", unit_number)
        return self._dummy_point_series()

    def _get_pii_prop(self, unit_number: int, service_id: int,
                      since: Time = None) -> Buffer:
        since = since if isinstance(since, float) else math.nan
        node_id = unit_number
        if node_id in PII_NODES:
            return self._get_latest(self._buffers[node_id][service_id], since)

        # else
        LOGGER.warning("There is no pii controller unit %d. "
                       "Returning dummy.", unit_number)
        return self._dummy_point_series()

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
        # in tuples: [(time1, value1), (time2, value2), etc.]

        # First, create a tree of buffers for each module.
        laser_buffers = {node_id: {svc_id: []
                                   for svc_id in LASER_SVC_GET}
                         for node_id in LASER_NODES}  # type: Buffers
        lockbox_buffers = {node_id: {svc_id: []
                                     for svc_id in PII_SVC_GET}
                           for node_id in PII_NODES}  # type: Buffers
        adc_buffers = {ADC_NODE: {svc_id: []
                                  for svc_id in ADC_SVC_GET}}  # type: Buffers
        muc_buffers = {MUC_NODE: {svc_id: []
                                  for svc_id in MUC_SVC_GET}}  # type: Buffers

        # Merge dictionaries into one, as "node" is a unique key.
        self._buffers = {}
        self._buffers.update(laser_buffers)
        self._buffers.update(lockbox_buffers)
        self._buffers.update(adc_buffers)
        self._buffers.update(muc_buffers)

    async def _send_command(self, node: int, service: int,
                            value: Union[MenloUnit, str]) -> None:
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
            if not buffer:
                LOGGER.info("Service %d:%d (%s) alive. First value: %s",
                            node, service, self._name_service(node, service),
                            value)

            # Convert the MenloUnit-ish string to a MenloUnit (NaN on error).
            val = math.nan
            try:
                val = int(value)
            except ValueError:
                try:
                    val = float(value)
                except ValueError:
                    LOGGER.error("Couldn't convert <%s> to either int or"
                                 "float.")
            self._rotate_log(self._buffers[node][service], val)
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

    async def request_full_status(self) -> None:
        for node in LASER_NODES + PII_NODES:
            await self._send_command(node, 255, '0')

    @staticmethod
    def _rotate_log(log_list: Buffer, value: MenloUnit) -> None:
        # Inserts value into log_list, making sure it's length stays capped.

        log_list.insert(0, (time.time(), value))

        # Shave of some elements in case the list got too long. Be careful to
        # not use any statement here that creates a new list. Such as
        #     list = list[0:foo_end]
        # which does NOT work, as it doesn't modify the passed-by-reference
        # list.
        del log_list[ROTATE_N:]

    @staticmethod
    def _get_latest(buffer: Buffer, since: float = None) -> Buffer:
        """Returns all tuples of time and value since "since" from given buffer.
        """
        if not isinstance(since, float):
            since = math.nan
        if buffer:
            if math.isnan(since):  # Get single latest data point.

                # In order to be consistent with queries using "since", we
                # return a length-1 array.
                return buffer[:1]

            # Get a timeline of recent data points whose timestamp is larger
            # than "since"
            oldest_index = next((i for i, dp in enumerate(buffer)
                                 if dp[0] < since), len(buffer))

            # Take all elements until oldest_index and return them in reversed
            # order (oldest item last) to simplify plotting.
            # Due to the async nature of this class, we must return a copy of
            # those elements. The original buffer will keep being modified
            # which will interfere with the caller's actions.
            # Hence this leads to PROBLEMS: return buffer[oldest_index - 1::-1]
            return list(reversed(buffer[:oldest_index]))

        LOGGER.debug("Returning emtpy buffer.")
        return MenloStack._dummy_point_series()

    @staticmethod
    def _dummy_point_series() -> Buffer:
        return []

    @staticmethod
    def _name_service(node: int, service: int) -> str:
        if node in LASER_NODES:
            if service in LASER_SVC_GET.keys():
                return LASER_SVC_GET[service]
        elif node in PII_NODES:
            if service in PII_SVC_GET.keys():
                return PII_SVC_GET[service]
        elif node == 16:  # ADC
            if service in ADC_SVC_GET.keys():
                return ADC_SVC_GET[service]
        elif node == 255:  # MUC
            if service in MUC_SVC_GET.keys():
                return MUC_SVC_GET[service]

        # Unknown combination of Node and Service.
        LOGGER.warning("Tried to name unknown service %d:%d.", node, service)
        return "unknown service"

    @staticmethod
    def _to_temperature(menlos: MenloUnit, is_setpoint: bool = False) -> float:
        """Takes a temp. in Celsius and converts in to Menlo units.

        The parameters of the quadratic expansion were approximated by R. Wilk
        based on a plot in the TEC controller chip datasheet."""
        factor = 27000 if is_setpoint else 1000
        a0 = factor * -2.489
        a1 = factor * 0.1717
        a2 = factor * -0.0004352
        return -a1/(2*a2) - math.sqrt((a1/(2*a2))**2 + (menlos - a0)/a2)

    @staticmethod
    def _from_temperature(celsius: float, is_setpoint: bool = False) -> int:
        """Takes a menlo current reading and converts in to ° Celsius.

        The parameters of the quadratic expansion are read by R. Wilk from a
        plot in the TEC controller chip datasheet."""
        factor = 27000 if is_setpoint else 1000
        a0 = factor * -2.489
        a1 = factor * 0.1717
        a2 = factor * -0.0004352
        return int(round(a0 + a1 * celsius + a2 * celsius**2))
