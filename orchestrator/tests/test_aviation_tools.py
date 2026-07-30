"""Tests for aviation data tools — NOTAM, METAR, ADS-B, charts, performance, airspace."""

from __future__ import annotations

import httpx
import pytest
import respx

from orchestrator.aviation_tools import (
    _bearing_deg,
    _haversine_nm,
    calculate_performance,
    get_adsb_traffic,
    get_airspace_info,
    get_charts,
    get_notams,
    get_weather,
)

# ---------------------------------------------------------------------------
# NOTAM tool
# ---------------------------------------------------------------------------


class TestGetNotams:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_notam_fetch(self) -> None:
        respx.get("https://external-api.faa.gov/notamapi/v1/notams").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "properties": {
                                "coreNOTAMData": {
                                    "notam": {
                                        "id": "A0001/24",
                                        "type": "D",
                                        "text": "RWY 27L CLSD",
                                        "effectiveStart": "2024-01-01T00:00:00Z",
                                        "effectiveEnd": "2024-02-01T00:00:00Z",
                                    }
                                }
                            }
                        }
                    ]
                },
            )
        )
        result = await get_notams("KJFK")
        assert result["identifier"] == "KJFK"
        assert result["count"] == 1
        assert result["notams"][0]["text"] == "RWY 27L CLSD"

    @pytest.mark.asyncio
    @respx.mock
    async def test_notam_api_error(self) -> None:
        respx.get("https://external-api.faa.gov/notamapi/v1/notams").mock(
            return_value=httpx.Response(503)
        )
        result = await get_notams("KJFK")
        assert "error" in result

    @pytest.mark.asyncio
    @respx.mock
    async def test_notam_auto_prefix(self) -> None:
        """3-letter identifiers get K prefix."""
        respx.get("https://external-api.faa.gov/notamapi/v1/notams").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        result = await get_notams("JFK")
        assert result["identifier"] == "KJFK"


# ---------------------------------------------------------------------------
# Weather tool
# ---------------------------------------------------------------------------


class TestGetWeather:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_metar(self) -> None:
        respx.get("https://aviationweather.gov/api/data/metar").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "rawOb": "KJFK 021756Z 31009KT 10SM FEW250 15/M04 A3012",
                        "wdir": 310,
                        "wspd": 9,
                        "visib": 10,
                        "temp": 15,
                        "dewp": -4,
                        "altim": 30.12,
                        "fltcat": "VFR",
                        "clouds": [{"cover": "FEW", "base": 25000}],
                    }
                ],
            )
        )
        respx.get("https://aviationweather.gov/api/data/taf").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await get_weather("KJFK")
        assert result["identifier"] == "KJFK"
        assert result["flight_category"] == "VFR"
        assert "310" in result["wind"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_weather_with_ceiling(self) -> None:
        respx.get("https://aviationweather.gov/api/data/metar").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "rawOb": "KJFK 021756Z 31009KT 3SM OVC008",
                        "wdir": 310,
                        "wspd": 9,
                        "visib": 3,
                        "temp": 10,
                        "dewp": 8,
                        "altim": 29.88,
                        "fltcat": "IFR",
                        "clouds": [{"cover": "OVC", "base": 800}],
                    }
                ],
            )
        )
        respx.get("https://aviationweather.gov/api/data/taf").mock(
            return_value=httpx.Response(200, json=[])
        )
        result = await get_weather("KJFK")
        assert result["flight_category"] == "IFR"
        assert "OVC" in result["ceiling"]


# ---------------------------------------------------------------------------
# ADS-B traffic — helper functions
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_zero_distance(self) -> None:
        assert _haversine_nm(40.0, -74.0, 40.0, -74.0) == pytest.approx(0.0, abs=0.01)

    def test_known_distance(self) -> None:
        # JFK to LGA is approximately 10 nm
        dist = _haversine_nm(40.6413, -73.7781, 40.7769, -73.8740)
        assert 5 < dist < 15

    def test_bearing_north(self) -> None:
        brg = _bearing_deg(40.0, -74.0, 41.0, -74.0)
        assert brg > 355 or brg < 5  # should be ~0 degrees (north)


