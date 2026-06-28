"""Generate data/tle/<key>.txt.gz for every satellite in the catalog.

The satellite catalog (NORAD ids, decayed flags) lives in app/targets.py so
there's a single source of truth; this script imports it.

Two modes:

  Full history (default) -- one authenticated Space-Track session that walks
  every satellite and downloads its complete elset history. Needs a free
  account; set creds via env vars SPACETRACK_USER / SPACETRACK_PASS. This is
  what production ships.

      python scripts/fetch_tle_history.py

  Bootstrap (--bootstrap) -- grab the current TLE for each non-decayed
  satellite from CelesTrak (no account) so the app runs end-to-end locally
  today. Only recent dates will be accurate; use this for development, not
  production. Decayed satellites (Mir, Skylab, Salyut 1) have no current TLE
  on CelesTrak and are skipped with a note.

      python scripts/fetch_tle_history.py --bootstrap
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
import time
from pathlib import Path

import httpx

# Single source of truth for the satellite catalog.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.targets import _SATELLITES  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TLE_DIR = DATA_DIR / "tle"

USER_AGENT = "isstrology-fetch-tle/1.0 (+https://github.com/; satellite tracker)"

SPACETRACK_BASE = "https://www.space-track.org"


def _spacetrack_query(norad: int) -> str:
    return (
        f"{SPACETRACK_BASE}/basicspacedata/query/class/gp_history/"
        f"NORAD_CAT_ID/{norad}/orderby/EPOCH%20asc/format/tle"
    )


def _celestrak_current(norad: int) -> str:
    return f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=tle"


def _write(key: str, text: str) -> int:
    """Write gzipped TLE text to data/tle/<key>.txt.gz; return elset count."""
    TLE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TLE_DIR / f"{key}.txt.gz"
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        f.write(text)
    n_pairs = sum(1 for line in text.splitlines() if line.startswith("1 "))
    size_kb = out_path.stat().st_size / 1024
    print(f"  Wrote {n_pairs} elsets to {out_path} ({size_kb:.0f} KB gzipped)")
    return n_pairs


def _selected(only):
    sats = [s for s in _SATELLITES if not only or s[0] in only]
    if only:
        unknown = set(only) - {s[0] for s in _SATELLITES}
        if unknown:
            sys.exit(f"Unknown satellite key(s): {', '.join(sorted(unknown))}")
    return sats


def fetch_full_history(only=None) -> None:
    user = os.environ.get("SPACETRACK_USER")
    password = os.environ.get("SPACETRACK_PASS")
    if not user or not password:
        sys.exit(
            "Set SPACETRACK_USER and SPACETRACK_PASS (free account at "
            "https://www.space-track.org). Or run with --bootstrap for a "
            "CelesTrak current-only archive."
        )
    headers = {"User-Agent": USER_AGENT}
    # One login session reused for every satellite, queried sequentially to
    # respect Space-Track's rate limits (<30 req/min, <300 req/hr).
    with httpx.Client(timeout=120.0, follow_redirects=True, headers=headers) as client:
        resp = client.post(
            f"{SPACETRACK_BASE}/ajaxauth/login",
            data={"identity": user, "password": password},
        )
        resp.raise_for_status()
        for i, (key, name, _emoji, norad, _decayed, _blurb) in enumerate(_selected(only)):
            if i:
                # Gentle pacing so we stay well under the per-minute cap.
                time.sleep(3.0)
            print(f"{name} (NORAD {norad}):")
            data = client.get(_spacetrack_query(norad))
            data.raise_for_status()
            if not data.text.lstrip().startswith("1 "):
                print(
                    f"  WARNING: no elsets returned for {name} (NORAD {norad}); "
                    f"skipping. Response: {data.text[:120]!r}"
                )
                continue
            _write(key, data.text)


def fetch_bootstrap(only=None) -> None:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
        for key, name, _emoji, norad, decayed, _blurb in _selected(only):
            if decayed:
                print(
                    f"{name} (NORAD {norad}): decayed — no current TLE on "
                    f"CelesTrak. Skipping; needs the authenticated full-history "
                    f"fetch (run without --bootstrap)."
                )
                continue
            print(f"{name} (NORAD {norad}):")
            resp = client.get(_celestrak_current(norad))
            resp.raise_for_status()
            text = resp.text
            # CelesTrak returns a 3-line set (name + 2 element lines); keep as-is.
            if "1 " not in text:
                print(
                    f"  WARNING: unexpected CelesTrak response for {name} "
                    f"(NORAD {norad}); skipping. Response: {text[:120]!r}"
                )
                continue
            _write(key, text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="CelesTrak current TLE only (no account); dev use.",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="KEY",
        help="Fetch only these satellite keys (e.g. --only salyut1). Default: all.",
    )
    args = parser.parse_args()
    if args.bootstrap:
        fetch_bootstrap(only=args.only)
    else:
        fetch_full_history(only=args.only)


if __name__ == "__main__":
    main()
