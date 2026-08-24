"""Insert Water-link daily usage into Home Assistant long-term statistics.

The meter reading exposed by the portal can lag behind by several days, which
means the sensor state alone puts the accumulated consumption on the wrong
date (https://github.com/zheffie/mijn_waterlink/issues/2). To fix that, the
actual per-day usage is fetched from the portal's ``measurements/day``
endpoint and imported with the recorder statistics API, so every day's
consumption lands on the day it actually happened.

The ``measurements/day`` endpoint returns chart data for the calendar month
containing the ``from`` parameter:

    {
      "estimatedConsumption": [ ... ],
      "actualConsumption": [
        {"day": 1, "isActualConsumption": true, "y": 220, "x": "01",
         "isOnTop": true, "total": 220, "isZeroConsumption": false},
        ...
      ],
      "average": 220,
      "total": 6810
    }

``day`` is the day of the month, ``total`` is that day's usage in liters.
Days with ``isZeroConsumption: true`` carry a small filler value (2% of the
month average, for chart rendering) and really mean zero usage.

The imported data is available as the external statistic
``mijn_waterlink:meter_<meter_id>_consumption`` (pick it in the Energy
dashboard as a water source).
"""

import calendar
import logging
from datetime import date, datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util, slugify

from .const import DOMAIN
from .waterlink_api import WaterlinkClient

try:
    # Replaces has_mean (deprecated, removed in HA Core 2026.11)
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # Home Assistant Core < 2025.3
    StatisticMeanType = None

_LOGGER = logging.getLogger(__name__)

# How far back to backfill when no statistics exist yet.
MAX_BACKFILL_DAYS = 365

# Readings can arrive days late. Wait this long for a missing day before
# giving up and importing the days that came after it.
GAP_GRACE_DAYS = 7


def get_statistic_id(meter_id) -> str:
    return f"{DOMAIN}:meter_{slugify(str(meter_id))}_consumption"


def _to_float(value):
    if isinstance(value, str):
        value = value.replace(",", ".")
    return float(value)


def parse_daily_measurements(raw, month: date) -> dict[date, float]:
    """Turn one month's measurements/day response into {day: usage in m³}.

    ``month`` is any date within the calendar month the response covers (the
    entries only carry a day-of-month number). Days without actual data yet
    are left out so they can be imported once their reading arrives.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("actualConsumption"), list):
        _LOGGER.warning("Unexpected measurements/day response format: %s", type(raw))
        return {}

    days_in_month = calendar.monthrange(month.year, month.month)[1]
    usage_per_day: dict[date, float] = {}
    for item in raw["actualConsumption"]:
        if not isinstance(item, dict) or not item.get("isActualConsumption"):
            continue
        day_number = item.get("day")
        if not isinstance(day_number, int) or not 1 <= day_number <= days_in_month:
            _LOGGER.debug("Skipping entry with invalid day number: %s", item)
            continue
        if item.get("isZeroConsumption"):
            # zero days carry a small filler value so the chart shows a bar
            liters = 0.0
        else:
            try:
                liters = _to_float(item.get("total"))
            except (TypeError, ValueError):
                _LOGGER.debug("Skipping entry with invalid total: %s", item)
                continue
            if liters <= 0:
                continue  # no data for this day (yet)
        usage_per_day[date(month.year, month.month, day_number)] = liters / 1000
    return usage_per_day


async def async_import_daily_statistics(
    hass: HomeAssistant, client: WaterlinkClient, meter_id
) -> None:
    """Fetch new daily measurements and import them as external statistics."""
    statistic_id = get_statistic_id(meter_id)
    recorder = get_instance(hass)
    today = dt_util.now().date()

    last_stats = await recorder.async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    if last_stats and last_stats.get(statistic_id):
        last_stat = last_stats[statistic_id][0]
        running_sum = last_stat.get("sum") or 0.0
        last_start = last_stat["start"]
        if isinstance(last_start, (int, float)):
            last_start = dt_util.utc_from_timestamp(last_start)
        prev_day = dt_util.as_local(last_start).date()
        from_date = prev_day + timedelta(days=1)
    else:
        running_sum = 0.0
        prev_day = None  # fresh backfill: accept whatever the history starts at
        from_date = today - timedelta(days=MAX_BACKFILL_DAYS)

    if from_date >= today:
        return  # already up to date (today is still incomplete)

    # The endpoint serves one calendar month per call.
    usage_per_day: dict[date, float] = {}
    month = from_date.replace(day=1)
    current_month = today.replace(day=1)
    while month <= current_month:
        try:
            raw = await hass.async_add_executor_job(client.get_daily_measurements, month)
        except Exception as err:
            _LOGGER.warning(
                "Fetching daily measurements for %s failed: %s", f"{month:%Y-%m}", err
            )
        else:
            usage_per_day.update(parse_daily_measurements(raw, month))
        month = (month + timedelta(days=32)).replace(day=1)

    # Import completed days only; today's value would never be corrected later.
    candidates = sorted(d for d in usage_per_day if from_date <= d < today)

    # A reading can arrive days late. If a day is missing, hold off importing
    # anything after it for GAP_GRACE_DAYS, otherwise the late day could never
    # be inserted (we only ever import past the last statistic).
    imported_days: list[date] = []
    for day in candidates:
        if prev_day is not None and (day - prev_day).days > 1:
            first_missing = prev_day + timedelta(days=1)
            newest_missing = day - timedelta(days=1)
            if (today - newest_missing).days <= GAP_GRACE_DAYS:
                _LOGGER.debug(
                    "Waiting for delayed measurements for %s..%s before importing %s",
                    first_missing,
                    newest_missing,
                    day,
                )
                break
            _LOGGER.warning(
                "No measurements for %s..%s after %d days; continuing without them",
                first_missing,
                newest_missing,
                GAP_GRACE_DAYS,
            )
        imported_days.append(day)
        prev_day = day

    if not imported_days:
        _LOGGER.debug("No new daily measurements for meter %s since %s", meter_id, from_date)
        return

    statistics: list[StatisticData] = []
    for day in imported_days:
        running_sum += usage_per_day[day]
        start = dt_util.start_of_local_day(datetime(day.year, day.month, day.day))
        statistics.append(StatisticData(start=start, sum=running_sum))

    metadata = StatisticMetaData(
        has_sum=True,
        name=f"water-link meter {meter_id} consumption",
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    )
    if StatisticMeanType is not None:
        metadata["mean_type"] = StatisticMeanType.NONE
        # Required since HA Core 2025.11 (recorder statistics API change).
        metadata["unit_class"] = "volume"
    else:
        metadata["has_mean"] = False

    async_add_external_statistics(hass, metadata, statistics)
    _LOGGER.info(
        "Imported %d day(s) of water usage for meter %s (%s .. %s)",
        len(statistics),
        meter_id,
        imported_days[0],
        imported_days[-1],
    )
