import logging
import serial

logger = logging.getLogger('pyodine.drivers.dds9_control')


class Dds9Control:
    """A stateful controller for the DDS9m frequency generator."""

    def pause() -> None:
        pass

    def resume() -> None:
        pass

    def set_frequency(freq: float, channel: int=-1) -> None:
        pass

    def set_amplitude(ampl: float, channel: int=-1) -> None:
        pass

    # This is a class variable, instances must derive their own set of
    # settings from this, see below.
    _default_settings = {
            'baudrate': 19200,
            'timeout': 3,
            'port': '/dev/ttyUSB0'
            }

    _settings = None  # This instance's settings.
    _port = None  # OS-specific ID of serial port (e.g. /dev/tty.. or COM..)

    def __init__(self) -> None:
        """This is the class' constructor."""
        self._settings = self._default_settings
        self.open_connection()

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

        if port is None:
            port = self._settings['port']

        self._port = serial.Serial(port)
        self._port.baudrate = self._settings['baudrate']
        self._port.timeout = self._settings['timeout']
        logger.info("Opened serial port " + self._port.name)

    def _close_connection(self) -> None:
        self._port.close()
        logger.info("Closed serial port " + self._port.name)


class Dds9Setting:
    """A complete set of state variables to control DDS9.

    Those objects can be sent to and received from the device.
    """
    pass
