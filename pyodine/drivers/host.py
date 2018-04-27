"""Controls aspects of the host computer that is running pyodine."""

import logging
import os

LOGGER = logging.getLogger("host")

def reboot() -> None:
    """Do a system reboot. Does not gracefully stop anything."""
    LOGGER.warning("Rebooting host computer now...")
    os.system('reboot')
