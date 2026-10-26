"""WindDesk: leakage-aware UK wind forecast monitoring.

Only Elexon FUELHH actuals (WIND) and WINDFOR forecasts are used.
The evaluation is for purchase decision dates in January 2026. Historical
warm-up days are fetched solely to build ex-ante rolling error calibration;
they are excluded from the January headline metrics.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import threading
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

API_BASE = os.getenv("ELEXON_API_BASE", "https://data.elexon.co.uk/bmrs/api/v1").rstrip("/")
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "900"))
ALLOW_DEMO_FALLBACK = os.getenv("ALLOW_DEMO_FALLBACK", "true").lower() in {"1", "true", "yes"}
EVAL_START = date(2026, 1, 1)  # decision dates, inclusive
EVAL_END = date(2026, 2, 1)    # decision dates, exclusive
WARMUP_DAYS = int(os.getenv("CALIBRATION_WARMUP_DAYS", "14"))
MIN_CALIBRATION_DAYS = int(os.getenv("MIN_CALIBRATION_DAYS", "5"))
CALIBRATION_WINDOW_DAYS = int(os.getenv("CALIBRATION_WINDOW_DAYS", "14"))
FUELHH_INTERVAL_MINUTES = 30
WINDFOR_INTERVAL_MINUTES = 60
EVALUATION_INTERVAL_MINUTES = 60
PERIODS_PER_DAY = 24
EVALUATION_INTERVAL_HOURS = EVALUATION_INTERVAL_MINUTES / 60
LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc

app = FastAPI(
    title="WindDesk API",
    version="2.0.0",
    description=(
        "Decision-time wind forecast verification for January 2026 purchase decisions. "
        "Uses Elexon FUELHH (WIND) and WINDFOR only; outputs are analytical, not trading instructions."
    ),
)
_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins or ["http://localhost:5173"], allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])

_cache_lock = threading.RLock()
_load_lock = threading.Lock()
_memory: dict[str, Any] = {"loaded_at": 0.0, "actuals": None, "forecasts": None, "source": None, "cached_at": None, "warnings": []}


class MetricsResponse(BaseModel):
    maeMW: float | None
    rmseMW: float | None
    biasMW: float | None
    wapePct: float | None
    mapePct: float | None
    mapeEligiblePeriods: int
    p90AbsErrorMW: float | None
    p95AbsErrorMW: float | None
    p90OverforecastMW: float | None
    overforecastPct: float | None
    overforecastMeanMW: float | None
    matchedPeriods: int
    forecastPeriods: int
    actualPeriods: int
    expectedPeriods: int
    coveragePct: float
    forecastAvailabilityPct: float
    missingForecastPeriods: int
    missingActualPeriods: int
    actualEnergyGWh: float | None
    forecastEnergyGWh: float | None


class DailyResponse(MetricsResponse):
    decisionDate: str
    deliveryDate: str
    label: str
    latestPublishTime: str | None
    periods: int
    calibrationReady: bool
    calibrationDays: int
    calibrationMatchedPeriods: int
    calibrationWindowStart: str
    calibrationWindowEndExclusive: str
    intervalLowResidualMW: float | None
    intervalHighResidualMW: float | None
    marginP90OverforecastMW: float | None
    intervalCoveragePct: float | None
    meanIntervalWidthMW: float | None


class LedgerRowResponse(BaseModel):
    startTime: str
    decisionDate: str
    deliveryDate: str
    intervalIndex: int
    resolutionMinutes: int
    actualMW: float | None
    forecastMW: float | None
    errorMW: float | None
    actualMinusForecastMW: float | None
    absoluteErrorMW: float | None
    shortfallMW: float | None
    percentageError: float | None
    publishTime: str | None
    decisionCutoff: str
    forecastLeadHours: float | None
    decisionLeadHours: float
    intervalLowMW: float | None
    intervalHighMW: float | None


class HorizonResponse(BaseModel):
    band: str
    lowerHours: float
    upperHours: float | None
    count: int
    maeMW: float | None
    rmseMW: float | None
    biasMW: float | None
    overforecastPct: float | None


class HourResponse(BaseModel):
    hour: int
    label: str
    count: int
    maeMW: float | None
    biasMW: float | None
    overforecastPct: float | None


class HistogramResponse(BaseModel):
    centerMW: float
    count: int
    lowerMW: float
    upperMW: float


class BacktestResponse(BaseModel):
    method: str
    nominalCoveragePct: float
    calibratedDecisionDays: int
    totalDecisionDays: int
    meanObservedCoveragePct: float | None
    meanIntervalWidthMW: float | None
    meanAbsoluteCoverageGapPct: float | None
    note: str


class AnalysisResponse(BaseModel):
    scope: dict[str, Any]
    metrics: MetricsResponse
    daily: list[DailyResponse]
    rows: list[LedgerRowResponse]
    horizon: list[HorizonResponse]
    byHour: list[HourResponse]
    histogram: list[HistogramResponse]
    backtest: BacktestResponse
    source: Literal["live", "cache", "stale-cache", "demo"]
    status: Literal["live", "cached", "demo"]
    warnings: list[str]
    generatedAt: str
    meta: dict[str, Any]


def parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
    raise ValueError("Elexon returned an unexpected JSON shape; expected a list of records.")


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def parse_cutoff(cutoff: str) -> tuple[int, int]:
    try:
        hour_s, minute_s = cutoff.split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (AttributeError, ValueError):
        raise HTTPException(status_code=400, detail="cutoff must be a valid HH:MM time in Europe/London")


def month_window(month: str) -> tuple[date, date]:
    try:
        year_s, month_s = month.split("-", 1)
        start = date(int(year_s), int(month_s), 1)
        end = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    except (AttributeError, ValueError):
        raise HTTPException(status_code=400, detail="month must use YYYY-MM format")
    if (start, end) != (EVAL_START, EVAL_END):
        raise HTTPException(status_code=400, detail="This pilot is intentionally scoped to January 2026 purchase decision dates.")
    return start, end


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile, implemented without a NumPy runtime dependency."""
    if not values:
        return None
    ordered = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not ordered:
        return None
    rank = min(max(p, 0.0), 1.0) * (len(ordered) - 1)
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def fetch_json(url: str, params: dict[str, str], *, attempts: int = 3) -> list[dict[str, Any]]:
    """One bounded, retryable Elexon request. Never silently turn an HTTP error into empty data."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(25.0, connect=8.0),
                follow_redirects=True,
                headers={"Accept": "application/json", "User-Agent": "WindDesk-Pilot/2.0"},
            ) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return as_records(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                # Respect upstream rate-limit guidance when provided; otherwise back off.
                retry_after = None
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = safe_float(exc.response.headers.get("Retry-After"))
                delay = min(8.0, max(0.0, retry_after)) if retry_after is not None else min(4.0, 0.4 * (2 ** attempt))
                time.sleep(delay)
    raise RuntimeError(f"Request failed for {url.rsplit('/', 2)[-2]}: {last_error}") from last_error


def _date_ranges(start: datetime, end: datetime, days: int) -> list[tuple[datetime, datetime]]:
    ranges: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        upper = min(cursor + timedelta(days=days), end)
        ranges.append((cursor, upper))
        cursor = upper
    return ranges


def _calendar_date_ranges(start: date, end_exclusive: date, days: int) -> list[tuple[date, date]]:
    """Build inclusive date-query ranges from an exclusive date boundary."""
    ranges: list[tuple[date, date]] = []
    cursor = start
    while cursor < end_exclusive:
        ranges.append((cursor, min(cursor + timedelta(days=days), end_exclusive) - timedelta(days=1)))
        cursor += timedelta(days=days)
    return ranges


def fetch_actuals(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """FUELHH uses inclusive settlement-date filters, with WIND only."""
    url = f"{API_BASE}/datasets/FUELHH/stream"
    # FUELHH's stream does not accept generic `from` / `to`; it requires date-only
    # settlement bounds. Convert both aware instant bounds back to the source's UK
    # settlement calendar and retain an exclusive end in our internal convention.
    start_date = start.astimezone(LONDON).date()
    end_local = end.astimezone(LONDON)
    end_date_exclusive = end_local.date() + (timedelta(days=1) if end_local.time() != dt_time.min else timedelta())
    ranges = _calendar_date_ranges(start_date, end_date_exclusive, 7)
    chunks: list[list[dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(fetch_json, url, {"settlementDateFrom": left.isoformat(), "settlementDateTo": right.isoformat(), "fuelType": "WIND"}): (left, right)
            for left, right in ranges
        }
        for future in as_completed(futures):
            chunks.append(future.result())
    return _dedupe_raw([record for group in chunks for record in group], ("startTime", "fuelType"), "publishTime")


def fetch_forecasts(published_from: datetime, published_to: datetime) -> list[dict[str, Any]]:
    """WINDFOR is filtered by publication time, not by target time."""
    url = f"{API_BASE}/datasets/WINDFOR/stream"
    ranges = _date_ranges(published_from, published_to, 3)
    chunks: list[list[dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(fetch_json, url, {
                "publishDateTimeFrom": iso_utc(left),
                "publishDateTimeTo": iso_utc(right),
            }): (left, right)
            for left, right in ranges
        }
        for future in as_completed(futures):
            chunks.append(future.result())
    return _dedupe_raw([record for group in chunks for record in group], ("startTime", "publishTime"), None)


def _dedupe_raw(records: list[dict[str, Any]], identity_fields: tuple[str, ...], revision_field: str | None) -> list[dict[str, Any]]:
    """Deduplicate overlapping pages with a stable tie-break for conflicting copies.

    The source normally repeats identical records at adjacent page boundaries. If two
    records have the same identity and revision timestamp but disagree, choosing the
    last row makes the result depend on response/page ordering. Canonical JSON gives
    that malformed case a repeatable representative while retaining normal revision
    selection semantics.
    """
    unique: dict[tuple[str, ...], dict[str, Any]] = {}
    for record in records:
        key = tuple(str(record.get(field, "")) for field in identity_fields)
        existing = unique.get(key)
        if existing is None:
            unique[key] = record
        elif revision_field:
            old_revision = parse_dt(existing.get(revision_field))
            new_revision = parse_dt(record.get(revision_field))
            if new_revision and (old_revision is None or new_revision > old_revision):
                unique[key] = record
            elif new_revision == old_revision and _canonical_record(record) < _canonical_record(existing):
                unique[key] = record
        elif _canonical_record(record) < _canonical_record(existing):
            unique[key] = record
    return list(unique.values())


def _canonical_record(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def normalize_actuals(records: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, float]:
    result: dict[str, tuple[datetime, float]] = {}
    for row in records:
        fuel = str(row.get("fuelType", row.get("fuel_type", ""))).upper()
        # The brief explicitly restricts actuals to WIND. Missing fuel labels are
        # not accepted as wind observations; ambiguous rows should reduce coverage.
        if fuel != "WIND":
            continue
        target = parse_dt(row.get("startTime") or row.get("start_time"))
        generation = safe_float(row.get("generation"))
        if target is None or generation is None or not (start <= target < end):
            continue
        settlement_date = row.get("settlementDate") or row.get("settlement_date")
        settlement_period = row.get("settlementPeriod") or row.get("settlement_period")
        if settlement_date is not None and settlement_period is not None:
            try:
                period = int(settlement_period)
                local_midnight = datetime.combine(date.fromisoformat(str(settlement_date)), dt_time.min, tzinfo=LONDON)
                expected_start = (local_midnight + timedelta(minutes=FUELHH_INTERVAL_MINUTES * (period - 1))).astimezone(UTC)
                if period < 1 or target != expected_start:
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
        key = iso_utc(target)
        published = parse_dt(row.get("publishTime") or row.get("publish_time")) or datetime.min.replace(tzinfo=UTC)
        old = result.get(key)
        if old is None or published > old[0] or (published == old[0] and generation < old[1]):
            result[key] = (published, generation)
    return {key: value for key, (_, value) in result.items()}


def normalize_hourly_actuals(records: list[dict[str, Any]], target_start: datetime, target_end: datetime) -> dict[str, float]:
    """Average complete pairs of half-hour FUELHH MW readings into hourly MW.

    WINDFOR stream targets are hourly. An hourly actual is the arithmetic mean of
    the two constituent half-hour average-generation readings. Incomplete pairs
    stay missing; no reading is copied or interpolated into another interval.
    """
    half_hours = normalize_actuals(records, target_start, target_end)
    buckets: dict[datetime, dict[int, float]] = {}
    for key, generation in half_hours.items():
        target = parse_dt(key)
        if target is None or target.second or target.microsecond or target.minute not in (0, 30):
            continue
        hour_start = target.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour_start, {})[target.minute] = generation
    return {
        iso_utc(hour_start): (values[0] + values[30]) / 2
        for hour_start, values in buckets.items()
        if 0 in values and 30 in values
    }


def normalize_forecasts(records: list[dict[str, Any]], target_start: datetime, target_end: datetime) -> list[dict[str, Any]]:
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in records:
        target = parse_dt(row.get("startTime") or row.get("start_time"))
        published = parse_dt(row.get("publishTime") or row.get("publish_time"))
        generation = safe_float(row.get("generation"))
        if target is None or published is None or generation is None:
            continue
        if not (target_start <= target < target_end):
            continue
        key = (iso_utc(target), iso_utc(published))
        normalized = {"key": key[0], "start": target, "published": published, "generation": generation}
        existing = dedup.get(key)
        if existing is None or _canonical_record(normalized) < _canonical_record(existing):
            dedup[key] = normalized
    return sorted(dedup.values(), key=lambda item: (item["key"], item["published"]))


def _json_cache_path(name: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / name


def _read_disk_cache() -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime] | None:
    """Read one versioned snapshot atomically; accept the original split-cache layout too."""
    snapshot_path = DATA_DIR / "elexon_snapshot.json"
    try:
        if snapshot_path.exists():
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if snapshot.get("schemaVersion") == 1 and isinstance(snapshot.get("actuals"), list) and isinstance(snapshot.get("forecasts"), list):
                fetched_at = parse_dt(snapshot.get("fetchedAt")) or datetime.fromtimestamp(snapshot_path.stat().st_mtime, UTC)
                return snapshot["actuals"], snapshot["forecasts"], fetched_at
    except (OSError, ValueError, TypeError):
        pass

    # Read older snapshots from an earlier pilot version during local upgrades.
    actual_path = DATA_DIR / "fuelhh_warmup_jan2026.json"
    forecast_path = DATA_DIR / "windfor_warmup_jan2026.json"
    meta_path = DATA_DIR / "snapshot_meta.json"
    try:
        if not (actual_path.exists() and forecast_path.exists() and meta_path.exists()):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        actuals = json.loads(actual_path.read_text(encoding="utf-8"))
        forecasts = json.loads(forecast_path.read_text(encoding="utf-8"))
        return actuals, forecasts, parse_dt(meta.get("fetchedAt")) or datetime.fromtimestamp(meta_path.stat().st_mtime, UTC)
    except (OSError, ValueError, TypeError):
        return None


def _write_disk_cache(actuals: list[dict[str, Any]], forecasts: list[dict[str, Any]], fetched_at: datetime) -> None:
    """Commit source records and their timestamp as one atomic snapshot file."""
    path = _json_cache_path("elexon_snapshot.json")
    snapshot = {
        "schemaVersion": 1,
        "fetchedAt": iso_utc(fetched_at),
        "actualRecords": len(actuals),
        "forecastRecords": len(forecasts),
        "actuals": actuals,
        "forecasts": forecasts,
    }
    # A unique same-directory temporary avoids collisions between worker processes;
    # os.replace keeps readers from observing a partially written snapshot.
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix="elexon_snapshot.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(snapshot, temporary, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def demo_data(decision_start: date, decision_end: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic synthetic fixture for UI/logic demonstrations; never Elexon observations."""
    rng = random.Random(20260126)
    actual_records: list[dict[str, Any]] = []
    forecast_records: list[dict[str, Any]] = []
    day = decision_start
    while day < decision_end:
        delivery_day = day + timedelta(days=1)
        actual_by_key: dict[str, float] = {}
        day_phase = (delivery_day.timetuple().tm_yday % 13) / 13 * 2 * math.pi
        for period in range(48):
            target_local = datetime.combine(delivery_day, dt_time.min, tzinfo=LONDON) + timedelta(minutes=30 * period)
            shape = 9200 + 3600 * math.sin(period / 48 * 2 * math.pi - 0.8) + 1400 * math.sin(day_phase)
            actual = max(250.0, shape + rng.gauss(0, 520))
            key = iso_utc(target_local)
            actual_by_key[key] = actual
            actual_records.append({"startTime": key, "fuelType": "WIND", "generation": round(actual, 2)})

        # Keep the fixture on WINDFOR's verified hourly target cadence.
        pub_slots = [(3, 30), (5, 30), (8, 30), (10, 30), (12, 30), (16, 30), (19, 30), (23, 30)]
        for slot_index, (hour, minute) in enumerate(pub_slots):
            published_local = datetime.combine(day, dt_time(hour, minute), tzinfo=LONDON)
            for interval_index in range(PERIODS_PER_DAY):
                target_local = datetime.combine(delivery_day, dt_time.min, tzinfo=LONDON) + timedelta(hours=interval_index)
                key = iso_utc(target_local)
                lead_hours = max(0.5, (target_local - published_local).total_seconds() / 3600)
                sigma = 240 + 20 * lead_hours + slot_index * 12
                next_key = iso_utc(target_local + timedelta(minutes=FUELHH_INTERVAL_MINUTES))
                hourly_actual = (actual_by_key[key] + actual_by_key[next_key]) / 2
                forecast = max(0.0, hourly_actual + rng.gauss(0, sigma))
                forecast_records.append({"startTime": key, "publishTime": iso_utc(published_local), "generation": round(forecast, 2)})
        day += timedelta(days=1)
    return actual_records, forecast_records


