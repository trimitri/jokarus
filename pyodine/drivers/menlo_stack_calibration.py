import enum

class OscCard(enum.IntEnum):
    """All oscillator supply cards that where actually produced."""
    OSC1A = 4  # Card number 1 from stack A
    OSC2A = 5  # Card number 2 from stack A
    OSC3A = 6
    OSC4A = 7
    OSC1B = 31216  # Card number 1 from stack B
    OSC2B = 21216
    OSC3B = 41216
    OSC4B = 11216

LD_CURRENT_SETTER = {card: lambda x: x for card in OscCard}
LD_CURRENT_SETTER[OscCard.OSC1A] = lambda 
