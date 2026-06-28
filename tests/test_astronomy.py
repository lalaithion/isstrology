"""Satellite tests use a tiny synthetic archive (no network/data file). The
headline `test_location_changes_sign` proves the observer's position actually
moves the answer — the thing v1 got wrong. Body tests run only when the
ephemeris/elements have been fetched (they need data/ephemeris/de421.bsp)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import astronomy, targets, tle_archive
from app.body_grid import GRID_PATH
from app.tle_archive import OutOfCoverageError, TLEArchive, parse_tle_epoch
from app.zodiac import SIGNS, sign_for_longitude

# A real historical ISS TLE (epoch 2021-09-06), enough to propagate a few hours.
ISS_L1 = "1 25544U 98067A   21249.51782528  .00001764  00000-0  39879-4 0  9990"
ISS_L2 = "2 25544  51.6442 213.4501 0003193  85.0982  47.5572 15.48685836300438"
EPOCH = parse_tle_epoch(ISS_L1)

_HAS_BODIES = GRID_PATH.exists()
needs_bodies = pytest.mark.skipif(
    not _HAS_BODIES, reason="run scripts/fetch_bodies.py + scripts/precompute_bodies.py"
)


@pytest.fixture(autouse=True)
def synthetic_iss(monkeypatch):
    """Make the 'iss' target resolve to a one-elset synthetic archive.
    Replacing the function outright bypasses its lru_cache; monkeypatch restores
    the original on teardown."""
    archive = TLEArchive([tle_archive.Elset(EPOCH, ISS_L1, ISS_L2)])
    monkeypatch.setattr(targets, "_load_tle_archive", lambda key: archive)
    yield


def _when(hours_from_epoch: float = 1.0) -> datetime:
    return EPOCH + timedelta(hours=hours_from_epoch)


# --- zodiac mapping -------------------------------------------------------

def test_sign_mapping_covers_full_circle():
    assert sign_for_longitude(0).name == "Aries"
    assert sign_for_longitude(35).name == "Taurus"
    assert sign_for_longitude(359.9).name == "Pisces"
    assert sign_for_longitude(360).name == "Aries"  # wraps
    assert sign_for_longitude(-1).name == "Pisces"  # wraps negative


# --- registry -------------------------------------------------------------

def test_registry_has_satellites_and_bodies():
    cats = {t.meta.category for t in targets.all_targets()}
    assert cats == {"satellite", "body"}
    assert targets.get_target("iss").meta.category == "satellite"
    assert targets.get_target("pluto").meta.category == "body"


def test_unknown_target_raises():
    with pytest.raises(KeyError):
        astronomy.compute("nonesuch", _when(), lat=0, lon=0)


# --- satellite pipeline ---------------------------------------------------

def test_satellite_fields_are_sane():
    r = astronomy.compute("iss", _when(), lat=40.0, lon=-74.0)
    assert r.target.key == "iss"
    assert r.sign in SIGNS
    assert 0.0 <= r.ecliptic_longitude < 360.0
    assert 0.0 <= r.ra_hours < 24.0
    assert -90.0 <= r.dec_degrees <= 90.0
    assert r.visible == (r.altitude_degrees > 0.0)
    # ~400km overhead up to ~Earth-diameter when on the far side.
    assert 300 < r.distance_km < 14000
    assert r.confidence in {"high", "moderate", "low"}


def test_location_changes_sign():
    """Huge LEO parallax => different observers see different signs at one
    instant. Sample the globe and expect more than one sign."""
    when = _when()
    signs = {
        astronomy.compute("iss", when, lat=lat, lon=lon).sign.name
        for lat in range(-60, 61, 30)
        for lon in range(-180, 180, 30)
    }
    assert len(signs) > 1


def test_out_of_coverage_before_and_after():
    with pytest.raises(OutOfCoverageError):
        astronomy.compute("iss", datetime(1990, 1, 1, tzinfo=timezone.utc), 0, 0)
    with pytest.raises(OutOfCoverageError):
        astronomy.compute("iss", datetime(2099, 1, 1, tzinfo=timezone.utc), 0, 0)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        astronomy.compute("iss", datetime(2021, 9, 6, 13, 0), lat=0, lon=0)


def test_confidence_tracks_staleness():
    assert astronomy.compute("iss", _when(1), 0, 0).confidence == "high"
    assert astronomy.compute("iss", _when(24), 0, 0).confidence == "moderate"
    assert astronomy.compute("iss", _when(200), 0, 0).confidence == "low"


def test_parse_coords_treats_empty_as_absent():
    """Hidden lat/lon fields submit as '' when a place name is typed instead."""
    from app.main import _parse_coords

    assert _parse_coords("", "") is None
    assert _parse_coords(None, None) is None
    assert _parse_coords("40.0", "") is None
    assert _parse_coords("notanumber", "1.0") is None
    assert _parse_coords("40.0", "-105.0") == (40.0, -105.0)


def test_coords_from_text():
    """Editing the 'My location (...)' label, or typing a bare pair, works;
    ordinary place names don't get misread as coordinates."""
    from app.main import _coords_from_text

    assert _coords_from_text("My location (40.00076, -105.23902)") == (40.00076, -105.23902)
    assert _coords_from_text("40.7, -74.0") == (40.7, -74.0)
    assert _coords_from_text("Boulder, CO") is None
    assert _coords_from_text("") is None
    assert _coords_from_text(None) is None
    assert _coords_from_text("999, 0") is None  # out of range


# --- body pipeline (needs fetched ephemeris) ------------------------------

@needs_bodies
def test_pluto_from_ephemeris():
    when = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    r = astronomy.compute("pluto", when, lat=40.0, lon=-74.0)
    assert r.sign in SIGNS
    assert 0.0 <= r.ecliptic_longitude < 360.0
    assert r.distance_au > 25.0  # Pluto is ~30 AU out
    assert r.confidence == "high"


@needs_bodies
def test_dwarf_planet_from_elements():
    when = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    for key in ("ceres", "eris", "sedna"):
        r = astronomy.compute(key, when, lat=40.0, lon=-74.0)
        assert r.sign in SIGNS
        assert 0.0 <= r.ecliptic_longitude < 360.0
        assert r.distance_au > 1.0


@needs_bodies
def test_location_barely_matters_for_bodies():
    """Opposite of satellites: parallax is negligible, so the sign is the same
    from anywhere on Earth."""
    when = datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc)
    a = astronomy.compute("eris", when, lat=80, lon=0).sign.name
    b = astronomy.compute("eris", when, lat=-80, lon=180).sign.name
    assert a == b
