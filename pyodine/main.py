"""Usually, this is the program you want to run.

It launches the lab control software and sets up the Pyodine server.
"""
import logging
from drivers.dds9_control import Dds9Control

logging.basicConfig(level=logging.INFO)

dds = Dds9Control()
