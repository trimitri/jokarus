import logging
import serial

logger = logging.getLogger('pyodine.drivers.dds9_control')


class Dds9Setting:
    """A complete set of state variables specific to DDS9.

    Those objects can be sent to and received from the device.
    """
    pass


class Dds9Control:
    """A stateful controller for the DDS9m frequency generator."""

    # This is a class variable; instances must derive their own set of
    # settings from this, see __init__ below.
    default_settings = {
            'baudrate': 19200,
            'timeout': 3,
            'port': '/dev/ttyUSB0'
            }

    def __init__(self):
        """This is the class' constructor."""

        # Store settings as an instance variable.
        self._settings = self.default_settings
        self._port = None  # OS-specific ID of serial port

        self._open_connection()
        self._state = self.get_state()
        if not self.ping():  # ensure proper device connection
            raise ConnectionError("Unexpected DDS9m behaviour.")
        logger.info("Connection to DDS9m established.")

    def __del__(self):
        """Close the serial connection"""
        self._close_connection()

    # public methods

    def get_state(self) -> Dds9Setting:
        """Queries the device for its internal state."""
        self._send_command('QUE')
        response = self._read_response()
        return self._parse_query_result(response)

    def pause(self) -> None:
        """Temporarily sets all outputs to zero voltage."""
        logger.warning('Method pause() not yet implemented.')

    def resume(self) -> None:
        """Resume frequence generation with previously used values."""
        logger.warning('Method resume() not yet implemented.')

    def set_frequency(self, freq: float, channel: int=-1) -> None:
        """Set frequency for one or all channels.

        If function is called without "channel", all channels are set.
        """
        logger.warning('Method set_frequency() not yet implemented.')

    def set_amplitude(self, ampl: float, channel: int=-1) -> None:
        """Set amplitude for one or all channels.

        If function is called without "channel", all channels are set.
        """
        logger.warning('Method set_amplitude() not yet implemented.')

    def set_phase(self, phase: float, channel: int=-1) -> None:
        """Set phase for one or all channels.

        If function is called without "channel", all channels are set.
        """
        logger.warning('Method set_phase() not yet implemented.')

    def ping(self) -> bool:
        is_consistent = self._state != self.get_state()
        if is_consistent:
            return True
        else:
            logger.error('DDS9 was not in expected state!')
            return False

    # private methods

    def _close_connection(self) -> None:
        self._port.close()
        logger.info("Closed serial port " + self._port.name)

    def _send_command(self, command: str='') -> None:
        """Prepare a command string and send it to the device."""

        # We need to prepend a newline to make sure DDS9 takes commands well.
        command_string = '\n' + command + '\n'

        # convert the query string to bytecode and send it through the port.
        self._port.write(command_string.encode())

    def _read_response(self) -> str:
        """Gets response from device through serial connection.

        Usually one would have to send a request first...
        """
        # recommended way of reading response, as of pySerial developer
        data = self._port.read(1)
        data += self._port.read(self._port.inWaiting())
        return data.decode()  # decode byte string to Unicode

    def _open_connection(self, port: str=None) -> None:
        """Opens the device connection for reading and writing."""

        port = port or self._settings['port']  # default argument value

        self._port = serial.Serial(port)
        self._port.baudrate = self._settings['baudrate']
        self._port.timeout = self._settings['timeout']
        logger.info("Opened serial port " + self._port.name)

    def _parse_query_result(self, result: str) -> Dds9Setting:
        lines = [l for l in result.splitlines() if len(l) in [22, 48]]
        print(lines)
