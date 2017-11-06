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

import numpy as np

from .temperature_ramp import TemperatureRamp
from ..drivers import ecdl_mopa, dds9_control, menlo_stack, mccdaq, ms_ntc
from ..util import asyncio_tools

LOGGER = logging.getLogger("pyodine.controller.subsystems")
LOGGER.setLevel(logging.DEBUG)


# TODO: Drop this and use `TecUnit` below instead.
TEC_CONTROLLERS = {'miob': 1, 'vhbg': 2, 'shgb': 3, 'shga': 4}

LOCKBOX_ID = 2
DDS_PORT = '/dev/ttyUSB2'

SCAN_TIME = 0.2  # The time to take for a frequency scan in seconds.

# Define some custom types.
# pylint: disable=invalid-name
MenloUnit = Union[float, int]

# Measurement (time, reading)
DataPoint = Tuple[float, MenloUnit]
Buffer = List[DataPoint]
# pylint: enable=invalid-name

class AuxTemp(enum.IntEnum):
    """How to index the array returned by get_aux_temps?"""
    AOM = 0
    AOM_AMP = 1
    CELL = 2
    EOM = 3
    LASER = 4
    MENLO = 5
    SHG = 6

class DaqInput:  # pylint: disable=too-few-public-methods
    """The MCC USB1608G-2AO features 16 analog inputs.

    Static constants container. Don't instanciate."""
    REF_5V = mccdaq.DaqChannel.C_4
    ERR_SIGNAL = mccdaq.DaqChannel.C_7
    RAMP_MONITOR = mccdaq.DaqChannel.C_11
    PUMP_DIODE = mccdaq.DaqChannel.C_12
    NTC_CELL = mccdaq.DaqChannel.C_0
    NTC_SHG = mccdaq.DaqChannel.C_8
    NTC_LASER = mccdaq.DaqChannel.C_9
    NTC_AOM = mccdaq.DaqChannel.C_9
    NTC_EOM = mccdaq.DaqChannel.C_2
    NTC_AOM_AMP = mccdaq.DaqChannel.C_10
    NTC_MENLO = mccdaq.DaqChannel.C_3

class DdsChannel(enum.IntEnum):
    """The four channels of the DDS device."""
    AOM = 1
    EOM = 0
    MIXER = 2
    FREE = 3  # not in use

class LdDriver(enum.IntEnum):
    MASTER_OSCILLATOR = 1
    POWER_AMPLIFIER = 2

class TecUnit(enum.IntEnum):
    """The Menlo stack's TEC controllers."""
    MIOB = 1
    VHBG = 2
    SHGB = 3
    SHGA = 4

class SubsystemError(RuntimeError):
    """One of the subsystems experienced a critical problem. Reset is advised.
    """
    pass


