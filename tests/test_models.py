"""Tests for parsing what the NXT server sends."""

from __future__ import annotations

import pytest
from api.const import IconId, SubjectType
from api.models import EnergySnapshot, SubjectInfo, as_bool, as_float, as_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        (True, True),
        (False, False),
        (0, False),
        (1, True),
        ("1", True),
        # The whole reason this helper exists: bool("0") is True in Python, so
        # a plain cast marks a non-dimmable output as dimmable.
        ("0", False),
        ("", False),
        ("false", False),
        ("FALSE", False),
        (" 1 ", True),
    ],
)
def test_as_bool(value, expected) -> None:
    """Dobiss sends the same flag as null, bool and string."""
    assert as_bool(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("7", 7), (7, 7), (7.9, 7), ("nonsense", None)],
)
def test_as_int(value, expected) -> None:
    """Unusable values become None rather than raising."""
    assert as_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("2619.643", 2619.643), (5, 5.0), ("bad", None)],
)
def test_as_float(value, expected) -> None:
    """Numbers arrive as strings more often than not."""
    assert as_float(value) == expected


def test_subject_info_parses_a_light() -> None:
    """A relay output programmed as a light."""
    info = SubjectInfo.from_payload(
        {
            "name": "Toilet gelijkvloers",
            "address": "2",
            "channel": "7",
            "type": "8",
            "icons_id": "0",
            "dimmable": None,
            "settings": {"locks": [None, None], "readonly": "0", "pincode": "1234"},
        },
        {"id": 8, "name": "Inkom"},
    )
    assert info.address == 2
    assert info.channel == 7
    assert info.subject_type is SubjectType.RELAY_MODULE
    assert info.icon is IconId.LIGHT
    assert info.is_light
    assert not info.dimmable
    assert info.unique_id == "dobissid_2_7"
    # The pincode of an output has no business in a state attribute.
    assert "pincode" not in info.raw["settings"]


def test_subject_info_survives_unknown_codes() -> None:
    """A firmware update may introduce types and icons we do not know."""
    info = SubjectInfo.from_payload(
        {
            "name": "Mystery",
            "address": "9",
            "channel": "1",
            "type": "99",
            "icons_id": "77",
        },
        {"id": 3, "name": "Elsewhere"},
    )
    assert info.subject_type is None
    assert info.icon is None
    assert not info.is_light


def test_subject_info_reads_the_cover_lock() -> None:
    """From NXT 3.0 the server states which channel is the other direction."""
    info = SubjectInfo.from_payload(
        {
            "name": "Rolluik Bureau Links",
            "address": "7",
            "channel": "9",
            "type": "8",
            "icons_id": "3",
            "dimmable": None,
            "settings": {"locks": [8, None]},
        },
        {"id": 1, "name": "Rolluiken"},
    )
    assert info.is_cover_up
    assert info.lock_channel == 8


def test_energy_snapshot_parses_the_live_payload() -> None:
    """The figures that the capacity tariff is billed on."""
    energy = EnergySnapshot()
    changed = energy.apply(
        {
            "battery_available": False,
            "0": {
                "datetime": "2026-09-19 09:58:00",
                "use": "0",
                "pro": "365",
                "use_low": 2619.643,
                "use_high": 2876.407,
                "pro_low": 1324.601,
                "pro_high": 573.131,
                "solar": None,
                "solar_total": "16647.553",
                "peak": 0.37,
                "peak_month": 5.33,
                "peak_month_datetime": "2026-09-16 17:30",
                "peak_forecast": 1.02,
                "peak_history": {
                    "labels": ["2026-08", "2026-09"],
                    "data": {"peak": ["5.95", "5.33"]},
                },
                "battery_soc": None,
                "own": 0,
                "own_pct": 0,
                "unit": "W",
            },
            "1": {"use": "4.98", "pro": "0.01", "solar": "0.00"},
            "2": {"use": "17.25", "pro": "6.17", "solar": "0.00"},
        }
    )
    assert changed
    assert energy.has_data
    assert energy.power_production == 365.0
    assert energy.energy_usage_high == 2876.407
    assert energy.peak_month == 5.33
    assert energy.peak_forecast == 1.02
    assert energy.peak_history == {"2026-08": 5.95, "2026-09": 5.33}
    assert energy.today_usage == 4.98
    assert energy.yesterday_production == 6.17
    assert energy.battery_soc is None
    assert not energy.battery_available
    # solar_total is set even though the instantaneous figure is null.
    assert energy.has_solar

    # Applying the same payload again is not a change.
    assert not energy.apply(
        {
            "battery_available": False,
            "0": {
                "datetime": "2026-09-19 09:58:00",
                "use": "0",
                "pro": "365",
                "use_low": 2619.643,
                "use_high": 2876.407,
                "pro_low": 1324.601,
                "pro_high": 573.131,
                "solar": None,
                "solar_total": "16647.553",
                "peak": 0.37,
                "peak_month": 5.33,
                "peak_month_datetime": "2026-09-16 17:30",
                "peak_forecast": 1.02,
                "peak_history": {
                    "labels": ["2026-08", "2026-09"],
                    "data": {"peak": ["5.95", "5.33"]},
                },
                "battery_soc": None,
                "own": 0,
                "own_pct": 0,
                "unit": "W",
            },
            "1": {"use": "4.98", "pro": "0.01", "solar": "0.00"},
            "2": {"use": "17.25", "pro": "6.17", "solar": "0.00"},
        }
    )
