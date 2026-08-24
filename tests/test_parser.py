"""Unit tests for parsing the measurements/day response (no credentials needed).

The response schema was captured from the live portal (see
tests/test_live_api.py): one calendar month of chart data, day-of-month
numbers, totals in liters, and a small filler value on zero-usage days.
"""

from datetime import date

import pytest

from custom_components.mijn_waterlink.statistics import (
    get_statistic_id,
    parse_daily_measurements,
)

JULY = date(2026, 7, 1)


def entry(day, total, actual=True, zero=False):
    return {
        "day": day,
        "isActualConsumption": actual,
        "y": total if actual else 0,
        "x": str(day).zfill(2),
        "isOnTop": actual,
        "total": total,
        "isZeroConsumption": zero,
    }


def response(*entries, estimated=()):
    return {
        "estimatedConsumption": list(estimated),
        "actualConsumption": list(entries),
        "average": 220,
        "total": sum(e.get("total") for e in entries if isinstance(e.get("total"), (int, float))),
    }


def test_liters_converted_to_cubic_meters():
    raw = response(entry(1, 220), entry(2, 147))
    assert parse_daily_measurements(raw, JULY) == {
        date(2026, 7, 1): pytest.approx(0.22),
        date(2026, 7, 2): pytest.approx(0.147),
    }


def test_zero_consumption_filler_value_becomes_zero():
    # zero days carry ~2% of the month average so the chart shows a bar
    raw = response(entry(1, 4.4, zero=True))
    assert parse_daily_measurements(raw, JULY) == {date(2026, 7, 1): 0.0}


def test_non_actual_entries_are_skipped():
    raw = response(entry(1, 220), entry(2, 180, actual=False))
    assert parse_daily_measurements(raw, JULY) == {date(2026, 7, 1): pytest.approx(0.22)}


def test_estimated_consumption_list_is_ignored():
    raw = response(entry(1, 220), estimated=[entry(2, 999, actual=False)])
    assert parse_daily_measurements(raw, JULY) == {date(2026, 7, 1): pytest.approx(0.22)}


def test_zero_total_without_flag_means_no_data_yet():
    raw = response(entry(1, 220), entry(2, 0))
    assert parse_daily_measurements(raw, JULY) == {date(2026, 7, 1): pytest.approx(0.22)}


def test_month_context_builds_the_dates():
    raw = response(entry(15, 100))
    assert parse_daily_measurements(raw, date(2025, 2, 1)) == {
        date(2025, 2, 15): pytest.approx(0.1)
    }


def test_day_numbers_outside_the_month_are_skipped():
    raw = response(entry(15, 100), entry(30, 100), entry(0, 100), entry(32, 100))
    # February 2025 has 28 days
    assert parse_daily_measurements(raw, date(2025, 2, 1)) == {
        date(2025, 2, 15): pytest.approx(0.1)
    }


def test_comma_decimal_totals_are_parsed():
    raw = response(entry(1, "4,4"))
    assert parse_daily_measurements(raw, JULY) == {date(2026, 7, 1): pytest.approx(0.0044)}


def test_invalid_entries_are_skipped():
    raw = response(entry(1, 220), entry(2, None), entry("3", 100), {"foo": "bar"})
    raw["actualConsumption"].append("not-a-dict")
    assert parse_daily_measurements(raw, JULY) == {date(2026, 7, 1): pytest.approx(0.22)}


def test_garbage_response_returns_empty():
    assert parse_daily_measurements("oops", JULY) == {}
    assert parse_daily_measurements(None, JULY) == {}
    assert parse_daily_measurements({}, JULY) == {}
    assert parse_daily_measurements({"actualConsumption": "x"}, JULY) == {}
    assert parse_daily_measurements({"error": "unauthorized"}, JULY) == {}


def test_statistic_id_is_valid_and_slugified():
    assert get_statistic_id("123456") == "mijn_waterlink:meter_123456_consumption"
    assert get_statistic_id("AB-12 34") == "mijn_waterlink:meter_ab_12_34_consumption"
