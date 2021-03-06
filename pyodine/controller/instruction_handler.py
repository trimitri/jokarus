"""Parses, checks and executes incoming instructions from external sources.

Security Policy
---------------
As this class's ``handle_instruction()`` deals with externally fed commands, it
must catch all possible errors itself and log and ignore the invalid
instruction.
"""
import enum
from functools import partial
import json
import logging

# We use Dict in type annotations, but not in the code. Thus we need to tell
# both flake8 and pylint to ignore the "unused import" warning for the
# following line.
from typing import Awaitable, Callable, Dict, Optional, Union  # pylint: disable=unused-import
from . import procedures, runlevels, subsystems
from ..pyodine_globals import (GLOBALS as GL, REQUEST)
from ..transport import texus_relay
from ..util import asyncio_tools

TecUnit = subsystems.TecUnit
# Define custom types.
LegalCall = Callable[..., Optional[Awaitable[None]]]  # pylint: disable=invalid-name

LOGGER = logging.getLogger("pyodine.controller.instruction_handler")
LOGGER.setLevel(logging.DEBUG)

class TimerEffect(enum.IntEnum):
    """The internal meanings of the TEXUS timer wires."""
    BIT_O = texus_relay.TimerWire.TEX_1
    """The 2^0 digit of the 3-bit runlevel request mechanism."""
    BIT_1 = texus_relay.TimerWire.TEX_3
    """The 2^1 digit of the 3-bit runlevel request mechanism."""
    BIT_2 = texus_relay.TimerWire.TEX_4
    """The 2^2 digit of the 3-bit runlevel request mechanism."""
    OFF = texus_relay.TimerWire.TEX_5
    """The (emergency?) power-off signal."""
    LO_TIMER = texus_relay.TimerWire.TEX_6
    """Timer signal fired at lift off.  Not the actual "LiftOff" signal!"""
    UG_TIMER = texus_relay.TimerWire.TEX_2
    """Timer signal fired at micro g.  Not the actual "3AxisGo" signal!"""
    LIFTOFF = texus_relay.TimerWire.LIFT_OFF
    """The actual rocket's "LiftOff" signal."""
    THREEXS = texus_relay.TimerWire.MICRO_G
    """The actual rocket's "3AxisGo" signal."""

_METHODS = dict()  # type: Dict[str, LegalCall]
"""Whitelist of legal methods to call."""

# pylint: disable=too-few-public-methods
# The main method is the single functionality of this class.
class InstructionHandler:
    """This class receives external commands and forwards them."""
    def __init__(self) -> None:
        _init_methods()

    async def handle_instruction(self, message: str) -> None:
        """Extract an instruction from ``message`` and execute it."""
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

            if method in _METHODS:
                await asyncio_tools.safe_async_call(_METHODS[method],
                                                    *arguments)
            else:
                LOGGER.error("Unknown method name (%s). Doing nothing.",
                             method)

        # As this is a server process, broad-except is permissible:
        except Exception:  # pylint: disable=broad-except
            LOGGER.exception("handle_instrunction() encountered a problem.")

    async def handle_timer_command(self, timer_state: texus_relay.TimerState) -> None:
        """React to a change in TEXUS timer state. """

        if REQUEST.is_override:
            LOGGER.debug("Manual override active: ignoring TEXUS timer command.")
            return

        REQUEST.liftoff = timer_state[TimerEffect.LIFTOFF]
        REQUEST.microg = timer_state[TimerEffect.UG_TIMER]
        REQUEST.off = timer_state[TimerEffect.OFF]
        REQUEST.level = parse_runlevel(timer_state)


def parse_runlevel(timer_state: texus_relay.TimerState) -> runlevels.Runlevel:
    """Extracts currently requested runlevel (0-7) from TEXUS Timer state."""
    level = 0
    if timer_state[TimerEffect.BIT_O]:
        level += 1
    if timer_state[TimerEffect.BIT_1]:
        level += 2
    if timer_state[TimerEffect.BIT_2]:
        level += 4
    return runlevels.Runlevel(level)

def _enable_texus_override(yes: bool) -> None:
    REQUEST.is_override = bool(yes)

