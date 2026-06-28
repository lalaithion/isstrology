"""The astronomy v1 only pretended to do, now for many objects.

Each target (see targets.py) returns a display-ready Observation; this module
maps its ecliptic longitude to a zodiac sign and assembles the result. Satellites
are computed live via SGP4 (observer parallax is huge in low orbit); bodies are a
lookup into a precomputed grid (they're slow and effectively location-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from . import targets
from .targets import MissingDataError, TargetMeta
from .tle_archive import OutOfCoverageError
from .zodiac import Sign, sign_for_longitude


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
    distance_au: float
    when_utc: datetime
    provenance: str
    confidence: str
    # Satellite-only (the observer-dependent geometry); None for bodies.
    distance_km: float | None = None
    ra_hours: float | None = None
    dec_degrees: float | None = None
    altitude_degrees: float | None = None
    azimuth_degrees: float | None = None
    visible: bool | None = None


def compute(target_key: str, when_utc: datetime, lat: float, lon: float,
            elevation_m: float = 0.0) -> SkyResult:
    """Sign (and supporting detail) of `target_key` at `when_utc` from (lat, lon).

    `when_utc` must be tz-aware UTC. Raises tle_archive.OutOfCoverageError if the
    instant is outside the target's coverage, targets.MissingDataError if the
    target's data hasn't been built, KeyError for an unknown target.
    """
    if when_utc.tzinfo is None:
        raise ValueError("when_utc must be timezone-aware (UTC)")
    when_utc = when_utc.astimezone(timezone.utc)

    target = targets.get_target(target_key)
    obs = target.observe(when_utc, lat, lon, elevation_m=elevation_m)

    return SkyResult(
        target=target.meta,
        sign=sign_for_longitude(obs.ecliptic_longitude),
        ecliptic_longitude=obs.ecliptic_longitude,
        distance_au=obs.distance_au,
        when_utc=when_utc,
        provenance=obs.provenance,
        confidence=obs.confidence,
        distance_km=obs.distance_km,
        ra_hours=obs.ra_hours,
        dec_degrees=obs.dec_degrees,
        altitude_degrees=obs.altitude_degrees,
        azimuth_degrees=obs.azimuth_degrees,
        visible=obs.visible,
    )


@dataclass(frozen=True)
class Row:
    """One object's outcome for the all-objects table."""
    meta: TargetMeta
    result: SkyResult | None
    status: str  # "ok" | "pre" | "post" | "nodata"
    note: str    # short human tag for non-ok rows


def compute_all(when_utc: datetime, lat: float, lon: float) -> list[Row]:
    """A Row for every registered object: its sign, or why it has none
    (not yet launched, re-entered, beyond our data)."""
    when_utc = when_utc.astimezone(timezone.utc)
    rows: list[Row] = []
    for target in targets.all_targets():
        meta = target.meta
        try:
            rows.append(Row(meta, compute(meta.key, when_utc, lat, lon), "ok", ""))
            continue
        except OutOfCoverageError:
            pass
        except MissingDataError:
            rows.append(Row(meta, None, "nodata", "Data not loaded"))
            continue
        # Out of coverage: classify as before-launch vs after-end for a tag.
        try:
            first, last = target.coverage()
        except MissingDataError:
            rows.append(Row(meta, None, "nodata", "Data not loaded"))
            continue
        if when_utc < first:
            note = ("Not yet launched" if meta.category == "satellite"
                    else "Please enter a date after 1900")
            rows.append(Row(meta, None, "pre", note))
        else:
            if meta.category != "satellite":
                note = "Please enter a date before 2052"
            elif getattr(target, "decayed", False):
                note = f"Re-entered {last:%Y}"
            else:
                note = f"Satellite positions not available after {last:%Y-%m-%d}"
            rows.append(Row(meta, None, "post", note))
    return rows
