"""Decodes and chops a bytestream into pyodine-flavoured JSON strings.
"""
import logging
from typing import List
from . import packer

LOGGER = logging.getLogger("pyodine.transport.decoder")
END_TOKEN = b'}\n\n\n'
MAX_MESSAGE_LENGTH = 10240  # in bytes


class Decoder:
    """Collect message chunks until complete JSON string is formed.
    """
    def __init__(self) -> None:
        self._rcv_buffer = b''

        # Complete messages, ready to be retrieved.
        self._msg_buffer = []  # type: List[str]

    def feed(self, data: bytes) -> None:
        """Feed the next chunk of bytes into the collecting mechanism."""
        LOGGER.debug('Feeding data into collector: %s ... %s',
                     data[:17], data[-16:])
        self._rcv_buffer += data

        if len(self._rcv_buffer) > MAX_MESSAGE_LENGTH:
            LOGGER.error("Receive buffer overflow. Message too long? "
                         "Resetting receive buffer.")
            self._rcv_buffer = b''

        # Comb out completed messages.
        else:
            while True:

                # Split buffer by messages.

                msg_boundary = self._rcv_buffer.find(END_TOKEN)
                if msg_boundary == -1:
                    break

                # Pop candidate from buffer.

                msg_candidate = (

                        # Get full message, including token.
                        self._rcv_buffer[:msg_boundary+len(END_TOKEN)]
                        ).decode(encoding='utf-8', errors='ignore')

                # Delete it from buffer.
                self._rcv_buffer = self._rcv_buffer[msg_boundary +
                                                    len(END_TOKEN):]

                # Store candidate if it is valid.

                if self._is_message(msg_candidate):
                    LOGGER.debug("Received complete message.")
                    self._msg_buffer.append(msg_candidate)
                else:
                    LOGGER.warning("Received invalid or incomplete message.")

    def _is_message(self, msg: str) -> bool:
        LOGGER.debug("Checking for validity: %s ... %s", msg[:17], msg[-16:])
        return packer.is_valid_message(msg)

    def n_pending(self) -> int:
        """Return the number of ready-to-retrieve complete messages."""
        return len(self._msg_buffer)

    def harvest(self) -> List[str]:
        """Returns all complete messages and deletes them.

        One would usually check n_pending() before."""
        crop = self._msg_buffer
        self._msg_buffer = []
        return crop
