"""The Subsystems class manages the connection to internal subsystems.

This is an interface to the actual things connected to each port of each
subsystem.
"""
import enum
import logging
import time
from typing import Dict, List, Tuple, Union
from ..drivers import menlo_stack
from .temperature_ramp import TemperatureRamp
# from ..drivers import mccdaq
from ..drivers.dds9_control import Dds9Control

LOGGER = logging.getLogger("pyodine.controller.subsystems")
LOGGER.setLevel(logging.DEBUG)

OSC_UNITS = {'mo': 1, 'pa': 2, 'shga': 3, 'shgb': 4}
PII_UNITS = {'nu': 1}

# Define some custom types.
# pylint: disable=invalid-name
MenloUnit = Union[float, int]

# Measurement (time, reading)
DataPoint = Tuple[float, MenloUnit]  # pylint: disable=unsubscriptable-object
Buffer = List[DataPoint]
# pylint: enable=invalid-name

class DdsChannel(enum.IntEnum):  # noqa: E302
    """The four channels of the DDS device."""
    AOM = 0
    EOM = 2
    MIXER = 1
    FREE = 3  # not in use


class Subsystems:
    """Provides a wrapper for all connected subsystems.
    Don't access the subsystems directly."""

    def __init__(self) -> None:
        self._menlo = None  # type: menlo_stack.MenloStack
        self._temp_ramps = dict()  # type: Dict[int, TemperatureRamp]
        self._init_temp_ramps()
        self._dds = Dds9Control('/dev/ttyUSB1', allow_unconnected=True)
        # self._daq = None

    async def init_async(self) -> None:
        """Needs to be awaited after initialization.

        It makes sure that all subsystems are ready."""
        await self.reset_menlo()

    async def reset_menlo(self) -> None:
        """Reset the connection to the Menlo subsystem."""
        if self._menlo is menlo_stack.MenloStack:
            del self._menlo

        self._menlo = menlo_stack.MenloStack()
        await self._menlo.init_async()

    async def refresh_status(self) -> None:
        await self._menlo.request_full_status()

    def get_full_set_of_readings(self,
                                 since: float = None) -> Dict[str, Buffer]:
        """Return a dict of all readings, ready to be sent to the client."""
        data = {}  # type: Dict[str, Buffer]

        # ADC readings
        for channel in range(8):
            data['adc' + str(channel)] = self._menlo.get_adc_voltage(channel,
                                                                     since)

        # TEC controller temperature readings
        for unit in [1, 2, 3, 4]:
            data['temp'+str(unit)] = self._menlo.get_temperature(unit, since)

        # Oscillator Supplies
        osc_roles = [('mo', 1, True), ('pa', 2, True),
                     ('shga', 3, False), ('shgb', 4, False)]
        for (name, unit, has_current_driver) in osc_roles:
            if has_current_driver:
                data[name + '_enabled'] = \
                    self._menlo.is_current_driver_enabled(unit)
                data[name + '_current'] = \
                    self._menlo.get_diode_current(unit, since)
                data[name + '_current_set'] = \
                    self._menlo.get_diode_current_setpoint(unit)
            data[name + '_tec_enabled'] = self._menlo.is_tec_enabled(unit)
            data[name + '_temp'] = self._menlo.get_temperature(unit, since)
            data[name + '_temp_raw_set'] = self._menlo.get_temp_setpoint(unit)
            data[name + '_temp_set'] = self._wrap_into_buffer(
                self._temp_ramps[unit].target_temperature)
            data[name + '_temp_ramp_active'] = self._wrap_into_buffer(
                self._temp_ramps[unit].is_running)
            data[name + '_temp_ok'] = self._menlo.is_temp_ok(unit)
            data[name + '_tec_current'] = self._menlo.get_tec_current(unit,
                                                                      since)
        # PII Controllers
        data['nu_lock_enabled'] = self._menlo.is_lock_enabled(1)
        data['nu_i1_enabled'] = self._menlo.is_integrator_enabled(1, 1)
        data['nu_i2_enabled'] = self._menlo.is_integrator_enabled(1, 2)
        data['nu_ramp_enabled'] = self._menlo.is_ramp_enabled(1)
        data['nu_prop'] = self._menlo.get_pii_prop_factor(1)
        data['nu_offset'] = self._menlo.get_pii_offset(1)
        data['nu_p_monitor'] = self._menlo.get_pii_monitor(1, p_only=True,
                                                           since=since)
        data['nu_monitor'] = self._menlo.get_pii_monitor(1, since=since)
        data['nu_ramp_amplitude'] = self._menlo.get_ramp_amplitude(1)
        return data

    def get_setup_parameters(self) -> Dict[str, Buffer]:
        """Return a dict of all setup parameters.

        These are the ones that don't usually change."""
        data = {}  # type: Dict[str, Buffer]
        freqs = self._dds.frequencies
        amplitudes = self._dds.amplitudes
        data['eom_freq'] = self._wrap_into_buffer(freqs[DdsChannel.EOM])
        data['aom_freq'] = self._wrap_into_buffer(freqs[DdsChannel.AOM])
        data['aom_amplitude'] = self._wrap_into_buffer(
            amplitudes[DdsChannel.AOM])
        data['eom_amplitude'] = self._wrap_into_buffer(
            amplitudes[DdsChannel.EOM])
        data['mixer_amplitude'] = self._wrap_into_buffer(
            amplitudes[DdsChannel.MIXER])
        data['mixer_phase'] = self._wrap_into_buffer(
            self._dds.phases[DdsChannel.MIXER])

        # Clock source may be unknown (None).
        if isinstance(self._dds.runs_on_ext_clock_source, bool):
            data['rf_use_external_clock'] = self._wrap_into_buffer(
                self._dds.runs_on_ext_clock_source)
        return data

    def set_current(self, unit_name: str, milliamps: float) -> None:
        """Set diode current setpoint of given unit."""
        LOGGER.debug("Setting diode current of unit %s to %s mA",
                     unit_name, milliamps)
        if (unit_name in OSC_UNITS
                and isinstance(milliamps, float)
                and milliamps >= 0):
            self._menlo.set_current(OSC_UNITS[unit_name], milliamps)
        else:
            LOGGER.error("Illegal setting for diode current.")

    def set_temp(self, unit_name, celsius: float,
                 bypass_ramp: bool = False) -> None:
        """Set the target temp. for the temperature ramp."""
        if isinstance(celsius, float):
            if bypass_ramp:
                LOGGER.debug("Setting TEC temp. of unit %s to %s°C directly.",
                             unit_name, celsius)
                self._menlo.set_temp(OSC_UNITS[unit_name], celsius)
            else:
                LOGGER.debug("Setting ramp target temp. of unit %s to %s°C",
                             unit_name, celsius)
                ramp = self._temp_ramps[OSC_UNITS[unit_name]]
                ramp.target_temperature = celsius
        else:
            LOGGER.error("Illegal setting for temperature setpoint.")

    def set_ramp_amplitude(self, unit_name: str, millivolts: int) -> None:
        """Set the amplitude of the Menlo-generated ramp. (deprecated!)"""
        # TODO Remove this as ramp is not actually implemented in hardware.
        if not isinstance(millivolts, int):
            LOGGER.error("Please give ramp amplitude in millivolts (int).")
            return
        if not self._is_pii_unit(unit_name):
            return
        self._menlo.set_ramp_amplitude(PII_UNITS[unit_name], millivolts)

    def set_mixer_phase(self, degrees: float) -> None:
        """Set the phase offset between EOM and mixer drivers in degrees."""
        if not isinstance(degrees, (float, int)):
            LOGGER.error("Provide a mixer phase in degrees (%s given).",
                         degrees)
            return
        LOGGER.debug("Setting mixer phase to %s°", degrees)

        # To set the phase difference, we need to set phases of both channels.
        self._dds.set_phase(0, int(DdsChannel.EOM))
        self._dds.set_phase(degrees, int(DdsChannel.MIXER))

    def set_aom_frequency(self, freq: float) -> None:
        """Set the acousto-optic modulator driver frequency in MHz."""
        if not isinstance(freq, (float, int)) or not freq > 0:
            LOGGER.error("Provide valid frequency (float) for AOM.")
            return
        LOGGER.debug("Setting AOM frequency to %s MHz.", freq)
        self._dds.set_frequency(freq, int(DdsChannel.AOM))

    def set_eom_frequency(self, freq: float) -> None:
        """Set the EOM and mixer frequency in MHz."""
        if not isinstance(freq, (float, int)) or not freq > 0:
            LOGGER.error("Provide valid frequency (float) for EOM.")
            return
        LOGGER.debug("Setting EOM frequency to %s MHz.", freq)
        self._dds.set_frequency(freq, int(DdsChannel.EOM))
        self._dds.set_frequency(freq, int(DdsChannel.MIXER))

    def set_aom_amplitude(self, amplitude: float) -> None:
        """Set the acousto-optic modulator driver amplitude betw. 0 and 1."""
        if not isinstance(amplitude, (float, int)) or amplitude < 0:
            LOGGER.error("Provide valid amplitude for AOM.")
            return
        LOGGER.debug("Setting AOM amplitude to %s %%.", amplitude * 100)
        self._dds.set_amplitude(amplitude, int(DdsChannel.AOM))

    def set_eom_amplitude(self, amplitude: float) -> None:
        """Set the electro-optic modulator driver amplitude betw. 0 and 1."""
        if not isinstance(amplitude, (float, int)) or amplitude < 0:
            LOGGER.error("Provide valid amplitude for EOM.")
            return
        LOGGER.debug("Setting EOM amplitude to %s %%.", amplitude * 100)
        self._dds.set_amplitude(amplitude, int(DdsChannel.EOM))

    def set_mixer_amplitude(self, amplitude: float) -> None:
        """Set the mixer driver amplitude betw. 0 and 1."""
        if not isinstance(amplitude, (float, int)) or amplitude < 0:
            LOGGER.error("Provide valid amplitude for mixer.")
            return
        LOGGER.debug("Setting mixer amplitude to %s %%.", amplitude * 100)
        self._dds.set_amplitude(amplitude, int(DdsChannel.MIXER))

    def switch_rf_clock_source(self, which: str) -> None:
        """Pass "external" or "internal" to switch RF clock source."""
        if which not in ['external', 'internal']:
            LOGGER.error('Can only switch to "external" or "internal" '
                         'reference, "%s" given.', which)
            return
        if which == 'external':
            self._dds.switch_to_ext_reference()
        else:  # str == 'internal'
            self._dds.switch_to_int_reference()

    def switch_temp_ramp(self, unit_name: str, enable: bool) -> None:
        """Start or halt ramping the temperature setpoint."""
        if self._is_osc_unit(unit_name):
            ramp = self._temp_ramps[OSC_UNITS[unit_name]]
            if enable:
                ramp.start_ramp()
            else:
                ramp.pause_ramp()

    def switch_tec(self, unit_name: str, switch_on: bool) -> None:
        if self._is_osc_unit(unit_name):
            if isinstance(switch_on, bool):
                self._menlo.switch_tec(OSC_UNITS[unit_name], switch_on)

    def switch_pii_ramp(self, unit_name: str, switch_on: bool) -> None:
        if self._is_pii_unit(unit_name):
            if isinstance(switch_on, bool):
                self._menlo.switch_ramp(PII_UNITS[unit_name], switch_on)
            else:
                LOGGER.error('Please provide boolean "on" argument when '
                             'switching pii ramp generation of unit %s.',
                             unit_name)

    def switch_ld(self, unit_name: str, switch_on: bool) -> None:
        if self._is_osc_unit(unit_name):
            if isinstance(switch_on, bool):
                self._menlo.switch_ld(OSC_UNITS[unit_name], switch_on)

    # Private Methods

    def _init_temp_ramps(self) -> None:
        """Initialize one TemperatureRamp instance for every TEC controller."""

        # TODO: Use functools.partials instead of default arguments to enforce
        # early binding.
        for name, unit in OSC_UNITS.items():
            def getter(u=unit) -> float:
                """Get the most recent temperature reading from MenloStack."""

                # We need to bind the loop variable "unit" to a local variable
                # here, e.g. using lambdas.
                temp_readings = self._menlo.get_temperature(u)
                if temp_readings:
                    return temp_readings[0][1]

                LOGGER.error("Couldn't determine temperature.")
                return float('nan')

            def setpt_getter(u=unit) -> float:
                """Gets the current TEC setpoint."""
                temp_setpts = self._menlo.get_temp_setpoint(u)
                if temp_setpts:
                    return temp_setpts[0][1]

                LOGGER.error("Couldn't determine temp. setpoint.")
                return float('nan')

            def setter(temp: float, u=unit) -> None:
                # Same here (see above).
                self._menlo.set_temp(u, temp)

            self._temp_ramps[unit] = TemperatureRamp(
                get_temp_callback=getter,
                get_temp_setpt_callback=setpt_getter,
                set_temp_callback=setter,
                name=name)

    @staticmethod
    def _wrap_into_buffer(value: Union[MenloUnit, bool]) -> Buffer:
        if isinstance(value, bool):
            return [(time.time(), 1 if value else 0)]  # bool is no MenloUnit

        if isinstance(value, float):
            return [(time.time(), float(value))]  # float(): make mypy happy

        if isinstance(value, int):
            return [(time.time(), int(value))]  # int(): make mypy happy

        if value is None:
            # Don't throw an error here, as None might just be an indication
            # that there isn't any data available yet.
            return []

        LOGGER.error("Type %s is not convertible into a MenloUnit.",
                     type(value))
        return []

    @staticmethod
    def _is_osc_unit(name: str) -> bool:
        if name not in OSC_UNITS:
            LOGGER.error('There is no oscillator supply unit "%s".', name)
            return False
        return True

    @staticmethod
    def _is_pii_unit(name: str) -> bool:
        if name not in PII_UNITS:
            LOGGER.error('There is no Lockbox "%s".', name)
            return False
        return True
