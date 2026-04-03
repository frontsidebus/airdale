"""Aviation data tools — NOTAM, METAR/TAF, ADS-B, charts, performance, airspace.

Each tool is an async function matching the Claude tool-use pattern.
All external API calls use httpx with configurable timeouts.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0


def _normalize_identifier(identifier: str) -> str:
    """Normalize airport identifier, adding K prefix only for US FAA codes.

    3-letter codes that look like US domestic (all alpha, no leading E/C/L/R
    which are common ICAO prefixes) get K-prefixed. 4-letter ICAO codes pass
    through unchanged.
    """
    identifier = identifier.strip().upper()
    if len(identifier) == 4:
        return identifier  # Already ICAO format
    if len(identifier) == 3 and identifier.isalpha():
        # Only prefix if it looks like a US FAA code (not a foreign 3-letter)
        return f"K{identifier}"
    return identifier


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class WeatherReport(BaseModel):
    """Parsed METAR/TAF weather data."""

    identifier: str
    raw_metar: str = ""
    raw_taf: str = ""
    wind: str = ""
    visibility: str = ""
    ceiling: str = ""
    temperature: str = ""
    dewpoint: str = ""
    altimeter: str = ""
    flight_category: str = ""  # VFR, MVFR, IFR, LIFR
    remarks: str = ""


class TrafficTarget(BaseModel):
    """A single ADS-B traffic target."""

    callsign: str = ""
    icao24: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_ft: float = 0.0
    heading: float = 0.0
    ground_speed_kt: float = 0.0
    vertical_rate_fpm: float = 0.0
    distance_nm: float = 0.0
    bearing: float = 0.0
    on_ground: bool = False


# ---------------------------------------------------------------------------
# NOTAM tool
# ---------------------------------------------------------------------------


async def get_notams(identifier: str) -> dict[str, Any]:
    """Fetch NOTAMs for an airport from the FAA NOTAM API.

    Args:
        identifier: Airport ICAO or FAA identifier (e.g., KJFK).

    Returns:
        Dict with NOTAMs or error message.
    """
    identifier = _normalize_identifier(identifier)

    url = "https://external-api.faa.gov/notamapi/v1/notams"
    params = {
        "icaoLocation": identifier,
        "notamType": "ALL",
        "sortBy": "effectiveStartDate",
        "sortOrder": "DESC",
    }

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            items = data.get("items", [])
            notams = []
            for item in items[:10]:  # Limit to 10 most recent
                props = item.get("properties", {})
                notams.append(
                    {
                        "id": props.get("coreNOTAMData", {}).get("notam", {}).get("id", ""),
                        "type": props.get("coreNOTAMData", {}).get("notam", {}).get("type", ""),
                        "text": props.get("coreNOTAMData", {}).get("notam", {}).get("text", ""),
                        "effective": props.get("coreNOTAMData", {})
                        .get("notam", {})
                        .get("effectiveStart", ""),
                        "expires": props.get("coreNOTAMData", {})
                        .get("notam", {})
                        .get("effectiveEnd", ""),
                    }
                )

            return {
                "identifier": identifier,
                "count": len(notams),
                "notams": notams,
            }

        except httpx.HTTPStatusError as e:
            logger.warning("NOTAM fetch failed for %s: %s", identifier, e)
            return {
                "error": f"NOTAM API returned {e.response.status_code}",
                "identifier": identifier,
            }
        except httpx.HTTPError as e:
            logger.warning("NOTAM fetch failed for %s: %s", identifier, e)
            return {"error": f"NOTAM fetch failed: {e}", "identifier": identifier}


# ---------------------------------------------------------------------------
# Weather (METAR/TAF) tool
# ---------------------------------------------------------------------------


async def get_weather(identifier: str) -> dict[str, Any]:
    """Fetch METAR and TAF from aviationweather.gov.

    Args:
        identifier: Airport ICAO identifier (e.g., KJFK).

    Returns:
        Parsed weather report or error.
    """
    identifier = _normalize_identifier(identifier)

    base_url = "https://aviationweather.gov/api/data"
    report = WeatherReport(identifier=identifier)

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        # Fetch METAR
        try:
            resp = await client.get(
                f"{base_url}/metar",
                params={"ids": identifier, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                metar = data[0] if isinstance(data, list) else data
                report.raw_metar = metar.get("rawOb", "")
                report.wind = f"{metar.get('wdir', '???')}° at {metar.get('wspd', '?')} kt"
                if metar.get("wgst"):
                    report.wind += f" gusting {metar['wgst']} kt"
                report.visibility = f"{metar.get('visib', '?')} sm"
                report.temperature = f"{metar.get('temp', '?')}°C"
                report.dewpoint = f"{metar.get('dewp', '?')}°C"
                report.altimeter = f"{metar.get('altim', '?')} inHg"
                report.flight_category = metar.get("fltcat", "")

                # Parse ceiling from cloud layers
                clouds = metar.get("clouds", [])
                for layer in clouds:
                    cover = layer.get("cover", "")
                    if cover in ("BKN", "OVC"):
                        report.ceiling = f"{cover} at {layer.get('base', '?')} ft"
                        break

        except httpx.HTTPError as e:
            logger.warning("METAR fetch failed for %s: %s", identifier, e)
            return {"error": f"METAR fetch failed: {e}", "identifier": identifier}

        # Fetch TAF
        try:
            resp = await client.get(
                f"{base_url}/taf",
                params={"ids": identifier, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data:
                taf = data[0] if isinstance(data, list) else data
                report.raw_taf = taf.get("rawTAF", "")
        except httpx.HTTPError:
            pass  # TAF is supplemental; don't fail if unavailable

    return report.model_dump()


# ---------------------------------------------------------------------------
# ADS-B traffic tool
# ---------------------------------------------------------------------------


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    r = 3440.065  # Earth radius in nm
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in degrees."""
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(
        math.radians(lat1)
    ) * math.cos(math.radians(lat2)) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


