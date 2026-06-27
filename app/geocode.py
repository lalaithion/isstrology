"""Place name -> (lat, lon) via OpenStreetMap Nominatim.

This is the only runtime network call in the app, and it's skipped entirely when
the browser sends coordinates directly. Results are cached to respect
Nominatim's usage policy (which also requires a descriptive User-Agent)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "isstrology2/2.0 (https://github.com/; contact via app)"


class GeocodeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Place:
    display_name: str
    lat: float
    lon: float


@lru_cache(maxsize=512)
def geocode(query: str) -> Place:
    query = query.strip()
    if not query:
        raise GeocodeError("Type a place name — like “Lisbon, Portugal.”")
    try:
        resp = httpx.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=10.0,
        )
        resp.raise_for_status()
        results = resp.json()
    except httpx.HTTPError as exc:
        raise GeocodeError(
            "Couldn't reach the place-lookup service just now. Give it another "
            "moment, or tap “📍 Use my location” instead."
        ) from exc
    if not results:
        raise GeocodeError(
            f"Couldn't find “{query}.” Try adding a region or country — "
            "like “Springfield, Illinois.”"
        )
    top = results[0]
    return Place(
        display_name=top.get("display_name", query),
        lat=float(top["lat"]),
        lon=float(top["lon"]),
    )
