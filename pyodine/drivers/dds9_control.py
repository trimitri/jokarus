"""This module provides a Python interface to the DDS9m frequency generator.

It contains two classes of which Dds9Control is the main class, providing a
stateful controller for all basic capabilities of the DDS9m circuit board.
To set up a connection to a DDS9 locally connected via serial connection
"/dev/ttyFooBar" one could do as follows:

import drivers.dds9_control
dds = drivers.dds9_control.Dds9Control("/dev/ttyFooBar")

<do stuff with dds, e.g.:>
dds.set_frequency(150)  # sets freq. of all channels to 150MHz

del(dds)  # close connection, device keeps running
"""
import copy
import logging
import time
from typing import List
import serial  # serial port communication

__author__ = 'Franz Gutsch'

LOGGER = logging.getLogger('pyodine.drivers.dds9_control')


class Dds9Setting:
    """A bunch of internal state variables received from DDS9.

    This object consolidates most of the info that the device returns when
    asked for its internal state. As there is only one type of query command
    available for the DDS9 ("QUE"), this is the only way actual internal state
    variables will be saved.
    """
    def __init__(self,
                 frequencies: list, phases: list, amplitudes: list) -> None:
        """Fill new instance with data and call validate() on it."""
        self.freqs = frequencies
        self.phases = phases
        self.ampls = amplitudes
        if not self.validate():
            LOGGER.warning("Invalid settings object, defaulting to all-zero.")
            self.freqs, self.phases, self.ampls = [4*[0] for x in range(3)]

    def validate(self) -> bool:
        """Check for complete and proper instance variables.

        If this happens to detect an invalid state, the instance is reset to a
        recognizable and valid "zero state".
        """

        # All lists are exactly four elements long.
        if [len(i) for i in [self.freqs, self.phases, self.ampls]] == 3*[4]:

            # All lists contain only integers.
            if all(
                    all(isinstance(x, int) and x >= 0 for x in quantity)
                    for quantity in [self.freqs, self.phases, self.ampls]):
                return True
            LOGGER.debug("Settings constituents must be positive integers.")
        else:
            LOGGER.debug("Settings constituents must have four items each.")
        return False

    def is_zero(self) -> bool:
        """Check, if settings object represents an invalid device state."""
        is_zero = all([all([x == 0 for x in quantity]) for quantity in
                       (self.freqs, self.phases, self.ampls)])
        return is_zero


class SetupParameters:
    """A set of default parameters, can be changed in main class constructor.
    """

    # This is just an object for data storage, it exposes no methods.
    # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.baudrate = 19200   # as stated in the device manual
        self.timeout = 1        # If we have to wait, something went wrong.

        # DDS9's internal circtuitry imposes a cap on the saved frequency's
        # numeric value. This, however, does not have to match the actual
        # highest output frequency, especially when using an external reference
        # clock.  See manual for details.
        self.max_freq_value = 171.1
        self.port = '/dev/ttyUSB1'  # Can be reset by constructor.
        self.ext_clock = 400  # 100MHz native clock * 4 for K_p multiplier
        self.int_clock = 2**32 * 1e-7  # 430 MHz internal OCXO clock

        # We set the chip's reference clock multiplier to 4, to achieve 400MHz
        # reference clock in conjunction with the connected 100MHz external
        # clock.
        # This is a hex value of 04, shifted by a hex 80 to set an internal
        # gain bit. See manual for details.
        self.ext_clock_multiplier_setting = '84'


