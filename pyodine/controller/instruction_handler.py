"""Parses, checks and executes incoming instructions from external sources.
"""
import json
import logging
from typing import Callable, Dict
from .subsystems import Subsystems
from .interfaces import Interfaces

LegalCall = Callable[..., None]  # pylint: disable=unsubscriptable-object

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
            'set_mo_current': lambda c: self._subs.set_current('mo', float(c)),
            'set_mo_temp': lambda t: self._subs.set_temp('mo', float(t)),
            'set_mo_temp_raw': lambda t: self._subs.set_temp(
                'mo', float(t), bypass_ramp=True),
            'set_pa_current': lambda c: self._subs.set_current('pa', float(c)),
            'set_pa_temp': lambda t: self._subs.set_temp('pa', float(t)),
            'switch_ld': self._subs.switch_ld,
            'switch_pii_ramp': self._subs.switch_pii_ramp,
            'switch_temp_ramp': self._subs.switch_temp_ramp,
            'switch_tec': self._subs.switch_tec,
            'setflag': self._face.set_flag}  # type: Dict[str, LegalCall]

    def handle_instruction(self, message: str) -> None:
        try:
            container = json.loads(message)
            method = container['data']['method']
            arguments = container['data']['args']
            if method in self._methods:
                if isinstance(arguments, list):
                    try:
                        LOGGER.debug("Calling method %s with arguments: %s",
                                     method, arguments)
                        (self._methods[method])(*arguments)
                    except TypeError:
                        LOGGER.exception("Wrong type/number of arguments.")
                else:
                    LOGGER.error('"arguments" has to be an array (list)')
            else:
                LOGGER.error("Unknown method name (%s). Doing nothing.",
                             method)
        except json.JSONDecodeError:
            LOGGER.warning("Instruction was no valid JSON string")
        except KeyError:
            LOGGER.warning("Instruction package was not of correct structure.")
        except ValueError:
            LOGGER.exception("Received value couldn't be converted to correct"
                             "type.")
