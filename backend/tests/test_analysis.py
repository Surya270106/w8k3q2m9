from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math

import pytest
import httpx
from fastapi.testclient import TestClient

from app import main as api

UTC = timezone.utc


def row(decision_day: date, actual: float, forecast: float, period: int = 1) -> dict:
    delivery_day = decision_day + timedelta(days=1)
    start = datetime.combine(delivery_day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=period - 1)
    error = forecast - actual
    return {
        "startTime": api.iso_utc(start),
        "decisionDate": decision_day.isoformat(),
        "deliveryDate": delivery_day.isoformat(),
        "intervalIndex": period,
        "resolutionMinutes": 60,
        "actualMW": actual,
        "forecastMW": forecast,
        "errorMW": error,
        "actualMinusForecastMW": -error,
        "absoluteErrorMW": abs(error),
        "shortfallMW": max(0.0, error),
        "percentageError": error / actual * 100 if actual >= 100 else None,
        "publishTime": api.iso_utc(start - timedelta(hours=18)),
        "decisionCutoff": f"{decision_day.isoformat()}T09:00+00:00",
        "forecastLeadHours": 18.0,
        "decisionLeadHours": 18.5,
        "intervalLowMW": None,
        "intervalHighMW": None,
    }


def make_calibration_rows() -> list[dict]:
    records = []
    # At least five fully completed delivery days before Jan 1.
    for offset in range(14, 0, -1):
        decision_day = date(2026, 1, 1) - timedelta(days=offset)
        for period in range(1, 25):
            records.append(row(decision_day, actual=1000.0, forecast=1000.0, period=period))
    # Current evaluation delivery (Jan 2) is deliberately a dramatic miss. It must not calibrate itself.
    for period in range(1, 25):
        records.append(row(date(2026, 1, 1), actual=0.0, forecast=10_000.0, period=period))
    return records


def test_cutoff_validation_rejects_invalid_times():
    assert api.parse_cutoff("09:00") == (9, 0)
    assert api.parse_cutoff("23:59") == (23, 59)
    with pytest.raises(Exception):
        api.parse_cutoff("24:00")
    with pytest.raises(Exception):
        api.parse_cutoff("9am")


def test_scope_only_allows_january_2026_decision_dates():
    assert api.month_window("2026-01") == (date(2026, 1, 1), date(2026, 2, 1))
    with pytest.raises(Exception):
        api.month_window("2026-02")


@pytest.mark.parametrize("timestamp", ["2026-01-02T00:00:00", "2026-01-02T00:00:00+25:00", "not-a-timestamp"])
def test_parse_datetime_rejects_naive_and_malformed_source_timestamps(timestamp):
    assert api.parse_dt(timestamp) is None


def test_parse_datetime_normalizes_explicit_timezone_offsets_to_utc():
    assert api.parse_dt("2026-01-02T01:00:00+01:00") == datetime(2026, 1, 2, tzinfo=UTC)


@pytest.mark.parametrize("status,expected_attempts", [(400, 1), (401, 1), (403, 1), (404, 1), (429, 3), (500, 3), (503, 3)])
def test_fetch_json_retries_only_throttling_or_server_statuses(monkeypatch, status, expected_attempts):
    calls = []

    class StubClient:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def get(self, url, params):
            calls.append((url, params))
            request = httpx.Request("GET", url)
            response = httpx.Response(status, request=request)
            raise httpx.HTTPStatusError("controlled", request=request, response=response)

    monkeypatch.setattr(api.httpx, "Client", StubClient)
    monkeypatch.setattr(api.time, "sleep", lambda _delay: None)
    with pytest.raises(RuntimeError):
        api.fetch_json("https://example.invalid/datasets/WINDFOR/stream", {}, attempts=3)
    assert len(calls) == expected_attempts


