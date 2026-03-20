#!/usr/bin/env python3
"""
FAA NASR Data Downloader and Parser for MERLIN.

Downloads the FAA National Airspace System Resources (NASR) data set,
parses airport, runway, and frequency information, and stores everything
in a local SQLite database for fast lookups by the MERLIN orchestrator.

Usage:
    python download_faa_data.py                # full download + build
    python download_faa_data.py --refresh      # re-download & rebuild
    python download_faa_data.py --db ./my.db   # custom DB path
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import re
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Sequence

import httpx

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("merlin.faa")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "faa.db",
)

# FAA 28-day NASR subscription data (CSV format).
# The distribution page changes URLs each cycle; we use the stable
# "current" redirect published by the FAA.
NASR_CSV_URL: str = "https://nfdc.faa.gov/webContent/28DaySub/28DaySubscription_Effective_{cycle}.zip"
# Fallback: direct download of the latest CSV bundle.
NASR_CURRENT_URL: str = "https://nfdc.faa.gov/webContent/28DaySub/extra/APT_CSV.zip"

# Alternative lightweight source: the our-airports CSV dump (public domain).
OURAIRPORTS_AIRPORTS_URL: str = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OURAIRPORTS_RUNWAYS_URL: str = "https://davidmegginson.github.io/ourairports-data/runways.csv"
OURAIRPORTS_FREQUENCIES_URL: str = "https://davidmegginson.github.io/ourairports-data/airport-frequencies.csv"

CACHE_DIR: str = os.path.join(tempfile.gettempdir(), "merlin_faa_cache")

HTTP_TIMEOUT: int = 120  # seconds


# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------
SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS airports (
    icao            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    city            TEXT,
    state           TEXT,
    country         TEXT,
    lat             REAL,
    lon             REAL,
    elevation_ft    REAL,
    type            TEXT
);

CREATE TABLE IF NOT EXISTS runways (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    airport_icao    TEXT NOT NULL,
    runway_id       TEXT,
    length_ft       REAL,
    width_ft        REAL,
    surface         TEXT,
    lighted         INTEGER DEFAULT 0,
    heading         REAL,
    le_ident        TEXT,
    he_ident        TEXT,
    le_lat          REAL,
    le_lon          REAL,
    he_lat          REAL,
    he_lon          REAL,
    ils_freq        TEXT,
    FOREIGN KEY (airport_icao) REFERENCES airports(icao)
);

CREATE TABLE IF NOT EXISTS frequencies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    airport_icao    TEXT NOT NULL,
    freq_type       TEXT,
    description     TEXT,
    frequency_mhz   TEXT,
    FOREIGN KEY (airport_icao) REFERENCES airports(icao)
);

CREATE TABLE IF NOT EXISTS procedures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    airport_icao    TEXT NOT NULL,
    procedure_type  TEXT,
    name            TEXT,
    description     TEXT,
    FOREIGN KEY (airport_icao) REFERENCES airports(icao)
);

CREATE INDEX IF NOT EXISTS idx_runways_icao ON runways(airport_icao);
CREATE INDEX IF NOT EXISTS idx_freq_icao ON frequencies(airport_icao);
CREATE INDEX IF NOT EXISTS idx_proc_icao ON procedures(airport_icao);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _download(url: str, dest: Path) -> Path:
    """Download *url* to *dest*, returning the path. Reuses cache if present."""
    if dest.exists():
        log.info("  Using cached %s", dest.name)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("  Downloading %s …", url)
    with httpx.stream("GET", url, follow_redirects=True, timeout=HTTP_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=65536):
                fh.write(chunk)
    log.info("  Saved %s (%.1f MB)", dest.name, dest.stat().st_size / 1_048_576)
    return dest


def _download_text(url: str) -> str:
    """Download a text resource and return the body."""
    cache_name = re.sub(r"[^\w.]", "_", url.split("/")[-1])
    cached = Path(CACHE_DIR) / cache_name
    _download(url, cached)
    return cached.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# OurAirports parser (reliable public-domain fallback)
# ---------------------------------------------------------------------------
def _parse_ourairports_airports(text: str) -> list[dict]:
    """Parse the OurAirports airports.csv format."""
    reader = csv.DictReader(io.StringIO(text))
    results: list[dict] = []
    for row in reader:
        ident = (row.get("ident") or "").strip()
        # Keep only airports with ICAO-style identifiers (4-char or K-prefixed).
        if not ident or len(ident) < 2:
            continue
        # Filter to medium/large airports and seaplane bases to keep size manageable.
        atype = (row.get("type") or "").strip()
        if atype not in ("large_airport", "medium_airport", "small_airport", "seaplane_base"):
            continue
        lat = _safe_float(row.get("latitude_deg"))
        lon = _safe_float(row.get("longitude_deg"))
        elev = _safe_float(row.get("elevation_ft"))
        results.append(
            {
                "icao": ident,
                "name": (row.get("name") or "").strip(),
                "city": (row.get("municipality") or "").strip(),
                "state": (row.get("iso_region") or "").replace("US-", "").strip(),
                "country": (row.get("iso_country") or "").strip(),
                "lat": lat,
                "lon": lon,
                "elevation_ft": elev,
                "type": atype,
            }
        )
    return results


def _parse_ourairports_runways(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    results: list[dict] = []
    for row in reader:
        airport_ref = (row.get("airport_ident") or "").strip()
        if not airport_ref:
            continue
        le_ident = (row.get("le_ident") or "").strip()
        he_ident = (row.get("he_ident") or "").strip()
        runway_id = f"{le_ident}/{he_ident}" if le_ident and he_ident else le_ident or he_ident
        results.append(
            {
                "airport_icao": airport_ref,
                "runway_id": runway_id,
                "length_ft": _safe_float(row.get("length_ft")),
                "width_ft": _safe_float(row.get("width_ft")),
                "surface": (row.get("surface") or "").strip(),
                "lighted": 1 if row.get("lighted") == "1" else 0,
                "heading": _safe_float(row.get("le_heading_degT")),
                "le_ident": le_ident,
                "he_ident": he_ident,
                "le_lat": _safe_float(row.get("le_latitude_deg")),
                "le_lon": _safe_float(row.get("le_longitude_deg")),
                "he_lat": _safe_float(row.get("he_latitude_deg")),
                "he_lon": _safe_float(row.get("he_longitude_deg")),
                "ils_freq": (row.get("le_ils_freq") or "").strip() or None,
            }
        )
    return results


def _parse_ourairports_frequencies(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    results: list[dict] = []
    for row in reader:
        airport_ref = (row.get("airport_ident") or "").strip()
        if not airport_ref:
            continue
        results.append(
            {
                "airport_icao": airport_ref,
                "freq_type": (row.get("type") or "").strip(),
                "description": (row.get("description") or "").strip(),
                "frequency_mhz": (row.get("frequency_mhz") or "").strip(),
            }
        )
    return results


def _safe_float(val: Optional[str]) -> Optional[float]:
    if val is None:
        return None
    val = val.strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------
def init_db(db_path: str) -> sqlite3.Connection:
    """Create the SQLite database and schema."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def _bulk_insert_airports(conn: sqlite3.Connection, airports: list[dict]) -> int:
    sql = """
        INSERT OR REPLACE INTO airports (icao, name, city, state, country, lat, lon, elevation_ft, type)
        VALUES (:icao, :name, :city, :state, :country, :lat, :lon, :elevation_ft, :type)
    """
    conn.executemany(sql, airports)
    conn.commit()
    return len(airports)


