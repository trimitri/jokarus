"""A driver for the Menlo stack websocket.

This module provides an interface wrapper class for the websockets interface
exposed by the Menlo Electronics control computer.

Safety Policy
-------------
This class silently assumes all passed arguments to be of correct type. The
values are allowed to be wrong, but may lead to silent errors/ignores.
"""
import asyncio
import enum
import logging
import time        # To keep track of when replies came in.
from typing import Dict, List, Tuple, Union

import websockets

from . import ati_tec
from .. import logger
from ..util import ntc_temp

# Adjust as needed
ROTATE_N = 128  # Keep log of received values smaller than this.
DEFAULT_URL = 'ws://menlostack:8000'
LOG_QUANTITIES = True  # Log quantities on disk as they are received.

# Zero the average Peltier current measured over this time span.
TEC_CALIBRATION_TIME = 10.0

# Probably due to poor circuit design (output overload?), the digital-analog
# converter used for setting the temperature setpoints performs very poorly
# with increasing output voltage (up to 4% error). Although the actual
# reference voltage used for this DAC is 4975mV, we will assume 4820mV here to
# compensate for this offset.
DAC_VREF = 4.820 # Voltage reference for the DAC chip
TEC_DAC_FACTOR = 2**16 / DAC_VREF  # Counts per volt for temp. setpoint DAC

# The ADC is part of a "closed-source" region of the circuit and seems to have
# a one count per mV conversion factor. Thus we use 1000 and not 2^10 here. In
# addition, there is a 1:1 current divider before the signal is fed to the ADC.
TEC_ADC_FACTOR = 1000/2  # Counts per volt for actual temp ADC

LOGGER = logging.getLogger('pyodine.drivers.menlo_stack')
LOGGER.setLevel(logging.INFO)

# Constants specific to the published Menlo interface.

OSC_NODES = [3, 4, 5, 6]  # node IDs of osc units 1 through 4
PII_NODES = [1, 2]          # node IDs of lockboxes 1 and 2
ADC_NODE = 16               # node ID of the analog-digital converter
MUC_NODE = 255              # node ID of the embedded system

# Usually we try to calibrate the TEC current zero readings on startup. As we
# cannot do this for running units, we have some canned calibration values here
# to be used in those cases.
TEC_CALIBRATION = {1: 1492, 2: 1464, 3: 1483, 4: 1487}

# Provide dictionaries for the service IDs.
OSC_SVC_GET = {
    256: "temp_setpoint",
    257: "LD_current_setpoint",
    272: "temperature",
    273: "UNKNOWN_01",
    274: "TEC_current",
    275: "LD_current",
    288: "temp_OK",
    304: "TEC_enabled",
    305: "LD_driver enabled"}
OSC_SVC_SET = {
    1: "TEC temperature",
    2: "enable TEC",
    3: "LD current",
    5: "enable LD",
    255: "update request"}
PII_SVC_GET = {
    256: "ramp_offset",
    257: "level",
    258: "ramp_value",
    272: "lockbox_monitor",
    273: "P_monitor",
    304: "lock_disabled",
    305: "I1_disabled",
    306: "I2_disabled",
    307: "ramp_active"}
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
    0: "ADC_channel_0",
    1: "ADC_channel_1",
    2: "ADC_channel_2",
    3: "ADC_channel_3",
    4: "ADC_channel_4",
    5: "ADC_channel_5",
    6: "ADC_channel_6",
    7: "ADC_channel_7",
    8: "ADC_temp_0",
    9: "ADC_temp_1",
    10: "ADC_temp_2",
    11: "ADC_temp_3",
    12: "ADC_temp_4",
    13: "ADC_temp_5",
    14: "ADC_temp_6",
    15: "ADC_temp_7"}
ADC_SVC_SET = {}  # type: Dict[int, str] # ADC has no input channels
MUC_SVC_GET = {1: "system_time"}

class OscCard(enum.Enum):
    """A physical oscillator supply card.

    Values are the respective board's serial number."""
    OSC1A = 4  # Card number 1 from stack A
    OSC2A = 5  # Card number 2 from stack A
    OSC3A = 6
    OSC4A = 7
    OSC1B = 31216  # Card number 1 from stack B
    OSC2B = 21216
    OSC3B = 41216
    OSC4B = 11216

