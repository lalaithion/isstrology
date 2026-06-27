"""Tropical zodiac: 12 equal 30 degree signs measured along the ecliptic from
the vernal equinox. `sign_for_longitude` is the only mapping the rest of the
app needs; keeping it isolated leaves room for a sidereal variant later."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Sign:
    name: str
    symbol: str
    flavor: str


# Order matters: index = floor(ecliptic_longitude / 30).
# Flavors describe the sign's vibe (object-neutral) so they read well for any
# tracked object: "Hubble was demanding the spotlight."
SIGNS: tuple[Sign, ...] = (
    Sign("Aries", "♈", "blazing and impatient"),
    Sign("Taurus", "♉", "steady and stubborn"),
    Sign("Gemini", "♊", "of two minds"),
    Sign("Cancer", "♋", "moody and tidal"),
    Sign("Leo", "♌", "demanding the spotlight"),
    Sign("Virgo", "♍", "precise and particular"),
    Sign("Libra", "♎", "poised and perfectly balanced"),
    Sign("Scorpio", "♏", "intense and secretive"),
    Sign("Sagittarius", "♐", "restless and far-roaming"),
    Sign("Capricorn", "♑", "patient and quietly ambitious"),
    Sign("Aquarius", "♒", "aloof and unconventional"),
    Sign("Pisces", "♓", "dreamy and adrift"),
)


def sign_for_longitude(ecliptic_longitude_deg: float) -> Sign:
    """Map an ecliptic longitude (degrees) to its zodiac sign."""
    index = int(ecliptic_longitude_deg % 360.0 // 30.0)
    return SIGNS[index]
