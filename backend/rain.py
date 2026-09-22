"""
Real rainfall for each city, from Open-Meteo (free for non-commercial use,
no key, data CC BY 4.0).

    GET /v1/rain/now?city=bengaluru   hourly rain, past 6 h and next 6 h,
                                      at the centre of the city's pilot box

This is weather-model output at kilometre scale -- not radar and not a gauge.
It is shown beside the nowcast; it does not yet drive the depth model.
Cached 15 minutes, so a busy demo stays far inside Open-Meteo's daily limit.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Query

from config import CITIES, DEFAULT_CITY

router = APIRouter(prefix="/v1/rain", tags=["rain"])
_cache: dict[str, tuple[float, dict]] = {}
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"


def _fetch(lat: float, lon: float) -> dict:
    q = urllib.parse.urlencode({"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": "precipitation",
                                "past_days": 1, "forecast_days": 2, "timezone": "Asia/Kolkata"})
    req = urllib.request.Request(f"https://api.open-meteo.com/v1/forecast?{q}",
                                 headers={"User-Agent": "RealTimers-SIH26085/1.0 (realtimers.onrender.com)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def _ist_hour() -> str:
    """The current hour in India, as Open-Meteo labels it with timezone=Asia/Kolkata."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%dT%H:00")


@router.get("/now")
def rain_now(city: str = Query(DEFAULT_CITY)):
    key = city.lower()
    if key not in CITIES:
        return {"available": False, "reason": f"unknown city {city}"}
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    W, S, E, N = CITIES[key]["bbox"]
    try:
        d = _fetch((S + N) / 2, (W + E) / 2)
        times, mm = d["hourly"]["time"], [v or 0.0 for v in d["hourly"]["precipitation"]]
        now = _ist_hour()
        i = next((k for k, t in enumerate(times) if t >= now), len(times) - 1)
        out = {"available": True, "city": key, "source": "Open-Meteo forecast, hourly, pilot-box centre",
               "attribution": ATTRIBUTION, "past_6h_mm": round(sum(mm[max(0, i - 6):i]), 1),
               "next_6h_mm": round(sum(mm[i:i + 6]), 1),
               "series": [{"time": t, "mm": v} for t, v in zip(times[max(0, i - 6):i + 6], mm[max(0, i - 6):i + 6])],
               "note": "Weather-model rain at kilometre scale -- not radar or a gauge; not yet driving the depth model."}
    except urllib.error.HTTPError as e:        # Open-Meteo refused: keep its code and message
        try:
            msg = json.load(e).get("reason", "")
        except Exception:
            msg = ""
        out = {"available": False, "reason": f"HTTP {e.code} {msg}".strip(), "attribution": ATTRIBUTION}
    except Exception as e:                     # no network, timeout, schema change: say so, don't break the page
        out = {"available": False, "reason": type(e).__name__, "attribution": ATTRIBUTION}
    # a success is kept 15 minutes; a failure only 1, so a fix shows up quickly
    _cache[key] = (time.time() - (0 if out["available"] else 840), out)
    return out
