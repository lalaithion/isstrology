"""Build data/bodies_grid.npz: each body's apparent ecliptic longitude (deg) and
Earth distance (AU) sampled daily across the DE421 range.

This is the heavy astronomy (ephemeris + two-body Kepler propagation + light-time)
done ONCE, offline, vectorized over all sample times — so the web app never runs
it per request. Inputs: data/ephemeris/de421.bsp and data/bodies/<key>.json from
scripts/fetch_bodies.py. Run after fetch_bodies.py:

    python scripts/precompute_bodies.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from skyfield.api import load, load_file
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN

try:  # public name in some Skyfield versions, underscored in others (1.49)
    from skyfield.keplerlib import KeplerOrbit
except ImportError:
    from skyfield.keplerlib import _KeplerOrbit as KeplerOrbit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.targets import _BODIES, BODY_DIR, EPHEM_PATH  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = DATA_DIR / "bodies_grid.npz"
STEP_DAYS = 1.0

_ts = load.timescale()


def _body(eph, key: str, segment_name: str | None):
    """The Skyfield target for a body: an ephemeris segment (Pluto) or a
    two-body orbit from JPL osculating elements (the dwarf planets)."""
    if segment_name is not None:
        return eph[segment_name]
    el = json.loads((BODY_DIR / f"{key}.json").read_text())
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


def main() -> None:
    if not EPHEM_PATH.exists():
        sys.exit("Missing data/ephemeris/de421.bsp — run scripts/fetch_bodies.py first.")
    eph = load_file(str(EPHEM_PATH))
    earth = eph["earth"]

    # Sample over the intersection of all ephemeris segment spans, inset a couple
    # days so light-time correction (which peeks slightly before each sample —
    # up to ~12h for distant Sedna) never reads past the ephemeris edge.
    segs = eph.spk.segments
    jd0 = math.ceil(max(s.start_jd for s in segs)) + 2
    jd_end = math.floor(min(s.end_jd for s in segs)) - 2
    jds = np.arange(jd0, jd_end + 1, STEP_DAYS)
    t = _ts.tdb_jd(jds)
    print(f"Sampling {len(jds)} days, {jd0} .. {jd_end} (JD), step {STEP_DAYS}d")

    arrays: dict[str, np.ndarray] = {
        "jd0": np.array(float(jd0)),
        "step": np.array(float(STEP_DAYS)),
        "n": np.array(len(jds)),
    }
    for key, name, _emoji, segment, _blurb in _BODIES:
        apparent = earth.at(t).observe(_body(eph, key, segment)).apparent()
        _lat, lon, dist = apparent.ecliptic_latlon(epoch=t)
        arrays[f"{key}_lon"] = lon.degrees.astype("float32")
        arrays[f"{key}_dist"] = dist.au.astype("float32")
        print(f"  {name}: lon {lon.degrees.min():.1f}–{lon.degrees.max():.1f}°, "
              f"dist {dist.au.min():.1f}–{dist.au.max():.1f} AU")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT_PATH, **arrays)
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