async def get_adsb_traffic(
    lat: float,
    lon: float,
    radius_nm: float = 30.0,
) -> dict[str, Any]:
    """Query OpenSky Network for nearby ADS-B traffic.

    Args:
        lat: Observer latitude.
        lon: Observer longitude.
        radius_nm: Search radius in nautical miles.

    Returns:
        Dict with list of traffic targets or error.
    """
    # Convert radius to lat/lon bounding box (approximate)
    lat_delta = radius_nm / 60.0  # 1 degree lat ≈ 60 nm
    cos_lat = math.cos(math.radians(lat))
    lon_delta = radius_nm / (60.0 * cos_lat) if abs(cos_lat) > 1e-6 else 180.0

    url = "https://opensky-network.org/api/states/all"
    params = {
        "lamin": lat - lat_delta,
        "lamax": lat + lat_delta,
        "lomin": lon - lon_delta,
        "lomax": lon + lon_delta,
    }

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            states = data.get("states", []) or []
            targets: list[dict[str, Any]] = []

            for s in states:
                if len(s) < 12:
                    continue
                t_lat = s[6]
                t_lon = s[5]
                if t_lat is None or t_lon is None:
                    continue

                dist = _haversine_nm(lat, lon, t_lat, t_lon)
                if dist > radius_nm:
                    continue

                brg = _bearing_deg(lat, lon, t_lat, t_lon)
                alt_m = s[7] or (s[13] if len(s) > 13 else 0) or 0
                alt_ft = alt_m * 3.28084

                target = TrafficTarget(
                    callsign=(s[1] or "").strip(),
                    icao24=s[0] or "",
                    latitude=t_lat,
                    longitude=t_lon,
                    altitude_ft=round(alt_ft),
                    heading=s[10] or 0,
                    ground_speed_kt=round((s[9] or 0) * 1.94384),  # m/s to kt
                    vertical_rate_fpm=round((s[11] or 0) * 196.85),  # m/s to fpm
                    distance_nm=round(dist, 1),
                    bearing=round(brg),
                    on_ground=s[8] or False,
                )
                targets.append(target.model_dump())

            # Sort by distance
            targets.sort(key=lambda t: t["distance_nm"])

            return {
                "observer": {"lat": lat, "lon": lon},
                "radius_nm": radius_nm,
                "count": len(targets),
                "traffic": targets[:20],  # Limit to 20 closest
            }

        except httpx.HTTPError as e:
            logger.warning("ADS-B query failed: %s", e)
            return {"error": f"ADS-B query failed: {e}"}