def load_records(refresh: bool = False, force_demo: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[str], datetime | None]:
    """Read a bounded snapshot from memory/disk, fetch live data, or use labelled demo data."""
    warmup_decision_start = EVAL_START - timedelta(days=WARMUP_DAYS + 1)
    # Need actuals through the day after the final January decision (delivery 1 Feb).
    delivery_start = datetime.combine(warmup_decision_start + timedelta(days=1), dt_time.min, tzinfo=LONDON).astimezone(UTC)
    delivery_end = datetime.combine(EVAL_END + timedelta(days=1), dt_time.min, tzinfo=LONDON).astimezone(UTC)
    publication_start = datetime.combine(warmup_decision_start - timedelta(days=3), dt_time.min, tzinfo=LONDON).astimezone(UTC)
    publication_end = datetime.combine(EVAL_END + timedelta(days=1), dt_time.min, tzinfo=LONDON).astimezone(UTC)

    if force_demo:
        actuals, forecasts = demo_data(warmup_decision_start, EVAL_END)
        return actuals, forecasts, "demo", ["Synthetic demo mode was explicitly selected. These values are not Elexon observations."], None

    now = time.time()
    with _load_lock:
        with _cache_lock:
            fresh = bool(_memory["actuals"] is not None and now - _memory["loaded_at"] < CACHE_TTL_SECONDS)
            if fresh and not refresh:
                return _memory["actuals"], _memory["forecasts"], _memory["source"], list(_memory["warnings"]), _memory["cached_at"]

        disk = _read_disk_cache()
        if disk and not refresh and (datetime.now(UTC) - disk[2]).total_seconds() <= CACHE_TTL_SECONDS:
            actuals, forecasts, fetched_at = disk
            with _cache_lock:
                _memory.update({"loaded_at": now, "actuals": actuals, "forecasts": forecasts, "source": "cache", "cached_at": fetched_at, "warnings": ["Using a recent local Elexon snapshot; refresh to request newer records."]})
            return actuals, forecasts, "cache", ["Using a recent local Elexon snapshot; refresh to request newer records."], fetched_at

        stale_disk = disk
        try:
            # Separate filters are intentional: FUELHH uses settlement-date bounds;
            # WINDFOR uses publication-time bounds to preserve vintage history.
            with ThreadPoolExecutor(max_workers=2) as pool:
                actual_future = pool.submit(fetch_actuals, delivery_start, delivery_end)
                forecast_future = pool.submit(fetch_forecasts, publication_start, publication_end)
                actuals, forecasts = actual_future.result(), forecast_future.result()
            actual_norm = normalize_actuals(actuals, delivery_start, delivery_end)
            forecast_norm = normalize_forecasts(forecasts, delivery_start, delivery_end)
            if len(actual_norm) < 48 or len(forecast_norm) < 48:
                raise RuntimeError(f"Elexon returned too few usable records (actual periods={len(actual_norm)}, forecast vintages={len(forecast_norm)}).")
            fetched_at = datetime.now(UTC)
            _write_disk_cache(actuals, forecasts, fetched_at)
            with _cache_lock:
                _memory.update({"loaded_at": time.time(), "actuals": actuals, "forecasts": forecasts, "source": "live", "cached_at": fetched_at, "warnings": []})
            return actuals, forecasts, "live", [], fetched_at
        except Exception as exc:
            message = f"Live Elexon fetch failed: {str(exc)[:260]}"
            if stale_disk:
                actuals, forecasts, fetched_at = stale_disk
                warnings = [message, "Showing a stale local snapshot; verify its timestamp before interpreting any values."]
                with _cache_lock:
                    _memory.update({"loaded_at": time.time(), "actuals": actuals, "forecasts": forecasts, "source": "stale-cache", "cached_at": fetched_at, "warnings": warnings})
                return actuals, forecasts, "stale-cache", warnings, fetched_at
            if not ALLOW_DEMO_FALLBACK:
                raise HTTPException(status_code=502, detail=message) from exc
            actuals, forecasts = demo_data(warmup_decision_start, EVAL_END)
            warnings = [message, "Showing deterministic synthetic demo data, not Elexon observations. Do not use for operational decisions."]
            with _cache_lock:
                _memory.update({"loaded_at": time.time(), "actuals": actuals, "forecasts": forecasts, "source": "demo", "cached_at": None, "warnings": warnings})
            return actuals, forecasts, "demo", warnings, None


