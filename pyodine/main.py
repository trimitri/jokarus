"""Usually, this is the program you want to run.

It launches the lab control software and sets up the Pyodine server.
(not yet ;)
"""
import logging
import drivers.dds9_control

logging.basicConfig(level=logging.INFO)

dds = drivers.dds9_control.Dds9Control()

print(dds.get_frequencies())
print(dds.get_amplitudes())
print(dds.get_phases())
