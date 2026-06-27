"""Fetch the data the BodyTarget pipeline needs (no authentication required).

Two steps, both run by default:

  (a) Download the JPL DE421 planetary ephemeris to data/ephemeris/de421.bsp
      via Skyfield's Loader (only if it isn't already there).

  (b) For each catalog body that uses osculating elements (everything except
      Pluto, which reads straight from the ephemeris), fetch elements from the
      JPL Small-Body Database and write data/bodies/<key>.json.

      python scripts/fetch_bodies.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

# Single source of truth for the body catalog.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.targets import _BODIES  # noqa: E402

from skyfield.api import Loader  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BODY_DIR = DATA_DIR / "bodies"
EPHEM_DIR = DATA_DIR / "ephemeris"
EPHEM_PATH = EPHEM_DIR / "de421.bsp"

USER_AGENT = "isstrology-fetch-bodies/1.0 (+https://github.com/; sky tracker)"

SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb.api"

# The six Keplerian elements BodyTarget._load_body_elements expects.
_ELEMENT_KEYS = ("a", "e", "i", "om", "w", "ma")


def fetch_ephemeris() -> None:
    EPHEM_DIR.mkdir(parents=True, exist_ok=True)
    if EPHEM_PATH.exists():
        print(f"Ephemeris already present: {EPHEM_PATH}")
        return
    print(f"Downloading DE421 ephemeris to {EPHEM_PATH} (~17 MB)...")
    loader = Loader(str(EPHEM_DIR))
    loader("de421.bsp")
    size_mb = EPHEM_PATH.stat().st_size / (1024 * 1024)
    print(f"Wrote {EPHEM_PATH} ({size_mb:.1f} MB)")


def fetch_body(client: httpx.Client, key: str, name: str) -> None:
    resp = client.get(SBDB_URL, params={"sstr": name, "full-prec": "true"})
    resp.raise_for_status()
    payload = resp.json()

    orbit = payload.get("orbit")
    if not orbit:
        print(f"  WARNING: SBDB returned no orbit for {name!r}; skipping.")
        return

    elements = {el["name"]: el["value"] for el in orbit["elements"]}
    record = {"epoch": float(orbit["epoch"])}
    for ekey in _ELEMENT_KEYS:
        record[ekey] = float(elements[ekey])
    record["name"] = name
    record["fetched_jd"] = record["epoch"]

    BODY_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BODY_DIR / f"{key}.json"
    out_path.write_text(json.dumps(record, indent=2) + "\n")
    print(
        f"  Wrote {out_path}: epoch={record['epoch']} a={record['a']} "
        f"e={record['e']} i={record['i']}"
    )


def fetch_bodies() -> None:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers) as client:
        for key, name, _emoji, segment, _blurb in _BODIES:
            if segment is not None:
                # Pluto (and any future ephemeris-segment body) needs no SBDB
                # fetch; it reads straight from the ephemeris.
                continue
            print(f"{name}:")
            fetch_body(client, key, name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ephemeris-only",
        action="store_true",
        help="Download only the DE421 ephemeris.",
    )
    parser.add_argument(
        "--bodies-only",
        action="store_true",
        help="Fetch only the small-body orbital elements.",
    )
    args = parser.parse_args()

    if not args.bodies_only:
        fetch_ephemeris()
    if not args.ephemeris_only:
        fetch_bodies()


if __name__ == "__main__":
    main()
