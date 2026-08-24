"""Unit tests for the statistics import logic — the fix for issue #2.

The recorder and the Waterlink client are mocked; these verify that daily
usage lands on the correct dates with correct cumulative sums, that the
importer fetches month by month, and that late-arriving days are waited for.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

import custom_components.mijn_waterlink.statistics as stats

METER_ID = "123456"
STATISTIC_ID = "mijn_waterlink:meter_123456_consumption"


def _day(offset):
    """A local date `offset` days before today."""
    return dt_util.now().date() - timedelta(days=offset)


def _midnight(offset):
    """Local midnight of the day `offset` days before today."""
    return dt_util.start_of_local_day(dt_util.now() - timedelta(days=offset))


def make_hass():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    return hass


def make_recorder(last_stats):
    recorder = MagicMock()
    recorder.async_add_executor_job = AsyncMock(return_value=last_stats)
    return recorder


def month_response_factory(liters_per_day: dict):
    """Build a per-month measurements/day response from {date: liters}."""

    def respond(month_start: date):
        entries = [
            {
                "day": d.day,
                "isActualConsumption": True,
                "y": liters,
                "x": f"{d.day:02d}",
                "isOnTop": True,
                "total": liters if liters else 4.4,  # portal filler on zero days
                "isZeroConsumption": liters == 0,
            }
            for d, liters in liters_per_day.items()
            if (d.year, d.month) == (month_start.year, month_start.month)
        ]
        return {
            "estimatedConsumption": [],
            "actualConsumption": entries,
            "average": 220,
            "total": sum(liters_per_day.values()),
        }

    return respond


async def _run(liters_per_day, last_stats):
    hass = make_hass()
    client = MagicMock()
    client.get_daily_measurements.side_effect = month_response_factory(liters_per_day)
    with (
        patch.object(stats, "get_instance", return_value=make_recorder(last_stats)),
        patch.object(stats, "async_add_external_statistics") as add_stats,
    ):
        await stats.async_import_daily_statistics(hass, client, METER_ID)
    return client, add_stats


def _last_stats(day_offset, total):
    return {STATISTIC_ID: [{"start": _midnight(day_offset).timestamp(), "sum": total}]}


async def test_backfill_from_scratch_excludes_today():
    client, add_stats = await _run(
        {_day(2): 200, _day(1): 300, _day(0): 100},  # today: incomplete
        last_stats={},
    )

    # first run backfills month by month from MAX_BACKFILL_DAYS ago
    first_month = _day(stats.MAX_BACKFILL_DAYS).replace(day=1)
    current_month = _day(0).replace(day=1)
    called_months = [c.args[0] for c in client.get_daily_measurements.call_args_list]
    assert called_months[0] == first_month
    assert called_months[-1] == current_month
    assert all(m.day == 1 for m in called_months)
    assert len(called_months) in (12, 13)

    add_stats.assert_called_once()
    _, metadata, rows = add_stats.call_args.args
    assert metadata["statistic_id"] == STATISTIC_ID
    assert metadata["source"] == "mijn_waterlink"
    assert metadata["has_sum"] is True
    assert metadata["unit_of_measurement"] == "m³"

    assert len(rows) == 2  # today is excluded
    assert rows[0]["start"] == _midnight(2)
    assert rows[0]["sum"] == pytest.approx(0.2)
    assert rows[1]["start"] == _midnight(1)
    assert rows[1]["sum"] == pytest.approx(0.5)


async def test_continues_from_last_statistic():
    client, add_stats = await _run(
        {_day(2): 200, _day(1): 300, _day(0): 100},
        last_stats=_last_stats(2, 5.0),  # day-2 already imported with sum 5.0
    )

    # fetches only from the month of the day after the last statistic
    assert client.get_daily_measurements.call_args_list[0].args[0] == _day(1).replace(day=1)

    add_stats.assert_called_once()
    rows = add_stats.call_args.args[2]
    assert len(rows) == 1
    assert rows[0]["start"] == _midnight(1)
    assert rows[0]["sum"] == pytest.approx(5.3)  # continues the running total


async def test_zero_usage_day_still_advances_the_import():
    _, add_stats = await _run(
        {_day(2): 0, _day(1): 300},
        last_stats=_last_stats(3, 5.0),
    )

    rows = add_stats.call_args.args[2]
    assert len(rows) == 2
    assert rows[0]["start"] == _midnight(2)
    assert rows[0]["sum"] == pytest.approx(5.0)  # zero usage: sum unchanged
    assert rows[1]["sum"] == pytest.approx(5.3)


async def test_waits_for_recent_missing_day():
    # day-2 has no data yet (late reading): nothing after it may be imported
    client, add_stats = await _run(
        {_day(3): 200, _day(1): 300},
        last_stats=_last_stats(4, 5.0),
    )

    rows = add_stats.call_args.args[2]
    assert len(rows) == 1
    assert rows[0]["start"] == _midnight(3)
    assert rows[0]["sum"] == pytest.approx(5.2)


async def test_waits_when_the_first_expected_day_is_missing():
    # last import was day-3; day-2 is missing, day-1 present: import nothing yet
    client, add_stats = await _run(
        {_day(1): 300},
        last_stats=_last_stats(3, 5.0),
    )

    add_stats.assert_not_called()


async def test_skips_gap_older_than_grace_period():
    # days 11..9 before today never got data — beyond GAP_GRACE_DAYS, move on
    assert stats.GAP_GRACE_DAYS < 8
    _, add_stats = await _run(
        {_day(12): 200, _day(8): 300},
        last_stats=_last_stats(13, 5.0),
    )

    rows = add_stats.call_args.args[2]
    assert len(rows) == 2
    assert rows[0]["start"] == _midnight(12)
    assert rows[1]["start"] == _midnight(8)
    assert rows[1]["sum"] == pytest.approx(5.5)


async def test_noop_when_already_up_to_date():
    client, add_stats = await _run({}, last_stats=_last_stats(1, 5.0))

    client.get_daily_measurements.assert_not_called()
    add_stats.assert_not_called()


async def test_noop_when_no_new_measurements():
    client, add_stats = await _run({}, last_stats={})

    assert client.get_daily_measurements.called
    add_stats.assert_not_called()


async def test_metadata_uses_new_recorder_api_fields():
    if stats.StatisticMeanType is None:
        pytest.skip("Home Assistant Core < 2025.3: StatisticMeanType not available")

    _, add_stats = await _run({_day(1): 300}, last_stats={})

    metadata = add_stats.call_args.args[1]
    assert metadata["mean_type"] == stats.StatisticMeanType.NONE
    assert metadata["unit_class"] == "volume"
    assert "has_mean" not in metadata
