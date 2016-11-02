import pytest
import serial
from pyodine.drivers.dds9_control import Dds9Control

wrong_port = '/dev/tty0'    # port must not be accessible (ConnectionError)
dead_port = '/dev/ttyUSB3'  # must be accessible, but no device is connected
live_port = '/dev/ttyUSB0'  # DDS9m must be connected to that port


@pytest.fixture  # Only open connection once for multiple tests.
def dds9():
    return Dds9Control(live_port)


def test_parse_query_result_on_valid_string():
    valid_input = 4*'59682F00 0000 029C 0000 00000000 00000000 000301\r\n'
    settings_object = Dds9Control._parse_query_result(valid_input)
    assert settings_object.validate() is True
    assert settings_object.is_zero() is False


def test_parse_query_result_on_invalid_string():
    invalid_input = 4*'59682F00 0000 029C 0000 00000000 00000000\r\n'
    settings_object = Dds9Control._parse_query_result(invalid_input)
    assert settings_object.validate() is True
    assert settings_object.is_zero() is True
    invalid_input = 'qwerty'
    settings_object = Dds9Control._parse_query_result(invalid_input)
    assert settings_object.validate() is True
    assert settings_object.is_zero() is True


def test_connect_to_dead_port():
    """Serial port is not accessible."""
    with pytest.raises(serial.SerialException):
        Dds9Control(wrong_port)


def test_connect_to_dead_device():
    """The port can be opened, but DDS9 doesn't respond."""
    with pytest.raises(ConnectionError):
        device = Dds9Control(dead_port)
        assert device.ping() is False


def test_check_device_sanity(dds9):
    """Connection to device is established and device is in non-zero state."""
    assert dds9.ping() is True


def test_set_phase(dds9: Dds9Control):
    """Device accepts and saves phase settings."""
    dds9.reset()
    dds9.set_phase(111)
    dds9.set_phase(99, 1)
    dds9.set_phase(0, 2)
    expected = [111, 99, 0, 111]
    actual = dds9.get_phases()
    diff = [expected[i] - actual[i] for i in range(4)]
    assert max(diff) < 1


def test_set_amplitudes(dds9: Dds9Control):
    """Device accepts and saves amplitude settings."""
    dds9.reset()
    dds9.set_amplitude(.777)  # set all channels
    dds9.set_amplitude(1, 1)  # reset some
    dds9.set_amplitude(0, 2)
    expected = [.777, 1, 0, .777]
    actual = dds9.get_amplitudes()
    diff = [expected[i] - actual[i] for i in range(4)]
    assert max(diff) < 0.01


def test_set_frequency(dds9):
    """Device accepts and saves frequency settings."""
    dds9.set_frequency(100)
    dds9.set_frequency(1000, 0)
    assert dds9.get_frequencies() == [1000, 100, 100, 100]