class TestGetAdsbTraffic:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_query(self) -> None:
        respx.get("https://opensky-network.org/api/states/all").mock(
            return_value=httpx.Response(
                200,
                json={
                    "states": [
                        [
                            "abc123",  # icao24
                            "UAL123 ",  # callsign
                            "US",  # origin
                            None,
                            None,
                            -73.9,  # lon
                            40.7,  # lat
                            3048,  # baro alt (m)
                            False,  # on_ground
                            120,  # velocity (m/s)
                            90,  # heading
                            5,  # vertical_rate (m/s)
                            None,
                            None,
                            None,
                            None,
                        ]
                    ]
                },
            )
        )
        result = await get_adsb_traffic(40.6, -74.0)
        assert result["count"] >= 1
        assert result["traffic"][0]["callsign"] == "UAL123"

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_response(self) -> None:
        respx.get("https://opensky-network.org/api/states/all").mock(
            return_value=httpx.Response(200, json={"states": []})
        )
        result = await get_adsb_traffic(40.6, -74.0)
        assert result["count"] == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_api_error(self) -> None:
        respx.get("https://opensky-network.org/api/states/all").mock(
            return_value=httpx.Response(500)
        )
        result = await get_adsb_traffic(40.6, -74.0)
        assert "error" in result


# ---------------------------------------------------------------------------
# Chart retrieval
# ---------------------------------------------------------------------------


class TestGetCharts:
    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_fetch(self) -> None:
        respx.get("https://api.aviationapi.com/v1/charts/KJFK").mock(
            return_value=httpx.Response(
                200,
                json={
                    "KJFK": [
                        {
                            "chart_name": "ILS RWY 4L",
                            "chart_code": "IAP",
                            "pdf_path": "https://example.com/chart.pdf",
                        }
                    ]
                },
            )
        )
        result = await get_charts("KJFK")
        assert result["count"] == 1
        assert result["charts"][0]["name"] == "ILS RWY 4L"

    @pytest.mark.asyncio
    @respx.mock
    async def test_filter_by_type(self) -> None:
        respx.get("https://api.aviationapi.com/v1/charts/KJFK").mock(
            return_value=httpx.Response(
                200,
                json={
                    "KJFK": [
                        {"chart_name": "APT", "chart_code": "APT", "pdf_path": ""},
                        {"chart_name": "ILS 4L", "chart_code": "IAP", "pdf_path": ""},
                    ]
                },
            )
        )
        result = await get_charts("KJFK", chart_type="IAP")
        assert result["count"] == 1


# ---------------------------------------------------------------------------
# Performance calculator
# ---------------------------------------------------------------------------


class TestCalculatePerformance:
    @pytest.mark.asyncio
    async def test_c172_sea_level(self) -> None:
        result = await calculate_performance("C172", altitude=0, temperature=15)
        assert "takeoff" in result
        assert result["takeoff"]["ground_roll_ft"] > 0
        assert result["aircraft"] == "C172"

    @pytest.mark.asyncio
    async def test_altitude_increases_distance(self) -> None:
        sea_level = await calculate_performance("C172", altitude=0, temperature=15)
        high_alt = await calculate_performance("C172", altitude=5000, temperature=15)
        assert high_alt["takeoff"]["ground_roll_ft"] > sea_level["takeoff"]["ground_roll_ft"]

    @pytest.mark.asyncio
    async def test_hot_day_increases_distance(self) -> None:
        cool = await calculate_performance("C172", altitude=0, temperature=15)
        hot = await calculate_performance("C172", altitude=0, temperature=35)
        assert hot["takeoff"]["ground_roll_ft"] > cool["takeoff"]["ground_roll_ft"]

    @pytest.mark.asyncio
    async def test_unknown_aircraft(self) -> None:
        result = await calculate_performance("F22")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_weight_correction(self) -> None:
        light = await calculate_performance("C172", weight=2000)
        heavy = await calculate_performance("C172", weight=2550)
        assert heavy["takeoff"]["ground_roll_ft"] > light["takeoff"]["ground_roll_ft"]


# ---------------------------------------------------------------------------
# Airspace info
# ---------------------------------------------------------------------------


class TestGetAirspaceInfo:
    @pytest.mark.asyncio
    async def test_class_a_airspace(self) -> None:
        result = await get_airspace_info(40.0, -74.0, altitude=25000)
        classes = [c["class"] for c in result["airspace_classes"]]
        assert "A" in classes

    @pytest.mark.asyncio
    async def test_low_altitude(self) -> None:
        result = await get_airspace_info(40.0, -74.0, altitude=1000)
        classes = [c["class"] for c in result["airspace_classes"]]
        assert "E/G" in classes

    @pytest.mark.asyncio
    async def test_has_notes(self) -> None:
        result = await get_airspace_info(40.0, -74.0, altitude=5000)
        assert len(result["notes"]) > 0
