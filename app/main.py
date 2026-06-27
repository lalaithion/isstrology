"""ISStrology v2 web app: date + time + location -> the ISS's zodiac sign."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import astronomy, geocode, targets
from .tle_archive import OutOfCoverageError

logger = logging.getLogger("isstrology")
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ISStrology")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _target_groups():
    metas = [t.meta for t in targets.all_targets()]
    return (
        [m for m in metas if m.category == "satellite"],
        [m for m in metas if m.category == "body"],
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    satellites, bodies = _target_groups()
    return templates.TemplateResponse(
        request, "index.html", {"satellites": satellites, "bodies": bodies}
    )


def _parse_coords(lat: str | None, lon: str | None) -> tuple[float, float] | None:
    """Both coordinates present and numeric -> (lat, lon); otherwise None."""
    if not (lat and lat.strip()) or not (lon and lon.strip()):
        return None
    try:
        return float(lat), float(lon)
    except ValueError:
        return None


def _error(request: Request, message: str) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "result.html", {"error": message}, status_code=200
    )


@app.post("/calculate", response_class=HTMLResponse)
def calculate(
    request: Request,
    date: str = Form(...),
    time: str = Form(...),
    target: str = Form("iss"),
    place: str | None = Form(None),
    lat: str | None = Form(None),
    lon: str | None = Form(None),
):
    # Hidden lat/lon fields submit as "" when unused, so parse leniently:
    # empty -> absent. Coordinates (browser geolocation) win over a place name.
    coords = _parse_coords(lat, lon)
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
        return _error(
            request,
            "Add a location first — type a place name, or tap “📍 Use my location.”",
        )

    try:
        naive_local = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return _error(request, "That date or time didn't look right — please pick them again.")

    try:
        when_utc, tz_name = astronomy.local_to_utc(naive_local, location_lat, location_lon)
        result = astronomy.compute(target, when_utc, location_lat, location_lon)
    except OutOfCoverageError as exc:
        return _error(request, str(exc))
    except targets.MissingDataError:
        return _error(
            request,
            "We haven't loaded the orbital data for that object yet — try the "
            "ISS, or check back soon.",
        )
    except KeyError:
        return _error(request, "That object isn't on the menu — pick one from the list.")
    except Exception:  # last-resort guard: never show a raw 500 to the user
        logger.exception("Unexpected error computing sign")
        return _error(
            request,
            "Something went sideways working that out. Please try again — and if "
            "it keeps happening, try a slightly different time or place.",
        )

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "result": result,
            "location_label": location_label,
            "tz_name": tz_name,
            "local_time": naive_local,
        },
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