def test_fetch_json_accepts_empty_array_and_retries_truncated_json(monkeypatch):
    calls = []
    responses = [[], ValueError("truncated JSON"), ValueError("truncated JSON"), ValueError("truncated JSON")]

    class StubClient:
        def __init__(self, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def get(self, url, params):
            calls.append(url)
            result = responses.pop(0)
            if isinstance(result, Exception):
                class BrokenResponse:
                    def raise_for_status(self): return None
                    def json(self): raise result
                return BrokenResponse()
            class GoodResponse:
                def raise_for_status(self): return None
                def json(self): return result
            return GoodResponse()

    monkeypatch.setattr(api.httpx, "Client", StubClient)
    monkeypatch.setattr(api.time, "sleep", lambda _delay: None)
    assert api.fetch_json("https://example.invalid/datasets/FUELHH/stream", {}) == []
    with pytest.raises(RuntimeError, match="truncated JSON"):
        api.fetch_json("https://example.invalid/datasets/FUELHH/stream", {})
    assert len(calls) == 4


def test_actual_normalization_keeps_wind_only():
    records = [
        {"startTime": "2026-01-02T00:00:00Z", "fuelType": "WIND", "generation": 120},
        {"startTime": "2026-01-02T00:00:00Z", "fuelType": "CCGT", "generation": 999},
    ]
    result = api.normalize_actuals(records, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert result["2026-01-02T00:00:00Z"] == 120


def test_actual_normalization_uses_latest_revision_when_publish_times_exist():
    records = [
        {"startTime": "2026-01-02T00:00:00Z", "fuelType": "WIND", "generation": 100, "publishTime": "2026-01-02T00:35:00Z"},
        {"startTime": "2026-01-02T00:00:00Z", "fuelType": "WIND", "generation": 108, "publishTime": "2026-01-02T01:10:00Z"},
    ]
    result = api.normalize_actuals(records, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert result["2026-01-02T00:00:00Z"] == 108


def test_fuelhh_settlement_date_and_period_validate_start_time():
    records = [
        {"startTime": "2026-01-02T12:00:00Z", "settlementDate": "2026-01-02", "settlementPeriod": 25, "fuelType": "WIND", "generation": 100},
        {"startTime": "2026-01-02T12:30:00Z", "settlementDate": "2026-01-02", "settlementPeriod": 26, "fuelType": "WIND", "generation": 120},
        {"startTime": "2026-01-02T13:00:00Z", "settlementDate": "2026-01-02", "settlementPeriod": 26, "fuelType": "WIND", "generation": 999},
    ]
    result = api.normalize_actuals(records, datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert result == {"2026-01-02T12:00:00Z": 100, "2026-01-02T12:30:00Z": 120}


@pytest.mark.parametrize("settlement_date,period,start_time", [
    ("2026-03-29", 3, "2026-03-29T01:00:00Z"),  # spring-forward: first interval after the skipped hour
    ("2026-10-25", 3, "2026-10-25T00:00:00Z"),  # first 01:00, still BST
    ("2026-10-25", 5, "2026-10-25T01:00:00Z"),  # repeated 01:00, now GMT
])
def test_fuelhh_settlement_periods_follow_utc_interval_sequence_across_dst(settlement_date, period, start_time):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2027, 1, 1, tzinfo=UTC)
    records = [{"startTime": start_time, "settlementDate": settlement_date,
                "settlementPeriod": period, "fuelType": "WIND", "generation": 123}]
    normalized = api.normalize_actuals(records, start, end)
    assert normalized == {api.iso_utc(api.parse_dt(start_time)): 123}


def test_hourly_actual_normalization_averages_1200_and_1230_only_as_a_pair():
    records = [
        {"startTime": "2026-01-02T12:00:00Z", "settlementDate": "2026-01-02", "settlementPeriod": 25, "fuelType": "WIND", "generation": 100},
        {"startTime": "2026-01-02T12:30:00Z", "settlementDate": "2026-01-02", "settlementPeriod": 26, "fuelType": "WIND", "generation": 120},
        {"startTime": "2026-01-02T13:00:00Z", "settlementDate": "2026-01-02", "settlementPeriod": 27, "fuelType": "WIND", "generation": 180},
    ]
    actuals = api.normalize_hourly_actuals(records, datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert actuals["2026-01-02T12:00:00Z"] == 110
    assert "2026-01-02T13:00:00Z" not in actuals  # no 13:30 input; do not copy/fill


def test_hourly_actual_normalization_converts_offsets_before_grouping():
    records = [
        {"startTime": "2026-01-02T13:00:00+01:00", "fuelType": "WIND", "generation": 100},
        {"startTime": "2026-01-02T13:30:00+01:00", "fuelType": "WIND", "generation": 120},
    ]
    actuals = api.normalize_hourly_actuals(records, datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert actuals == {"2026-01-02T12:00:00Z": 110}


def test_forecast_normalization_deduplicates_same_vintage():
    raw = [
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T08:30:00Z", "generation": 80},
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T08:30:00Z", "generation": 81},
    ]
    normalized = api.normalize_forecasts(raw, datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert len(normalized) == 1
    assert normalized[0]["generation"] == 80


def test_forecast_normalization_rejects_naive_publication_and_delivery_timestamps():
    bounds = (datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    rows = [
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T09:00:00", "generation": 100},
        {"startTime": "2026-01-02T00:00:00", "publishTime": "2026-01-01T09:00:00Z", "generation": 100},
    ]
    assert api.normalize_forecasts(rows, *bounds) == []


def test_source_normalization_drops_null_missing_non_numeric_nan_and_infinite_values():
    actual_start = datetime(2026, 1, 2, tzinfo=UTC)
    bounds = (actual_start, actual_start + timedelta(days=1))
    records = [
        {"startTime": api.iso_utc(actual_start + timedelta(minutes=30*i)), "fuelType": "WIND", "generation": value}
        for i, value in enumerate([None, "not-number", "NaN", "Infinity", "-Infinity"])
    ]
    assert api.normalize_actuals(records, *bounds) == {}
    forecasts = [
        {"startTime": api.iso_utc(actual_start), "publishTime": f"2026-01-01T0{i}:00:00Z", "generation": value}
        for i, value in enumerate([None, "not-number", "NaN", "Infinity", "-Infinity"])
    ]
    assert api.normalize_forecasts(forecasts, *bounds) == []


def test_conflicting_duplicate_vintage_is_independent_of_input_order():
    raw = [
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T08:30:00Z", "generation": 80},
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T08:30:00Z", "generation": 81},
    ]
    bounds = (datetime(2026, 1, 2, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    forward = api.normalize_forecasts(raw, *bounds)
    reverse = api.normalize_forecasts(list(reversed(raw)), *bounds)
    assert forward == reverse


def test_decision_alignment_selects_latest_vintage_at_or_before_cutoff():
    actuals = [
        {"startTime": "2026-01-02T00:00:00Z", "fuelType": "WIND", "generation": 100},
        {"startTime": "2026-01-02T00:30:00Z", "fuelType": "WIND", "generation": 120},
    ]
    forecasts = [
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T08:30:00Z", "generation": 110},
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T10:00:00+01:00", "generation": 120},
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T09:01:00Z", "generation": 999},
        {"startTime": "2026-01-02T00:30:00Z", "publishTime": "2026-01-02T12:00:00Z", "generation": 777},
    ]
    rows = api.build_decision_rows(actuals, forecasts, date(2026, 1, 1), date(2026, 1, 2), "09:00")
    selected = next(item for item in rows if item["decisionDate"] == "2026-01-01" and item["intervalIndex"] == 1)
    assert selected["deliveryDate"] == "2026-01-02"
    assert selected["actualMW"] == 110
    assert selected["actualHalfHour00MW"] == 100
    assert selected["actualHalfHour30MW"] == 120
    assert selected["forecastMW"] == 120
    assert selected["publishTime"] == "2026-01-01T09:00:00Z"
    assert selected["errorMW"] == 10
    assert len([item for item in rows if item["decisionDate"] == "2026-01-01"]) == 24


def test_decision_cutoff_change_changes_selected_vintage():
    actuals = [
        {"startTime": "2026-01-02T00:00:00Z", "fuelType": "WIND", "generation": 100},
        {"startTime": "2026-01-02T00:30:00Z", "fuelType": "WIND", "generation": 100},
    ]
    forecasts = [
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T08:30:00Z", "generation": 110},
        {"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T10:30:00Z", "generation": 130},
    ]
    early = api.build_decision_rows(actuals, forecasts, date(2026, 1, 1), date(2026, 1, 2), "09:00")
    late = api.build_decision_rows(actuals, forecasts, date(2026, 1, 1), date(2026, 1, 2), "11:00")
    early_row = next(item for item in early if item["decisionDate"] == "2026-01-01" and item["intervalIndex"] == 1)
    late_row = next(item for item in late if item["decisionDate"] == "2026-01-01" and item["intervalIndex"] == 1)
    assert early_row["forecastMW"] == 110
    assert late_row["forecastMW"] == 130


def test_missing_half_hour_pair_remains_missing_in_hourly_expected_denominator():
    midnight = datetime(2026, 1, 2, tzinfo=UTC)
    actuals = [
        {"startTime": api.iso_utc(midnight + timedelta(minutes=30 * i)), "fuelType": "WIND", "generation": 100}
        for i in range(48) if i != 25
    ]
    forecasts = [
        {"startTime": api.iso_utc(midnight + timedelta(hours=i)), "publishTime": "2026-01-01T09:00:00Z", "generation": 110}
        for i in range(24)
    ]
    rows = api.build_decision_rows(actuals, forecasts, date(2026, 1, 1), date(2026, 1, 2), "09:00")
    hour = next(item for item in rows if item["decisionDate"] == "2026-01-01" and item["intervalIndex"] == 13)
    assert hour["forecastMW"] == 110
    assert hour["actualMW"] is None
    assert hour["actualHalfHour00MW"] == 100
    assert hour["actualHalfHour30MW"] is None
    metrics = api.metric_block([row for row in rows if row["decisionDate"] == "2026-01-01"])
    assert metrics["expectedPeriods"] == 24
    assert metrics["matchedPeriods"] == 23
    assert metrics["missingActualPeriods"] == 1


def test_expected_periods_include_missing_records_in_denominator():
    rows = [
        {"actualMW": 100.0, "forecastMW": 110.0, "errorMW": 10.0},
        {"actualMW": 100.0, "forecastMW": None, "errorMW": None},
        {"actualMW": None, "forecastMW": 100.0, "errorMW": None},
        {"actualMW": 100.0, "forecastMW": 100.0, "errorMW": 0.0},
    ]
    metrics = api.metric_block(rows)
    assert metrics["expectedPeriods"] == 4
    assert metrics["matchedPeriods"] == 2
    assert metrics["coveragePct"] == 50.0


def test_metrics_use_forecast_minus_actual_sign_convention():
    rows = [
        {"actualMW": 100.0, "forecastMW": 120.0, "errorMW": 20.0},
        {"actualMW": 200.0, "forecastMW": 180.0, "errorMW": -20.0},
    ]
    metrics = api.metric_block(rows)
    assert metrics["maeMW"] == 20
    assert metrics["biasMW"] == 0
    assert metrics["wapePct"] == pytest.approx(40 / 300 * 100, abs=0.001)
    assert metrics["overforecastPct"] == 50


def test_metric_definitions_match_hand_calculated_fixture():
    rows = [
        {"actualMW": 100.0, "forecastMW": 102.0, "errorMW": 2.0, "forecastLeadHours": 6.0},
        {"actualMW": 200.0, "forecastMW": 198.0, "errorMW": -2.0, "forecastLeadHours": 12.0},
        {"actualMW": 50.0, "forecastMW": 50.0, "errorMW": 0.0, "forecastLeadHours": 18.0},
        {"actualMW": 0.0, "forecastMW": 4.0, "errorMW": 4.0, "forecastLeadHours": 24.0},
    ]
    metrics = api.metric_block(rows)
    assert metrics["maeMW"] == 2.0
    assert metrics["rmseMW"] == pytest.approx(6 ** 0.5, abs=0.01)  # public metric is rounded to 2 decimals
    assert metrics["biasMW"] == 1.0
    assert metrics["wapePct"] == pytest.approx(8 / 350 * 100, abs=0.001)
    assert metrics["mapePct"] == pytest.approx(1.5)
    assert metrics["mapeEligiblePeriods"] == 2
    assert metrics["p90AbsErrorMW"] == pytest.approx(3.4)
    assert metrics["p95AbsErrorMW"] == pytest.approx(3.7)
    assert metrics["p90OverforecastMW"] == pytest.approx(3.4)
    assert metrics["overforecastPct"] == 50.0
    assert metrics["overforecastMeanMW"] == 3.0
    assert api.build_horizon_metrics(rows)[0]["count"] == 1
    assert api.build_horizon_metrics(rows)[1]["count"] == 1


def test_metric_block_empty_zero_total_and_single_observation_are_explicit():
    empty = api.metric_block([])
    assert empty["matchedPeriods"] == 0
    assert empty["maeMW"] is None
    assert empty["wapePct"] is None
    zero_actual = api.metric_block([{"actualMW": 0.0, "forecastMW": 0.0, "errorMW": 0.0}])
    assert zero_actual["wapePct"] is None
    assert zero_actual["mapePct"] is None
    assert zero_actual["p90AbsErrorMW"] == 0.0
    single = api.metric_block([{"actualMW": 100.0, "forecastMW": 125.0, "errorMW": 25.0}])
    assert single["maeMW"] == single["rmseMW"] == single["biasMW"] == 25.0
    assert single["p90AbsErrorMW"] == single["p95AbsErrorMW"] == single["p90OverforecastMW"] == 25.0


def test_metric_block_large_finite_errors_do_not_overflow_rmse_to_infinity():
    metrics = api.metric_block([
        {"actualMW": 0.0, "forecastMW": 1e200, "errorMW": 1e200},
        {"actualMW": 0.0, "forecastMW": -1e200, "errorMW": -1e200},
    ])
    assert metrics["rmseMW"] == pytest.approx(1e200)
    assert math.isfinite(metrics["rmseMW"])


def test_p90_overforecast_is_not_p90_absolute_error():
    rows = [
        {"actualMW": 100.0, "forecastMW": 90.0, "errorMW": -10.0},
        {"actualMW": 100.0, "forecastMW": 90.0, "errorMW": -10.0},
        {"actualMW": 100.0, "forecastMW": 130.0, "errorMW": 30.0},
        {"actualMW": 100.0, "forecastMW": 120.0, "errorMW": 20.0},
        {"actualMW": 100.0, "forecastMW": 100.0, "errorMW": 0.0},
    ]
    metrics = api.metric_block(rows)
    assert metrics["p90AbsErrorMW"] >= metrics["p90OverforecastMW"]
    assert metrics["p90OverforecastMW"] == pytest.approx(26.0)


def test_rolling_calibration_excludes_current_delivery_day():
    rows = make_calibration_rows()
    daily, _ = api.add_walk_forward_calibration(rows, date(2026, 1, 1), date(2026, 1, 2))
    jan1 = daily[0]
    assert jan1["calibrationReady"] is True
    assert jan1["calibrationWindowEndExclusive"] == "2026-01-01"
    assert jan1["intervalLowResidualMW"] == 0
    assert jan1["intervalHighResidualMW"] == 0
    assert jan1["marginP90OverforecastMW"] == 0
    assert jan1["intervalCoveragePct"] == 0  # today's 10 GW miss did not widen today's own band


def test_calibration_requires_minimum_history():
    rows = []
    for period in range(1, 25):
        rows.append(row(date(2026, 1, 1), actual=100, forecast=100, period=period))
    daily, _ = api.add_walk_forward_calibration(rows, date(2026, 1, 1), date(2026, 1, 2))
    assert daily[0]["calibrationReady"] is False
    assert daily[0]["marginP90OverforecastMW"] is None


def test_partial_delivery_days_do_not_count_as_complete_calibration_days():
    records = []
    delivery_days = [date(2025, 12, 18) + timedelta(days=i) for i in range(6)]
    for index, delivery_day in enumerate(delivery_days):
        decision_day = delivery_day - timedelta(days=1)
        period_count = 24 if index < 4 else 23
        for period in range(1, period_count + 1):
            records.append(row(decision_day, actual=1000, forecast=1010, period=period))
    daily, _ = api.add_walk_forward_calibration(records, date(2026, 1, 1), date(2026, 1, 2))
    assert daily[0]["calibrationDays"] == 4
    assert daily[0]["calibrationMatchedPeriods"] == 4 * 24
    assert daily[0]["calibrationReady"] is False


def test_january_evaluation_rows_are_january_decisions_and_next_day_deliveries():
    actuals, forecasts = api.demo_data(date(2025, 12, 17), date(2026, 2, 1))
    result = api.analysis_payload(actuals, forecasts, "demo", [], None, "09:00")
    assert len(result["daily"]) == 31
    assert result["daily"][0]["decisionDate"] == "2026-01-01"
    assert result["daily"][0]["deliveryDate"] == "2026-01-02"
    assert result["daily"][-1]["decisionDate"] == "2026-01-31"
    assert result["daily"][-1]["deliveryDate"] == "2026-02-01"
    assert result["metrics"]["expectedPeriods"] == 31 * 24
    assert all(row["decisionDate"] >= "2026-01-01" for row in result["rows"])
    assert result["meta"]["warmupDecisionDays"] == api.WARMUP_DAYS + 1
    assert len(result["horizon"]) == 8
    assert sum(item["count"] for item in result["histogram"]) == result["metrics"]["matchedPeriods"]



def test_snapshot_cache_round_trip_is_atomic_and_versioned(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    actuals = [{"startTime": "2026-01-02T00:00:00Z", "fuelType": "WIND", "generation": 123}]
    forecasts = [{"startTime": "2026-01-02T00:00:00Z", "publishTime": "2026-01-01T09:00:00Z", "generation": 130}]
    fetched = datetime(2026, 1, 2, 1, 0, tzinfo=UTC)
    api._write_disk_cache(actuals, forecasts, fetched)
    snapshot = tmp_path / "elexon_snapshot.json"
    assert snapshot.exists()
    assert not (tmp_path / "elexon_snapshot.json.tmp").exists()
    actual_read, forecast_read, fetched_read = api._read_disk_cache()
    assert actual_read == actuals
    assert forecast_read == forecasts
    assert fetched_read == fetched


def test_analysis_hash_is_invariant_to_source_record_order():
    actuals, forecasts = api.demo_data(date(2025, 12, 17), date(2026, 2, 1))
    first = api.analysis_payload(actuals, forecasts, "demo", [], None, "09:00")
    second = api.analysis_payload(list(reversed(actuals)), list(reversed(forecasts)), "demo", [], None, "09:00")
    assert first["meta"]["dataSha256"] == second["meta"]["dataSha256"]
    assert first["meta"]["analysisRunId"] == second["meta"]["analysisRunId"]

def test_demo_payload_is_explicitly_marked_and_has_reproducible_run_id():
    actuals, forecasts = api.demo_data(date(2025, 12, 17), date(2026, 2, 1))
    first = api.analysis_payload(actuals, forecasts, "demo", ["synthetic"], None, "09:00")
    second = api.analysis_payload(actuals, forecasts, "demo", ["synthetic"], None, "09:00")
    assert first["source"] == "demo"
    assert first["status"] == "demo"
    assert first["metrics"]["matchedPeriods"] > 700
    assert first["meta"]["analysisRunId"] == second["meta"]["analysisRunId"]



def test_actuals_fetch_uses_settlement_date_bounds_and_wind_filter(monkeypatch):
    captured = []
    def fake_fetch(url, params, **kwargs):
        captured.append((url, params))
        return []
    monkeypatch.setattr(api, "fetch_json", fake_fetch)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    assert api.fetch_actuals(start, end) == []
    assert len(captured) == 1
    url, params = captured[0]
    assert url.endswith("/datasets/FUELHH/stream")
    assert params == {"settlementDateFrom": "2026-01-01", "settlementDateTo": "2026-01-01", "fuelType": "WIND"}


def test_actual_settlement_date_chunk_ranges_are_inclusive_and_non_overlapping():
    ranges = api._calendar_date_ranges(date(2026, 1, 1), date(2026, 1, 17), 7)
    assert ranges == [
        (date(2026, 1, 1), date(2026, 1, 7)),
        (date(2026, 1, 8), date(2026, 1, 14)),
        (date(2026, 1, 15), date(2026, 1, 16)),
    ]


def test_forecast_fetch_uses_publication_time_bounds(monkeypatch):
    captured = []
    def fake_fetch(url, params, **kwargs):
        captured.append((url, params))
        return []
    monkeypatch.setattr(api, "fetch_json", fake_fetch)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    assert api.fetch_forecasts(start, end) == []
    assert len(captured) == 1
    url, params = captured[0]
    assert url.endswith("/datasets/WINDFOR/stream")
    assert params == {"publishDateTimeFrom": "2026-01-01T00:00:00Z", "publishDateTimeTo": "2026-01-02T00:00:00Z"}


def test_actual_normalization_rejects_missing_fuel_type():
    records = [{"startTime": "2026-01-02T00:00:00Z", "generation": 120}]
    result = api.normalize_actuals(records, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC))
    assert result == {}

def test_health_endpoint_is_available_without_upstream_network():
    with TestClient(api.app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_endpoint_does_not_claim_live_data():
    with TestClient(api.app) as client:
        response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "winddesk"}


def test_analysis_http_endpoint_rejects_unsupported_month():
    with TestClient(api.app) as client:
        response = client.get("/api/analysis?month=2026-02")
    assert response.status_code == 400
    assert "January 2026" in response.json()["detail"]


def test_analysis_http_endpoint_returns_upstream_error_without_demo_fallback(monkeypatch):
    def fail_load(**_kwargs):
        raise api.HTTPException(status_code=502, detail="controlled source failure")
    monkeypatch.setattr(api, "load_records", fail_load)
    with TestClient(api.app) as client:
        response = client.get("/api/analysis?refresh=true&demo=false")
    assert response.status_code == 502
    assert response.json() == {"detail": "controlled source failure"}


def test_demo_analysis_http_endpoint_is_explicit_and_response_validated(monkeypatch):
    def fail_live(*_args, **_kwargs):
        raise AssertionError("demo=true must not call a live Elexon endpoint")
    monkeypatch.setattr(api, "fetch_actuals", fail_live)
    monkeypatch.setattr(api, "fetch_forecasts", fail_live)
    with TestClient(api.app) as client:
        response = client.get("/api/analysis?demo=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "demo"
    assert payload["status"] == "demo"
    assert payload["meta"]["fetchedAt"] is None
    assert any("Synthetic demo mode" in warning for warning in payload["warnings"])
    row = next(item for item in payload["rows"] if item["decisionDate"] == "2026-01-01" and item["intervalIndex"] == 13)
    assert row["actualHalfHour00MW"] is not None
    assert row["actualHalfHour30MW"] is not None
    assert row["actualMW"] == round((row["actualHalfHour00MW"] + row["actualHalfHour30MW"]) / 2, 2)


def test_explicit_demo_analysis_endpoint_does_not_call_live_api(monkeypatch):
    def fail_live(*_args, **_kwargs):
        raise AssertionError("live fetch must not be called when demo=true")
    monkeypatch.setattr(api, "fetch_actuals", fail_live)
    monkeypatch.setattr(api, "fetch_forecasts", fail_live)
    # Call the route function directly to avoid mutable global cache state from other tests.
    response = api.analysis(month="2026-01", cutoff="09:00", refresh=False, demo=True)
    assert response["source"] == "demo"
    assert response["status"] == "demo"


def test_analysis_response_schema_exposes_constituent_actuals():
    actuals, forecasts = api.demo_data(date(2025, 12, 17), date(2026, 2, 1))
    payload = api.analysis_payload(actuals, forecasts, "demo", ["synthetic"], None, "09:00")
    response = api.AnalysisResponse.model_validate(payload)
    row = next(item for item in response.rows if item.decisionDate == "2026-01-01" and item.intervalIndex == 13)
    assert row.actualHalfHour00MW is not None
    assert row.actualHalfHour30MW is not None
    assert row.actualMW == round((row.actualHalfHour00MW + row.actualHalfHour30MW) / 2, 2)