def build_decision_rows(
    actual_raw: list[dict[str, Any]], forecast_raw: list[dict[str, Any]],
    decision_start: date, decision_end: date, cutoff: str,
) -> list[dict[str, Any]]:
    """Create every expected hourly interval and select its last eligible vintage.

    WINDFOR targets are hourly. Actuals are joined only after complete pairs of
    half-hour FUELHH readings have been averaged to the same hourly interval.
    """
    cut_hour, cut_minute = parse_cutoff(cutoff)
    warmup_start = decision_start - timedelta(days=WARMUP_DAYS + 1)
    delivery_start = datetime.combine(warmup_start + timedelta(days=1), dt_time.min, tzinfo=LONDON).astimezone(UTC)
    delivery_end = datetime.combine(decision_end + timedelta(days=1), dt_time.min, tzinfo=LONDON).astimezone(UTC)
    actuals = normalize_hourly_actuals(actual_raw, delivery_start, delivery_end)
    forecasts = normalize_forecasts(forecast_raw, delivery_start, delivery_end)
    by_target: dict[str, list[dict[str, Any]]] = {}
    for forecast in forecasts:
        by_target.setdefault(forecast["key"], []).append(forecast)
    for records in by_target.values():
        records.sort(key=lambda rec: rec["published"])

    rows: list[dict[str, Any]] = []
    day = warmup_start
    while day < decision_end:
        delivery_day = day + timedelta(days=1)
        cutoff_local = datetime.combine(day, dt_time(cut_hour, cut_minute), tzinfo=LONDON)
        cutoff_utc = cutoff_local.astimezone(UTC)
        for interval_index in range(PERIODS_PER_DAY):
            target_local = datetime.combine(delivery_day, dt_time.min, tzinfo=LONDON) + timedelta(hours=interval_index)
            target_utc = target_local.astimezone(UTC)
            key = iso_utc(target_utc)
            candidates = [record for record in by_target.get(key, []) if record["published"] <= cutoff_utc]
            selected = candidates[-1] if candidates else None
            actual = actuals.get(key)
            forecast_value = selected["generation"] if selected else None
            error = forecast_value - actual if forecast_value is not None and actual is not None else None
            residual = actual - forecast_value if forecast_value is not None and actual is not None else None
            forecast_lead = (target_utc - selected["published"]).total_seconds() / 3600 if selected else None
            decision_lead = (target_utc - cutoff_utc).total_seconds() / 3600
            rows.append({
                "startTime": key,
                "decisionDate": day.isoformat(),
                "deliveryDate": delivery_day.isoformat(),
                "intervalIndex": interval_index + 1,
                "resolutionMinutes": EVALUATION_INTERVAL_MINUTES,
                "actualMW": round(actual, 2) if actual is not None else None,
                "forecastMW": round(forecast_value, 2) if forecast_value is not None else None,
                "errorMW": round(error, 2) if error is not None else None,
                "actualMinusForecastMW": round(residual, 2) if residual is not None else None,
                "absoluteErrorMW": round(abs(error), 2) if error is not None else None,
                "shortfallMW": round(max(0.0, error), 2) if error is not None else None,
                "percentageError": round(error / actual * 100, 2) if error is not None and actual is not None and actual >= 100 else None,
                "publishTime": iso_utc(selected["published"]) if selected else None,
                "decisionCutoff": cutoff_local.isoformat(timespec="minutes"),
                "forecastLeadHours": round(forecast_lead, 3) if forecast_lead is not None else None,
                "decisionLeadHours": round(decision_lead, 3),
                "intervalLowMW": None,
                "intervalHighMW": None,
            })
        day += timedelta(days=1)
    return rows


