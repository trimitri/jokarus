"""The Subsystems class manages the connection to internal subsystems.

This is an interface to the actual things connected to each port of each
subsystem.

SAFETY POLICY: This class silently assumes all passed arguments to be of
correct type. The values are allowed to be wrong, though.
"""
import asyncio
import enum
from functools import partial
import logging
import time
from typing import Dict, List, Tuple, Union
from .temperature_ramp import TemperatureRamp
from ..drivers import ecdl_mopa, dds9_control, menlo_stack, mccdaq
from ..util import io_tools

LOGGER = logging.getLogger("pyodine.controller.subsystems")
LOGGER.setLevel(logging.DEBUG)

LD_DRIVERS = {'mo': 1, 'pa': 3}
TEC_CONTROLLERS = {'miob': 1, 'vhbg': 2, 'shga': 3, 'shgb': 4}

LOCKBOXES = {'nu': 2}
DDS_PORT = '/dev/ttyUSB2'

# Define some custom types.
# pylint: disable=invalid-name
MenloUnit = Union[float, int]

# Measurement (time, reading)
DataPoint = Tuple[float, MenloUnit]  # pylint: disable=unsubscriptable-object
Buffer = List[DataPoint]
# pylint: enable=invalid-name


class DdsChannel(enum.IntEnum):
    """The four channels of the DDS device."""
    AOM = 1
    EOM = 0
    MIXER = 2
    FREE = 3  # not in use


class DaqChannel(enum.IntEnum):
    """The MCC USB1608G-2AO features 16 analog inputs."""
    ERR_SIGNAL = 7
    RAMP_MONITOR = 11


class SubsystemError(RuntimeError):
    """One of the subsystems experienced a critical problem. Reset is advised.
    """
    pass