def _init_methods() -> None:
    """We need to wait before all the globals have been initialized."""
    assert GL.subs
    _METHODS['engage_lock'] = partial(procedures.engage_lock, GL.subs)
    _METHODS['release_lock'] = partial(procedures.release_lock, GL.subs)
    _METHODS['set_aom_freq'] = lambda f: GL.subs.set_aom_frequency(float(f))
    _METHODS['set_eom_freq'] = lambda f: GL.subs.set_eom_frequency(float(f))
    _METHODS['set_mixer_freq'] = lambda f: GL.subs.set_mixer_frequency(float(f))
    _METHODS['set_mixer_phase'] = lambda p: GL.subs.set_mixer_phase(float(p))
    _METHODS['set_aom_amplitude'] = lambda a: GL.subs.set_aom_amplitude(float(a))
    _METHODS['set_eom_amplitude'] = lambda a: GL.subs.set_eom_amplitude(float(a))
    _METHODS['set_mixer_amplitude'] = lambda a: GL.subs.set_mixer_amplitude(float(a))

    _METHODS['set_mo_current_set'] = lambda c: GL.subs.set_current(
        subsystems.LdDriver.MASTER_OSCILLATOR, float(c))
    _METHODS['set_vhbg_temp_set'] = lambda t: GL.subs.set_temp(TecUnit.VHBG, float(t))
    _METHODS['set_vhbg_temp_raw_set'] = lambda t: GL.subs.set_temp(
        TecUnit.VHBG, float(t), bypass_ramp=True)

    _METHODS['set_pa_current_set'] = lambda c: GL.subs.set_current(
        subsystems.LdDriver.POWER_AMPLIFIER, float(c))
    _METHODS['set_miob_temp_set'] = lambda t: GL.subs.set_temp(TecUnit.MIOB, float(t))
    _METHODS['set_miob_temp_raw_set'] = lambda t: GL.subs.set_temp(
        TecUnit.MIOB, float(t), bypass_ramp=True)

    _METHODS['set_shga_temp_set'] = lambda t: GL.subs.set_temp(TecUnit.SHGA, float(t))
    _METHODS['set_shga_temp_raw_set'] = lambda t: GL.subs.set_temp(
        TecUnit.SHGA, float(t), bypass_ramp=True)

    _METHODS['set_shgb_temp_set'] = lambda t: GL.subs.set_temp(TecUnit.SHGB, float(t))
    _METHODS['set_shgb_temp_raw_set'] = lambda t: GL.subs.set_temp(
        TecUnit.SHGB, float(t), bypass_ramp=True)

    _METHODS['set_nu_prop'] = GL.subs.set_error_scale
    _METHODS['set_nu_offset'] = GL.subs.set_error_offset
    _METHODS['switch_rf_clock_source'] = GL.subs.switch_rf_clock_source
    _METHODS['switch_mo'] = lambda on: GL.subs.switch_ld(subsystems.LdDriver.MASTER_OSCILLATOR, on)
    _METHODS['switch_pa'] = lambda on: GL.subs.switch_ld(subsystems.LdDriver.POWER_AMPLIFIER, on)
    _METHODS['switch_nu_ramp'] = GL.subs.switch_pii_ramp
    _METHODS['switch_nu_lock'] = GL.subs.switch_lock
    _METHODS['switch_temp_ramp'] = GL.subs.switch_temp_ramp
    _METHODS['switch_tec'] = GL.subs.switch_tec
    _METHODS['switch_integrator'] = GL.subs.switch_integrator
    _METHODS['setflag'] = GL.face.set_flag

    _METHODS['start_runlevel'] = runlevels.start_runner
    _METHODS['stop_runlevel'] = runlevels.stop_runner

    _METHODS['texus_override_enable'] = _enable_texus_override
    _METHODS['texus_override'] = _texus_override_parser

def _texus_override_parser(entity: str, value: Union[bool, int]) -> None:
    if not REQUEST.is_override:
        LOGGER.error("Won't accept TEXUS override, as manual override is disabled.")
        return

    LOGGER.info("Overriding %s to be %s...", entity, value)
    try:
        if entity == 'liftoff':
            REQUEST.liftoff = bool(value)
        elif entity == 'microg':
            REQUEST.microg = bool(value)
        elif entity == 'off':
            REQUEST.off = bool(value)
        elif entity == 'level':
            REQUEST.level = runlevels.Runlevel(int(value))
        else:
            LOGGER.error("Unknown TEXUS quantity ('%s').", entity)
    except (ValueError, TypeError, ArithmeticError):  # who knows...
        LOGGER.error("Error parsing value %s for TEXUS override.", value)
        LOGGER.debug("Exc. info: ", exc_info=True)