def metric_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = len(rows)
    forecasted = [row for row in rows if row["forecastMW"] is not None]
    matched = [row for row in rows if row["forecastMW"] is not None and row["actualMW"] is not None]
    if not matched:
        return {
            "maeMW": None, "rmseMW": None, "biasMW": None, "wapePct": None,
            "mapePct": None, "mapeEligiblePeriods": 0, "p90AbsErrorMW": None, "p95AbsErrorMW": None,
            "p90OverforecastMW": None, "overforecastPct": None, "overforecastMeanMW": None,
            "matchedPeriods": 0, "forecastPeriods": len(forecasted), "actualPeriods": sum(r["actualMW"] is not None for r in rows),
            "expectedPeriods": expected, "coveragePct": 0.0,
            "forecastAvailabilityPct": round(len(forecasted) / expected * 100, 2) if expected else 0.0,
            "missingForecastPeriods": expected - len(forecasted),
            "missingActualPeriods": expected - sum(r["actualMW"] is not None for r in rows),
            "actualEnergyGWh": None, "forecastEnergyGWh": None,
        }
    errors = [float(row["errorMW"]) for row in matched]
    absolute = [abs(value) for value in errors]
    actual_values = [float(row["actualMW"]) for row in matched]
    forecast_values = [float(row["forecastMW"]) for row in matched]
    total_actual = sum(actual_values)
    abs_sum = sum(absolute)
    mape_items = [(abs(float(row["errorMW"])) / float(row["actualMW"])) * 100 for row in matched if float(row["actualMW"]) >= 100]
    positive = [value for value in errors if value > 0]
    return {
        "maeMW": round(sum(absolute) / len(absolute), 2),
        "rmseMW": round(math.sqrt(sum(value * value for value in errors) / len(errors)), 2),
        "biasMW": round(sum(errors) / len(errors), 2),  # forecast - actual; positive means over-forecast
        "wapePct": round(abs_sum / total_actual * 100, 3) if total_actual > 0 else None,
        "mapePct": round(sum(mape_items) / len(mape_items), 3) if mape_items else None,
        "mapeEligiblePeriods": len(mape_items),
        "p90AbsErrorMW": round(percentile(absolute, 0.90) or 0.0, 2),
        "p95AbsErrorMW": round(percentile(absolute, 0.95) or 0.0, 2),
        "p90OverforecastMW": round(percentile([max(0.0, value) for value in errors], 0.90) or 0.0, 2),
        "overforecastPct": round(sum(value > 0 for value in errors) / len(errors) * 100, 2),
        "overforecastMeanMW": round(sum(positive) / len(positive), 2) if positive else 0.0,
        "matchedPeriods": len(matched),
        "forecastPeriods": len(forecasted),
        "actualPeriods": sum(row["actualMW"] is not None for row in rows),
        "expectedPeriods": expected,
        "coveragePct": round(len(matched) / expected * 100, 2) if expected else 0.0,
        "forecastAvailabilityPct": round(len(forecasted) / expected * 100, 2) if expected else 0.0,
        "missingForecastPeriods": expected - len(forecasted),
        "missingActualPeriods": expected - sum(row["actualMW"] is not None for row in rows),
        "actualEnergyGWh": round(sum(actual_values) * EVALUATION_INTERVAL_HOURS / 1000, 3),
        "forecastEnergyGWh": round(sum(forecast_values) * EVALUATION_INTERVAL_HOURS / 1000, 3),
    }


