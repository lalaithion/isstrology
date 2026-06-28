"""Registry of trackable objects and how to locate each in the sky.

Two kinds of target, computed very differently:

  SatelliteTarget — live SGP4. The observer's position matters enormously (low
      orbits have huge parallax) and the sign shifts every few minutes, so there
      is nothing to precompute; the TLE history IS the precomputed input.

  BodyTarget — a pure lookup into a precomputed daily grid (see body_grid.py and
      scripts/precompute_bodies.py). Bodies move slowly and their parallax is
      negligible, so the heavy ephemeris/Kepler math is done once at build time
      and kept out of the request path entirely.

Adding an object = one catalog entry plus its data; deliberately a flat registry,
not a provider/router hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from skyfield.api import EarthSatellite, load, wgs84

from . import body_grid, tle_archive
from .tle_archive import OutOfCoverageError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TLE_DIR = DATA_DIR / "tle"
BODY_DIR = DATA_DIR / "bodies"
EPHEM_PATH = DATA_DIR / "ephemeris" / "de421.bsp"  # build-time input only

AU_KM = 149_597_870.7
_GRACE = timedelta(days=14)

# One timescale for the whole app (built-in data, no runtime network).
_ts = load.timescale()


def timescale():
    return _ts


class MissingDataError(RuntimeError):
    """A target's data file hasn't been built/fetched yet."""


@dataclass(frozen=True)
class TargetMeta:
    key: str
    name: str
    emoji: str
    category: str  # "satellite" | "body"
    blurb: str


@dataclass(frozen=True)
class Observation:
    """Final, display-ready values for one object. Satellite-only fields are
    None for bodies (which the UI never asks of them)."""
    ecliptic_longitude: float
    distance_au: float
    distance_km: float | None = None
    ra_hours: float | None = None
    dec_degrees: float | None = None
    altitude_degrees: float | None = None
    azimuth_degrees: float | None = None
    visible: bool | None = None
    provenance: str = ""
    confidence: str = "high"


# --- catalogs -------------------------------------------------------------

# (key, name, emoji, NORAD id, decayed?, blurb)
_SATELLITES = [
    ("iss", "the ISS", "🛰️", 25544, False,
     "the International Space Station, home since 1998"),
    ("tiangong", "Tiangong", "🇨🇳", 48274, False,
     "China's space station, crewed since 2021"),
    ("hubble", "Hubble", "🔭", 20580, False,
     "the Hubble Space Telescope, watching the cosmos since 1990"),
    ("vanguard1", "Vanguard 1", "🥫", 5, False,
     "the oldest human-made object still in orbit (launched 1958)"),
    ("mir", "Mir", "🚉", 16609, True,
     "the Soviet/Russian station that flew 1986–2001"),
    ("skylab", "Skylab", "🛰️", 6633, True,
     "America's first space station, 1973–1979"),
    ("salyut1", "Salyut 1", "☭", 5160, True,
     "the first space station ever, briefly aloft in 1971"),
]

# (key, name, emoji, ephemeris-segment-name | None, blurb). The segment name is
# only used by the build script (Pluto reads straight from the ephemeris; the
# rest come from osculating elements). At serve time every body is a grid lookup.
_BODIES = [
    ("pluto", "Pluto", "♇", "pluto barycenter",
     "the famous demoted dwarf planet"),
    ("ceres", "Ceres", "⚳", None,
     "the dwarf planet in the asteroid belt"),
    ("eris", "Eris", "🪨", None,
     "the scattered-disk dwarf planet whose discovery demoted Pluto"),
    ("haumea", "Haumea", "🥚", None,
     "an egg-shaped dwarf planet with its own ring"),
    ("makemake", "Makemake", "🗿", None,
     "a bright Kuiper-belt dwarf planet"),
    ("sedna", "Sedna", "❄️", None,
     "a remote world on an 11,000-year orbit"),
]

_BODY_GRID_MISSING = (
    "Precomputed body data is missing. Run scripts/fetch_bodies.py then "
    "scripts/precompute_bodies.py."
)


@lru_cache(maxsize=16)
def _load_tle_archive(key: str) -> tle_archive.TLEArchive:
    path = TLE_DIR / f"{key}.txt.gz"
    try:
        return tle_archive.load_archive(path)
    except tle_archive.TLEArchiveError as exc:
        raise MissingDataError(str(exc)) from exc


def _confidence(staleness_hours: float) -> str:
    if staleness_hours <= 6:
        return "high"
    if staleness_hours <= 48:
        return "moderate"
    return "low"


def _check_coverage(meta: TargetMeta, first, last, when, *, decayed=False) -> None:
    """Raise an object-aware OutOfCoverageError if `when` is outside coverage."""
    if when < first - _GRACE:
        if meta.category == "satellite":
            msg = (f"{meta.name.capitalize()} wasn't in orbit yet — tracking "
                   f"begins {first:%B %-d, %Y}. Try a later date.")
        else:
            msg = (f"Our ephemeris only reaches back to {first:%Y}. "
                   f"Pick a date after {first:%B %-d, %Y}.")
        raise OutOfCoverageError(msg)
    if when > last + _GRACE:
        if meta.category != "satellite":
            msg = (f"Our ephemeris only runs through {last:%Y}. "
                   f"Pick a date on or before {last:%B %-d, %Y}.")
        elif decayed:
            msg = (f"{meta.name.capitalize()} had re-entered the atmosphere by "
                   f"then — it was tracked until {last:%B %-d, %Y}. "
                   f"Try a date on or before that.")
        else:
            msg = (f"That's beyond our data for {meta.name} (through "
                   f"{last:%B %-d, %Y}); its orbit can't be predicted reliably "
                   f"much past then. Try an earlier date.")
        raise OutOfCoverageError(msg)


# --- target types ---------------------------------------------------------

class SatelliteTarget:
    def __init__(self, meta: TargetMeta, norad_id: int, decayed: bool):
        self.meta = meta
        self.norad_id = norad_id
        self.decayed = decayed

    def coverage(self) -> tuple[datetime, datetime]:
        return _load_tle_archive(self.meta.key).coverage

    def observe(self, when_utc, lat, lon, elevation_m=0.0) -> Observation:
        archive = _load_tle_archive(self.meta.key)
        first, last = archive.coverage
        _check_coverage(self.meta, first, last, when_utc, decayed=self.decayed)
        elset = archive.nearest(when_utc)

        sat = EarthSatellite(elset.line1, elset.line2, self.meta.name, _ts)
        observer = wgs84.latlon(lat, lon, elevation_m=elevation_m)
        t = _ts.from_datetime(when_utc)
        pos = (sat - observer).at(t)

        _lat, ecl_lon, _ = pos.ecliptic_latlon(epoch=t)
        ra, dec, dist = pos.radec(epoch=t)
        alt, az, _ = pos.altaz()
        staleness_h = abs((when_utc - elset.epoch).total_seconds()) / 3600.0
        return Observation(
            ecliptic_longitude=ecl_lon.degrees % 360.0,
            distance_km=dist.km,
            distance_au=dist.au,
            ra_hours=ra.hours,
            dec_degrees=dec.degrees,
            altitude_degrees=alt.degrees,
            azimuth_degrees=az.degrees,
            visible=alt.degrees > 0.0,
            provenance=(f"orbital element set from {elset.epoch:%Y-%m-%d %H:%M UTC} "
                        f"({staleness_h:.0f}h from your moment)"),
            confidence=_confidence(staleness_h),
        )


class BodyTarget:
    def __init__(self, meta: TargetMeta, segment_name: str | None):
        self.meta = meta
        self.segment_name = segment_name  # used only by the build script

    def coverage(self) -> tuple[datetime, datetime]:
        try:
            return body_grid.coverage()
        except FileNotFoundError as exc:
            raise MissingDataError(_BODY_GRID_MISSING) from exc

    def observe(self, when_utc, lat, lon, elevation_m=0.0) -> Observation:
        first, last = self.coverage()
        _check_coverage(self.meta, first, last, when_utc)
        try:
            ecl_lon, dist_au = body_grid.lookup(self.meta.key, when_utc)
        except FileNotFoundError as exc:
            raise MissingDataError(_BODY_GRID_MISSING) from exc
        return Observation(
            ecliptic_longitude=ecl_lon,
            distance_au=dist_au,
            provenance="precomputed from JPL DE421 ephemeris",
            confidence="high",
        )


# --- registry -------------------------------------------------------------

@lru_cache(maxsize=1)
def _registry() -> dict[str, object]:
    reg: dict[str, object] = {}
    for key, name, emoji, norad, decayed, blurb in _SATELLITES:
        meta = TargetMeta(key, name, emoji, "satellite", blurb)
        reg[key] = SatelliteTarget(meta, norad, decayed)
    for key, name, emoji, segment, blurb in _BODIES:
        meta = TargetMeta(key, name, emoji, "body", blurb)
        reg[key] = BodyTarget(meta, segment)
    return reg


def get_target(key: str):
    target = _registry().get(key)
    if target is None:
        raise KeyError(key)
    return target


def all_targets() -> list:
    """All targets in display order (for the UI)."""
    return list(_registry().values())
