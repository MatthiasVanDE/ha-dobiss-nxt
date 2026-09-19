"""Shared fixtures.

The tests target the API package, which is deliberately free of Home Assistant
imports so it can be exercised without spinning up a full Home Assistant test
harness.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "dobiss")
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def discover_payload() -> dict:
    """Return a discovery response shaped like a real NXT server on 4.30."""
    return json.loads((FIXTURES / "discover.json").read_text(encoding="utf-8"))


@pytest.fixture
def status_payload() -> dict:
    """Return a status response matching the discovery fixture."""
    return json.loads((FIXTURES / "status.json").read_text(encoding="utf-8"))
