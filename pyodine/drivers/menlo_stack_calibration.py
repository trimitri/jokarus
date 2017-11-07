"""Enhance the Menlo stack accuracy by means of individual calibration.
"""
from . import menlo_stack as mnl

# Using linear fits on data acquired in a calibration run, we may improve the
# current driver accuracy. Data is on JOKARUS share.
LD_CURRENT_SETTER = {card: lambda I: I for card in mnl.OscCard}
"""Translate a desired current setpoint into a value to send to the stack."""
LD_CURRENT_SETTER[mnl.OscCard.OSC1A] = lambda I: 1.0430516711750952 * I + 10.07060657466415

LD_CURRENT_GETTER = {card: lambda x: x for card in mnl.OscCard}
"""Estimate the actual current given a menlo current reading."""
LD_CURRENT_GETTER[mnl.OscCard.OSC1A] = lambda I: 1.021324354657688 * I + 17.542087542087543

LD_CURRENT_SETPOINT_GETTER = {card: lambda x: x for card in mnl.OscCard}
"""Estimate the actual current setpoint given a menlo current setpoint reading."""
LD_CURRENT_SETPOINT_GETTER[mnl.OscCard.OSC1A] = lambda I: 0.9587252747252747 * I - 9.654945054945046
