"""Various constants determining the peculiarities and behaviour of JOKARUS.
"""
# pylint: disable=invalid-name

DAQ_ALLOWABLE_BLOCKING_TIME = 2
"""The DAQ may be blocked this many seconds before we assume that something has
gone wrong.
"""

DAQ_MAX_SCAN_AMPLITUDE = 19
"""Maximum allowable peak-peak amplitude in volts when doing DAQ signal scans.

As for the physical capabilities of the DAQ device, this must not exceed 20
volts.
"""

DAQ_MIN_RAMP_AMPLITUDE = .01  # Don't use less than 2 * 100mV peak-peak
"""When evaluating DAQ scans, don't consider anything with less amplitude than
~ * 10V to be a valid ramp.
"""

DAQ_ERR_RAMP_TRIM_FACTORS = [0.05, 0.02]
"""Trim these percentages (begin, end) off a ramp scan for err. sig. readings.

As the DAQ uses a Z-shaped signal for ramp scanning, there is mostly
useless and potentially misleading data at the beginning and end of the scan.
"""

DAQ_LOG_RAMP_TRIM_FACTORS = [0.1, 0.05]
"""Trim these percentages (begin, end) off a ramp scan for log port readings.

As the DAQ uses a Z-shaped signal for ramp scanning, there is mostly
useless and potentially misleading data at the beginning and end of the scan.
This is especially true for the logarithmic output port of the spectroscopy
module, as it has some low-pass behaviour.  Furthermore, the "LOG scan" is done
with max. amplitude, leading to some capping at the beginning and end.
"""

DAQ_SCAN_TIME = 0.5
"""The time to take for a frequency scan in seconds."""

MENLO_MINIMUM_WAIT = .2
"""The Menlo stack interface roundtrip time in seconds.

When sending a simple request to the menlo stack, it will take at most this
long until the change will be reflected in the readings.  "Simple" meaning,
that it doesn't take any hardware (current, temp.) to change.
"""

MESSAGE_TYPES = ['readings', 'texus', 'setup', 'signal', 'aux_temps']
"""Those types of messages can be sent out by pyodine.  Messages of types that
are not in this list will be dropped and not published.
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

LD_MO_TUNING_RANGE = [85, 155]
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

LOCKBOX_ALLOWABLE_IMBALANCE = .015
"""OK deviation of lockbox level from center position.

The Lockbox will be balanced if the level is further off than this.
Has to be in [0, .5], as the lockbox level is normalized to [0, 1] and one
can't deviate any further from 0.5 in this range.
"""

LOCKBOX_BALANCE_POINT = .45
"""The lockbox equilibrium position.

Where should a perfectly balanced lockbox be resting? This should be given with
respect to the [0, 1] lockbox control range interval.  Thus, the obvious choice
is 0.5.  However, off-center balance points could be of use for directional
locking!
"""

LOCKBOX_BALANCE_INTERVAL = 1.08
"""Chech for lock imbalance every ~ seconds."""

LOCKBOX_RAIL_ZONE = 0.1
"""The lockbox is considered railed this close to the edge of range of motion.

Given relative to range of motion.  For 20V RoM, a value of 0.1 would lead to
1V at the top and 1V at the bottom to be considered lost territory.
"""

LOCKBOX_RAIL_CHECK_INTERVAL = .84
"""Check a running lock every ~ seconds for loss of lock."""

LOCKBOX_RANGE_mV = [-10000, 10000]
"""What is the lockbox output stage able to generate?"""

LOCKBOX_P_TO_I_DELAY = .5
"""In engaging the lock, wait this many seconds after engaging the P stage and
before engaging the first integrator.
"""

LOCKBOX_I_TO_I_DELAY = 2
"""In engaging the lock, wait this many seconds after engaging the first
integrator stage and before engaging the second integrator.
"""

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

LOCKBOX_MHz_mV = LD_MO_MHz_mA * _LOCKBOX_mA_mV
"""Tuning coefficient of lockbox control output in MHz per Volt."""

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

PD_DO_PUBLISH = False
"""Publish photodiode readings every time they're inquired."""
PD_LOG_INTERVAL = 2.7
"""Interval [s] at which the auxiliary photodiode readings are acquired."""

RS232_MAX_MESSAGE_BYTES = 102400  # 100kiB
"""Maximum message size in bytes the RS232 relay has to expect from pyodine."""

# pylint: enable=invalid-name