_OSC_CARD_IDX = {OscCard.OSC1A: 3,
                 OscCard.OSC1B: 3,
                 1: 3,
                 OscCard.OSC2A: 4,
                 OscCard.OSC2B: 4,
                 2: 4,
                 OscCard.OSC3A: 5,
                 OscCard.OSC3B: 5,
                 3: 5,
                 OscCard.OSC4A: 6,
                 OscCard.OSC4B: 6,
                 4: 6}  # type: Dict[Union[OscCard, int], int]
"""The CAN bus indices assigned to the physical cards."""

# Define some custom types. As the typing library is quite a recent feature,
# there are some inconveniencies regarding pylint:
# pylint: disable=invalid-name,unsubscriptable-object
MenloUnit = Union[float, int]
DataPoint = Tuple[float, MenloUnit]  # Measurement (time, reading)
Buffer = List[DataPoint]
Buffers = Dict[int, Dict[int, Buffer]]  # Node -> Service -> Buffer
Time = float  # Unix timestamp, as returned by time.time()
# pylint: enable=invalid-name,unsubscriptable-object


class Calibration:  # This won't be instanciated. # pylint: disable=too-few-public-methods
    """Static Menlo stack calibration data."""
    # Using linear fits on data acquired in a calibration run, we may improve the
    # current driver accuracy. Data is on JOKARUS share.
    LD_CURRENT_SETTER = {card: lambda I: I for card in OscCard}
    """Translate a desired current setpoint into a value to send to the stack."""
    LD_CURRENT_SETTER[OscCard.OSC1A] = \
        lambda I: 1.0430516711750952 * I + 10.07060657466415

    LD_CURRENT_GETTER = {card: lambda x: x for card in OscCard}
    """Estimate the actual current given a menlo current reading."""
    LD_CURRENT_GETTER[OscCard.OSC1A] = \
        lambda I: 0.9791694725028058 * I + 7.16309764309765

    LD_CURRENT_SETPOINT_GETTER = {card: lambda x: x for card in OscCard}
    """Estimate the actual current setpoint given a menlo current setpoint reading."""
    LD_CURRENT_SETPOINT_GETTER[OscCard.OSC1A] = \
        lambda I: 0.9587252747252747 * I - 9.654945054945046


