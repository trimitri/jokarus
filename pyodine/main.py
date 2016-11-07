"""Usually, this is the program you want to run.

It launches the lab control software and sets up the Pyodine server.
(not yet ;)
"""
import logging
import drivers.dds9_control

# Only execute if run as main program (not on import).
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    dds = drivers.dds9_control.Dds9Control()
    del(dds)
