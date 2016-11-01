import pytest
import serial
from pyodine.drivers.dds9_control import Dds9Control


def test_connect_to_dead_port():
    with pytest.raises(serial.SerialException):
        Dds9Control('/dev/tty0')


def test_parse_query_result_on_valid_string():
    valid_input = 4*'59682F00 0000 029C 0000 00000000 00000000 000301\r\n'
    settings_object = Dds9Control._parse_query_result(valid_input)
    assert settings_object.validate() is True
    assert settings_object.is_nonzero() is True


def test_parse_query_result_on_invalid_string():
    invalid_input = 4*'59682F00 0000 029C 0000 00000000 00000000\r\n'
    settings_object = Dds9Control._parse_query_result(invalid_input)
    assert settings_object.validate() is True
    assert settings_object.is_nonzero() is False
    invalid_input = 'qwerty'
    settings_object = Dds9Control._parse_query_result(invalid_input)
    assert settings_object.validate() is True
    assert settings_object.is_nonzero() is False
