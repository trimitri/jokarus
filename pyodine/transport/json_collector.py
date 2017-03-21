"""Json strings tend to be longer than the chunk size transferrable via RS232.

The JsonCollector class provides a joining service for split Json strings.
"""
import logging

LOGGER = logging.getLogger("pyodine.transport.json_collector")


class JsonCollector:
    """Collect message chunks until complete JSON string is formed.
    """
    def __init__(self):
        self.max_n_chunks = 100  # Max. # of messages to be combined into one.
        self._rcv_buffer = b''
        self._n_chunks = 0

    def push(self, data: bytes) -> None:
        LOGGER.debug('Pushing data into collector: %s', data[:30])
        self._rcv_buffer += data
        self._n_chunks += 1

        if self._n_chunks > self.max_n_chunks:
            LOGGER.warning("Too many chunks in package. Resetting packager.")
            self._reset()

    def reset(self) -> None:
        LOGGER.debug("Resetting collector.")
        self._rcv_buffer = b''
        self._n_chunks = 0

    def is_complete(self) -> bool:
        tester = self._rcv_buffer.decode(encoding='utf-8', errors='ignore')
        if tester[-4:] == '}\n\n\n':
            if tester[0] == '{':
                LOGGER.debug("Returning complete message.")
                return True
            else:
                LOGGER.warning("Only received tail of a message. "
                               "Resetting collector.")
                self.reset()
        LOGGER.debug("Message not a complete JSON string yet.")
        return False

    def harvest(self) -> str:
        """Returns the buffers content and empties it.

        You would usually call is_complete before."""
        result = self._rcv_buffer.decode(encoding='utf-8', errors='ignore')
        self.reset()
        return result
