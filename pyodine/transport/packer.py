"""Create pyodine-flavoured JSON strings out of Python objects.
"""
import json
import logging
from typing import Dict, Any

LOGGER = logging.getLogger('pyodine.transport.packer')
MESSAGE_TYPES = ['readings', 'texus']


def create_message(payload: dict, msg_type: str) -> str:
    if msg_type in MESSAGE_TYPES:
        container = {}  # type: Dict[str, Any]
        container['data'] = payload
        container['type'] = msg_type
        container['checksum'] = ''  # FIXME
        message = json.dumps(container)
        message += "\n\n\n"
    else:
        LOGGER.warning("Unknown message type. Returning empty message.")
        message = ''
    return message


def is_valid_message(msg: str) -> bool:
    return has_msg_suffix(msg) and has_msg_prefix(msg)


def has_msg_suffix(msg: str) -> bool:
    return msg[-4:] == '}\n\n\n'


def has_msg_prefix(msg: str) -> bool:
    return msg[0] == '{'
