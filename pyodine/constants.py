"""Various constants determining the peculiarities and behaviour of JOKARUS.
"""
# pylint: disable=invalid-name

DAQ_DELAY_s = 0.2
"""How long does the DAQ take to physically realize a given setting.

This is guesswork.
"""

DAQ_RAMP_OFFSET_RANGE_V = [-0.5, 0.5]
"""The portion of the DAQ range of motion that is used for tuning the laser.

In order to not disturb lockbox railing detection, this is kept at a very small
range of motion.  We don't need it in JOKARUS anyway, because the "catching
directional lock" behaviour seems to work and thus we don't need such a fine
tuner during prelock.
"""

DAQ_GRANULARITY_V = 20 / 2**16
"""How fine can the DAQ analog output be set (in Volts)?

This is a 16 bit device.
"""

MIOB_TEMP_TUNING_RANGE = [24, 26]
"""Lowest and highest MiOB temperature available to the tuner.

Based on arbitrary guesswork.  Due to the tight current limit on the VHBG TEC,
we must not deviate from the VHBG working point too much.  5K should be safe,
as VHBG can reach about 7K difference.  Also, of course the upper and lower
limits must not damage any laser components.
"""

LD_MO_MHz_mA = -74
"""Laser detuning in Mhz per mA MO current change.

This is an estimate taken from the printed MiLas "user guide".
"""
# TODO: Conduct better measurement of Milas MHz per mA.

LD_MO_TUNING_RANGE = [80, 160]
"""Lowest and highest MO current available to the tuner.

Based on FBH preliminary spec sheet.
"""

LD_MO_DELAY_s = 1
"""How long does a new current take to settle in the system?

This is guesswork.
"""

LD_MO_DELAY_FULL_LOOP_s = 3
"""How long does a new current take to settle and be measured?

This is guesswork.
"""

LD_MO_GRANULARITY_mA = .125
"""Lowest current step the MO current driver will take.

This is accurately known due to the DAC resolution.
"""

LOCK_SFG_FACTOR = 2
"""The spectrum moves by this many Hz when tuning the laser by 1 Hz.

This is to allow for sum-frequency generation (SFG) setups.
"""

LOCKBOX_ALLOWABLE_IMBALANCE = .1
"""OK deviation of lockbox level from center position.

The Lockbox will be balanced if the level is further off than this.
Has to be in [0, .5], as the lockbox level is normalized to [0, 1] and one
can't deviate any further from 0.5 in this range.
"""

LOCKBOX_RANGE_mV = [-10000, 10000]
"""What is the lockbox output stage able to generate?"""

TEC_GRANULARITY_K = 0.0005
"""The lowest temperature step the TECs can do.

This is an approximate number empirically tested on 2017-11-09 to work at room
temp.
"""

###
# Private quantities only used for calculation
###

_LOCKBOX_mA_mV = 0.00079119970889856704
"""Actual LD current change in mA per applied ramp input (mV) into lockbox.

Fitted to the data taken on 2017-10-23.
"""

_LOCKBOX_MONITOR_mV = lambda x: 1.0226708051346947 * x + 21.502497351238581
"""Acquiring the actual lockbox control signal from the Menlo reading.

This was obtained from the data taken on 2017-10-23.
"""

_MIOB_mV_K = 95821.785132407866
"""Measured detuning of laser detuning (in lockbox mV) vs MiOB temp in K.

Acquired 2017-11-08 from a fit to a measurement taken 2017-11-07.
"""

###
# Calculated Quantities
###

MIOB_MHz_K = LD_MO_MHz_mA * _LOCKBOX_mA_mV * _MIOB_mV_K
"""Laser tuning in MHz per Kelvin of MiOB temperature change."""
# This is about 30% apart from a measurement that the FBH did
# (Tuningcurve.pdf):
# MIOB_MHz_K = -4330  # FBH measurement

DAQ_MHz_V = LD_MO_MHz_mA * _LOCKBOX_mA_mV * 1000
"""How far will the laser tune for 1V of DAQ ramp?"""

LOCKBOX_MHz_mV = LD_MO_MHz_mA * _LOCKBOX_mA_mV
"""Tuning coefficient of lockbox control output in MHz per Volt."""

#####################
# MiLas laser specs #
#####################

MILAS_MO_MAX = 180
"""MiLas value as agreed upon on 5.12., see ecdl_mopa.MopaSpec docstring."""
MILAS_MO_SEED = 60
"""MiLas value as agreed upon on 5.12., see ecdl_mopa.MopaSpec docstring."""
MILAS_PA_MAX = 1550
"""MiLas value as agreed upon on 5.12., see ecdl_mopa.MopaSpec docstring."""
MILAS_PA_TRANSPARENCY = 200
"""MiLas value as agreed upon on 5.12., see ecdl_mopa.MopaSpec docstring."""
MILAS_PA_BACKFIRE = 260
"""MiLas value as agreed upon on 5.12., see ecdl_mopa.MopaSpec docstring."""

# pylint: enable=invalid-name
