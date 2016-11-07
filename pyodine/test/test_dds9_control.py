import os
import pytest
import serial
from pyodine.drivers.dds9_control import Dds9Control

wrong_port = '/dev/tty0'    # port must not be accessible (ConnectionError)
dead_port = '/dev/ttyUSB3'  # must be accessible, but no device is connected
live_port = '/dev/ttyUSB0'  # DDS9m must be connected to that port


# Most tests can only be performed when there is a live DDS9m device available.
# We create a marker here to skip those tests automatically if there is no
# device connected.
is_dds9_connected = True   # For now, just manually hard-code this value!
needs_live_device = pytest.mark.skipif(
        not is_dds9_connected, reason="No actual DDS9 is plugged in.")


@pytest.fixture  # Only open connection once for multiple tests.
def dds9():
    """Provides the serial connection to the actual DDS9 device."""
    return Dds9Control(live_port)


def test__parse_query_result_on_valid_string():
    valid_input = 4*'59682F00 0000 029C 0000 00000000 00000000 000301\r\n'
    settings_object = Dds9Control._parse_query_result(valid_input)
    assert settings_object.validate() is True
    assert settings_object.is_zero() is False


def test__parse_query_result_on_invalid_string():
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


@pytest.mark.skipif(not os.path.exists(dead_port),
                    reason="Inaccessible port specified.")
def test_connect_to_dead_device():
    """The port can be opened, but DDS9 doesn't respond."""
    with pytest.raises(ConnectionError):
        device = Dds9Control(dead_port)
        assert device.ping() is False


@needs_live_device
def test_check_device_sanity(dds9: Dds9Control):
    """Connection to device is established and device is in non-zero state."""
    assert dds9.ping() is True


@needs_live_device
def test_recognize_illegal_command(dds9: Dds9Control):
    response = dds9._send_command('python')

    # Check if this gives us the "bad phase" error, as "p" actually starts a
    # set phase command.
    print(response)
    assert response.find('?4') > 0


@needs_live_device
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


@needs_live_device
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


@needs_live_device
def test_set_frequency(dds9: Dds9Control):
    """Device accepts and saves frequency settings."""
    dds9.reset()
    dds9.set_frequency(123)
    dds9.set_frequency(0.007, 1)
    dds9.set_frequency(1000, 2)  # will be capped to 171 MHz!
    expected = [123, 7e-3, 171, 123]
    actual = dds9.get_frequencies()
    print(expected)
    print(actual)
    diff = [expected[i] - actual[i] for i in range(4)]

    # Internally, the chip works with 0.1Hz steps:
    assert max(diff) < 1e-8


@needs_live_device
def test_pause_resume(dds9: Dds9Control):
    dds9.reset()
    assert dds9.ping() is True
    dds9.set_amplitude(1)
    assert dds9.get_amplitudes() == 4*[1]
    dds9.pause()
    assert dds9.get_amplitudes() == 4*[0]
    dds9.set_amplitude(.5)
    assert max([abs(dds9.get_amplitudes()[i] - .5) for i in range(4)]) < .01
    dds9.resume()
    assert dds9.get_amplitudes() == 4*[1]


@needs_live_device
def test_switch_reference_source(dds9: Dds9Control):
    dds9.switch_to_external_frequency_reference()
    dds9.switch_to_internal_frequency_reference()


@needs_live_device
def test_set_frequency_on_external_clock(dds9: Dds9Control):
    """Device accepts and saves frequency settings."""
    dds9.reset()
    dds9.switch_to_external_frequency_reference()
    dds9.set_frequency(123)
    dds9.set_frequency(0.007, 1)
    dds9.set_frequency(1000, 2)  # will be capped!
    cap_frequency = dds9._settings['max_freq_value'] / dds9._clock_mult

    # The last channel is supposed to have the same frequency as the first one,
    # as the very first set_ command acts on all channels.
    expected = [123, 7e-3, cap_frequency, 123]

    actual = dds9.get_frequencies()
    print(dds9._clock_mult)
    print(expected)
    print(actual)
    diff = [expected[i] - actual[i] for i in range(4)]

    # Internally, the chip works with 0.1Hz steps:
    assert max(diff) < 1e-8
