"""A driver for the Menlo stack websocket.

This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.

This class is supposed to not raise any exception. Problems, even arising from
invalid input arguments are handled gracefully and logged.
"""

import asyncio     # Needed for websockets.
import logging
import math
import time        # To keep track of when replies came in.
from typing import Dict, List, Tuple, Union
import numpy as np

import websockets

# Adjust as needed
ROTATE_N = 128  # Keep log of received values smaller than this.
DEFAULT_URL = 'ws://menlostack:8000'
TEC_CALIBRATION_TIME = 10.0

LOGGER = logging.getLogger('pyodine.drivers.menlo_stack')
LOGGER.setLevel(logging.INFO)

# Constants specific to the published Menlo interface.

OSC_NODES = [3, 4, 5, 6]  # node IDs of osc units 1 through 4
PII_NODES = [1, 2]          # node IDs of lockboxes 1 and 2
ADC_NODE = 16               # node ID of the analog-digital converter
MUC_NODE = 255              # node ID of the embedded system

# Provide dictionaries for the service IDs.
OSC_SVC_GET = {
    256: "temp setpoint",
    257: "LD current setpoint",
    272: "meas. LD temperature",
    273: "UNKNOWN 01",
    274: "meas. TEC current",
    275: "meas. LD current",
    288: "temp OK flag",
    304: "TEC enabled",
    305: "LD driver enabled"}
