"""Serve-time lookup of precomputed body positions.

scripts/precompute_bodies.py samples each body's apparent ecliptic longitude and
Earth distance on a uniform daily grid (bodies move slowly and their parallax
from Earth's surface is negligible, so one geocentric series serves everyone).
Here we just index into that grid and linearly interpolate — microseconds, and
no Skyfield/ephemeris in the request path. Deliberately depends only on numpy so
it stays trivial to port."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

GRID_PATH = Path(__file__).resolve().parent.parent / "data" / "bodies_grid.npz"

_JD_UNIX_EPOCH = 2440587.5  # JD at 1970-01-01T00:00Z


@lru_cache(maxsize=1)
def _grid():
    """(jd0, step_days, n, {f'{key}_lon': arr, f'{key}_dist': arr}). Raises
    FileNotFoundError if the grid hasn't been built."""
    if not GRID_PATH.exists():
        raise FileNotFoundError(GRID_PATH)
    with np.load(GRID_PATH) as npz:
        jd0 = float(npz["jd0"])
        step = float(npz["step"])
        n = int(npz["n"])
        arrays = {k: npz[k] for k in npz.files if k.endswith(("_lon", "_dist"))}
    return jd0, step, n, arrays


def _jd_from_utc(when_utc: datetime) -> float:
    return when_utc.timestamp() / 86400.0 + _JD_UNIX_EPOCH


def _dt_from_jd(jd: float) -> datetime:
    return datetime.fromtimestamp((jd - _JD_UNIX_EPOCH) * 86400.0, tz=timezone.utc)


def coverage() -> tuple[datetime, datetime]:
    jd0, step, n, _ = _grid()
    return _dt_from_jd(jd0), _dt_from_jd(jd0 + (n - 1) * step)


def lookup(key: str, when_utc: datetime) -> tuple[float, float]:
    """(ecliptic_longitude_deg, distance_au) for `key` at `when_utc`."""
    jd0, step, n, arrays = _grid()
    lon_arr = arrays[f"{key}_lon"]
    dist_arr = arrays[f"{key}_dist"]

    x = (_jd_from_utc(when_utc) - jd0) / step
    i = int(math.floor(x))
    if i >= n - 1:
        return float(lon_arr[-1]) % 360.0, float(dist_arr[-1])
    if i < 0:
        return float(lon_arr[0]) % 360.0, float(dist_arr[0])

    frac = x - i
    l0, l1 = float(lon_arr[i]), float(lon_arr[i + 1])
    # Interpolate across the 0/360 wrap correctly.
    if l1 - l0 > 180:
        l1 -= 360
    elif l1 - l0 < -180:
        l1 += 360
    lon = (l0 + (l1 - l0) * frac) % 360.0
    dist = float(dist_arr[i]) + (float(dist_arr[i + 1]) - float(dist_arr[i])) * frac
    return lon, dist
