"""Controls aspects of the host computer that is running pyodine."""

import os

def reboot() -> None:
    """Do a system reboot. Does not gracefully stop anything."""
    os.system('reboot')