# ---------------------------------------------------------------------------
# Chart retrieval tool
# ---------------------------------------------------------------------------


async def get_charts(
    identifier: str,
    chart_type: str = "all",
) -> dict[str, Any]:
    """Retrieve aviation chart references from the FAA DTPP.

    Args:
        identifier: Airport ICAO identifier.
        chart_type: Chart type filter: 'all', 'apt', 'sid', 'star', 'iap'.

    Returns:
        Dict with chart URLs or error.
    """
    identifier = _normalize_identifier(identifier)

    url = f"https://api.aviationapi.com/v1/charts/{identifier}"

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

            # The API returns a dict keyed by identifier
            charts_raw = data.get(identifier, [])
            if isinstance(charts_raw, dict):
                charts_raw = [charts_raw]

            charts = []
            for chart in charts_raw:
                ctype = chart.get("chart_code", "").lower()
                if chart_type != "all" and ctype != chart_type.lower():
                    continue
                charts.append(
                    {
                        "name": chart.get("chart_name", ""),
                        "type": chart.get("chart_code", ""),
                        "url": chart.get("pdf_path", ""),
                    }
                )

            return {
                "identifier": identifier,
                "chart_type": chart_type,
                "count": len(charts),
                "charts": charts,
            }

        except httpx.HTTPError as e:
            logger.warning("Chart fetch failed for %s: %s", identifier, e)
            return {"error": f"Chart fetch failed: {e}", "identifier": identifier}


# ---------------------------------------------------------------------------
# Performance calculator tool
# ---------------------------------------------------------------------------


# Basic performance data for common sim aircraft (simplified)
_PERF_DATA: dict[str, dict[str, Any]] = {
    "C172": {
        "takeoff_ground_roll_ft": 960,
        "takeoff_50ft_distance_ft": 1685,
        "landing_ground_roll_ft": 550,
        "landing_50ft_distance_ft": 1295,
        "rate_of_climb_fpm": 730,
        "cruise_speed_kt": 122,
        "fuel_burn_gph": 8.5,
        "max_gross_weight_lbs": 2550,
        "best_glide_kt": 65,
    },
    "C152": {
        "takeoff_ground_roll_ft": 735,
        "takeoff_50ft_distance_ft": 1340,
        "landing_ground_roll_ft": 475,
        "landing_50ft_distance_ft": 1200,
        "rate_of_climb_fpm": 715,
        "cruise_speed_kt": 107,
        "fuel_burn_gph": 6.1,
        "max_gross_weight_lbs": 1670,
        "best_glide_kt": 60,
    },
    "PA28": {
        "takeoff_ground_roll_ft": 1000,
        "takeoff_50ft_distance_ft": 1600,
        "landing_ground_roll_ft": 600,
        "landing_50ft_distance_ft": 1300,
        "rate_of_climb_fpm": 660,
        "cruise_speed_kt": 117,
        "fuel_burn_gph": 8.0,
        "max_gross_weight_lbs": 2325,
        "best_glide_kt": 73,
    },
}

# Altitude correction: +12% per 1000ft density altitude for takeoff/landing
_ALT_CORRECTION_PER_1000FT = 0.12
# Temperature correction: +10% per 10°C above ISA
_TEMP_CORRECTION_PER_10C = 0.10
_ISA_TEMP_AT_SL = 15.0  # °C
_ISA_LAPSE_RATE = 2.0  # °C per 1000ft


