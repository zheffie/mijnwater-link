"""Live tests against the real Water-link portal.

Excluded from normal runs. Provide credentials (see tests/conftest.py) and run:

    pytest -m live -s

Raw API responses are saved to git-ignored ``tests/live_*_sample.json`` files
so the undocumented response schema can be inspected.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from custom_components.mijn_waterlink.statistics import parse_daily_measurements
from custom_components.mijn_waterlink.waterlink_api import WaterlinkClient

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client(credentials):
    client = WaterlinkClient(
        credentials["username"],
        credentials["password"],
        credentials["client_id"],
        credentials["meter_id"],
    )
    client.authenticate()
    return client


def test_authenticate(client):
    assert client.token, "Authentication succeeded but no access token was set"


def test_get_meter_data(client):
    data = client.get_meter_data()

    sample_path = Path(__file__).parent / "live_meter_data_sample.json"
    sample_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nMeter data saved to {sample_path}:\n{json.dumps(data, indent=2)}")

    assert isinstance(data, dict)
    assert "meterReading" in data


def test_get_daily_measurements_and_parse(client):
    today = date.today()
    current_month = today.replace(day=1)
    previous_month = (current_month - timedelta(days=1)).replace(day=1)

    usage_per_day = {}
    for month in (previous_month, current_month):
        raw = client.get_daily_measurements(month)

        sample_path = Path(__file__).parent / f"live_measurements_{month:%Y_%m}_sample.json"
        sample_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        print(f"\nRaw measurements/day response for {month:%Y-%m} saved to {sample_path}")

        usage_per_day.update(parse_daily_measurements(raw, month))

    print(f"Parsed {len(usage_per_day)} day(s) of usage:")
    for day, usage in sorted(usage_per_day.items()):
        print(f"  {day}: {usage:.3f} m³")

    # show how not-yet-received days are encoded (readings arrive days late)
    recent = [d for d in (today - timedelta(days=o) for o in range(4)) if d not in usage_per_day]
    if recent:
        print(f"Days without actual data yet (expected for recent days): {sorted(recent)}")

    assert usage_per_day, (
        "Parser extracted no daily usage — inspect the saved sample files and "
        "adjust custom_components/mijn_waterlink/statistics.py"
    )
    for day, usage in usage_per_day.items():
        assert previous_month <= day <= today, f"Date out of range: {day}"
        assert 0 <= usage < 20, f"Implausible daily usage for {day}: {usage} m³"
