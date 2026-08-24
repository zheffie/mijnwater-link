"""Shared test fixtures.

Live tests need credentials, provided either as environment variables
(WATERLINK_USERNAME, WATERLINK_PASSWORD, WATERLINK_CLIENT_ID,
WATERLINK_METER_ID) or in a git-ignored ``tests/credentials.json`` file —
copy ``tests/credentials.example.json`` and fill it in.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ENV_VARS = {
    "username": "WATERLINK_USERNAME",
    "password": "WATERLINK_PASSWORD",
    "client_id": "WATERLINK_CLIENT_ID",
    "meter_id": "WATERLINK_METER_ID",
}


@pytest.fixture(scope="session")
def credentials():
    creds = {key: os.environ.get(var) for key, var in ENV_VARS.items()}
    if all(creds.values()):
        return creds

    path = Path(__file__).parent / "credentials.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in ENV_VARS if not data.get(key)]
        if missing:
            pytest.fail(f"tests/credentials.json is missing: {', '.join(missing)}")
        return {key: str(data[key]) for key in ENV_VARS}

    pytest.skip(
        "No Water-link credentials: set WATERLINK_* environment variables or "
        "create tests/credentials.json (see tests/credentials.example.json)"
    )
