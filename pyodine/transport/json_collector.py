"""Imitate the .websocket_server functionality using RS232 instead of TCP/IP.
"""
import logging

LOGGER = logging.getLogger("pyodine.transport.json_collector")


class JsonCollector:
    """Collect message chunks until complete JSON string is formed.
    """

    MAX_CHUNKS = 100  # Max. number of messages to be combined into one.

    def __init__(self):
        self.max_n_chunks = 100
        self._rcv_buffer = b''
        self._n_chunks = 0

    def push(self, data: bytes) -> None:
        self._rcv_buffer += data
        self._n_chunks += 1

        if self._n_chunks > self.max_n_chunks:
            LOGGER.warning("Too many chunks in package. Resetting packager.")
            self._reset()

    def reset(self) -> None:
        self._rcv_buffer = b''
        self._n_chunks = 0

    def is_complete(self) -> bool:
        tester = self._rcv_buffer.decode(encoding='utf-8', errors='ignore')
        if tester[-4:] == '}\n\n\n':
            if tester[0] == '{':
                return True
            else:
                LOGGER.warning("Only received tail of a message. "
                               "Resetting collector.")
                self.reset()
        return False

    def harvest(self) -> str:
        """Returns the buffers content and empties it.

        You would usually call is_complete before."""
        result = self._rcv_buffer.decode(encoding='utf-8', errors='ignore')
        self.reset()
        return result