def add_walk_forward_calibration(all_rows: list[dict[str, Any]], decision_start: date, decision_end: date) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Calibrate each decision using only fully completed delivery days before that decision.

    For decision date d, eligible calibration rows must have deliveryDate < d. The current
    delivery day's actuals and later dates never enter the interval/margin estimate.
    """
    by_decision: dict[str, list[dict[str, Any]]] = {}
    for row in all_rows:
        by_decision.setdefault(row["decisionDate"], []).append(row)
    all_evaluation: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    current = decision_start
    while current < decision_end:
        d = current.isoformat()
        delivery = (current + timedelta(days=1)).isoformat()
        this_rows = by_decision.get(d, [])
        history_start = (current - timedelta(days=CALIBRATION_WINDOW_DAYS)).isoformat()
        # Critical timing constraint: on decision date d, only delivery days strictly before d are complete.
        calibration_candidates = [
            row for row in all_rows
            if history_start <= row["deliveryDate"] < d
            and row["actualMW"] is not None and row["forecastMW"] is not None
        ]
        # Count a day toward the minimum only when all 24 hourly intervals have a
        # matched observation. Partial days remain visible in coverage metrics but
        # cannot masquerade as a completed calibration day.
        matched_by_delivery: dict[str, list[dict[str, Any]]] = {}
        for row in calibration_candidates:
            matched_by_delivery.setdefault(row["deliveryDate"], []).append(row)
        sample_days = sorted(day for day, values in matched_by_delivery.items() if len(values) == PERIODS_PER_DAY)
        calibration = [row for day in sample_days for row in matched_by_delivery[day]]
        residuals = [float(row["actualMW"]) - float(row["forecastMW"]) for row in calibration]
        overforecast = [max(0.0, float(row["forecastMW"]) - float(row["actualMW"])) for row in calibration]
        calibration_ready = len(sample_days) >= MIN_CALIBRATION_DAYS
        q10_residual = percentile(residuals, 0.10) if calibration_ready else None
        q90_residual = percentile(residuals, 0.90) if calibration_ready else None
        p90_overforecast = percentile(overforecast, 0.90) if calibration_ready else None
        if calibration_ready:
            for row in this_rows:
                if row["forecastMW"] is None:
                    continue
                low = max(0.0, float(row["forecastMW"]) + float(q10_residual))
                high = max(low, float(row["forecastMW"]) + float(q90_residual))
                row["intervalLowMW"] = round(low, 2)
                row["intervalHighMW"] = round(high, 2)

        matched_today = [row for row in this_rows if row["forecastMW"] is not None and row["actualMW"] is not None]
        in_band = [row for row in matched_today if row["intervalLowMW"] is not None and row["intervalHighMW"] is not None and row["intervalLowMW"] <= row["actualMW"] <= row["intervalHighMW"]]
        widths = [row["intervalHighMW"] - row["intervalLowMW"] for row in this_rows if row["intervalLowMW"] is not None and row["intervalHighMW"] is not None]
        day_metrics = metric_block(this_rows)
        day_publish = max((row["publishTime"] for row in this_rows if row["publishTime"]), default=None)
        day_obj = {
            "decisionDate": d,
            "deliveryDate": delivery,
            "label": (current + timedelta(days=1)).strftime("%d %b"),
            **day_metrics,
            "latestPublishTime": day_publish,
            "periods": len(this_rows),
            "calibrationReady": calibration_ready,
            "calibrationDays": len(sample_days),
            "calibrationMatchedPeriods": len(calibration),
            "calibrationWindowStart": history_start,
            "calibrationWindowEndExclusive": d,
            "intervalLowResidualMW": round(float(q10_residual), 2) if q10_residual is not None else None,
            "intervalHighResidualMW": round(float(q90_residual), 2) if q90_residual is not None else None,
            "marginP90OverforecastMW": round(float(p90_overforecast), 2) if p90_overforecast is not None else None,
            "intervalCoveragePct": round(len(in_band) / len(matched_today) * 100, 2) if matched_today and calibration_ready else None,
            "meanIntervalWidthMW": round(sum(widths) / len(widths), 2) if widths else None,
        }
        daily.append(day_obj)
        all_evaluation.extend(this_rows)
        current += timedelta(days=1)

    calibrated_days = [d for d in daily if d["calibrationReady"] and d["intervalCoveragePct"] is not None]
    coverage_values = [float(d["intervalCoveragePct"]) for d in calibrated_days]
    widths = [float(d["meanIntervalWidthMW"]) for d in calibrated_days if d["meanIntervalWidthMW"] is not None]
    backtest = {
        "method": "Expanding-origin style rolling calibration with a 14-day trailing window; calibration uses only completed delivery days before each decision date.",
        "nominalCoveragePct": 80.0,
        "calibratedDecisionDays": len(calibrated_days),
        "totalDecisionDays": len(daily),
        "meanObservedCoveragePct": round(sum(coverage_values) / len(coverage_values), 2) if coverage_values else None,
        "meanIntervalWidthMW": round(sum(widths) / len(widths), 2) if widths else None,
        "meanAbsoluteCoverageGapPct": round(sum(abs(x - 80.0) for x in coverage_values) / len(coverage_values), 2) if coverage_values else None,
        "note": "Empirical bands are diagnostics, not guarantees. The P90 over-forecast buffer is an error-risk indicator, not a procurement quantity.",
    }
    return daily, backtest


def build_horizon_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bands = [
        (0.0, 12.0, "0–12h"), (12.0, 18.0, "12–18h"), (18.0, 24.0, "18–24h"),
        (24.0, 30.0, "24–30h"), (30.0, 36.0, "30–36h"), (36.0, 42.0, "36–42h"), (42.0, 60.0, "42–60h"), (60.0, 10000.0, "60h+"),
    ]
    output = []
    for lower, upper, label in bands:
        selected = [row for row in rows if row["forecastLeadHours"] is not None and lower <= row["forecastLeadHours"] < upper and row["actualMW"] is not None and row["forecastMW"] is not None]
        metrics = metric_block(selected)
        output.append({"band": label, "lowerHours": lower, "upperHours": None if upper == 10000 else upper, "count": metrics["matchedPeriods"], "maeMW": metrics["maeMW"], "rmseMW": metrics["rmseMW"], "biasMW": metrics["biasMW"], "overforecastPct": metrics["overforecastPct"]})
    return output


def build_hour_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {hour: [] for hour in range(24)}
    for row in rows:
        start = parse_dt(row["startTime"])
        if start:
            grouped[start.astimezone(LONDON).hour].append(row)
    output = []
    for hour, values in grouped.items():
        metrics = metric_block(values)
        output.append({"hour": hour, "label": f"{hour:02d}:00", "count": metrics["matchedPeriods"], "maeMW": metrics["maeMW"], "biasMW": metrics["biasMW"], "overforecastPct": metrics["overforecastPct"]})
    return output


def build_histogram(rows: list[dict[str, Any]], bins: int = 18) -> list[dict[str, Any]]:
    errors = [float(row["errorMW"]) for row in rows if row["errorMW"] is not None]
    if not errors:
        return []
    low, high = min(errors), max(errors)
    if math.isclose(low, high):
        return [{"centerMW": round(low, 2), "count": len(errors), "lowerMW": round(low, 2), "upperMW": round(high, 2)}]
    width = (high - low) / bins
    counts = [0] * bins
    for value in errors:
        index = min(bins - 1, int((value - low) / width))
        counts[index] += 1
    return [{"centerMW": round(low + (index + 0.5) * width, 2), "count": count, "lowerMW": round(low + index * width, 2), "upperMW": round(low + (index + 1) * width, 2)} for index, count in enumerate(counts)]


def analysis_payload(actual_raw: list[dict[str, Any]], forecast_raw: list[dict[str, Any]], source: str, warnings: list[str], fetched_at: datetime | None, cutoff: str) -> dict[str, Any]:
    all_rows = build_decision_rows(actual_raw, forecast_raw, EVAL_START, EVAL_END, cutoff)
    eval_rows = [row for row in all_rows if EVAL_START.isoformat() <= row["decisionDate"] < EVAL_END.isoformat()]
    daily, backtest = add_walk_forward_calibration(all_rows, EVAL_START, EVAL_END)
    metrics = metric_block(eval_rows)
    response_warnings = list(warnings)
    if source == "demo":
        response_warnings.append("Demo analysis uses hourly intervals built from paired synthetic half-hours; no Elexon observations are represented.")
    else:
        response_warnings.append("Resolution harmonization: WINDFOR targets are hourly. Each evaluation actual is the mean of both matching 30-minute FUELHH WIND readings; incomplete pairs remain missing.")
    if metrics["missingForecastPeriods"] or metrics["missingActualPeriods"]:
        response_warnings.append(
            "January data is incomplete: "
            f"{metrics['missingForecastPeriods']} missing forecast periods and "
            f"{metrics['missingActualPeriods']} missing actual periods "
            f"out of {metrics['expectedPeriods']} expected."
        )
    matched = [row for row in eval_rows if row["forecastMW"] is not None and row["actualMW"] is not None]
    latest_publish = max((row["publishTime"] for row in matched if row["publishTime"]), default=None)
    evaluation_delivery_start = datetime.combine(EVAL_START + timedelta(days=1), dt_time.min, tzinfo=LONDON).astimezone(UTC)
    evaluation_delivery_end = datetime.combine(EVAL_END + timedelta(days=1), dt_time.min, tzinfo=LONDON).astimezone(UTC)
    actual_half_hour_count = len(normalize_actuals(actual_raw, evaluation_delivery_start, evaluation_delivery_end))
    expected_actual_half_hours = len(eval_rows) * EVALUATION_INTERVAL_MINUTES // FUELHH_INTERVAL_MINUTES
    canonical_actuals = sorted(actual_raw, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
    canonical_forecasts = sorted(forecast_raw, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
    canonical = json.dumps({"actuals": canonical_actuals, "forecasts": canonical_forecasts}, sort_keys=True, separators=(",", ":"), default=str).encode()
    data_hash = hashlib.sha256(canonical).hexdigest()
    run_hash = hashlib.sha256(f"{data_hash}|{cutoff}|{EVAL_START}|{EVAL_END}".encode()).hexdigest()[:20]
    warmup_rows = [row for row in all_rows if row["decisionDate"] < EVAL_START.isoformat()]
    return {
        "scope": {
            "decisionMonth": "2026-01", "decisionStart": EVAL_START.isoformat(), "decisionEndExclusive": EVAL_END.isoformat(),
            "deliveryStart": (EVAL_START + timedelta(days=1)).isoformat(), "deliveryEndInclusive": EVAL_END.isoformat(),
            "timezone": "Europe/London", "cutoff": cutoff,
            "decisionRule": "For each hourly delivery interval, choose the latest WINDFOR record whose startTime is that interval start and whose publishTime is at or before the configured UK-local cut-off on the preceding decision date.",
            "resolutionRule": "WINDFOR is hourly in the verified stream response. FUELHH actual MW is averaged from both constituent half-hour readings; an incomplete pair is not scored.",
            "calibrationRule": "Margin and interval estimates use a trailing 14-day window of matched errors from fully completed delivery days strictly before the decision date. Warm-up rows are excluded from January headline scores.",
        },
        "metrics": metrics,
        "daily": daily,
        "rows": eval_rows,
        "horizon": build_horizon_metrics(matched),
        "byHour": build_hour_metrics(matched),
        "histogram": build_histogram(matched),
        "backtest": backtest,
        "source": source,
        "status": "demo" if source == "demo" else ("cached" if source in {"cache", "stale-cache"} else "live"),
         "warnings": response_warnings,
        "generatedAt": iso_utc(datetime.now(UTC)),
        "meta": {
            "actualRecords": len(actual_raw), "forecastRecords": len(forecast_raw),
            "matchedPeriods": metrics["matchedPeriods"], "expectedDecisionPeriods": len(eval_rows),
            "warmupDecisionDays": len({row["decisionDate"] for row in warmup_rows}),
            "latestSelectedPublishTime": latest_publish,
            "sourceDatasets": ["FUELHH (fuelType=WIND)", "WINDFOR"],
            "units": "MW; 60-minute evaluation intervals",
            "sourceActualResolutionMinutes": FUELHH_INTERVAL_MINUTES,
            "sourceForecastResolutionMinutes": WINDFOR_INTERVAL_MINUTES,
            "evaluationResolutionMinutes": EVALUATION_INTERVAL_MINUTES,
            "sourceActualHalfHourlyPeriods": actual_half_hour_count,
            "expectedSourceActualHalfHourlyPeriods": expected_actual_half_hours,
            "fetchedAt": iso_utc(fetched_at) if fetched_at else None,
            "dataSha256": data_hash, "analysisRunId": run_hash,
            "decisionPeriodCountPerDay": PERIODS_PER_DAY,
            "cacheTtlSeconds": CACHE_TTL_SECONDS,
            "minCalibrationDays": MIN_CALIBRATION_DAYS,
            "calibrationWindowDays": CALIBRATION_WINDOW_DAYS,
        },
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    # Liveness only: a healthy process does not imply that Elexon is reachable or
    # that the in-memory snapshot contains live records.
    return {"status": "ok", "service": "winddesk", "version": "2.0.0", "evaluationDecisionMonth": "2026-01"}


@app.get("/api/ready")
def readiness() -> dict[str, Any]:
    """Report whether the API process can serve requests, independent of source state."""
    return {"status": "ready", "service": "winddesk"}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return {
        "decisionStart": EVAL_START.isoformat(), "decisionEndInclusive": (EVAL_END - timedelta(days=1)).isoformat(),
        "deliveryStart": (EVAL_START + timedelta(days=1)).isoformat(), "deliveryEndInclusive": EVAL_END.isoformat(),
        "timezone": "Europe/London", "defaultCutoff": "09:00", "sourceDatasets": ["FUELHH", "WINDFOR"],
        "calibrationWarmupDays": WARMUP_DAYS,
    }


@app.get("/api/analysis", response_model=AnalysisResponse)
def analysis(
    month: str = Query(default="2026-01", description="Purchase decision month; this pilot supports January 2026 only"),
    cutoff: str = Query(default="09:00", description="UK local cutoff on D-1, HH:MM"),
    refresh: bool = Query(default=False, description="Force a refresh from Elexon"),
    demo: bool = Query(default=False, description="Explicitly use deterministic synthetic data for UI exploration"),
) -> dict[str, Any]:
    month_window(month)
    parse_cutoff(cutoff)
    actuals, forecasts, source, warnings, fetched_at = load_records(refresh=refresh, force_demo=demo)
    try:
        result = analysis_payload(actuals, forecasts, source, warnings, fetched_at, cutoff)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not analyze the selected dataset: {str(exc)[:260]}") from exc
    return result


# In the single-container production image, FastAPI also serves the built React SPA.
# During local split development the static directory is absent and Vite serves the UI.
STATIC_DIR = Path(os.getenv("STATIC_DIR", "static"))
if STATIC_DIR.is_dir():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend_fallback(path: str):
        # Static files may be served directly, all other paths return the SPA entrypoint.
        if path == "api" or path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (STATIC_DIR / path).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
