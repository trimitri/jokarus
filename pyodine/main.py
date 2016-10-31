"""Usually, this is the program you want to run.

It launches the lab control software and sets up the Pyodine server.
"""
from drivers.dds9_control import Dds9Control

dds = Dds9Control()
dds.get_state()
