# Aviation Tools Reference

MERLIN provides six aviation data tools that Claude can invoke mid-response via the tool-use protocol. Each tool is an async function in `orchestrator/orchestrator/aviation_tools.py` that calls external APIs using `httpx` with a 10-second timeout.

All tools follow the same error contract: on failure, they return a dict with an `"error"` key containing a human-readable message, allowing Claude to gracefully inform the pilot rather than crashing.

---

## get_notams

Fetches NOTAMs (Notices to Air Missions) for an airport from the FAA NOTAM API.

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `identifier` | `str` | Airport ICAO or FAA identifier (e.g., `KJFK`, `JFK`) |

### Identifier Handling

Three-letter FAA identifiers without a `K` prefix are automatically prefixed. For example, `JFK` becomes `KJFK`. Four-letter ICAO identifiers are used as-is.

### API Endpoint

```
GET https://external-api.faa.gov/notamapi/v1/notams
    ?icaoLocation={identifier}
    &notamType=ALL
    &sortBy=effectiveStartDate
    &sortOrder=DESC
```

### Response Format

```json
{
  "identifier": "KJFK",
  "count": 3,
  "notams": [
    {
      "id": "A0001/24",
      "type": "N",
      "text": "RWY 04L/22R CLSD FOR MAINT",
      "effective": "2024-03-15T08:00:00Z",
      "expires": "2024-03-16T20:00:00Z"
    }
  ]
}
```

Results are limited to the 10 most recent NOTAMs, sorted by effective date descending.

---

## get_weather

Fetches METAR (current conditions) and TAF (forecast) from aviationweather.gov.

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `identifier` | `str` | Airport ICAO identifier (e.g., `KJFK`) |

### API Endpoints

```
GET https://aviationweather.gov/api/data/metar?ids={identifier}&format=json
GET https://aviationweather.gov/api/data/taf?ids={identifier}&format=json
```

The TAF fetch is supplemental -- if it fails, the tool returns the METAR data without the forecast rather than failing entirely.

### Response Format

```json
{
  "identifier": "KJFK",
  "raw_metar": "KJFK 151856Z 27015G25KT 10SM FEW250 22/06 A2992 RMK AO2",
  "raw_taf": "TAF KJFK 151730Z 1518/1624 27012KT P6SM SCT250...",
  "wind": "270 deg at 15 kt gusting 25 kt",
  "visibility": "10 sm",
  "ceiling": "",
  "temperature": "22 deg C",
  "dewpoint": "6 deg C",
  "altimeter": "29.92 inHg",
  "flight_category": "VFR",
  "remarks": ""
}
```

### Parsed Fields

| Field | Source | Notes |
|---|---|---|
| `wind` | `wdir`, `wspd`, `wgst` | Includes gust if present |
| `visibility` | `visib` | Statute miles |
| `ceiling` | `clouds` array | First BKN or OVC layer |
| `temperature` | `temp` | Celsius |
| `dewpoint` | `dewp` | Celsius |
| `altimeter` | `altim` | Inches of mercury |
| `flight_category` | `fltcat` | VFR, MVFR, IFR, or LIFR |

---

## get_adsb_traffic

Queries the OpenSky Network for nearby ADS-B traffic relative to the aircraft's position.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lat` | `float` | -- | Observer latitude (decimal degrees) |
| `lon` | `float` | -- | Observer longitude (decimal degrees) |
| `radius_nm` | `float` | `30.0` | Search radius in nautical miles |

### How It Works

1. Converts the NM radius to a lat/lon bounding box (1 degree latitude is approximately 60 NM; longitude is corrected for latitude using cosine).
2. Queries the OpenSky Network REST API with the bounding box.
3. For each returned state vector, computes the **haversine great-circle distance** and **initial bearing** from the observer.
4. Filters targets outside the radius, sorts by distance ascending, and returns the 20 closest.

### API Endpoint

```
GET https://opensky-network.org/api/states/all
    ?lamin={lat-delta}&lamax={lat+delta}
    &lomin={lon-delta}&lomax={lon+delta}
```

### Response Format

```json
{
  "observer": {"lat": 40.6413, "lon": -73.7781},
  "radius_nm": 30.0,
  "count": 5,
  "traffic": [
    {
      "callsign": "DAL1234",
      "icao24": "a12345",
      "latitude": 40.72,
      "longitude": -73.85,
      "altitude_ft": 5200,
      "heading": 270.0,
      "ground_speed_kt": 180,
      "vertical_rate_fpm": -500,
      "distance_nm": 8.3,
      "bearing": 42,
      "on_ground": false
    }
  ]
}
```

### Unit Conversions

| Source Unit | Display Unit | Conversion |
|---|---|---|
| Barometric/geometric altitude (meters) | feet | multiply by 3.28084 |
| Ground speed (m/s) | knots | multiply by 1.94384 |
| Vertical rate (m/s) | ft/min | multiply by 196.85 |

---

## get_charts

