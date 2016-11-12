Electronic Components
=====================

Only some notable features are mentioned for each component, as details for all
components are available in their datasheets located in the Jokarus project
folder on Naqserv.

Frequency generator DDS9m
-------------------------

The `Model DDS9m 170MHz 4-Channel Signal Generator Module` is made by `Novatech
Instruments INC.`.

A driver written in Python is available for the DDS9 as part of the pyodine
project: :doc:`api/pyodine.drivers.dds9_control`

Oven-Controlled Oscillator AOCJY2
-----------------------------------

The `AOCJY2 Series` oven-controlled crystal oscillator is made by `Abracon
Corporation, CA`.

It will be used as an external clock source for the DDS9m signal generator. 
This oscillator, together with its circuitry designed by M. Schoch, produces an
output power of :math:`>1V_{rms}` at 100MHz. **Combined with a 6dB attenuator**,
this gives about 500mV RMS input voltage when connected to the DDS9m. This is at
the upper specified limit for input power from the clock source to DDS9m.
