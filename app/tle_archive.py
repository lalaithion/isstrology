"""Loads the bundled ISS TLE history once at startup and answers "which elset
is closest in time to instant T" via binary search. The closest-epoch TLE is
what SGP4 should propagate from: accuracy degrades the further T is from the
elset's epoch (the ISS also reboosts periodically), so nearest-in-time wins."""

from __future__ import annotations

import bisect
import gzip
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# Either filename works; the gzipped form is what the fetch script ships.
_CANDIDATES = ("iss_tle_history.txt.gz", "iss_tle_history.txt")


@dataclass(frozen=True)
class Elset:
    epoch: datetime  # tz-aware UTC
    line1: str
    line2: str


class TLEArchiveError(RuntimeError):
    pass


class OutOfCoverageError(ValueError):
    """Requested instant is outside the archive's epoch range."""


def parse_tle_epoch(line1: str) -> datetime:
    """Epoch lives in columns 19-32 of TLE line 1: 'YYDDD.DDDDDDDD'."""
    two_digit_year = int(line1[18:20])
    day_of_year = float(line1[20:32])
    year = 2000 + two_digit_year if two_digit_year < 57 else 1900 + two_digit_year
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    return start + timedelta(days=day_of_year - 1.0)


def _open(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")


def _iter_line_pairs(handle):
    """Yield (line1, line2) from a TLE stream, tolerating optional '0 NAME'
    title lines (3LE) and blank lines."""
    pending: str | None = None
    for raw in handle:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("1 ") and len(line) >= 69:
            pending = line
        elif line.startswith("2 ") and len(line) >= 69 and pending is not None:
            yield pending, line
            pending = None
        # title lines and anything else are ignored


class TLEArchive:
    def __init__(self, elsets: list[Elset]):
        if not elsets:
            raise TLEArchiveError("TLE archive is empty")
        self._elsets = elsets
        self._epochs = [e.epoch for e in elsets]

    @property
    def coverage(self) -> tuple[datetime, datetime]:
        return self._elsets[0].epoch, self._elsets[-1].epoch

    def nearest(self, when: datetime) -> Elset:
        """Closest elset by absolute time distance. Coverage bounds are enforced
        by the caller (targets._check_coverage) so the message can name the
        object; here we just return the nearest in time."""
        i = bisect_left(self._epochs, when)
        candidates = []
        if i < len(self._epochs):
            candidates.append(self._elsets[i])
        if i > 0:
            candidates.append(self._elsets[i - 1])
        return min(candidates, key=lambda e: abs(e.epoch - when))


def load_archive(path: Path | None = None) -> TLEArchive:
    if path is None:
        for name in _CANDIDATES:
            p = DATA_DIR / name
            if p.exists():
                path = p
                break
    if path is None or not path.exists():
        raise TLEArchiveError(
            "No TLE archive found in data/. Run scripts/fetch_tle_history.py "
            "to generate data/iss_tle_history.txt.gz."
        )
    elsets: list[Elset] = []
    with _open(path) as handle:
        for line1, line2 in _iter_line_pairs(handle):
            try:
                epoch = parse_tle_epoch(line1)
            except (ValueError, IndexError):
                continue
            elsets.append(Elset(epoch=epoch, line1=line1, line2=line2))
    elsets.sort(key=lambda e: e.epoch)
    # Drop exact-duplicate epochs (Space-Track history can repeat elsets).
    deduped: list[Elset] = []
    seen_epochs: list[datetime] = []
    for e in elsets:
        idx = bisect.bisect_left(seen_epochs, e.epoch)
        if idx < len(seen_epochs) and seen_epochs[idx] == e.epoch:
            continue
        seen_epochs.insert(idx, e.epoch)
        deduped.append(e)
    return TLEArchive(deduped)