class Subsystems:
    """Provides a wrapper for all connected subsystems.
    Don't access the subsystems directly."""

    def __init__(self) -> None:

        # Wait for Menlo to show up and initialize laser control as soon as
        # they arrive.
        self._menlo = None  # type: menlo_stack.MenloStack
        self._laser = None  # type: ecdl_mopa.EcdlMopa
        asyncio.ensure_future(
            io_tools.poll_resource(
                lambda: bool(self._menlo), 5, self.reset_menlo,
                self._init_laser, name="Menlo"))

        # Initialize the DDS connection and monitor it for connection problems.
        # We keep the poller alive to monitor the RS232 connection which got
        # stuck sometimes during testing.
        self._dds = None  # type: dds9_control.Dds9Control
        asyncio.ensure_future(
            io_tools.poll_resource(self.dds_alive, 5.5, self.reset_dds,
                                   continuous=True, name="DDS"))

        # The DAQ connection will be established and monitored through polling.
        self._daq = None  # type: mccdaq.MccDaq
        asyncio.ensure_future(io_tools.poll_resource(
            self.daq_alive, 3.7, self.reset_daq, name="DAQ"))

        self._temp_ramps = dict()  # type: Dict[int, TemperatureRamp]
        self._init_temp_ramps()

        LOGGER.info("Initialized Subsystems.")

    def daq_alive(self) -> bool:
        """The DAQ is connected and healthy."""
        if self._daq and self._daq.ping():
            return True
        return False

    def dds_alive(self) -> bool:
        """The DDS is connected and healthy."""
        if self._dds and self._dds.ping():
            return True
        return False

    def get_full_set_of_readings(self,
                                 since: float = None) -> Dict[str, Buffer]:
        """Return a dict of all readings, ready to be sent to the client."""
        data = {}  # type: Dict[str, Buffer]

        if self._menlo is None:
            return data

        # ADC readings
        for channel in range(8):
            data['adc' + str(channel)] = self._menlo.get_adc_voltage(channel,
                                                                     since)

        # LD current drivers
        for name, unit in LD_DRIVERS.items():
            data[name + '_enabled'] = \
                self._menlo.is_current_driver_enabled(unit)
            data[name + '_current'] = \
                self._menlo.get_diode_current(unit, since)
            data[name + '_current_set'] = \
                self._menlo.get_diode_current_setpoint(unit)

        # TEC controllers
        for name, unit in TEC_CONTROLLERS.items():
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

        # PII Controller
        data['nu_lock_enabled'] = self._menlo.is_lock_enabled(LOCKBOXES['nu'])
        data['nu_i1_enabled'] = \
            self._menlo.is_integrator_enabled(LOCKBOXES['nu'], 1)
        data['nu_i2_enabled'] = \
            self._menlo.is_integrator_enabled(LOCKBOXES['nu'], 2)
        data['nu_ramp_enabled'] = self._menlo.is_ramp_enabled(LOCKBOXES['nu'])
        data['nu_prop'] = self._menlo.get_error_scale(LOCKBOXES['nu'])
        data['nu_offset'] = self._menlo.get_error_offset(LOCKBOXES['nu'])
        data['nu_p_monitor'] = self._menlo.get_pii_monitor(
            LOCKBOXES['nu'], p_only=True, since=since)
        data['nu_monitor'] = self._menlo.get_pii_monitor(LOCKBOXES['nu'],
                                                         since=since)
        data['nu_ramp_amplitude'] = \
            self._menlo.get_ramp_amplitude(LOCKBOXES['nu'])

        return data

    def get_setup_parameters(self) -> Dict[str, Buffer]:
        """Return a dict of all setup parameters.

        These are the ones that don't usually change."""
        data = {}  # type: Dict[str, Buffer]
        try:
            freqs = self._dds.frequencies
            amplitudes = self._dds.amplitudes
            phases = self._dds.phases
            ext_clock = self._dds.runs_on_ext_clock_source
        except (ConnectionError, AttributeError):
            LOGGER.error("Couldn't get setup parameters as DDS is offline")
            return data

        data['eom_freq'] = self._wrap_into_buffer(freqs[DdsChannel.EOM])
        data['aom_freq'] = self._wrap_into_buffer(freqs[DdsChannel.AOM])
        data['aom_amplitude'] = self._wrap_into_buffer(amplitudes[DdsChannel.AOM])
        data['eom_amplitude'] = self._wrap_into_buffer(amplitudes[DdsChannel.EOM])
        data['mixer_amplitude'] = self._wrap_into_buffer(amplitudes[DdsChannel.MIXER])
        data['mixer_phase'] = self._wrap_into_buffer(phases[DdsChannel.MIXER])

        if isinstance(ext_clock, bool):  # May be unknown (None).
            data['rf_use_external_clock'] = self._wrap_into_buffer(ext_clock)
        return data

    def nu_locked(self) -> bool:
        """Is the frequency lock engaged?"""
        return False  # FIXME

    def power_up_mo(self) -> None:
        """
        Switch on master oscillator and crank it to startup current.

        This will only succeed, if PA is at a sufficient power level. Consider
        running .power_up_pa() before to ensure this.

        :raises SubsystemError:
        """
        self.switch_ld('mo', True)
        self.set_current('mo', self._laser.mo_powerup_current)

    def power_up_pa(self) -> None:
        """
        Switch on power amplifier and crank it to startup current.

        :raises SubsystemError:
        """
        self.switch_ld('pa', True)
        self.set_current('pa', self._laser.pa_powerup_current)

    async def refresh_status(self) -> None:
        if self._menlo is not None:
            await self._menlo.request_full_status()

    def reset_daq(self) -> None:
        """Reset the USB connection to the DAQ. Does not clear internal state.
        """
        # For lack of better understanding of the object destruction mechanism,
        # we del here before we set it to None.
        del self._daq
        self._daq = None
        try:
            attempt = mccdaq.MccDaq()
        except ConnectionError:
            LOGGER.exception("Couldn't connect to DAQ.")
        else:
            LOGGER.info("Successfully (re-)set DAQ.")
            self._daq = attempt

    async def reset_dds(self) -> None:
        """Reset the connection to the Menlo subsystem.

        This will not raise anything on failure. Check dds_alive() to for
        success.
        """
        # For lack of better understanding of the object destruction mechanism,
        # we del here before we set it to None.
        del self._dds
        self._dds = None
        try:
            attempt = dds9_control.Dds9Control(DDS_PORT)
        except ConnectionError:
            LOGGER.exception("Couldn't connect to DDS.")
        else:
            LOGGER.info("Successfully (re-)set DDS.")
            self._dds = attempt

    async def reset_menlo(self) -> None:
        """Reset the connection to the Menlo subsystem."""
        # For lack of better understanding of the object destruction mechanism,
        # we del here before we set it to None.
        del self._menlo
        self._menlo = None
        attempt = menlo_stack.MenloStack()
        try:
            await attempt.init_async()
        except ConnectionError:
            LOGGER.exception("Couldn't connect to menlo stack.")
        else:
            LOGGER.info("Successfully reset Menlo stack.")
            self._menlo = attempt

    def scan_ramp(self, amplitude: float = 1):
        return self._daq.scan_once(amplitude * 10, .2, [7, 11])  # FIXME

    def set_aom_amplitude(self, amplitude: float) -> None:
        """Set the acousto-optic modulator driver amplitude betw. 0 and 1."""
        if not isinstance(amplitude, (float, int)) or amplitude < 0:
            LOGGER.error("Provide valid amplitude for AOM.")
            return
        try:
            self._dds.set_amplitude(amplitude, int(DdsChannel.AOM))
        except (AttributeError, ConnectionError):
            LOGGER.error("DDS offline.")
        else:
            LOGGER.info("Set AOM amplitude to %s %%.", amplitude * 100)

    def set_aom_frequency(self, freq: float) -> None:
        """Set the acousto-optic modulator driver frequency in MHz."""
        if not isinstance(freq, (float, int)) or not freq > 0:
            LOGGER.error("Provide valid frequency (float) for AOM.")
            return
        try:
            self._dds.set_frequency(freq, int(DdsChannel.AOM))
        except (AttributeError, ConnectionError):
            LOGGER.error("DDS offline.")
        else:
            LOGGER.info("Setting AOM frequency to %s MHz.", freq)

    def set_current(self, unit_name: str, milliamps: float) -> None:
        """Set diode current setpoint of given unit.

        :raises SubsystemError: Something went wrong in calling a callback.
        """
        try:
            if unit_name == 'mo':
                self._laser.set_mo_current(milliamps)
            elif unit_name == 'pa':
                self._laser.set_pa_current(milliamps)
            else:
                LOGGER.error('Can only set current for either "mo" or "pa".')
        except ValueError:
            LOGGER.exception("Failed to set laser current.")
        except ecdl_mopa.CallbackError as err:
            raise SubsystemError("Critical error in osc. sup. unit!") from err
        LOGGER.info("Set diode current of unit %s to %s mA", unit_name, milliamps)

    def set_eom_amplitude(self, amplitude: float) -> None:
        """Set the electro-optic modulator driver amplitude betw. 0 and 1."""
        if not isinstance(amplitude, (float, int)) or amplitude < 0:
            LOGGER.error("Provide valid amplitude for EOM.")
            return
        try:
            self._dds.set_amplitude(amplitude, int(DdsChannel.EOM))
        except (AttributeError, ConnectionError):
            LOGGER.error("DDS offline.")
        else:
            LOGGER.info("Set EOM amplitude to %s %%.", amplitude * 100)

    def set_eom_frequency(self, freq: float) -> None:
        """Set the EOM and mixer frequency in MHz."""
        if not isinstance(freq, (float, int)) or not freq > 0:
            LOGGER.error("Provide valid frequency (float) for EOM.")
            return
        try:
            self._dds.set_frequency(freq, int(DdsChannel.EOM))
        except (AttributeError, ConnectionError):
            LOGGER.error("DDS offline.")
        else:
            LOGGER.info("Set EOM frequency to %s MHz.", freq)

    def set_error_offset(self, unit_name: str, percent: float) -> None:
        """Set the scaling factor for error signal input to lockbox."""
        try:
            percent = float(percent)
        except (TypeError, ValueError):
            LOGGER.exception("Please give a number for error signal offset.")
            return
        if not self._is_pii_unit(unit_name):
            return

        self._menlo.set_error_offset(LOCKBOXES[unit_name], percent)

    def set_error_scale(self, unit_name: str, factor: float) -> None:
        """Set the scaling factor for error signal input to lockbox."""
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            LOGGER.exception("Please give a number for scaling factor.")
            return
        if not self._is_pii_unit(unit_name):
            return

        self._menlo.set_error_scale(LOCKBOXES[unit_name], factor)

    def set_ramp_amplitude(self, unit_name: str, millivolts: int) -> None:
        """Set the amplitude of the Menlo-generated ramp. (deprecated!)"""
        # TODO Remove this as ramp is not actually implemented in hardware.
        if not isinstance(millivolts, int):
            LOGGER.error("Please give ramp amplitude in millivolts (int).")
            return
        if not self._is_pii_unit(unit_name):
            return
        self._menlo.set_ramp_amplitude(LOCKBOXES[unit_name], millivolts)

    def set_mixer_amplitude(self, amplitude: float) -> None:
        """Set the mixer driver amplitude betw. 0 and 1."""
        if not isinstance(amplitude, (float, int)) or amplitude < 0:
            LOGGER.error("Provide valid amplitude for mixer.")
            return
        try:
            self._dds.set_amplitude(amplitude, int(DdsChannel.MIXER))
        except (AttributeError, ConnectionError):
            LOGGER.error("DDS offline.")
        else:
            LOGGER.info("Set mixer amplitude to %s %%.", amplitude * 100)

    def set_mixer_frequency(self, freq: float) -> None:
        """Set the Mixer frequency in MHz. Will usually be identical to EOM."""
        if not isinstance(freq, (float, int)) or not freq > 0:
            LOGGER.error("Provide valid frequency (float) for Mixer.")
            return
        try:
            self._dds.set_frequency(freq, int(DdsChannel.MIXER))
        except (AttributeError, ConnectionError):
            LOGGER.error("DDS offline.")
        else:
            LOGGER.info("Set mixer frequency to %s MHz.", freq)

    def set_mixer_phase(self, degrees: float) -> None:
        """Set the phase offset between EOM and mixer drivers in degrees."""
        if not isinstance(degrees, (float, int)):
            LOGGER.error("Provide a mixer phase in degrees (%s given).", degrees)
            return

        try:
            # To set the phase difference, we need to set phases of both channels.
            self._dds.set_phase(0, int(DdsChannel.EOM))
            self._dds.set_phase(degrees, int(DdsChannel.MIXER))
        except (AttributeError, ConnectionError):
            LOGGER.error("Can't set phase as DDS is offline")
        else:
            LOGGER.debug("Set mixer phase to %s°", degrees)

    def set_temp(self, unit_name, celsius: float,
                 bypass_ramp: bool = False) -> None:
        """Set the target temp. for the temperature ramp."""
        try:
            temp = float(celsius)
        except (TypeError, ArithmeticError, ValueError):
            LOGGER.error("Couldn't convert temp setting %s to float.", celsius)
            return

        if self._is_tec_unit(unit_name):
            if bypass_ramp:
                LOGGER.debug("Setting TEC temp. of unit %s to %s°C directly.",
                             unit_name, temp)
                self._menlo.set_temp(TEC_CONTROLLERS[unit_name], temp)
            else:
                LOGGER.debug("Setting ramp target temp. of unit %s to %s°C",
                             unit_name, temp)
                ramp = self._temp_ramps[TEC_CONTROLLERS[unit_name]]
                ramp.target_temperature = temp

    def switch_rf_clock_source(self, which: str) -> None:
        """Pass "external" or "internal" to switch RF clock source."""
        if which not in ['external', 'internal']:
            LOGGER.error('Can only switch to "external" or "internal" '
                         'reference, "%s" given.', which)
            return
        try:
            if which == 'external':
                self._dds.switch_to_ext_reference()
            else:  # str == 'internal'
                self._dds.switch_to_int_reference()
        except (AttributeError, ConnectionError):
            LOGGER.error("DDS offline.")
        else:
            LOGGER.info("Switched to %s clock reference.", which)

    def switch_integrator(
            self, unit_name: str, stage: int, switch_on: bool) -> None:
        """Switch the given PII integrator stage (1 or 2) on or off.

        :param unit_name: Which PII unit to act on (1 or 2)
        :param stage: Which stage to act on--1 (fast) or 2 (slow)
        :param switch_on: True for enabling integrator false for disabling it
        """
        if not self._is_pii_unit(unit_name):  # Will emit error itself.
            return
        if stage not in [1, 2]:
            LOGGER.error("Please provide integrator stage: 1 or 2. Given: %s",
                         stage)
            return
        if not isinstance(switch_on, bool):
            LOGGER.error("Provide boolean \"is_instance\" whether to switch "
                         "stage on. Given: %s", switch_on)
            return

        self._menlo.switch_integrator(LOCKBOXES[unit_name], stage, switch_on)

    def switch_ld(self, unit_name: str, switch_on: bool) -> None:
        """
        :raises SubsystemError:
        """
        try:
            if unit_name == 'mo':
                if switch_on:
                    self._laser.enable_mo()
                else:
                    self._laser.disable_mo()
            elif unit_name == 'pa':
                if switch_on:
                    self._laser.enable_pa()
                else:
                    self._laser.disable_pa()
            else:
                LOGGER.error('Can only set current for either "mo" or "pa".')
        except ValueError as err:
            LOGGER.error(str(err))
        except ecdl_mopa.CallbackError:
            LOGGER.exception("Critical error in osc. sup. unit!")
            raise SubsystemError("Critical error in osc. sup. unit!")

    def switch_lock(self, unit_name: str, switch_on: bool) -> None:
        if self._is_pii_unit(unit_name):
            if isinstance(switch_on, bool):
                self._menlo.switch_lock(LOCKBOXES[unit_name], switch_on)
            else:
                LOGGER.error("Please provide boolean \"on\" argument when "
                             "switching pii lock electronics of unit %s.",
                             unit_name)

    def switch_pii_ramp(self, unit_name: str, switch_on: bool) -> None:
        if self._is_pii_unit(unit_name):
            if isinstance(switch_on, bool):
                self._menlo.switch_ramp(LOCKBOXES[unit_name], switch_on)
            else:
                LOGGER.error('Please provide boolean "on" argument when '
                             'switching pii ramp generation of unit %s.',
                             unit_name)

    def switch_tec(self, unit_name: str, switch_on: bool) -> None:
        if self._is_tec_unit(unit_name):
            if isinstance(switch_on, bool):
                self._menlo.switch_tec(TEC_CONTROLLERS[unit_name], switch_on)

    def switch_temp_ramp(self, unit_name: str, enable: bool) -> None:
        """Start or halt ramping the temperature setpoint."""
        if self._is_tec_unit(unit_name):
            ramp = self._temp_ramps[TEC_CONTROLLERS[unit_name]]
            if enable:
                ramp.start_ramp()
            else:
                ramp.pause_ramp()


    # Private Methods

    def _init_laser(self) -> None:
        # Initalize a laser controller class using the methods that the menlo
        # stack current drivers expose.
        get_mo = partial(self._menlo.get_diode_current,
                         unit_number=LD_DRIVERS['mo'])
        get_pa = partial(self._menlo.get_diode_current,
                         unit_number=LD_DRIVERS['pa'])
        set_mo = partial(self._menlo.set_current, unit_number=LD_DRIVERS['mo'])
        set_pa = partial(self._menlo.set_current, unit_number=LD_DRIVERS['pa'])
        disable_mo = partial(self._menlo.switch_ld,
                             switch_on=False, unit_number=LD_DRIVERS['mo'])
        disable_pa = partial(self._menlo.switch_ld,
                             switch_on=False, unit_number=LD_DRIVERS['pa'])
        enable_mo = partial(self._menlo.switch_ld,
                            switch_on=True, unit_number=LD_DRIVERS['mo'])
        enable_pa = partial(self._menlo.switch_ld,
                            switch_on=True, unit_number=LD_DRIVERS['pa'])

        self._laser = ecdl_mopa.EcdlMopa(
            get_mo_callback=lambda: get_mo()[0][1],
            get_pa_callback=lambda: get_pa()[0][1],
            set_mo_callback=lambda c: set_mo(milliamps=c),
            set_pa_callback=lambda c: set_pa(milliamps=c),
            disable_mo_callback=disable_mo,
            disable_pa_callback=disable_pa,
            enable_mo_callback=enable_mo,
            enable_pa_callback=enable_pa)

    def _init_temp_ramps(self) -> None:
        """Initialize one TemperatureRamp instance for every TEC controller."""

        # TODO: Use functools.partials instead of default arguments to enforce
        # early binding.
        for name, unit in TEC_CONTROLLERS.items():
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

        # Set maximum allowable temperature gradients according to the
        # datasheets or educated guesses.
        self._temp_ramps[TEC_CONTROLLERS['miob']].maximum_gradient = 1/60
        self._temp_ramps[TEC_CONTROLLERS['vhbg']].maximum_gradient = 1/5
        self._temp_ramps[TEC_CONTROLLERS['shga']].maximum_gradient = 1/5
        self._temp_ramps[TEC_CONTROLLERS['shgb']].maximum_gradient = 1/5

    def _is_tec_unit(self, name: str) -> bool:
        if self._menlo is None:
            return False
        if name not in TEC_CONTROLLERS:
            LOGGER.error('There is no TEC controller named "%s".', name)
            return False
        return True

    def _is_pii_unit(self, name: str) -> bool:
        if self._menlo is None:
            return False
        if name not in LOCKBOXES:
            LOGGER.error('There is no Lockbox by the name "%s".', name)
            return False
        return True

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
