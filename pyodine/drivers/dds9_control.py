import logging  # DEBUG, INFO, WARN, ERROR etc.
import pytest  # simple unit testing
import serial  # serial port communication
import time  # sometimes we need to wait for the device

logger = logging.getLogger('pyodine.drivers.dds9_control')


class Dds9Setting:
    """A bunch of state variables received from DDS9.

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
            logger.warning("Invalid settings object, defaulting to all-zero.")
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
                    all(type(x) is int and x >= 0 for x in quantity)
                    for quantity in [self.freqs, self.phases, self.ampls]):
                return True
            logger.debug("Settings constituents must be positive integers.")
        else:
            logger.debug("Settings constituents must have four items each.")
        return False

    def is_zero(self) -> bool:
        """Check, if settings object represents an invalid device state."""
        is_zero = all([all([x == 0 for x in quantity]) for quantity in
                       (self.freqs, self.phases, self.ampls)])
        return is_zero


class Dds9Control:
    """A stateful controller for the DDS9m frequency generator."""

    # This is a class variable; instances must derive their own set of settings
    # from this, see __init__ below.
    default_settings = {
        'baudrate': 19200,  # as stated in the device manual for default value
        'timeout': 1,       # If we have to wait, something went wrong.

        # DDS9's internal circtuitry imposes a cap on the saved frequency's
        # numeric value. This, however, does not have to match the actual
        # highest output frequency, especially when using an external reference
        # clock.  See manual for details.
        'max_freq_value': 171.1,
        'port': '/dev/ttyUSB0',  # Hard-code this to your needs.
        'ext_clock': 400  # 100MHz actual clock * 4 for K_p multiplier chip
        }

    def __init__(self, port: str=None):
        """Set the device connection up and set some basic device parameters.

        Depending on the device state, calling this constructor may actually
        change the running device's parameters. Most notably, the reference
        clock is set to the internal quartz and phases may re-align.
        """

        # Set up instance variables.

        self._settings = self.default_settings

        # Overwrite default port setting if port is given by caller.
        if type(port) is str and len(port) > 0:
            self._settings['port'] = port

        self._port = None  # Connection has not been opened yet.
        self._paused_amplitudes = None  # Will be set by pause().

        # Set frequency multiplicators to use when reading and writing the
        # frequency registers of the microcontroller. The multiplicator to use
        # when on the internal clock source is just one. But when switching to
        # an external clock source, the rate of internal div. by external clock
        # needs to be used.
        self._clock_mult = None  # will be set the switch_... commands.
        self._clock_mult_int = 1
        self._clock_mult_ext = 2**32 * 1e-7 / self._settings['ext_clock']

        # Initialize device.

        self._open_connection()

        # Immediately execute any sent command, instead of waiting for an
        # explicit "Execute commands!" command.
        self._send_command('I a')

        # Send an "Execute commands!" command, in case the setting above wasn't
        # set before.
        self._send_command('I p')

        # Use full scale output voltage, as opposed to other possible
        # settings (half, quarter, eighth).
        self._send_command('Vs 1')

        # Disable echoing of received commands to allow for faster operation.
        self._send_command('E d')

        # Re-align phase setting after each command. This way we are able to
        # set absolute phase offsets reliably.
        self._send_command('M a')

        self.switch_to_internal_frequency_reference()

        # Save actual device state into class instance variable.
        self._state = self._update_state()

        # Conduct a basic health test.

        if not self.ping():  # ensure proper device connection
            raise ConnectionError("Unexpected DDS9m behaviour.")
        logger.info("Connection to DDS9m established.")

    # public methods

    def set_frequency(self, freq: float, channel: int=-1) -> None:
        """Set frequency in MHz for one or all channels.

        If the method is called without "channel", all channels are set.
        """
        def set_channel(channel, encoded_value):
            command_string = 'F' + str(channel) + ' ' + str(encoded_value)
            self._send_command(command_string)

        try:
            freq = float(freq)
        except (ValueError, TypeError):
            logger.error("Could not parse given frequency. Resetting to 0 Hz.")
            freq = 0.0

        scaled_freq = freq * self._clock_mult

        # The internal freq. generation chip only stores freq. values up to 171
        # MHz.
        max_value = self._settings['max_freq_value']
        if scaled_freq > max_value:
            logger.warning("Capping requested frequency to {}"
                           "MHz.".format(max_value/self._clock_mult))
            scaled_freq = max_value

        encoded_value = '{0:.7f}'.format(scaled_freq)

        if channel in range(4):
            set_channel(channel, encoded_value)
        else:
            for channel in range(4):
                set_channel(channel, encoded_value)
        self._update_state()

    def get_frequencies(self) -> list:
        """Returns the frequency of each channel in MHz.

        When running on external reference clock, this may only yield the
        correct frequency values, if the external clock frequency is set
        correctly; check by calling .get_settings().
        """

        # The frequency is returned in units of 0.1Hz, but requested in MHz.
        return [f / self._clock_mult * 1e-7 for f in self._state.freqs]

    def set_amplitude(self, ampl: float, channel: int=-1) -> None:
        """Set amplitude (float in [0, 1]) for one or all channels.

        If function is called without "channel", all channels are set.
        """
        def set_channel(channel, encoded_value):
            command_string = 'V' + str(channel) + ' ' + str(encoded_value)
            self._send_command(command_string)

        encoded_value = int(float(ampl) * 1023)
        if encoded_value > 1023:
            encoded_value = 1023
        if encoded_value < 0:
            encoded_value = 0
        if channel in range(4):
            set_channel(channel, encoded_value)
        else:
            for channel in range(4):
                set_channel(channel, encoded_value)
        self._update_state()

    def get_amplitudes(self) -> list:
        """Returns a list of relative amplitudes for all channels.

        The amplitudes are returned as a list of floats in [0,1].
        """
        return [a/1023. for a in self._state.ampls]

    def set_phase(self, phase: float, channel: int=-1) -> None:
        """Set phase in degrees <360 for one or all channels.

        If function is called without "channel", all channels are set.
        """
        def set_channel(channel, encoded_value):
            command_string = 'P' + str(channel) + ' ' + str(encoded_value)
            self._send_command(command_string)

        # Note that the modulo automatically shifts any float into legal range.
        encoded_value = int(float(phase % 360) * 16383/360)

        if channel > 3:
            logger.warning("set_phase: Only channels 0-3 may be specified. "
                           "Setting all channels.")

        if channel in range(4):
            set_channel(channel, encoded_value)
        else:
            for channel in range(4):
                set_channel(channel, encoded_value)
        self._update_state()

    def get_phases(self) -> list:
        return [p*360/16384 for p in self._state.phases]

    def get_settings(self) -> dict:
        """Returns a copy of the internal "_settings" object."""
        return self._settings.copy()  # Don't let the user change our settings.

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
        if type(self._paused_amplitudes) is list:
            for channel in range(4):
                self.set_amplitude(self._paused_amplitudes[channel], channel)
        else:
            logger.error("Can't resume as there is no saved state.")

    def switch_to_external_frequency_reference(self) -> None:
        self._send_command('Kp 84')
        time.sleep(0.2)
        self._send_command('C E')
        self._clock_mult = self._clock_mult_ext
        time.sleep(0.2)

    def switch_to_internal_frequency_reference(self) -> None:
        self._send_command('Kp 0f')  # Reset clock multiplier to default (15)
        time.sleep(0.2)
        self._send_command('C I')
        self._clock_mult = self._clock_mult_int
        time.sleep(0.2)

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
        power.
        We need to set the clock source, as there is no way to find out if the
        device is in internal or external mode after a reset; and internal mode
        is always the safe bet.  If we didn't know the clock source, we also
        wouldn't now the clock multiplier and hence wouldn't be able to set or
        read correct frequency values.
        """
        self._send_command('R')

        # If we don't let DDS9 rest after a reset, it gives all garbled values.
        time.sleep(0.5)
        self.switch_to_internal_frequency_reference()  # See docstring above.

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
            logger.warning("Device was in zero state.")

    def _send_command(self, command: str='') -> str:
        """Prepare a command string and send it to the device."""

        def read_response() -> str:
            """Gets response from device through serial connection."""
            # recommended way of reading response, as of pySerial developer
            data = self._port.read(1)
            data += self._port.read(self._port.inWaiting())
            self._port.reset_output_buffer()

            # decode byte string to Unicode
            return data.decode(encoding='utf-8', errors='ignore')

        # We need to prepend a newline to make sure DDS9 takes commands well.
        command_string = '\n' + command + '\n'

        # convert the query string to bytecode and send it through the port.
        self._port.write(command_string.encode())
        response = read_response()
        logging.debug("sent: " + command + ", got: ")
        logging.debug(response)
        return response

    def _open_connection(self, port: str=None) -> None:
        """Opens the device connection for reading and writing."""

        port = port or self._settings['port']  # default argument value

        self._port = serial.Serial(port)
        self._port.baudrate = self._settings['baudrate']
        self._port.timeout = self._settings['timeout']
        logger.info("Connected to serial port " + self._port.name)

    @staticmethod  # Fcn. may be called without creating an instance first.
    def _parse_query_result(result: str) -> Dds9Setting:
        """Parse DDS9's answer on the "QUE" question.

        This will create a new Dds9Setting object and return it.
        """
        relevant_lines = [l for l in result.splitlines() if len(l) == 48]

        # Replace with dummy data if illegal string was passed.
        if len(relevant_lines) != 4:
            logger.error("Too few valid lines in QUE response.")
            relevant_lines = ['0 0 0 0 0 0 0' for i in range(4)]
        channels = [l.split() for l in relevant_lines]

        # Data was grouped into channels before, now we sort by physical
        # quantity first and then by channel:
        params = list(zip(*channels))  # transpose
        frequencies = [int(f, 16) for f in params[0]]
        phases = [int(f, 16) for f in params[1]]
        amplitudes = [int(f, 16) for f in params[2]]
        return Dds9Setting(frequencies, phases, amplitudes)

"""In the production enviroment, this module is not supposed to be run. Instead
it will always just be imported.  However, if the module is run nevertheless,
it will act as a test suite testing itself: """
if __name__ == '__main__':
    pytest.main(args=['-x', '..'])  # Run Pytest test suite on pyodine dir.
