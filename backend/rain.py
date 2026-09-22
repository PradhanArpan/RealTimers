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
import urllib.parse
import urllib.request

from fastapi import APIRouter, Query

from config import CITIES, DEFAULT_CITY

router = APIRouter(prefix="/v1/rain", tags=["rain"])
_cache: dict[str, tuple[float, dict]] = {}
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"


def _fetch(lat: float, lon: float) -> dict:
    q = urllib.parse.urlencode({"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": "precipitation",
                                "past_hours": 6, "forecast_hours": 6, "timezone": "Asia/Kolkata"})
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{q}", timeout=6) as r:
        return json.load(r)


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
        i = min(6, len(times))          # past_hours=6: the series starts six hours before now
        out = {"available": True, "city": key, "source": "Open-Meteo forecast, hourly, pilot-box centre",
               "attribution": ATTRIBUTION, "past_6h_mm": round(sum(mm[max(0, i - 6):i]), 1),
               "next_6h_mm": round(sum(mm[i:i + 6]), 1), "series": [{"time": t, "mm": v} for t, v in zip(times, mm)],
               "note": "Weather-model rain at kilometre scale -- not radar or a gauge; not yet driving the depth model."}
    except Exception as e:                     # no network, rate limit, schema change: say so, don't break the page
        out = {"available": False, "reason": type(e).__name__, "attribution": ATTRIBUTION}
    _cache[key] = (time.time(), out)
    return out