async def calculate_performance(
    aircraft: str,
    weight: float = 0,
    altitude: float = 0,
    temperature: float = 15.0,
) -> dict[str, Any]:
    """Calculate estimated takeoff/landing performance.

    Uses simplified performance data with altitude and temperature corrections.

    Args:
        aircraft: Aircraft type code (e.g., C172, PA28).
        weight: Gross weight in lbs (0 = use max gross).
        altitude: Field elevation in feet.
        temperature: OAT in degrees Celsius.

    Returns:
        Performance estimates or error.
    """
    aircraft = aircraft.strip().upper()
    perf = _PERF_DATA.get(aircraft)
    if perf is None:
        available = ", ".join(_PERF_DATA.keys())
        return {"error": f"No performance data for {aircraft}. Available: {available}"}

    # ISA temperature at altitude
    isa_temp = _ISA_TEMP_AT_SL - (altitude / 1000) * _ISA_LAPSE_RATE
    temp_deviation = temperature - isa_temp

    # Correction factors
    alt_factor = 1.0 + (altitude / 1000) * _ALT_CORRECTION_PER_1000FT
    temp_factor = 1.0 + max(0, temp_deviation / 10) * _TEMP_CORRECTION_PER_10C

    # Weight correction (rough: distance scales with weight ratio squared)
    max_wt = perf["max_gross_weight_lbs"]
    actual_wt = weight if weight > 0 else max_wt
    weight_factor = (actual_wt / max_wt) ** 2 if max_wt > 0 else 1.0

    combined = alt_factor * temp_factor * weight_factor

    return {
        "aircraft": aircraft,
        "conditions": {
            "field_elevation_ft": altitude,
            "temperature_c": temperature,
            "isa_deviation_c": round(temp_deviation, 1),
            "weight_lbs": actual_wt,
        },
        "takeoff": {
            "ground_roll_ft": round(perf["takeoff_ground_roll_ft"] * combined),
            "over_50ft_ft": round(perf["takeoff_50ft_distance_ft"] * combined),
        },
        "landing": {
            "ground_roll_ft": round(perf["landing_ground_roll_ft"] * combined),
            "over_50ft_ft": round(perf["landing_50ft_distance_ft"] * combined),
        },
        "climb": {
            "rate_fpm": round(perf["rate_of_climb_fpm"] / alt_factor),
        },
        "cruise": {
            "speed_kt": perf["cruise_speed_kt"],
            "fuel_burn_gph": perf["fuel_burn_gph"],
        },
        "best_glide_kt": perf["best_glide_kt"],
        "note": "Estimates based on standard corrections. Verify against POH.",
    }


# ---------------------------------------------------------------------------
# Airspace info tool
# ---------------------------------------------------------------------------


async def get_airspace_info(
    lat: float,
    lon: float,
    altitude: float = 0,
) -> dict[str, Any]:
    """Query airspace classification for a given position and altitude.

    Uses a simplified logic based on common US airspace rules.
    In a production system this would query an airspace database or API.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        altitude: Altitude in feet MSL.

    Returns:
        Dict describing the airspace at this position.
    """
    # This is a simplified implementation. A production version would use
    # FAA airspace data (NASR, CIFP) or a service like airmap.com
    result: dict[str, Any] = {
        "position": {"lat": lat, "lon": lon},
        "altitude_ft": altitude,
        "airspace_classes": [],
        "restrictions": [],
        "notes": [],
    }

    # Basic altitude-based classification (simplified)
    if altitude >= 60000:
        result["airspace_classes"].append(
            {
                "class": "E",
                "description": "Class E airspace (above FL600)",
            }
        )
    elif altitude >= 18000:
        result["airspace_classes"].append(
            {
                "class": "A",
                "description": "Class A airspace (FL180-FL600). IFR only.",
            }
        )
        result["notes"].append("IFR flight plan required. Positive control.")
    else:
        result["airspace_classes"].append(
            {
                "class": "E/G",
                "description": "Class E or G airspace (position-dependent)",
            }
        )
        if altitude <= 1200:
            result["notes"].append("May be Class G below 1200 AGL in uncontrolled areas")

    result["notes"].append(
        "This is a simplified classification. Check sectional charts "
        "and NOTAMs for TFRs, MOAs, and restricted areas at this position."
    )

    return result