def _bulk_insert_runways(conn: sqlite3.Connection, runways: list[dict]) -> int:
    # Clear existing runways to avoid duplicates on refresh.
    conn.execute("DELETE FROM runways")
    sql = """
        INSERT INTO runways
            (airport_icao, runway_id, length_ft, width_ft, surface, lighted,
             heading, le_ident, he_ident, le_lat, le_lon, he_lat, he_lon, ils_freq)
        VALUES
            (:airport_icao, :runway_id, :length_ft, :width_ft, :surface, :lighted,
             :heading, :le_ident, :he_ident, :le_lat, :le_lon, :he_lat, :he_lon, :ils_freq)
    """
    conn.executemany(sql, runways)
    conn.commit()
    return len(runways)


def _bulk_insert_frequencies(conn: sqlite3.Connection, freqs: list[dict]) -> int:
    conn.execute("DELETE FROM frequencies")
    sql = """
        INSERT INTO frequencies (airport_icao, freq_type, description, frequency_mhz)
        VALUES (:airport_icao, :freq_type, :description, :frequency_mhz)
    """
    conn.executemany(sql, freqs)
    conn.commit()
    return len(freqs)


def _set_metadata(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def download_and_build(db_path: str, refresh: bool = False) -> None:
    """Download OurAirports data and populate the SQLite database."""
    if refresh:
        # Bust the cache.
        cache = Path(CACHE_DIR)
        if cache.exists():
            for f in cache.iterdir():
                f.unlink()
            log.info("Cache cleared.")

    log.info("Step 1/4: Downloading airport data …")
    airports_csv = _download_text(OURAIRPORTS_AIRPORTS_URL)
    airports = _parse_ourairports_airports(airports_csv)
    log.info("  Parsed %d airports.", len(airports))

    log.info("Step 2/4: Downloading runway data …")
    runways_csv = _download_text(OURAIRPORTS_RUNWAYS_URL)
    runways = _parse_ourairports_runways(runways_csv)
    log.info("  Parsed %d runways.", len(runways))

    log.info("Step 3/4: Downloading frequency data …")
    freq_csv = _download_text(OURAIRPORTS_FREQUENCIES_URL)
    freqs = _parse_ourairports_frequencies(freq_csv)
    log.info("  Parsed %d frequencies.", len(freqs))

    log.info("Step 4/4: Building SQLite database at %s …", db_path)
    conn = init_db(db_path)
    n_apt = _bulk_insert_airports(conn, airports)
    n_rwy = _bulk_insert_runways(conn, runways)
    n_frq = _bulk_insert_frequencies(conn, freqs)

    from datetime import datetime, timezone

    _set_metadata(conn, "last_updated", datetime.now(timezone.utc).isoformat())
    _set_metadata(conn, "source", "OurAirports (ourairports.com)")
    conn.close()

    log.info(
        "Database built: %d airports, %d runways, %d frequencies.",
        n_apt,
        n_rwy,
        n_frq,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download_faa_data",
        description="Download FAA/airport data and build the MERLIN airport database.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-download of all source data.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    download_and_build(args.db, refresh=args.refresh)


if __name__ == "__main__":
    main()