# pylint: disable=too-many-public-methods
# This is a driver for a lot of connected cards and thus needs a lot of
# methods.
class MenloStack:
    """Provides an interface to the Menlo electronics stack."""

    # Laser Diode Driver Control.

    def __init__(self) -> None:
        """This does not do anything. Make sure to await the init() coro!"""
        LOGGER.info("Initializing Menlo stack...")
        self._buffers = None  # type: Buffers
        self._connection = None  # type: websockets.client.WebSocketClientProtocol

        # Calibratable offsets for TEC current readings. Those are >> 0, thus
        # calibration is mandatory to get useful readings.
        self._tec_current_offsets = {unit: 0.0 for unit in range(1, 5)}

        # Takes care of converting thermistor resistance to temperature and
        # vice versa.
        self._standard_ntc = ntc_temp.NtcTemp(use_celsius=True)

    async def init_async(self, url: str = DEFAULT_URL) -> None:
        """This replaces the default constructor.

        Be sure to await this coroutine before using the class.

        :param url: Menlo stack URL, like "ws://1.2.3.4:8000"
        :raises ConnectionError: If the stack doesn't reply or no stack was
                    found at the given address.
        """
        try:
            self._connection = await websockets.connect(url)

        # There's multiple ways the connection to the MUC can fail. We don't
        # really care what went wrong, we'll just tell the user what it was and
        # fail. OSError is raised when nothing is connected to the port at all.
        except (websockets.InvalidURI, websockets.InvalidHandshake, OSError) as err:
            raise ConnectionError("Couldn't talk to server at given port/address.") from err

        self._init_buffers()
        asyncio.ensure_future(self._listen_to_socket())
        await self.calibrate_tecs()
        LOGGER.info("Initialized Menlo stack.")

    async def calibrate_tec(self, unit_number: int) -> None:
        """Find zero-crossing of TEC current reading and compensate for it.

        TEC of given unit must be disabled.
        """
        try:
            self._get_osc_node_id(unit_number)
        except ValueError:
            LOGGER.exception("No such node.")
            return

        # Find out if the unit is active.
        is_disabled = None  # type: bool  # TEC unit is in standby.

        # Wait at most ten seconds for data.
        for _ in range(10):
            # Did we receive the on/off flag already?
            # Attention: We check for the length of the returned buffer here,
            # this is not a boolean!
            if self.is_tec_enabled(unit_number):
                # Extract the actual info from the Buffer.
                is_disabled = self.is_tec_enabled(unit_number)[0][1] == 0
                break  # Success! We know the state. Exit the loop.
            else:
                await asyncio.sleep(1)  # Wait a for data.

        # The user must disable the TEC themselves, as we don't want to be
        # responsible for possible effects.
        if is_disabled:
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
            canned_zero = TEC_CALIBRATION[unit_number]
            self._tec_current_offsets[unit_number] = canned_zero
            LOGGER.warning("Can't calibrate TEC %s, as it is running. Using "
                           "canned value %s mA for zero.",
                           unit_number, canned_zero)

    async def calibrate_tecs(self) -> None:
        """Calibrate zero-crossings of all TEC units' current readings."""
        LOGGER.info("Calibrating TECs...")
        await self.request_full_status()
        tasks = [self.calibrate_tec(unit) for unit in range(1, 5)]
        await asyncio.wait(tasks, timeout=2 * TEC_CALIBRATION_TIME)

    def get_adc_voltage(self, channel: int, since: Time = None) -> Buffer:
        """Get reading of the analog-digital converter in Volts."""
        if channel in ADC_SVC_GET:
            return self._get_latest(self._buffers[16][channel], since)

        LOGGER.warning("ADC channel index out of bounds. Returning dummy.")
        return self._dummy_point_series()

    def is_current_driver_enabled(self, unit: Union[int, OscCard]) -> Buffer:
        return self._get_osc_prop(unit, 305)

    def is_tec_enabled(self, unit: Union[int, OscCard]) -> Buffer:
        return self._get_osc_prop(unit, 304)

    def is_lock_enabled(self, unit_number: int) -> Buffer:
        """Is the closed-loop lock currently engaged? Returns a Buffer!"""
        readings = self._get_pii_prop(unit_number, 304)
        return [(time, 1 if reading == 0 else 0)
                for (time, reading) in readings]

    def is_integrator_enabled(self, unit_number: int, stage: int) -> Buffer:
        """Is the given unit's integrator stage "stage" enabled?
        0: Disabled
        1: Enabled
        """
        readings = None  # type: Buffer
        if stage == 1:
            readings = self._get_pii_prop(unit_number, 305)
        else:
            readings = self._get_pii_prop(unit_number, 306)

        # There is a logic inversion here, as the firmware actually reports if
        # the stage is *disabled*.
        return [(time, 1 if reading == 0 else 0)
                for (time, reading) in readings]

    def is_ramp_enabled(self, unit_number: int) -> Buffer:
        """Is the externally provided ramp passed through or ignored?"""
        readings = self._get_pii_prop(unit_number, 307)

        # There is a logic inversion here, as the firmware actually reports if
        # the stage is *disabled*.
        return [(time, 1 if reading == 0 else 0)
                for (time, reading) in readings]

    def get_pii_monitor(self, unit_number: int, p_only: bool = False,
                        since: Time = None) -> Buffer:
        return self._get_pii_prop(unit_number, 273 if p_only else 272, since)

    def is_temp_ok(self, unit_number: int) -> Buffer:
        return self._get_osc_prop(unit_number, 288)

    def get_temperature(self, unit: Union[int, OscCard], since: Time = None) -> Buffer:
        """Buffer of temp. readings in °C of given unit since `since`."""
        return [(time, self._to_temperature(int(val)))
                for (time, val) in self._get_osc_prop(unit, 272, since)]

    def get_temp_setpoint(self, unit: Union[int, OscCard]) -> Buffer:
        return [(time, self._to_temperature(int(val), is_setpoint=True))
                for (time, val) in self._get_osc_prop(unit, 256)]

    def get_temp_rth(self, unit_number: int, since: Time = None) -> Buffer:
        """Get the object thermistor resistance of given TEC unit."""
        return [(time, self._to_ntc_resistance(int(val), False))
                for (time, val)
                in self._get_osc_prop(unit_number, 272, since)]

    def get_temp_setpt_rth(self, unit_number: int) -> Buffer:
        return [(time, self._to_ntc_resistance(int(val), is_setpoint=True))
                for (time, val) in self._get_osc_prop(unit_number, 256)]

    def get_diode_current(self, unit: Union[OscCard, int], since: Time = None) -> Buffer:
        """Get actual measured diode current, applying calibration if present.
        """
        raw = self._get_osc_prop(unit, 275, since)
        try:  # Use calibration.
            return [(time, Calibration.LD_CURRENT_GETTER[OscCard(unit)](val))
                    for (time, val) in raw]
        except (KeyError, ValueError):  # No calibration present.
            return raw

    def get_diode_current_setpoint(self, unit: OscCard,
                                   since: Time = None) -> Buffer:
        """The currently set current setpoint of given card."""
        raw = self._get_osc_prop(unit, 257, since)
        try:  # Use calibration.
            return [(time, Calibration.LD_CURRENT_SETPOINT_GETTER[OscCard(unit)](val / 8.))
                    for (time, val) in raw]
        except (KeyError, ValueError):  # No calibration present.
            return [(time, val / 8.) for (time, val) in raw]

    def get_tec_current(self, unit_number: int, since: Time = None) -> Buffer:
        return [(time, val - self._tec_current_offsets[unit_number])
                for (time, val)
                in self._get_osc_prop(unit_number, 274, since=since)]

    def set_temp(self, unit_number: int, temp: float) -> None:
        """Set temperature setpoint of given oscillator supply unit in °C.

        This assumes "standard" coefficients for the steinhart-hart equation.
        For better control, use set_temp_rth() instead.

        Caution: avoid using this directly. All components require externally
        implemented temperature ramping."""
        ohms = self._standard_ntc.to_resistance(float(temp))
        self.set_temp_rth(ohms, int(unit_number))

    def set_temp_rth(self, ohms: float, unit_number: int) -> None:
        """Set temperature setpoint by providing a thermistor resistance.

        As the menlo stack is agnostic as to which flavour of NTC is connected
        to it's TEC units, this is the highest level function we can reliably
        provide.
        """
        node = self._get_osc_node_id(int(unit_number))
        dac_counts = self._to_dac_counts(float(ohms))
        self._send_command(node, 1, dac_counts)
        logger.log_quantity('temp_sp',
                            "{}\t{}\t{}".format(unit_number, ohms, dac_counts))

    def set_current(self, unit: Union[int, OscCard], milliamps: float) -> None:
        """Set the current driver setpoint to the given value in mA.
        """
        # Apply calibration data if present.
        if unit in Calibration.LD_CURRENT_SETTER:
            milliamps = Calibration.LD_CURRENT_SETTER[OscCard(unit)](milliamps)

        # Enforce argument types.
        try:
            dac_value = int(milliamps * 8)  # One DAC count is 0.125 mA.
        except (ValueError, TypeError, ArithmeticError):
            LOGGER.exception("Invalid argument passed.")
            return

        try:  # Only work on existing nodes.
            node = self._get_osc_node_id(unit)
        except ValueError:
            LOGGER.exception("No such osc. sup. node.")
            return

        # Check for legal range of requested DAC voltage (which is then
        # internally translated to the current setpoint).
        if dac_value >= 0 and dac_value < 2**16-3:
            self._send_command(node, 3, str(dac_value))
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
            self._send_command(node, 2, 1 if switch_on else 0)

    def switch_ld(self, unit_number: int, switch_on: bool) -> None:
        """Turn current driver of given unit on or off."""
        if unit_number + 2 in OSC_NODES:
            LOGGER.info("Switching current driver of unit %s %s.",
                        unit_number, "ON" if switch_on else "OFF")
            self._send_command(unit_number + 2, 5, 1 if switch_on else 0)
        else:
            LOGGER.error("There is no oscillator supply unit %s", unit_number)

    def switch_ramp(self, unit: int, switch_on: bool) -> None:
        """Switch the ramp generation of given PII unit on or off."""
        if unit in PII_NODES:
            LOGGER.info("Switching ramp generation of PII unit %s %s.",
                        unit, "ON" if switch_on else "OFF")
            self._send_command(unit, 3, 0 if switch_on else 1)
        else:
            LOGGER.error("There is no PII unit %s", unit)

    def switch_lock(self, unit: int, switch_on: bool) -> None:
        """Switch the lock electronics of given PII unit on or off."""
        if unit in PII_NODES:
            LOGGER.info("Switching lock of PII unit %s %s.", unit,
                        "ON" if switch_on else "OFF")

            # There is a logic inversion here, as the actual flag the firmware
            # exposes switches the lock off if '1' is sent.
            self._send_command(unit, 0, 0 if switch_on else 1)
        else:
            LOGGER.error("There is no PII unit %s", unit)

    def switch_integrator(
            self, unit: int, stage: int, switch_on: bool) -> None:
        """Switch the given PII integrator stage (1 or 2) on or off.

        :param unit_name: Which PII unit to act on (1 or 2)
        :param stage: Which stage to act on--1 (fast) or 2 (slow)
        :param switch_on: True for enabling integrator false for disabling it
        """
        if not self._is_pii_unit(unit):
            return
        LOGGER.info("Switching integrator stage %s of unit %s %s.",
                    stage, unit, "ON" if switch_on else "OFF")

        # Quirk: An invalid service id will switch the second integrator.
        service_id = 1 if stage == 1 else 2

        # There is a logic inversion here, as the actual flag exposed by
        # the firmware switches the integrator off if '1' is sent.
        self._send_command(unit, service_id, 0 if switch_on else 1)

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
        self._send_command(unit, 6, millivolts)

    def get_ramp_amplitude(self, unit: int) -> Buffer:
        return self._get_pii_prop(unit, 258)

    def set_error_scale(self, unit: int, factor: float) -> None:
        """Set the scaling factor of the error signal input stage (P gain).

        The input stage is a voltage multiplier. One input to the multiplier is
        the error signal, the other input is constant and given here. Thus it
        works as follows:

        * 1.0: 0dB, just multiply signal by one.
        * -1.0: 0dB, but signal is inverted!
        * 0.5: -3dB attenuation

        :param unit: The PII unit to act on (1 or 2)
        :param factor: The error signal is multiplied by this. Valid: [-1, 1]
        """
        # The error signal (as well as the level internally generated through
        # this command) passes an amplifier before being fed into the "AD633"
        # multiplier. That amplifier multiplies the voltage of the
        # respective signals by 4.3. 2.3V input signal thus lead to 10V at the
        # AD633, which is it's maximum input voltage.

        if unit not in PII_NODES:
            LOGGER.error("Can't set error scale of unit %s, as there is no "
                         "such unit.", unit)
            return
        if not factor <= 2300 or not factor >= -2300:
            LOGGER.error("Error scale out of bounds (-2300...2300, %s "
                         "given).", factor)
            return
        LOGGER.info("Setting error scaling of PII unit %s to %s", unit, factor)
        self._send_command(unit, 5, factor)

    def get_error_scale(self, unit: int) -> Buffer:
        """Scaling factor of the error signal input stage (P gain)."""
        return self._get_pii_prop(unit, 257)

    def set_error_offset(self, unit: int, millivolts: float) -> None:
        """Set the error signal input stage offset compensation.

        **Building on the explanation given at set_error_scale()**:
        # TODO: move this to Menlo documentation and away from the code.
        The AD633 voltage multiplier is also equipped with an offset port. The
        DAC connected to this offset port may add or substract up to 19.6mV
        from the multiplied output voltage. As the multiplier output swings
        about +-10V, this is only a 2% offset though.

        :param unit: The PII unit to act on (1 or 2)
        :param millivolts: Arbitrary value, see menlo test sheet for meaning.
        """
        if unit not in PII_NODES:
            LOGGER.error("Can't set error scale of unit %s, as there is no "
                         "such unit.", unit)
            return
        LOGGER.info("Setting error offset of PII unit %s to %s%%",
                    unit, millivolts)

        # TODO: move this to Menlo documentation and away from the code.
        # The DAC used in this stage has a 1000mV = 1/51 Volt "attenuation"
        # dac_counts = 10 * percent  # 1000 counts = 19.6 mV
        self._send_command(unit, 4, millivolts)

    def get_error_offset(self, unit: int) -> Buffer:
        """The error signal input stage offset compensation in percent."""
        return self._get_pii_prop(unit, 256)

    ###################
    # Private Methods #
    ###################

    def _get_osc_prop(self, unit: Union[int, OscCard], service_id: int,
                      since: Time = None) -> Buffer:
        node_id = self._get_osc_node_id(unit)
        since = since if isinstance(since, float) else None
        return self._get_latest(self._buffers[node_id][service_id], since)

    def _get_pii_prop(self, unit_number: int, service_id: int,
                      since: Time = None) -> Buffer:
        since = since if isinstance(since, float) else None
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

    def _send_command(self, node: int, service: int,
                      value: Union[MenloUnit, str]) -> None:
        message = str(node) + ':0:' + str(service) + ':' + str(value)
        logger.log_quantity('menlo_request', message)
        asyncio.ensure_future(self._connection.send(message))

    def _store_reply(self, node: int, service: int, value: str) -> None:
        """
        :raises ValueError: Couldn't parse value as MenloUnit.
        """
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

            # Convert the MenloUnit-ish string to a MenloUnit
            val = None  # type: MenloUnit
            try:
                val = int(value)
            except ValueError:
                try:
                    val = float(value)
                except ValueError:
                    raise ValueError("Couldn't convert {} to either int or float.".format(value))
            self._rotate_log(self._buffers[node][service], val)

            # Log untouched data to disk.
            if LOG_QUANTITIES:
                try:
                    logger.log_quantity(
                        "menlo_{}_{}_{}".format(node, service,
                                                self._name_service(node, service)),
                        float(val))
                except ValueError:  # Don't use the name, as it's weird.
                    logger.log_quantity("menlo_{}_{}".format(node, service),
                                        float(val))
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
        """**Coroutine**! Ask all cards for info they don't regularly send."""
        for node in OSC_NODES + PII_NODES:
            self._send_command(node, 255, '0')

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
            since = None
        if buffer:
            if not since:  # Get single latest data point.

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
    def _to_ntc_resistance(counts: int, is_setpoint: bool) -> float:
        """Convert ADC/DAC counts into NTC thermistor resistance.

        This may be used for reading out the actual object temperature as well
        as reading the current temperature setpoint value.

        :param counts: Reading, as received digitally from DAC or ADC
        :param is_setpoint: The reading does originate from the temp. setpoint
                    combined DAC chip and not from the actual object temp. ADC.
        :returns: Resistance of the NTC thermistor in Ohms.
        """
        volts = float(counts) / TEC_ADC_FACTOR
        if is_setpoint:
            volts = float(counts) / TEC_DAC_FACTOR

        return ati_tec.tempsp_to_ohms(volts)

    @staticmethod
    def _to_dac_counts(ohms: float) -> int:
        """Convert NTC thermistor resistance to DAC counts.

        This is used for setting the temperature setpoint.

        :param ohms: Resistance of NTC thermistor in Ohms.
        :returns: numeric value to send to DAC.
        :raises: ValueError -- Illegal resistance was passed.
        """
        volts = ati_tec.ohms_to_tempsp(float(ohms))
        counts = int(round(TEC_DAC_FACTOR * volts))
        if counts < 0 or counts > 2**16 - 4:
            raise ValueError("NTC resistance out of DAC range.")
        return counts

    def _to_temperature(self, counts: int, is_setpoint: bool = False) -> float:
        """Take a menlo DAC reading and convert it to ° Celsius.
        """
        ohms = self._to_ntc_resistance(counts, is_setpoint)
        return self._standard_ntc.to_temp(ohms)

    @staticmethod
    def _get_osc_node_id(unit: Union[int, OscCard]) -> int:
        """The CAN bus node id of the given oscillator supply unit.

        :param unit: Can either be a physical `OscCard`, or a card index (1-4).
                    Card indices are accepted for backwards compatibility
                    reasons; see also `OSC_CARD_IDX`.
        :raises ValueError: Couldn't parse passed unit.
        """
        try:
            return _OSC_CARD_IDX[unit]
        except (TypeError, KeyError) as err:
            raise ValueError("No such OSC node.") from err

    @staticmethod
    def _is_pii_unit(unit_number: int) -> bool:
        if unit_number in PII_NODES:
            return True
        LOGGER.error("There is no PII unit %s", unit_number)
        return False
