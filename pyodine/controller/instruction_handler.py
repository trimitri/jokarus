"""Parses, checks and executes incoming instructions from external sources.

Security Policy
---------------
As this class's `handle_instruction()` deals with externally fed commands, it
must catch all possible errors itself and log and ignore the invalid
instruction.
"""
import json
import logging

# We use Dict in type annotations, but not in the code. Thus we need to tell
# both flake8 and pylint to ignore the "unused import" warning for the
# following line.
from typing import Callable, Dict  # noqa: F401 # pylint: disable=unused-import
from .subsystems import Subsystems
from .interfaces import Interfaces

# Define custom types.
LegalCall = Callable[..., None]  # pylint: disable=invalid-name

LOGGER = logging.getLogger("pyodine.controller.instruction_handler")
LOGGER.setLevel(logging.DEBUG)


# pylint: disable=too-few-public-methods
# The main method is the single functionality of this class.
class InstructionHandler:
    """This class receives external commands and forwards them."""

    def __init__(self, subsystem_controller: Subsystems,
                 interface_controller: Interfaces) -> None:
        self._subs = subsystem_controller
        self._face = interface_controller

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

            'set_mo_current_set': lambda c: self._subs.set_current('mo',
                                                                   float(c)),
            'set_vhbg_temp_set': lambda t: self._subs.set_temp('vhbg',
                                                               float(t)),
            'set_vhbg_temp_raw_set': lambda t: self._subs.set_temp(
                'vhbg', float(t), bypass_ramp=True),

            'set_pa_current_set': lambda c: self._subs.set_current('pa',
                                                                   float(c)),
            'set_miob_temp_set': lambda t: self._subs.set_temp('miob',
                                                               float(t)),
            'set_miob_temp_raw_set': lambda t: self._subs.set_temp(
                'miob', float(t), bypass_ramp=True),

            'set_shga_temp_set': lambda t: self._subs.set_temp(
                'shga', float(t)),
            'set_shga_temp_raw_set': lambda t: self._subs.set_temp(
                'shga', float(t), bypass_ramp=True),

            'set_shgb_temp_set': lambda t: self._subs.set_temp('shgb',
                                                               float(t)),
            'set_shgb_temp_raw_set': lambda t: self._subs.set_temp(
                'shgb', float(t), bypass_ramp=True),

            'set_nu_ramp_amplitude': lambda a: self._subs.set_ramp_amplitude(
                'nu', int(a)),
            'set_nu_prop': lambda f: self._subs.set_error_scale('nu', f),
            'set_nu_offset': lambda p: self._subs.set_error_offset('nu', p),
            'switch_rf_clock_source': self._subs.switch_rf_clock_source,
            'switch_ld': self._subs.switch_ld,
            'switch_nu_ramp': lambda f: self._subs.switch_pii_ramp('nu', f),
            'switch_nu_lock': lambda f: self._subs.switch_lock('nu', f),
            'switch_temp_ramp': self._subs.switch_temp_ramp,
            'switch_tec': self._subs.switch_tec,
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
