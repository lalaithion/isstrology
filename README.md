# ISStrology

Give it a **date, time, location, and an object** and it tells you which
**zodiac sign that object was crossing** at that moment, as seen from exactly
where you stood.

Track low-orbit satellites (the ISS, Hubble, Mir, Vanguard-1 …) or distant
worlds (Pluto, Eris, Sedna …). The contrast is the fun: a satellite at ~400 km
has enormous parallax, so its sign depends on your location and changes every
few minutes — while a dwarf planet billions of km away looks the same from
anywhere on Earth.

## Objects

- **Satellites & stations:** ISS, Tiangong, Hubble, Vanguard-1 (oldest object
  still in orbit, 1958), Mir, Skylab, Salyut 1 (the first space station, 1971).
- **Dwarf planets & distant worlds:** Pluto, Ceres, Eris, Haumea, Makemake, Sedna.

## How it works

Two pipelines behind one interface (`app/targets.py`):

- **Satellites** — closest-epoch TLE (binary search over a bundled history) →
  SGP4 → subtract the observer's position (parallax!) → ecliptic longitude → sign.
- **Bodies** — JPL DE421 ephemeris (Pluto directly; the dwarf planets via
  two-body propagation of JPL osculating elements) → observed from Earth → sign.

```
app/targets.py      registry of objects + how to locate each (the extension seam)
app/astronomy.py    shared: position -> ecliptic longitude -> sign, timezone handling
app/tle_archive.py  load a satellite's TLE history, nearest-by-epoch lookup
app/zodiac.py       ecliptic longitude -> sign
app/geocode.py      place name -> lat/lon (Nominatim)
app/main.py         FastAPI routes + one HTML page
scripts/fetch_tle_history.py   builds data/tle/<key>.txt.gz for every satellite
scripts/fetch_bodies.py        downloads DE421 + JPL elements for the bodies
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

### Fetch the data

**Bodies (no account needed):**

```bash
python scripts/fetch_bodies.py        # DE421 ephemeris + dwarf-planet elements
python scripts/precompute_bodies.py   # -> data/bodies_grid.npz (served at runtime)
```

The second step bakes each body's apparent ecliptic longitude + distance into a
daily grid, so the request path is a microsecond lookup with no ephemeris math.
DE421 is only needed for this build step, not at runtime.

**Satellites** need orbital data per object:

- *Full history (accurate for any past date back to each object's launch):*
  create a free account at <https://www.space-track.org>, then

  ```bash
  export SPACETRACK_USER='you@example.com'
  export SPACETRACK_PASS='your-password'
  python scripts/fetch_tle_history.py        # all satellites, one session
  ```

- *Quick start (no account, recent dates only, in-orbit objects only):*

  ```bash
  python scripts/fetch_tle_history.py --bootstrap
  ```

  Decayed stations (Mir, Skylab, Salyut 1) have no current TLE and need the
  authenticated full-history fetch.

## Run

```bash
uvicorn app.main:app --reload
# open http://127.0.0.1:8000
```

## Test

```bash
pytest
```

Satellite tests use a synthetic archive (no network/data). Body tests run only
once `scripts/fetch_bodies.py` has been run.

## Deploy (Render)

`render.yaml` defines a Docker web service that ships the `data/` directory
(TLE histories, DE421, body elements) so no fetch is needed at boot.

## Extending

Add an object = one entry in `app/targets.py` (`_SATELLITES` or `_BODIES`) plus
its data file. Satellites only need a NORAD id; bodies a name JPL recognizes.
Deliberately a flat registry, not a provider/router hierarchy.
