"""Unit tests for the Waterlink HTTP client (no credentials needed)."""

from datetime import date

from custom_components.mijn_waterlink.waterlink_api import WaterlinkClient


def test_get_daily_measurements_builds_expected_request(requests_mock):
    client = WaterlinkClient("user", "pass", "client-id", "123456")
    client.token = "test-token"

    requests_mock.get(
        "https://portaaldigitalemeters.water-link.be/api/measurements/day",
        json=[{"date": "2025-06-01", "consumption": 0.25}],
    )

    result = client.get_daily_measurements(date(2025, 6, 1))

    assert result == [{"date": "2025-06-01", "consumption": 0.25}]
    request = requests_mock.request_history[0]
    assert request.qs["from"] == ["2025-06-01"]
    assert request.qs["meternumber"] == ["123456"]
    assert request.headers["Authorization"] == "Bearer test-token"


def test_get_meter_data_uses_meter_endpoint(requests_mock):
    client = WaterlinkClient("user", "pass", "client-id", "123456")
    client.token = "test-token"

    requests_mock.get(
        "https://portaaldigitalemeters.water-link.be/api/meters/123456",
        json={"meterReading": "123,456"},
    )

    assert client.get_meter_data() == {"meterReading": "123,456"}
    assert requests_mock.request_history[0].headers["Authorization"] == "Bearer test-token"