Retrieves aviation chart references (approach plates, SIDs, STARs, airport diagrams) from the FAA Digital Terminal Procedures Publication (DTPP).

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `identifier` | `str` | -- | Airport ICAO identifier |
| `chart_type` | `str` | `"all"` | Filter: `all`, `apt`, `sid`, `star`, `iap` |

### API Endpoint

```
GET https://api.aviationapi.com/v1/charts/{identifier}
```

### Chart Types

| Code | Description |
|---|---|
| `apt` | Airport diagram |
| `sid` | Standard Instrument Departure |
| `star` | Standard Terminal Arrival Route |
| `iap` | Instrument Approach Procedure |

### Response Format

```json
{
  "identifier": "KJFK",
  "chart_type": "iap",
  "count": 12,
  "charts": [
    {
      "name": "ILS OR LOC RWY 04L",
      "type": "IAP",
      "url": "https://aeronav.faa.gov/d-tpp/2403/00058IL4L.PDF"
    }
  ]
}
```

---

## calculate_performance

Computes estimated takeoff and landing distances with altitude, temperature, and weight corrections.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `aircraft` | `str` | -- | Aircraft type code (e.g., `C172`, `PA28`) |
| `weight` | `float` | `0` | Gross weight in lbs (0 = use max gross) |
| `altitude` | `float` | `0` | Field elevation in feet |
| `temperature` | `float` | `15.0` | OAT in degrees Celsius |

### Supported Aircraft

| Code | Base TO Roll | Base TO Over 50ft | Base LDG Roll | Base LDG Over 50ft | Climb FPM |
|---|---|---|---|---|---|
| `C172` | 960 ft | 1,685 ft | 550 ft | 1,295 ft | 730 |
| `C152` | 735 ft | 1,340 ft | 475 ft | 1,200 ft | 715 |
| `PA28` | 1,000 ft | 1,600 ft | 600 ft | 1,300 ft | 660 |

### Correction Factors

All base distances are adjusted by three correction factors multiplied together:

**Altitude correction**: +12% per 1,000 ft of field elevation.

```
alt_factor = 1.0 + (altitude / 1000) * 0.12
```

**Temperature correction**: +10% per 10 deg C above ISA at that altitude. ISA temperature is calculated as 15 deg C at sea level with a 2 deg C lapse rate per 1,000 ft. Only positive deviations (hotter than ISA) increase the distance.

```
isa_temp = 15.0 - (altitude / 1000) * 2.0
temp_deviation = temperature - isa_temp
temp_factor = 1.0 + max(0, temp_deviation / 10) * 0.10
```

**Weight correction**: Distance scales with the square of the weight ratio.

```
weight_factor = (actual_weight / max_gross_weight) ** 2
```

Rate of climb is corrected inversely by the altitude factor only:

```
adjusted_roc = base_roc / alt_factor
```

### Response Format

```json
{
  "aircraft": "C172",
  "conditions": {
    "field_elevation_ft": 5000,
    "temperature_c": 30.0,
    "isa_deviation_c": 25.0,
    "weight_lbs": 2400
  },
  "takeoff": {
    "ground_roll_ft": 1611,
    "over_50ft_ft": 2828
  },
  "landing": {
    "ground_roll_ft": 923,
    "over_50ft_ft": 2174
  },
  "climb": {
    "rate_fpm": 456
  },
  "cruise": {
    "speed_kt": 122,
    "fuel_burn_gph": 8.5
  },
  "best_glide_kt": 65,
  "note": "Estimates based on standard corrections. Verify against POH."
}
```

---

## get_airspace_info

Returns airspace classification for a given position and altitude.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lat` | `float` | -- | Latitude in decimal degrees |
| `lon` | `float` | -- | Longitude in decimal degrees |
| `altitude` | `float` | `0` | Altitude in feet MSL |

### Classification Logic

This is a simplified altitude-based implementation. A production deployment would query FAA NASR/CIFP data or an airspace API.

| Altitude | Classification | Notes |
|---|---|---|
| >= 60,000 ft | Class E | Above FL600 |
| >= 18,000 ft | Class A | FL180-FL600, IFR only, positive control |
| < 18,000 ft | Class E/G | Position-dependent; may be Class G below 1,200 AGL in uncontrolled areas |

### Response Format

```json
{
  "position": {"lat": 40.6413, "lon": -73.7781},
  "altitude_ft": 25000,
  "airspace_classes": [
    {
      "class": "A",
      "description": "Class A airspace (FL180-FL600). IFR only."
    }
  ],
  "restrictions": [],
  "notes": [
    "IFR flight plan required. Positive control.",
    "This is a simplified classification. Check sectional charts and NOTAMs for TFRs, MOAs, and restricted areas at this position."
  ]
}
```

---

## Error Handling

All tools share the same error contract. On any `httpx.HTTPError` or `httpx.HTTPStatusError`, the tool returns a dict with an `"error"` key:

```json
{
  "error": "NOTAM API returned 503",
  "identifier": "KJFK"
}
```

Claude uses this error message to inform the pilot that the data source is temporarily unavailable, and falls back to whatever knowledge it has in context.
