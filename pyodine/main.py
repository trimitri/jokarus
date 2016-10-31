"""Usually, this is the program you want to run.

It launches the lab control software and sets up the Pyodine server.
"""
import logging
from drivers.dds9_control import Dds9Control, Dds9Setting

logging.basicConfig(level=logging.DEBUG)

# dds = Dds9Control()
Dds9Setting([0, 0, 0, 0], [0, 0, None, 0], [0, 0, 0, 0])
Dds9Setting([0, 0, 0, 0], [0, 0, 0], [0, 0, 0, 0])