OSC_SVC_SET = {
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

# Define some custom types. As the typing library is quite a recent feature,
# there are some inconveniencies regarding pylint:
# pylint: disable=invalid-name,unsubscriptable-object
MenloUnit = Union[float, int]
DataPoint = Tuple[float, MenloUnit]  # Measurement (time, reading)
Buffer = List[DataPoint]
Buffers = Dict[int, Dict[int, Buffer]]  # Node -> Service -> Buffer
Time = float  # Unix timestamp, as returned by time.time()
# pylint: enable=invalid-name,unsubscriptable-object


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
        self.calibrate_tecs()

    async def calibrate_tec(self, unit_number: int) -> None:
        """Find zero-crossing of TEC current reading and compensate for it.

        TEC of given unit must be disabled.
        """
        try:
            self._get_osc_node_id(unit_number)
        except ValueError:
            LOGGER.exception("No such node.")
        else:
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

    def calibrate_tecs(self) -> None:
        """Calibrate zero-crossings of all TEC units' current readings."""
        tasks = [self.calibrate_tec(unit) for unit in range(1, 5)]
        asyncio.ensure_future(
            asyncio.wait(tasks, timeout=2 * TEC_CALIBRATION_TIME))

    def get_adc_voltage(self, channel: int, since: Time = None) -> Buffer:
        """Get reading of the analog-digital converter in Volts."""
        if channel in ADC_SVC_GET:
            return self._get_latest(self._buffers[16][channel], since)

        LOGGER.warning("ADC channel index out of bounds. Returning dummy.")
        return self._dummy_point_series()

    def is_current_driver_enabled(self, unit_number: int) -> Buffer:
        return self._get_osc_prop(unit_number, 305)

    def is_tec_enabled(self, unit_number: int) -> Buffer:
        return self._get_osc_prop(unit_number, 304)

    def is_lock_enabled(self, unit_number: int) -> Buffer:
        return self._get_pii_prop(unit_number, 304)

    def is_integrator_enabled(self, unit_number: int, stage: int) -> Buffer:
        """Is the given unit's integrator stage "stage" shorted or not?
        0: It is shorted / disabled
        1: Enabled
        """
        try:
            stage = int(stage)
        except (TypeError, ArithmeticError):
            LOGGER.exception("Error parsing stage index.")
        else:
            if stage == 1:
                return self._get_pii_prop(unit_number, 305)
            if stage == 2:
                return self._get_pii_prop(unit_number, 306)
            LOGGER.error("Please choose integrator stage 1 or 2.")
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
        return self._get_osc_prop(unit_number, 288)

    def get_temperature(self, unit_number: int, since: Time = None) -> Buffer:
        return [(time, self._to_temperature(val))
                for (time, val)
                in self._get_osc_prop(unit_number, 272, since)]

    def get_temp_setpoint(self, unit_number: int) -> Buffer:
        return [(time, self._to_temperature(val, is_setpoint=True))
                for (time, val) in self._get_osc_prop(unit_number, 256)]

    def get_diode_current(self,
                          unit_number: int, since: Time = None) -> Buffer:
        return self._get_osc_prop(unit_number, 275, since)

    def get_diode_current_setpoint(self, unit_number: int,
                                   since: Time = None) -> Buffer:
        return [(time, val / 8.)
                for (time, val)
                in self._get_osc_prop(unit_number, 257, since)]

    def get_tec_current(self, unit_number: int, since: Time = None) -> Buffer:
        return [(time, val - self._tec_current_offsets[unit_number])
                for (time, val)
                in self._get_osc_prop(unit_number, 274, since=since)]

    def set_temp(self, unit_number: int, temp: float) -> None:
        """Set temperature setpoint of given oscillator supply unit in °C.

        Caution: avoid using this directly. All components require externally
        implemented temperature ramping."""

        # Coerce input param types if possible. Abort otherwise.
        try:
            unit_number = int(unit_number)
            temp = float(temp)
        except (ValueError, TypeError):
            LOGGER.exception("Invalid argument passed. Refusing.")
            return

        # Only work on existing nodes. Abort otherwise.
        node = 2 + unit_number
        if node not in OSC_NODES:
            LOGGER.error("Oscillator Supply unit index out of range."
                         "Doing nothing.")
            return

        try:
            dac_value = str(self._from_temperature(temp, is_setpoint=True))
        except ValueError:
            LOGGER.exception("Temperature out of range. Ignoring.")
        else:
            asyncio.ensure_future(self._send_command(node, 1, dac_value))

    def set_current(self, unit_number: int, milliamps: float) -> None:
        """Set the current driver setpoint to the given value in mA.
        """
        # Enforce argument types.
        try:
            unit_number = int(unit_number)
            dac_value = int(milliamps * 8)  # One DAC count is 0.125 mA.
        except (ValueError, TypeError, ArithmeticError):
            LOGGER.exception("Invalid argument passed.")
            return

        try:  # Only work on existing nodes.
            node = self._get_osc_node_id(unit_number)
        except ValueError:
            LOGGER.exception("No such osc. sup. node.")
            return

        # Check for legal range of requested DAC voltage (which is then
        # internally translated to the current setpoint).
        # TODO: Put -1 instead of -3 as soon as Menlo spec arrives.
        if dac_value >= 0 and dac_value < 2**16-3:
            asyncio.ensure_future(self._send_command(node, 3, str(dac_value)))
        else:
            LOGGER.error("Passed current setpoint out of DAC range.")

    def switch_tec(self, unit_number: int, switch_on: bool) -> None:
        """Turn thermoelectric cooling of given unit on or off."""
        try:
            node = self._get_osc_node_id(int(unit_number))
        except ValueError:
            LOGGER.exception("No such osc. sup. node.")
        except (TypeError, OverflowError):
            LOGGER.exception("Weird unit number.")
        else:
            LOGGER.info("Switching TEC of unit %s %s.",
                        unit_number, "ON" if switch_on else "OFF")
            asyncio.ensure_future(
                self._send_command(node, 2, 1 if switch_on else 0))

    def switch_ld(self, unit_number: int, switch_on: bool) -> None:
        """Turn current driver of given unit on or off."""
        if unit_number + 2 in OSC_NODES:
            LOGGER.info("Switching current driver of unit %s %s.",
                        unit_number, "ON" if switch_on else "OFF")
            asyncio.ensure_future(
                self._send_command(unit_number + 2, 5, 1 if switch_on else 0))
        else:
            LOGGER.error("There is no oscillator supply unit %s", unit_number)

    def switch_ramp(self, unit: int, switch_on: bool) -> None:
        """Switch the ramp generation of given PII unit on or off."""
        if unit in PII_NODES:
            LOGGER.info("Switching ramp generation of PII unit %s %s.",
                        unit, "ON" if switch_on else "OFF")
            asyncio.ensure_future(
                self._send_command(unit, 3, 1 if switch_on else 0))
        else:
            LOGGER.error("There is no PII unit %s", unit)

    def set_ramp_amplitude(self, unit: int, millivolts: int) -> None:
        """TODO: this seems unnecessary and not operational."""
        if unit not in PII_NODES:
            LOGGER.error("Can't set ramp amplitude of unit %s, as there is no "
                         "such unit.", unit)
            return
        if millivolts < -2500 or millivolts > 2500:
            LOGGER.error("Ramp amplitude out of bounds (-2500...2500, %s "
                         "given).", millivolts)
            return
        LOGGER.info("Setting ramp amplitude of PII unit %s to %s mV",
                    unit, millivolts)
        asyncio.ensure_future(
            self._send_command(unit, 6, millivolts))

    def get_ramp_amplitude(self, unit: int) -> Buffer:
        """TODO: this seems unnecessary and not operational."""
        if unit not in PII_NODES:
            LOGGER.error("Can't set ramp amplitude of unit %s, as there is no "
                         "such unit.", unit)
            return self._dummy_point_series()
        return self._get_pii_prop(unit, 258)

    ###################
    # Private Methods #
    ###################

    def _get_osc_prop(self, unit_number: int, service_id: int,
                      since: Time = None) -> Buffer:
        node_id = (unit_number + 2)
        if node_id in OSC_NODES:
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
        osc_buffers = {node_id: {svc_id: [] for svc_id in OSC_SVC_GET}
                       for node_id in OSC_NODES}  # type: Buffers
        pii_buffers = {node_id: {svc_id: [] for svc_id in PII_SVC_GET}
                       for node_id in PII_NODES}  # type: Buffers
        adc_buffers = {ADC_NODE: {svc_id: []
                                  for svc_id in ADC_SVC_GET}}  # type: Buffers
        muc_buffers = {MUC_NODE: {svc_id: []
                                  for svc_id in MUC_SVC_GET}}  # type: Buffers

        # Merge dictionaries into one, as "node" is a unique key.
        self._buffers = {}
        self._buffers.update(osc_buffers)
        self._buffers.update(pii_buffers)
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
                LOGGER.debug("Service %d:%d (%s) alive. First value: %s",
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

    def _parse_reply(self, received_string: str) -> None:
        LOGGER.debug("Parsing reply '%s'", received_string)

        # Some responses contain a packed set of single values. Those are
        # concatenated using the '@' token.
        responses = received_string.split('@')

        for resp in responses:
            parts = resp.split(":")
            self._store_reply(int(parts[0]), int(parts[1]), parts[2])

    async def request_full_status(self) -> None:
        for node in OSC_NODES + PII_NODES:
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
        if node in OSC_NODES:
            if service in OSC_SVC_GET.keys():
                return OSC_SVC_GET[service]
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
        based on a plot in the TEC controller chip datasheet.

        :raises ArithmeticError: when the conversion fails.
        """
        factor = 27000 if is_setpoint else 1000
        a_0 = factor * -2.489
        a_1 = factor * 0.1717
        a_2 = factor * -0.0004352
        return -a_1/(2*a_2) - math.sqrt((a_1/(2*a_2))**2 + (menlos - a_0)/a_2)

    @staticmethod
    def _from_temperature(celsius: float, is_setpoint: bool = False) -> int:
        """Takes a menlo current reading and converts in to ° Celsius.

        The parameters of the quadratic expansion are read by R. Wilk from a
        plot in the TEC controller chip datasheet.

        :raises ArithmeticError: if the conversion failed.
        :raises ValueError: if the resulting dac_value is out of bounds.
        """
        factor = 27000 if is_setpoint else 1000
        a_0 = factor * -2.489
        a_1 = factor * 0.1717
        a_2 = factor * -0.0004352
        dac_value = int(round(a_0 + a_1 * celsius + a_2 * celsius**2))

        # Only continue if we arrived at a legal DAC value.
        # TODO: put -1 instead of -3 as soon as definitive Menlo spec. arrives.
        if dac_value >= 0 and dac_value < 2**16 - 3:
            return dac_value
        # else
        raise ValueError("Temperature out of DAC range.")

    @staticmethod
    def to_ntc_resistance(counts: int, is_setpoint: bool) -> float:
        """Convert ADC/DAC counts into (estimated) NTC thermistor resistance.

        This is used for reading out the actual object temperature as well as
        reading the current temperature setpoint value.

        :param counts: Reading, as received digitally from DAC or ADC
        :param is_setpoint: The reading does originate from the temp. setpoint
            combined ADC/DAC chip and not from the actual object temp. ADC.
        :returns: Resistance of the NTC thermistor in Ohms.
        """

        # The actual curve is approximated by a fourth-order polynomial:
        counts_per_volt = 27000 if is_setpoint else 1000

        # We obtained the R(U) relation for the thermistor resistance vs. the
        # applied set voltage for the given chip in form of a sufficiently
        # accurate fourth-order polynomial.
        coeffs = [2.32131941486, -53.7758974562, 629.141287209,
                  -4474.03732095, 15601.7430608]
        try:
            volts = counts / counts_per_volt
            ohms = np.polyval(coeffs, volts)
        except ArithmeticError:
            raise ValueError("Passed DAC counts out of range.")
        else:
            return ohms

    @staticmethod
    def to_dac_counts(ohms: float) -> int:
        """Convert NTC thermistor resistance DAC counts.

        This is used for setting the temperature setpoint.

        :param ohms: Resistance of NTC thermistor in Ohms.
        :returns: numeric value to send to DAC.
        """
        counts_per_volt = 27000

        # By some analytical trickery, we obtained the coefficients of a 6th
        # order polynomial approximating the U(R) relation of the used TEC
        # chip.
        coefficients = [9.96544974929286e-25, -6.48193814201448e-20,
                        1.83265994944409e-15, -2.95535304724271e-11,
                        3.03070724899164e-7, -0.00223020840250838,
                        10.2544735672273]
        try:
            volts = np.polyval(coefficients, ohms)
            counts = int(counts_per_volt * volts)
        except ArithmeticError:
            raise ValueError("Provided resistance is out of bounds.")
        else:
            return counts

    @classmethod
    def _get_osc_node_id(cls, unit_number: int) -> int:
        # Return the CAN bus node id of the osc unit with given index.

        # We consolidate all possible exceptions this method could raise into
        # the expected "ValueError" to make sure nothing is unhandled.
        try:
            node = int(unit_number) + 2
        except (ValueError, TypeError, ArithmeticError):
            LOGGER.exception("No such osc. sup. node.")
            raise ValueError("Couldn't parse passed unit_number.")
        else:
            if node in OSC_NODES:
                return node
        raise ValueError("There is no oscillator supply unit %s.", unit_number)
