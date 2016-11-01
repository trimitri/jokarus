import pytest
import serial
from pyodine.drivers.dds9_control import Dds9Control

wrong_port = '/dev/tty0'  # port must not be used by python
dead_port = '/dev/ttyUSB3'  # port is accessible, but no device connected
live_port = '/dev/ttyUSB0'  # DDS9m must be connected to that port


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


def test_check_device_sanity():
    """Connection to device is established and device is in non-zero state."""
    device = Dds9Control(live_port)
    assert device.ping() is True


def test_check_device_memory():
    """Device stays in a state specified by user."""
    assert False
