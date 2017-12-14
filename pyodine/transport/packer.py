"""Create pyodine-flavoured JSON strings out of Python objects.
"""
import json
import logging
from typing import Dict, Any  # pylint: disable=unused-import
from .. import constants as cs

LOGGER = logging.getLogger('pyodine.transport.packer')


def create_message(payload: dict, msg_type: str) -> str:
    """Wrap the passed payload into a pyodine-flavoured JSON-String.
    """
    if msg_type in cs.MESSAGE_TYPES:
        container = {}  # type: Dict[str, Any]
        container['data'] = payload
        container['type'] = msg_type
        container['checksum'] = ''  # TODO
        message = json.dumps(container, sort_keys=True)
        message = message.replace('NaN', 'null')
        message += "\n\n\n"
    else:
        LOGGER.warning("Unknown message type %s. Returning empty message.",
                       msg_type)
        message = ''
    return message


def is_valid_message(msg: str) -> bool:
    return has_msg_suffix(msg) and has_msg_prefix(msg)


def has_msg_suffix(msg: str) -> bool:
    return msg[-4:] == '}\n\n\n'


def has_msg_prefix(msg: str) -> bool:
    return msg[0] == '{'
