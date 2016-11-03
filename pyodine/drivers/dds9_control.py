import logging  # DEBUG, INFO, WARN, ERROR etc.
import pytest  # simple unit testing
import serial  # serial port communication
import time  # sometimes we need to wait for the device

logger = logging.getLogger('pyodine.drivers.dds9_control')


class Dds9Setting:
    """A complete set of state variables specific to DDS9.

    Those objects can be sent to and received from the device.
    """
    def __init__(self,
                 frequencies: list, phases: list, amplitudes: list) -> None:
        self.freqs = frequencies
        self.phases = phases
        self.ampls = amplitudes
        if not self.validate():
            logger.warning("Invalid settings object, defaulting to all-zero.")
            self.freqs, self.phases, self.ampls = [4*[0] for x in range(3)]

    def validate(self) -> bool:
        """Makes sure that instance has proper format and resets it if not."""

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
        """Check, if settings object represents a non-trivial device state."""
        is_zero = all([all([x == 0 for x in quantity]) for quantity in
                       (self.freqs, self.phases, self.ampls)])
        return is_zero


class Dds9Control:
    """A stateful controller for the DDS9m frequency generator."""

    # This is a class variable; instances must derive their own set of
    # settings from this, see __init__ below.
    default_settings = {
            'baudrate': 19200,
            'timeout': 1,
            'port': '/dev/ttyUSB0'
            }

    def __init__(self, port: str=None):
        """This is the class' constructor."""

        # Set up instance variables.

        self._settings = self.default_settings

        # Overwrite default port setting if port is given by caller.
        if type(port) is str and len(port) > 0:
            self._settings['port'] = port

        self._port = None  # Connection has not been opened yet.
        self._paused_amplitudes = None  # Will be set by pause().

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

        # Save actual device state into class instance variable.
        self._state = self._update_state()

        # Conduct a basic health test.

        if not self.ping():  # ensure proper device connection
            raise ConnectionError("Unexpected DDS9m behaviour.")
        logger.info("Connection to DDS9m established.")

    # public methods

    def set_frequency(self, freq: float, channel: int=-1) -> None:
        """Set frequency in MHz for one or all channels.

        If function is called without "channel", all channels are set.
        """
        def set_channel(channel, encoded_value):
            command_string = 'F' + str(channel) + ' ' + str(encoded_value)
            self._send_command(command_string)

        try:
            freq = float(freq)
        except (ValueError, TypeError):
            logger.error("Could not parse given frequency. Resetting to 0 Hz.")
            freq = 0.0
        if freq > 171:
            logger.warning("Capping requested frequency to 171 MHz.")
            freq = 171.0

        encoded_value = '{0:.7f}'.format(freq)

        if channel in range(4):
            set_channel(channel, encoded_value)
        else:
            for channel in range(4):
                set_channel(channel, encoded_value)
        self._update_state()

    def get_frequencies(self) -> list:
        """Returns the frequency of each channel in MHz."""

        # The frequency is returned in units of 0.1Hz, but requested in MHz.
        return [1e-7 * f for f in self._state.freqs]

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

    def reset(self) -> None:
        """Reset DDS9 to state saved in ROM. Equivalent to cycling power."""
        self._send_command('R')

        # If we don't let DDS9 rest after a reset, it gives all garbled values.
        time.sleep(0.5)

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
