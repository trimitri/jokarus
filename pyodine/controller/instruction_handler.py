"""Parses, checks and executes incoming instructions from external sources.
"""
import json
import logging
from .subsystems import Subsystems
from .interfaces import Interfaces

LOGGER = logging.getLogger("pyodine.controller.instruction_handler")


class InstructionHandler:

    def __init__(self, subsystem_controller: Subsystems,
                 interface_controller: Interfaces) -> None:
        self._subs = subsystem_controller
        self._face = interface_controller
        self.LEGAL_METHODS = {
                'set_mo_current': lambda c: self._subs.set_current('mo', c),
                'set_mo_temp': lambda t: self._subs.set_temp('mo', t),
                'set_pa_current': lambda c: self._subs.set_current('pa', c),
                'set_pa_temp': lambda t: self._subs.set_temp('pa', t),
                'switch_tec': self._subs.switch_tec,
                'switch_ld': self._subs.switch_ld,
                'setflag': self._face.set_flag,
                }

    def handle_instruction(self, message: str) -> None:
        try:
            container = json.loads(message)
            method = container['data']['method']
            arguments = container['data']['args']
            if method in self.LEGAL_METHODS:
                try:
                    LOGGER.debug("Calling method %s with arguments: %s",
                                 method, arguments)
                    (self.LEGAL_METHODS[method])(*arguments)
                except TypeError:
                    LOGGER.warning("Wrong type/number of arguments.")
            else:
                LOGGER.warn("Unknown method name (%s). Doing nothing.", method)
        except json.JSONDecodeError:
            LOGGER.warning("Instruction was no valid JSON string")
        except KeyError:
            LOGGER.warning("Instruction package was not of correct structure.")

    def _setflag(self, entity_id: str, state: bool) -> None:
        LOGGER.info('Setting flag "%s" to %s.', entity_id, state)
        # FIXME
