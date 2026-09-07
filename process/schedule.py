from datetime import datetime, time
from typing import Optional

SAMBOVAGT_AFSENDER_NOEGLEORD = [
    "hospital",
    "sygehus",
    "psykiatrien",
    "ouh",
    "hospice",
    "capio a/s",
]


def is_sambovagt_active(afsender: str, now: Optional[datetime] = None) -> bool:
    """Afgør om Sambovagt-perioden er aktiv på det angivne tidspunkt (default: nu).

    Afsenderen skal matche et af nøgleordene (hospital, Sygehus, Psykiatrien, OUH,
    Hospice, Capio A/S), ellers returneres False uden at tidspunktet tjekkes.

    Man-tor: 15:30-23:00
    Fredag: 13:30-23:00
    Lør-søn: 07:00-23:00
    """
    afsender_lower = (afsender or "").lower()
    if not any(nøgleord in afsender_lower for nøgleord in SAMBOVAGT_AFSENDER_NOEGLEORD):
        return False

    now = now or datetime.now()
    weekday = now.weekday()  # Mandag=0 ... Søndag=6
    t = now.time()

    if weekday in (0, 1, 2, 3):  # Man-tor
        return time(15, 30) <= t <= time(23, 0)
    elif weekday == 4:  # Fredag
        return time(13, 30) <= t <= time(23, 0)
    else:  # Lør-søn
        return time(7, 0) <= t <= time(23, 0)