class Subsystems:
    """Provides a wrapper for all connected subsystems.

    The instance will provide access to the Laser at .laser .
    """

    def __init__(self) -> None:

        # Wait for Menlo to show up and initialize laser control as soon as
        # they arrive.
        self._menlo = None  # type: menlo_stack.MenloStack
        self.laser = None  # type: ecdl_mopa.EcdlMopa
        asyncio.ensure_future(
            asyncio_tools.poll_resource(
                lambda: bool(self._menlo), 5, self.reset_menlo,
                self._init_laser, name="Menlo"))

        # Initialize the DDS connection and monitor it for connection problems.
        # We keep the poller alive to monitor the RS232 connection which got
        # stuck sometimes during testing.
        self._dds = None  # type: dds9_control.Dds9Control
        asyncio.ensure_future(
            asyncio_tools.poll_resource(self.dds_alive, 5.5, self.reset_dds,
                                        continuous=True, name="DDS"))

        # The DAQ connection will be established and monitored through polling.
        self._daq = None  # type: mccdaq.MccDaq
        asyncio.ensure_future(asyncio_tools.poll_resource(
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

    async def fetch_scan(self, amplitude: float = 1) -> np.ndarray:
        """Scan the frequency once and return the readings acquired.

        This is the main method used by the `lock_buddy` module to perform
        prelock.

        :param amplitude: The peak-to-peak amplitude to use for scanning,
                    ranging [0, 1]. 1 corresponds to 10V peak-peak.
        :raises ConnectionError: DAQ is unavailable.
        """
        blocking_fetch = lambda: self._daq.fetch_scan(
            amplitude * 10,  # Limit the full scan ampl. to 10V to avoid capping
            SCAN_TIME,
            [(DaqInput.RAMP_MONITOR, mccdaq.InputRange.PM_10V),
             (DaqInput.ERR_SIGNAL, mccdaq.InputRange.PM_2V),
             (DaqInput.PUMP_DIODE, mccdaq.InputRange.PM_5V)],
            mccdaq.RampShape.DESCENT)
        try:
            return await asyncio.get_event_loop().run_in_executor(None, blocking_fetch)
        except (AttributeError, ConnectionError) as err:
            raise ConnectionError(
                "Couldn't fetch signal as DAQ is unavailable.") from err

    async def get_aux_temps(self) -> List[float]:
        """Read temperatures of auxiliary sensors, as indexed by AuxTemp.

        :raises ConnectionError: Couldn't convince the DAQ to send us data.
        """
        channels = [(DaqInput.NTC_AOM, mccdaq.InputRange.PM_5V),
                    (DaqInput.NTC_AOM_AMP, mccdaq.InputRange.PM_5V),
                    (DaqInput.NTC_CELL, mccdaq.InputRange.PM_5V),
                    (DaqInput.NTC_EOM, mccdaq.InputRange.PM_5V),
                    (DaqInput.NTC_LASER, mccdaq.InputRange.PM_5V),
                    (DaqInput.NTC_MENLO, mccdaq.InputRange.PM_5V),
                    (DaqInput.NTC_SHG, mccdaq.InputRange.PM_5V)]
        def fetch_readings() -> List[float]:
            return self._daq.sample_channels(channels).tolist()[0]  # may raise!

        return ms_ntc.to_temperatures(
            await asyncio.get_event_loop().run_in_executor(None, fetch_readings))

    def get_full_set_of_readings(self, since: float = None) -> Dict[str, Buffer]:
        """Return a dict of all readings, ready to be sent to the client."""
        data = {}  # type: Dict[str, Buffer]

        if self._menlo is None:
            return data

        # ADC readings
        for channel in range(8):
            data['adc' + str(channel)] = self._menlo.get_adc_voltage(channel,
                                                                     since)

        # LD current drivers
        for name, unit in [('mo', LdDriver.MASTER_OSCILLATOR),
                           ('pa', LdDriver.POWER_AMPLIFIER)]:
            data[name + '_enabled'] = self._menlo.is_current_driver_enabled(unit)
            data[name + '_current'] = self._menlo.get_diode_current(unit, since)
            data[name + '_current_set'] = self._menlo.get_diode_current_setpoint(unit)

        # TEC controllers
        for name, unit in TEC_CONTROLLERS.items():
            unt = TecUnit(unit)
            data[name + '_tec_enabled'] = self._menlo.is_tec_enabled(unt)
            data[name + '_temp'] = self._menlo.get_temperature(unt, since)
            data[name + '_temp_raw_set'] = self._menlo.get_temp_setpoint(unt)
            data[name + '_temp_set'] = self._wrap_into_buffer(
                self._temp_ramps[unt].target_temperature)
            data[name + '_temp_ramp_active'] = self._wrap_into_buffer(
                self._temp_ramps[unt].is_running)
            data[name + '_temp_ok'] = self._menlo.is_temp_ok(unt)
            data[name + '_tec_current'] = self._menlo.get_tec_current(unt, since)

        # PII Controller
        data['nu_lock_enabled'] = self._menlo.is_lock_enabled(LOCKBOX_ID)
        data['nu_i1_enabled'] = \
            self._menlo.is_integrator_enabled(LOCKBOX_ID, 1)
        data['nu_i2_enabled'] = \
            self._menlo.is_integrator_enabled(LOCKBOX_ID, 2)
        data['nu_ramp_enabled'] = self._menlo.is_ramp_enabled(LOCKBOX_ID)
        data['nu_prop'] = self._menlo.get_error_scale(LOCKBOX_ID)
        data['nu_offset'] = self._menlo.get_error_offset(LOCKBOX_ID)
        data['nu_p_monitor'] = self._menlo.get_pii_monitor(
            LOCKBOX_ID, p_only=True, since=since)
        data['nu_monitor'] = self._menlo.get_pii_monitor(LOCKBOX_ID,
                                                         since=since)
        data['nu_ramp_amplitude'] = \
            self._menlo.get_ramp_amplitude(LOCKBOX_ID)

        return data

    def get_ld_current(self, unit: LdDriver) -> float:
        """Return the latest laser diode current in milliamperes.

        :param unit: The LD driver unit to act on. Either an `LdDriver` enum
                member or a plain int may be given.
        :raises ValueError: Given unit is not a `LdDriver`
        :raises ConnectionError: Requested data couldn't be acquired, probably
                    because Menlo is not available (yet).
        """
        try:
            return self._unwrap_buffer(
                self._menlo.get_diode_current(LdDriver(unit)))
        except (ValueError, AttributeError) as err:
            raise ConnectionError("Couldn't fetch diode current from Menlo.") from err

    def get_lockbox_level(self) -> float:
        return self._unwrap_buffer(self._menlo.get_pii_monitor(LOCKBOX_ID))

    def get_ramp_offset(self) -> float:
        """The zero position of the ramp used to acquire the error signal"""
        return self._daq.ramp_offset

    def set_ramp_offset(self, volts: float) -> None:
        """The zero position of the ramp used to acquire the error signal

        :param volts: Offset in volts, must be in [-5, 5]
        """
        try:
            self._daq.ramp_offset = volts
        except ValueError:
            LOGGER.exception("Couldn't set ramp offset.")

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

    def get_temp(self, unit: int) -> float:
        """Returns the temperature of the given unit in °C.

        Consider using this module's provided Enums for choice of unit number.

        :param unit: Unique identifier of the temperature to be fetched.
                    Possible values are in `.TecUnit`, (TODO to be continued...).
        :raises ConnectionError: Couldn't get the requested temperature from
                    from the concerned subsystem.
        :raises ValueError: There is no temperature with the ID `unit`.
        """
        # The structure right now is more complicated than it would need to be
        # (see get_temp_setpt() for comparison), but we prepared this for
        # fetching all kinds of temperatures from around the system, not only
        # Menlo TEC units.
        try:
            tec_enum = TecUnit(unit)
        except ValueError:
            pass
        else:
            try:
                return self._unwrap_buffer(self._menlo.get_temperature(tec_enum))
            except (ValueError, AttributeError) as err:
                raise ConnectionError("Couldn't fetch temp from Menlo.") from err

        raise ValueError("Unknown unit number {}.".format(unit))

    def get_temp_setpt(self, unit: TecUnit) -> float:
        """Returns the temperature setpoint of the given unit in °C.

        :param unit: The TEC unit to fetch from. See provided enum TecUnit for
                    available units.

        :raises ConnectionError: Couldn't reach the concerned subsystem.
        :raises ValueError: The provided unit is not a TecUnit.
        """
        try:
            return self._unwrap_buffer(self._menlo.get_temperature(TecUnit(unit)))
        except (AttributeError, ValueError) as err:
            raise ConnectionError("Couldn't fetch temp. setpt. from Menlo.") from err

    def get_temp_ramp_target(self, unit: TecUnit) -> float:
        """Returns the target temperature of the unit's ramp."""
        return self._temp_ramps[unit].target_temperature

    def is_tec_enabled(self, unit: TecUnit) -> bool:
        """Is ``unit``'s TEC controller currently running?

        :raises ConnectionError: No values have been received (yet).
        """
        try:
            return self._unwrap_buffer(self._menlo.is_tec_enabled(unit)) == 1
        except ValueError:
            raise ConnectionError("Didn't receive data from Menlo.")

    def nu_locked(self) -> bool:
        """Is the frequency lock engaged?

        :raises ConnectionError: Menlo couldn't be reached.
        """
        try:
            return self._unwrap_buffer(
                self._menlo.is_lock_enabled(LOCKBOX_ID)) == 1
        except (AttributeError, ValueError) as err:  # Menlo is not available.
            raise ConnectionError(
                "Can't inquire nu lock state, as Menlo is unavailable.") from err

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

    def set_current(self, unit: LdDriver, milliamps: float) -> None:
        """Set diode current setpoint of given unit.

        :raises SubsystemError: Something went wrong in calling a callback.
        """
        try:
            if unit == LdDriver.MASTER_OSCILLATOR:
                self.laser.set_mo_current(milliamps)
            elif unit == LdDriver.POWER_AMPLIFIER:
                self.laser.set_pa_current(milliamps)
            else:
                LOGGER.error('Can only set current for either "mo" or "pa".')
        except ValueError:
            LOGGER.exception("Failed to set laser current.")
        except ecdl_mopa.CallbackError as err:
            raise SubsystemError("Critical error in osc. sup. unit!") from err
        LOGGER.info("Set diode current of unit %s to %s mA", unit, milliamps)

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

    def set_error_offset(self, millivolts: float) -> None:
        """Set the scaling factor for error signal input to lockbox."""
        try:
            millivolts = float(millivolts)
        except (TypeError, ValueError):
            LOGGER.exception("Please give a number for error signal offset.")
            return
        self._menlo.set_error_offset(LOCKBOX_ID, millivolts)

    def set_error_scale(self, factor: float) -> None:
        """Set the scaling factor for error signal input to lockbox."""
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            LOGGER.exception("Please give a number for scaling factor.")
            return
        self._menlo.set_error_scale(LOCKBOX_ID, factor)

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

    def set_temp(self, unit: TecUnit, celsius: float, bypass_ramp: bool = False) -> None:
        """Set the target temp. for the temperature ramp."""
        try:
            temp = float(celsius)
        except (TypeError, ArithmeticError, ValueError):
            LOGGER.error("Couldn't convert temp setting %s to float.", celsius)
            return

        try:
            unit = TecUnit(unit)
        except (ValueError, TypeError):
            LOGGER.exception("Invalid unit: %s.", unit)
        else:
            if bypass_ramp:
                LOGGER.debug("Setting TEC temp. of unit %s to %s°C directly.",
                             unit, temp)
                self._menlo.set_temp(unit, temp)
            else:
                LOGGER.debug("Setting ramp target temp. of unit %s to %s°C",
                             unit, temp)
                ramp = self._temp_ramps[unit]
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
            self, stage: int, switch_on: bool) -> None:
        """Switch the given PII integrator stage (1 or 2) on or off.

        :param stage: Which stage to act on--1 (fast) or 2 (slow)
        :param switch_on: True for enabling integrator false for disabling it
        """
        if stage not in [1, 2]:
            LOGGER.error("Please provide integrator stage: 1 or 2. Given: %s",
                         stage)
            return
        if not isinstance(switch_on, bool):
            LOGGER.error("Provide boolean \"is_instance\" whether to switch "
                         "stage on. Given: %s", switch_on)
            return

        self._menlo.switch_integrator(LOCKBOX_ID, stage, switch_on)

    def switch_ld(self, unit: LdDriver, switch_on: bool) -> None:
        """
        :raises SubsystemError:
        """
        try:
            if unit == LdDriver.MASTER_OSCILLATOR:
                if switch_on:
                    self.laser.enable_mo()
                else:
                    self.laser.disable_mo()
            elif unit == LdDriver.POWER_AMPLIFIER:
                if switch_on:
                    self.laser.enable_pa()
                else:
                    self.laser.disable_pa()
            else:
                LOGGER.error('Can only set current for either "mo" or "pa".')
        except ValueError:
            LOGGER.exception("Couldn't switch LD")
        except ecdl_mopa.CallbackError:
            LOGGER.exception("Critical error in osc. sup. unit!")
            raise SubsystemError("Critical error in osc. sup. unit!")

    def switch_lock(self, switch_on: bool) -> None:
        if isinstance(switch_on, bool):
            self._menlo.switch_lock(LOCKBOX_ID, switch_on)
        else:
            LOGGER.error("Please provide boolean \"on\" argument when "
                         "switching pii lock electronics.")

    def switch_pii_ramp(self, switch_on: bool) -> None:
        if isinstance(switch_on, bool):
            self._menlo.switch_ramp(LOCKBOX_ID, switch_on)
        else:
            LOGGER.error('Please provide boolean "on" argument when '
                         'switching pii ramp generation.')

    def switch_tec(self, unit_name: str, switch_on: bool) -> None:
        if self._is_tec_unit(unit_name):
            if isinstance(switch_on, bool):
                self._menlo.switch_tec(TEC_CONTROLLERS[unit_name], switch_on)

    def switch_tec_by_id(self, unit: TecUnit, switch_on: bool) -> None:
        """Like switch_tec(), but using the unit ID instead of name."""
        try:
            unit = TecUnit(unit)
        except (ValueError, TypeError):
            LOGGER.exception("Invalid unit: %s.", unit)
        if isinstance(switch_on, bool):
            self._menlo.switch_tec(unit, switch_on)

    def switch_temp_ramp(self, unit: TecUnit, enable: bool) -> None:
        """Start or halt ramping the temperature setpoint."""
        try:
            unit = TecUnit(unit)
        except (ValueError, TypeError):
            LOGGER.exception("TEC unit %s doesn't exist.", unit)
        else:
            if enable:
                self._temp_ramps[unit].start_ramp()
            else:
                self._temp_ramps[unit].pause_ramp()


    # Private Methods

    def _init_laser(self) -> None:
        # Initalize a laser controller class using the methods that the menlo
        # stack current drivers expose.
        mo_id = LdDriver.MASTER_OSCILLATOR
        pa_id = LdDriver.POWER_AMPLIFIER
        get_mo = partial(self._menlo.get_diode_current, unit_number=mo_id)
        get_pa = partial(self._menlo.get_diode_current, unit_number=pa_id)
        set_mo = partial(self._menlo.set_current, unit_number=mo_id)
        set_pa = partial(self._menlo.set_current, unit_number=pa_id)
        disable_mo = partial(self._menlo.switch_ld, switch_on=False, unit_number=mo_id)
        disable_pa = partial(self._menlo.switch_ld, switch_on=False, unit_number=pa_id)
        enable_mo = partial(self._menlo.switch_ld, switch_on=True, unit_number=mo_id)
        enable_pa = partial(self._menlo.switch_ld, switch_on=True, unit_number=pa_id)

        self.laser = ecdl_mopa.EcdlMopa(
            # _unwrap_buffer may raise if there's no data yet, but EcdlMopa can
            # handle Exceptions raised in callbacks.
            get_mo_callback=lambda: self._unwrap_buffer(get_mo()),
            get_pa_callback=lambda: self._unwrap_buffer(get_pa()),
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
        # TODO: Look again at all those NaN's and if's. Maybe use exceptions
        # instead?
        for name, unit in TEC_CONTROLLERS.items():
            def getter(bound_unit: int = unit) -> float:
                """Get the most recent temperature reading from MenloStack."""

                # We need to bind the loop variable "unit" to a local variable
                # here, e.g. using lambdas.
                temp_readings = self._menlo.get_temperature(bound_unit)
                if temp_readings:
                    return self._unwrap_buffer(temp_readings)

                LOGGER.error("Couldn't determine temperature.")
                return float('nan')

            def setpt_getter(bound_unit: int = unit) -> float:
                """Gets the current TEC setpoint."""
                temp_setpts = self._menlo.get_temp_setpoint(bound_unit)
                if temp_setpts:
                    return self._unwrap_buffer(temp_setpts)

                LOGGER.error("Couldn't determine temp. setpoint.")
                return float('nan')

            def setter(temp: float, bound_unit: int = unit) -> None:
                # Same here (see above).
                self._menlo.set_temp(bound_unit, temp)

            self._temp_ramps[unit] = TemperatureRamp(
                get_temp_callback=getter,
                get_temp_setpt_callback=setpt_getter,
                set_temp_callback=setter,
                name=name)

        # Set maximum allowable temperature gradients according to the
        # datasheets or educated guesses.
        self._temp_ramps[TecUnit.MIOB].maximum_gradient = 1/60
        self._temp_ramps[TecUnit.VHBG].maximum_gradient = 1/5
        self._temp_ramps[TecUnit.SHGA].maximum_gradient = 1/5
        self._temp_ramps[TecUnit.SHGB].maximum_gradient = 1/5

    def _is_tec_unit(self, name: str) -> bool:
        if self._menlo is None:
            return False
        if name not in TEC_CONTROLLERS:
            LOGGER.error('There is no TEC controller named "%s".', name)
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

    @staticmethod
    def _unwrap_buffer(buffer: Buffer) -> MenloUnit:
        # Extract the latest reading from a buffer if possible. Raises!
        try:
            return buffer[0][1]
        except IndexError as err:
            raise ValueError("Buffer is empty!") from err
