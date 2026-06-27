"""The astronomy v1 only pretended to do, now for many objects.

For each target the registry (see targets.py) produces a Skyfield position seen
from the observer; this module reads its ecliptic longitude of date and maps it
to a zodiac sign. Earth satellites get there via SGP4 (where the observer's
position matters enormously — low-orbit parallax is huge); solar-system bodies
via a planetary ephemeris (where it barely matters at all)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from skyfield.api import wgs84

from . import targets
from .targets import TargetMeta
from .zodiac import Sign, sign_for_longitude

_ts = targets.timescale()


@lru_cache(maxsize=1)
def _timezone_finder():
    # Imported lazily: timezonefinder pulls in a large data blob at construction.
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def resolve_timezone(lat: float, lon: float) -> str:
    """IANA tz name for a coordinate, or 'UTC' over open ocean / unknown."""
    name = _timezone_finder().timezone_at(lat=lat, lng=lon)
    return name or "UTC"


def local_to_utc(naive_local: datetime, lat: float, lon: float) -> tuple[datetime, str]:
    """Interpret a naive local wall-clock time at (lat, lon) as UTC.

    Users enter the time on the clock where they were; v1 wrongly assumed UTC.
    """
    tz_name = resolve_timezone(lat, lon)
    local = naive_local.replace(tzinfo=ZoneInfo(tz_name))
    return local.astimezone(timezone.utc), tz_name


@dataclass(frozen=True)
class SkyResult:
    target: TargetMeta
    sign: Sign
    ecliptic_longitude: float
    ecliptic_latitude: float
    ra_hours: float
    dec_degrees: float
    altitude_degrees: float
    azimuth_degrees: float
    visible: bool
    distance_km: float
    distance_au: float
    when_utc: datetime
    provenance: str
    confidence: str


def compute(target_key: str, when_utc: datetime, lat: float, lon: float,
            elevation_m: float = 0.0) -> SkyResult:
    """Sign (and supporting detail) of `target_key` at `when_utc` from (lat, lon).

    `when_utc` must be tz-aware UTC. Raises tle_archive.OutOfCoverageError if the
    instant is outside the target's coverage, targets.MissingDataError if the
    target's data file hasn't been fetched, KeyError for an unknown target.
    """
    if when_utc.tzinfo is None:
        raise ValueError("when_utc must be timezone-aware (UTC)")
    when_utc = when_utc.astimezone(timezone.utc)

    target = targets.get_target(target_key)
    observer = wgs84.latlon(lat, lon, elevation_m=elevation_m)
    t = _ts.from_datetime(when_utc)

    obs = target.observe(t, observer, when_utc)
    pos = obs.position

    ecl_lat, ecl_lon, _ = pos.ecliptic_latlon(epoch=t)  # ecliptic of date
    ra, dec, distance = pos.radec(epoch=t)
    alt, az, _ = pos.altaz()

    return SkyResult(
        target=target.meta,
        sign=sign_for_longitude(ecl_lon.degrees),
        ecliptic_longitude=ecl_lon.degrees % 360.0,
        ecliptic_latitude=ecl_lat.degrees,
        ra_hours=ra.hours,
        dec_degrees=dec.degrees,
        altitude_degrees=alt.degrees,
        azimuth_degrees=az.degrees,
        visible=alt.degrees > 0.0,
        distance_km=distance.km,
        distance_au=distance.au,
        when_utc=when_utc,
        provenance=obs.provenance,
        confidence=obs.confidence,
    )
