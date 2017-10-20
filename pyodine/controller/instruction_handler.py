"""Parses, checks and executes incoming instructions from external sources.

Security Policy
---------------
As this class's `handle_instruction()` deals with externally fed commands, it
must catch all possible errors itself and log and ignore the invalid
instruction.
"""
import enum
import json
import logging

# We use Dict in type annotations, but not in the code. Thus we need to tell
# both flake8 and pylint to ignore the "unused import" warning for the
# following line.
from typing import Callable, Dict, List  # pylint: disable=unused-import
from . import interfaces, subsystems, control_flow, lock_buddy
from ..transport import texus_relay

TecUnit = subsystems.TecUnit
# Define custom types.
LegalCall = Callable[..., None]  # pylint: disable=invalid-name

LOGGER = logging.getLogger("pyodine.controller.instruction_handler")
LOGGER.setLevel(logging.DEBUG)

class TimerEffect(enum.IntEnum):
    """The link between actual system responses and TEXUS timer wires."""
    HOT = texus_relay.TimerWire.TEX_1
    LASER = texus_relay.TimerWire.TEX_2
    LOCK = texus_relay.TimerWire.TEX_3

# pylint: disable=too-few-public-methods
# The main method is the single functionality of this class.
class InstructionHandler:
    """This class receives external commands and forwards them."""

    def __init__(self, subsystem_controller: subsystems.Subsystems,
                 interface_controller: interfaces.Interfaces,
                 locker: lock_buddy.LockBuddy) -> None:
        self._subs = subsystem_controller
        self._face = interface_controller
        self._locker = locker
        self._flow = control_flow

        self._methods = {
            'set_aom_freq': lambda f: self._subs.set_aom_frequency(float(f)),
            'set_eom_freq': lambda f: self._subs.set_eom_frequency(float(f)),
            'set_mixer_freq': lambda f: self._subs.set_mixer_frequency(
                float(f)),
            'set_mixer_phase': lambda p: self._subs.set_mixer_phase(float(p)),
            'set_aom_amplitude': lambda a: self._subs.set_aom_amplitude(
                float(a)),
            'set_eom_amplitude': lambda a: self._subs.set_eom_amplitude(
                float(a)),
            'set_mixer_amplitude': lambda a: self._subs.set_mixer_amplitude(
                float(a)),

            'set_mo_current_set': lambda c: self._subs.set_current('mo', float(c)),
            'set_vhbg_temp_set': lambda t: self._subs.set_temp(TecUnit.VHBG, float(t)),
            'set_vhbg_temp_raw_set': lambda t: self._subs.set_temp(
                TecUnit.VHBG, float(t), bypass_ramp=True),

            'set_pa_current_set': lambda c: self._subs.set_current('pa',
                                                                   float(c)),
            'set_miob_temp_set': lambda t: self._subs.set_temp(TecUnit.MIOB, float(t)),
            'set_miob_temp_raw_set': lambda t: self._subs.set_temp(
                TecUnit.MIOB, float(t), bypass_ramp=True),

            'set_shga_temp_set': lambda t: self._subs.set_temp(TecUnit.SHGA, float(t)),
            'set_shga_temp_raw_set': lambda t: self._subs.set_temp(
                TecUnit.SHGA, float(t), bypass_ramp=True),

            'set_shgb_temp_set': lambda t: self._subs.set_temp(TecUnit.SHGB, float(t)),
            'set_shgb_temp_raw_set': lambda t: self._subs.set_temp(
                TecUnit.SHGB, float(t), bypass_ramp=True),

            'set_nu_prop': lambda f: self._subs.set_error_scale('nu', f),
            'set_nu_offset': lambda p: self._subs.set_error_offset('nu', p),
            'switch_rf_clock_source': self._subs.switch_rf_clock_source,
            'switch_ld': self._subs.switch_ld,
            'switch_nu_ramp': lambda f: self._subs.switch_pii_ramp('nu', f),
            'switch_nu_lock': lambda f: self._subs.switch_lock('nu', f),
            'switch_temp_ramp': self._subs.switch_temp_ramp,
            'switch_tec': self._subs.switch_tec,
            'switch_integrator': self._subs.switch_integrator,
            'setflag': self._face.set_flag}  # type: Dict[str, LegalCall]

    def handle_instruction(self, message: str) -> None:
        # Use a "meta" try to comply with class security policy. However, due
        # to the command whitelisting, we should not actually have to catch
        # anything out here.
        try:
            try:  # Parse data.
                container = json.loads(str(message))
            except (json.JSONDecodeError, TypeError):
                LOGGER.warning("Instruction was no valid JSON string")
                return

            try:  # Read data.
                method = container['data']['method']
                arguments = container['data']['args']
            except KeyError:
                LOGGER.error("Instruction package didn't include mandatory "
                             "members.")
                return

            if method in self._methods:
                try:
                    LOGGER.debug("Calling method %s with arguments: %s",
                                 method, arguments)
                    (self._methods[method])(*arguments)
                except TypeError:
                    LOGGER.exception("Wrong type/number of arguments.")
            else:
                LOGGER.error("Unknown method name (%s). Doing nothing.",
                             method)

        # As this is a server process, broad-except is permissible:
        except Exception:  # pylint: disable=broad-except
            LOGGER.exception("We caught an unexpected exception. This most "
                             "likely indicates an *actual* problem.")

    async def handle_timer_command(self, wire: texus_relay.TimerWire,
                                   timer_state: List[bool]) -> None:
        """React to a change in TEXUS timer state.

        :raises RuntimerError: One of the associated actions failed.
        """
        # We don't catch the possible RuntimerError's below, as this function
        # is only used as a callback. Due to the way callbacks are handled in
        # pyodine, their Exceptions are always caught and logged.
        # For Errors raised into here, there also is no smarter action than
        # just logging them, as this function reports directly to top-level.

        if wire == TimerEffect.HOT:
            if timer_state[wire]:
                control_flow.heat_up(self._subs)
            else:
                control_flow.cool_down(self._subs)
        elif wire == TimerEffect.LASER:
            if timer_state[wire]:
                await control_flow.laser_power_up(self._subs)
            else:
                await control_flow.laser_power_down(self._subs)
        elif wire == TimerEffect.LOCK:
            if timer_state[wire]:
                await control_flow.prelock_and_lock(self._locker)
            else:
                await control_flow.unlock(self._locker)
        else:
            LOGGER.warning("Change in unused timer wire %s detected. Ignoring.")
