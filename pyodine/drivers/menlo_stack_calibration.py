"""Enhance the Menlo stack accuracy by means of individual calibration.
"""
import enum

class OscCard(enum.Enum):
    """All oscillator supply cards that where actually produced."""
    OSC1A = 4  # Card number 1 from stack A
    OSC2A = 5  # Card number 2 from stack A
    OSC3A = 6
    OSC4A = 7
    OSC1B = 31216  # Card number 1 from stack B
    OSC2B = 21216
    OSC3B = 41216
    OSC4B = 11216

# Using linear fits on data acquired in a calibration run, we may improve the
# current driver accuracy. Data is on JOKARUS share.
LD_CURRENT_SETTER = {card: lambda I: I for card in OscCard}
"""Translate a desired current setpoint into a value to send to Menlo."""
LD_CURRENT_SETTER[OscCard.OSC1A] = lambda I: 1.0430516711750952 * I + 10.07060657466415

LD_CURRENT_GETTER = {card: lambda x: x for card in OscCard}
"""Estimate the actual current given a menlo current reading."""
LD_CURRENT_GETTER[OscCard.OSC1A] = lambda I: 1.021324354657688 * I + 17.542087542087543