class Dds9Control:
    """A stateful controller for the DDS9m frequency generator.

    Caution: Setting this controller up on a running device may change some of
    its parameters. See __init__ constructor below for details.

    Raises a ConnectionError when no working connection to the device could be
    set up. In this case it would be advisable to del() the instance (in order
    to free the serial port) and then try again.
    """

    # instances must derive their own set of settings
    # from this, see __init__ below.

    def __init__(self, port: str = None) -> None:
        """Set the device connection up and set some basic device parameters.

        Depending on the device state, calling this constructor may actually
        change the running device's parameters. Most notably, the reference
        clock is set to the internal quartz and phases may re-align.

        Raises a ConnectionError when no working connection to the device could
        be set up. In this case it would be advisable to del() the instance and
        retry.
        """

        self._settings = SetupParameters()

        # Change port if it was given.
        if isinstance(port, str) and port:
            self._settings.port = port

        # Will be set by pause() in order to be able to resume with the same
        # amplitudes afterwards.
        self._paused_amplitudes = None  # type: List[float]

        # Which clock source is in use? This is unknown at start and impossible
        # to find out without setting it. Possible values are 'int' and 'ext'.
        self._ref_clock = ''

        # Set frequency multiplicators to use when reading and writing the
        # frequency registers of the microcontroller. The multiplicator to use
        # when on the internal clock source is just one. But when switching to
        # an external clock source, the internal clock divided  by external
        # clock has to be used.
        # Variable will be set by the switch_... commands.
        self._freq_scale_factor = None  # type: float

        self._state = None  # type: Dds9Setting

        # Initialize device.
        self._conn = None  # type: serial.Serial
        self._open_connection()  # Sets above variable.

        # Immediately execute any sent command, instead of waiting for an
        # explicit "Execute commands!" command.
        self._send_command('I a')

        # Send an "Execute commands!" command now, in case the setting above
        # wasn't set before.
        self._send_command('I p')

        # Use full scale output voltage, as opposed to other possible
        # settings (half, quarter, eighth).
        self._send_command('Vs 1')

        # Disable echoing of received commands to allow for faster operation.
        self._send_command('E d')

        # Re-align phase setting after each command. This way we are able to
        # set absolute phase offsets reliably.
        self._send_command('M a')

        # Save actual device state into class instance variable.
        self._update_state()

        # Unfortunately, I didn't find a way to get information about which
        # clock source is currently in use from the device. We thus need to set
        # a clock source to have that information.
        # The internal source is preferred for stability reasons. As far as
        # this driver is concerned, ext. clock source would work here just as
        # well.
        self.switch_to_ext_reference(adjust_frequencies=False)

        # Conduct a basic health test.

        if not self.ping():  # ensure proper device connection
            raise ConnectionError("Unexpected DDS9m behaviour.")
        LOGGER.info("Connection to DDS9m established.")

    def set_frequency(self, freq: float, channel: int = -1) -> None:
        """Set frequency in MHz for one or all channels.

        If the method is called without "channel", all channels are set.
        When running on external reference clock, this may only set the
        correct frequency values if the external clock frequency is set
        correctly; check by calling .get_settings()['ext_clock'].
        """
        def set_channel(channel, encoded_value):
            command_string = 'F' + str(channel) + ' ' + str(encoded_value)
            self._send_command(command_string)

        try:
            freq = float(freq)
        except (ValueError, TypeError):
            LOGGER.error("Could not parse given frequency. Resetting to 0 Hz.")
            freq = 0.0

        scaled_freq = freq * self._freq_scale_factor

        # The internal freq. generation chip only stores freq. values up to 171
        # MHz.
        max_value = self._settings.max_freq_value
        if scaled_freq > max_value:
            LOGGER.error("Capping requested frequency to %s MHz.",
                         max_value/self._freq_scale_factor)
            scaled_freq = max_value

        encoded_value = '{0:.7f}'.format(scaled_freq)

        if channel in range(4):
            set_channel(channel, encoded_value)
        else:
            for chan in range(4):
                set_channel(chan, encoded_value)
        self._update_state()

    @property
    def frequencies(self) -> List[float]:
        """Returns the frequency of each channel in MHz.

        When running on external reference clock, this may only yield the
        correct frequency values, if the external clock frequency is set
        correctly; check by calling .get_settings().
        """

        # The frequency is returned in units of 0.1Hz, but requested in MHz.
        return [f / self._freq_scale_factor * 1e-7 for f in self._state.freqs]

    def set_amplitude(self, ampl: float, channel: int = -1) -> None:
        """Set amplitude (float in [0, 1]) for one or all channels.

        If argument "channel" is omitted, all channels are set.
        """
        def set_channel(channel, encoded_value):
            command_string = 'V' + str(channel) + ' ' + str(encoded_value)
            self._send_command(command_string)

        encoded_value = int(float(ampl) * 1023)
        if encoded_value > 1023:
            LOGGER.warning("Amplitude capped to 1")
            encoded_value = 1023
        if encoded_value < 0:
            LOGGER.warning("Can't set amplitude < 0, resetting to 0.")
            encoded_value = 0

        if channel > 3:
            LOGGER.warning("set_amplitude: Only channels 0-3 may be specified."
                           " Setting all channels.")
        if channel in range(4):
            set_channel(channel, encoded_value)
        else:
            for chan in range(4):
                set_channel(chan, encoded_value)
        self._update_state()

    def get_amplitudes(self) -> List[float]:
        """Returns a list of relative amplitudes for all channels.

        The amplitudes are returned as a list of floats in [0,1].
        """
        return [a/1023. for a in self._state.ampls]

    def set_phase(self, phase: float, channel: int = -1) -> None:
        """Set phase in degrees <360 for one or all channels.

        If argument "channel" is omitted, all channels are set.
        """
        def set_channel(channel, encoded_value):
            command_string = 'P' + str(channel) + ' ' + str(encoded_value)
            self._send_command(command_string)

        # Note that the modulo automatically shifts any float into legal range.
        try:
            encoded_value = int(float(phase % 360) * 16383/360)
        except (ValueError, TypeError):
            LOGGER.error("Invalid phase value received. Setting phase to 0.")
            encoded_value = 0

        if channel > 3:
            LOGGER.warning("set_phase: Only channels 0-3 may be specified. "
                           "Setting all channels.")
        if channel in range(4):
            set_channel(channel, encoded_value)
        else:
            for chan in range(4):
                set_channel(chan, encoded_value)
        self._update_state()

    @property
    def phases(self) -> List[float]:
        return [p*360/16384 for p in self._state.phases]

    def get_settings(self) -> SetupParameters:
        """Returns a copy of the internal "_settings" object."""
        return copy.deepcopy(self._settings)

    def ping(self) -> bool:
        """Device is accessible and in non-zero state."""
        self._update_state()
        return not self._state.is_zero()

    def pause(self) -> None:
        """Temporarily sets all outputs to zero voltage."""
        self._paused_amplitudes = self.get_amplitudes()
        self.set_amplitude(0)

    def resume(self) -> None:
        """Resume frequency generation with previously used amplitudes."""
        if isinstance(self._paused_amplitudes, list):
            for channel in range(4):
                self.set_amplitude(self._paused_amplitudes[channel], channel)
        else:
            LOGGER.error("Can't resume as we didn't pause() before.")

    def switch_to_ext_reference(
            self, adjust_frequencies: bool = True) -> None:
        """Base generated frequencies on external clock source.

        As the internal frequency calculations will be changed by that, we need
        to adjust the internally set frequency values to keep the output
        frequency constant. For very high frequencies this may lead to capping,
        in which case the output frequencies will change.
        Set adjust_frequencies to False if you want to disable the adjustment
        altogether.
        """
        if self._ref_clock == 'int':
            LOGGER.info("Already set to use ext. clock reference. "
                        "Doing nothing.")
            return

        if adjust_frequencies:
            former_freqs = self.frequencies
        self._send_command(
            'Kp ' + self._settings.ext_clock_multiplier_setting)
        time.sleep(0.2)
        self._send_command('C E')
        self._freq_scale_factor = (
            self._settings.ext_clock / self._settings.int_clock)
        time.sleep(0.2)

        if adjust_frequencies:
            # Reset previous frequencies, taking the new clock multiplier
            # into account.
            for i in range(4):
                self.set_frequency(former_freqs[i], i)
        self._ref_clock = 'ext'

    def switch_to_int_reference(
            self, adjust_frequencies: bool = True) -> None:
        """Base generated frequencies on internal clock source.

        As the internal frequency calculations will be changed by that, we need
        to adjust the internally set frequency values to keep the output
        frequency constant. For very high frequencies this may lead to capping,
        in which case the output frequencies will change. Set
        adjust_frequencies to False if you want to disable that behaviour
        altogether.
        """
        if self._ref_clock == 'int':
            LOGGER.info("Already set to use int. clock reference. "
                        "Doing nothing.")
            return

        if adjust_frequencies:
            former_freqs = self.frequencies

        # Reset clock multiplier to default value (0f hex. == 15 decimal)
        self._send_command('Kp 0f')
        time.sleep(0.2)
        self._send_command('C I')
        self._freq_scale_factor = 1
        self._ref_clock = 'int'
        time.sleep(0.2)

        if adjust_frequencies:
            # Reset previous frequencies, taking the new clock multiplier
            # into account.
            for i in range(4):
                self.set_frequency(former_freqs[i], i)

    def save(self) -> None:
        """Save current device configuration to EEPROM.

        The new device state will then be the default state when powering up.
        Use this with caution, as it "consumes" EEPROM writes.
        """
        self._send_command('S')
        time.sleep(.5)

    def reset(self) -> None:
        """Reset DDS9 to state saved in ROM and switch to int. clock source.

        Except for the clock source constraint, this is equivalent to cycling
        power.  We need to set the clock source, as there is no way to find out
        if the device is in internal or external mode after a reset; and
        internal mode is always the safe bet.  If we didn't know the clock
        source, we also wouldn't know the clock multiplier and hence wouldn't
        be able to set or read correct frequency values.
        """
        self._send_command('R')

        # If we don't let DDS9 rest after a reset, it gives all garbled values.
        time.sleep(0.5)

        # See docstring above.
        self.switch_to_int_reference(adjust_frequencies=False)

        self._update_state()

    def reset_to_factory_default(self) -> None:
        """Deletes ALL device config and restores to factory default.

        Use this only when necessary, as it will write to EEPROM.
        """
        self._send_command('CLR')
        time.sleep(2)  # Allow some generous 2 secs to recover.

    # private methods

    def _update_state(self) -> None:
        """Queries the device for its internal state and updates _state."""
        response = self._send_command('QUE')
        state = self._parse_query_result(response)
        self._state = state
        if state.is_zero():
            LOGGER.warning("Device was in zero state.")

    def _send_command(self, command: str = '') -> str:
        """Prepare a command string and send it to the device."""

        def read_response() -> str:
            """Gets response from device through serial connection."""

            # recommended way of reading response, as of pySerial developer
            data = self._conn.read(1)
            data += self._conn.read(self._conn.inWaiting())
            self._conn.reset_output_buffer()

            # decode byte string to Unicode
            return data.decode(encoding='utf-8', errors='ignore')

        # We need to prepend a newline to make sure DDS9 takes commands well.
        command_string = '\n' + command + '\n'

        # convert the query string to bytecode and send it through the port.
        self._conn.write(command_string.encode())
        response = read_response()
        logging.debug("sent: " + command + ", got: ")
        logging.debug(response)
        return response

    def _open_connection(self) -> None:
        """Opens the device connection for reading and writing."""
        self._conn = serial.Serial(self._settings.port)
        self._conn.baudrate = self._settings.baudrate
        self._conn.timeout = self._settings.timeout
        LOGGER.info("Connected to serial port " + self._conn.name)

    @staticmethod  # Fcn. may be called without creating an instance first.
    def _parse_query_result(result: str) -> Dds9Setting:
        """Parse DDS9's answer on the "QUE" question.

        This will create a new Dds9Setting object and return it.
        """
        relevant_lines = [l for l in result.splitlines() if len(l) == 48]

        # Replace with dummy data if illegal string was passed.
        if len(relevant_lines) != 4:
            LOGGER.error("Too few valid lines in QUE response.")
            relevant_lines = ['0 0 0 0 0 0 0' for i in range(4)]
        channels = [l.split() for l in relevant_lines]

        # Data was grouped into channels before, now we sort by physical
        # quantity first and then by channel:
        params = list(zip(*channels))  # transpose
        frequencies = [int(f, 16) for f in params[0]]
        phases = [int(f, 16) for f in params[1]]
        amplitudes = [int(f, 16) for f in params[2]]
        return Dds9Setting(frequencies, phases, amplitudes)
