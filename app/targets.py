"""Registry of trackable objects and how to locate each in the sky.

Two kinds of target share one interface so the rest of the app stays uniform:

  SatelliteTarget — Earth satellites via SGP4 (ISS, Hubble, Mir, ...). The
      observer's position matters enormously here: low orbits have huge parallax.

  BodyTarget — solar-system bodies via a planetary ephemeris and (for the
      dwarf planets) two-body propagation of osculating elements. These are so
      far away that the observer's location barely changes the answer.

This is the one extension seam the app needs. Adding an object = one catalog
entry plus its data file; deliberately not a provider/router hierarchy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from skyfield.api import EarthSatellite, load, load_file, wgs84
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN

try:  # public in some Skyfield versions, underscore-prefixed in others (e.g. 1.49)
    from skyfield.keplerlib import KeplerOrbit
except ImportError:
    from skyfield.keplerlib import _KeplerOrbit as KeplerOrbit

from . import tle_archive
from .tle_archive import OutOfCoverageError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TLE_DIR = DATA_DIR / "tle"
BODY_DIR = DATA_DIR / "bodies"
EPHEM_PATH = DATA_DIR / "ephemeris" / "de421.bsp"

AU_KM = 149_597_870.7
_GRACE = timedelta(days=14)

# One timescale + ephemeris for the whole app (built-in data, no runtime network).
_ts = load.timescale()


def timescale():
    return _ts


class MissingDataError(RuntimeError):
    """A target's data file hasn't been fetched yet."""


@dataclass(frozen=True)
class TargetMeta:
    key: str
    name: str
    emoji: str
    category: str  # "satellite" | "body"
    blurb: str


@dataclass(frozen=True)
class Observation:
    position: object  # a Skyfield position: ecliptic_latlon / radec / altaz / distance
    provenance: str
    confidence: str


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
    ("salyut1", "Salyut 1", "☭", 4870, True,
     "the first space station ever, briefly aloft in 1971"),
]

# (key, name, emoji, ephemeris-segment-name | None, blurb). A segment name means
# read it straight from the ephemeris (Pluto); None means osculating elements.
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


# --- ephemeris helpers ----------------------------------------------------

@lru_cache(maxsize=1)
def _ephemeris():
    if not EPHEM_PATH.exists():
        raise MissingDataError(
            "Planetary ephemeris (de421.bsp) is missing. "
            "Run scripts/fetch_bodies.py."
        )
    return load_file(str(EPHEM_PATH))


@lru_cache(maxsize=1)
def _ephem_coverage() -> tuple[datetime, datetime]:
    """Intersection of all ephemeris segment spans, as UTC datetimes."""
    segs = _ephemeris().spk.segments
    start = max(s.start_jd for s in segs)
    end = min(s.end_jd for s in segs)
    return (
        _ts.tdb_jd(start).utc_datetime(),
        _ts.tdb_jd(end).utc_datetime(),
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

    def observe(self, t, observer, when_utc) -> Observation:
        archive = _load_tle_archive(self.meta.key)
        first, last = archive.coverage
        _check_coverage(self.meta, first, last, when_utc, decayed=self.decayed)
        elset = archive.nearest(when_utc)
        sat = EarthSatellite(elset.line1, elset.line2, self.meta.name, _ts)
        position = (sat - observer).at(t)
        staleness_h = abs((when_utc - elset.epoch).total_seconds()) / 3600.0
        provenance = (f"orbital element set from {elset.epoch:%Y-%m-%d %H:%M UTC} "
                      f"({staleness_h:.0f}h from your moment)")
        return Observation(position, provenance, _confidence(staleness_h))


class BodyTarget:
    def __init__(self, meta: TargetMeta, segment_name: str | None):
        self.meta = meta
        self.segment_name = segment_name

    def coverage(self) -> tuple[datetime, datetime]:
        return _ephem_coverage()

    def _body(self):
        eph = _ephemeris()
        if self.segment_name is not None:
            return eph[self.segment_name]
        # Two-body orbit from JPL osculating elements (plenty accurate for a
        # 30°-wide sign bin). _from_mean_anomaly is internal to Skyfield but the
        # dependency is version-pinned, so the signature is stable for us.
        el = _load_body_elements(self.meta.key)
        semilatus_rectum_au = el["a"] * (1.0 - el["e"] ** 2)
        orbit = KeplerOrbit._from_mean_anomaly(
            semilatus_rectum_au,
            el["e"],
            el["i"],
            el["om"],
            el["w"],
            el["ma"],
            _ts.tdb_jd(el["epoch"]),
            GM_SUN,
            center=10,  # heliocentric (Sun = SPK id 10)
        )
        return eph["sun"] + orbit

    def observe(self, t, observer, when_utc) -> Observation:
        first, last = _ephem_coverage()
        _check_coverage(self.meta, first, last, when_utc)
        eph = _ephemeris()
        position = (eph["earth"] + observer).at(t).observe(self._body()).apparent()
        return Observation(position, "JPL DE421 ephemeris", "high")


@lru_cache(maxsize=16)
def _load_body_elements(key: str) -> dict:
    path = BODY_DIR / f"{key}.json"
    if not path.exists():
        raise MissingDataError(
            f"Orbital elements for {key} are missing. Run scripts/fetch_bodies.py."
        )
    return json.loads(path.read_text())


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
