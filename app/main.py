"""ISStrology v2 web app: date + time + location -> every object's zodiac sign."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import astronomy, geocode

logger = logging.getLogger("isstrology")
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ISStrology")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


def _parse_coords(lat: str | None, lon: str | None) -> tuple[float, float] | None:
    """Both coordinates present and numeric -> (lat, lon); otherwise None."""
    if not (lat and lat.strip()) or not (lon and lon.strip()):
        return None
    try:
        return float(lat), float(lon)
    except ValueError:
        return None


_MY_LOCATION_RE = re.compile(r"(?i)^\s*my location\s*\((.*)\)\s*$")
_COORD_PAIR_RE = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def _coords_from_text(text: str | None) -> tuple[float, float] | None:
    """Pull a lat/lon pair from free text: a bare '40.1, -105.2' or the
    'My location (40.1, -105.2)' label the geolocate button writes — so editing
    those numbers works. Returns None for ordinary place names."""
    if not text:
        return None
    s = text.strip()
    wrapped = _MY_LOCATION_RE.match(s)
    if wrapped:
        s = wrapped.group(1)
    m = _COORD_PAIR_RE.match(s)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
        return (lat, lon)
    return None


def _error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "result.html", {"error": message}, status_code=200
    )


@app.post("/calculate", response_class=HTMLResponse)
def calculate(
    request: Request,
    year: str = Form(...),
    month: str = Form(...),
    day: str = Form(...),
    time: str = Form(...),
    place: str | None = Form(None),
    lat: str | None = Form(None),
    lon: str | None = Form(None),
):
    # Hidden lat/lon fields submit as "" when unused, so parse leniently:
    # empty -> absent. Coordinates (browser geolocation) win over a place name.
    # Explicit hidden fields (unedited geolocation) win; otherwise accept
    # coordinates typed/edited into the place box before falling back to geocoding.
    coords = _parse_coords(lat, lon) or _coords_from_text(place)
    if coords is not None:
        location_lat, location_lon = coords
        location_label = place.strip() if place and place.strip() else (
            f"{location_lat:.4f}, {location_lon:.4f}"
        )
    elif place and place.strip():
        try:
            found = geocode.geocode(place)
        except geocode.GeocodeError as exc:
            return _error(request, str(exc))
        location_lat, location_lon = found.lat, found.lon
        location_label = found.display_name
    else:
        return _error(request, "Please enter a location first.")

    try:
        y, mo, d = int(year), int(month), int(day)
        hh, mm = (int(p) for p in time.split(":"))
        naive_local = datetime(y, mo, d, hh, mm)
    except (ValueError, TypeError):
        return _error(request, "Your selected date is invalid.")

    try:
        when_utc, tz_name = astronomy.local_to_utc(naive_local, location_lat, location_lon)
        rows = astronomy.compute_all(when_utc, location_lat, location_lon)
    except Exception:  # last-resort guard: never show a raw 500 to the user
        logger.exception("Unexpected error computing signs")
        return _error(request, "An unexpected error occurred. Please try again.")

    satellites = [r for r in rows if r.meta.category == "satellite"]
    bodies = [r for r in rows if r.meta.category == "body"]
    hero = next((r for r in rows if r.meta.key == "iss"), None)
    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "hero": hero,
            "satellites": satellites,
            "bodies": bodies,
            "location_label": location_label,
            "tz_name": tz_name,
            "local_time": naive_local,
        },
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
