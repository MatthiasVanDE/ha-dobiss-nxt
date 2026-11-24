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


def _grid_frame(**overrides):
    """Build a healthy frame, as the NXT sent it on 2026-11-23 before 16:40."""
    current = {
        "datetime": "2026-11-23 16:39:00",
        "use": "2380",
        "pro": "0",
        "use_low": 3348.256,
        "use_high": 3798.57,
        "pro_low": 1500.375,
        "pro_high": 655.584,
        "solar": None,
        "solar_total": "16647.553",
        "peak": 2.69,
        "peak_forecast": 3.59,
        "peak_month": 6.15,
        "peak_month_datetime": "2026-11-04 07:15",
    }
    current.update(overrides)
    return {"battery_available": False, "0": current}


# What the NXT sent from 2026-11-23 16:40: its P1 source was gone and it read a
# heat pump sub-meter instead, with the tariff-2 registers null.
FALLBACK_FRAME = {
    "battery_available": False,
    "0": {
        "datetime": "2026-11-24 06:43:00",
        "use": "2601",
        "pro": "0",
        "use_low": 15394.376,
        "use_high": None,
        "pro_low": 0,
        "pro_high": None,
        "solar": None,
        "solar_total": "16647.553",
        "peak": 2.5,
        "peak_forecast": 2.51,
        "peak_month": 32879.06,
        "peak_month_datetime": "2026-11-23 16:45",
        "peak_history": {
            "labels": ["2026-09", "2026-10", "2026-11"],
            "data": {"peak": ["35847.29", "4.26", "32879.06"]},
        },
    },
    "1": {"use": "14.31", "pro": "0.00", "solar": "0.00"},
    "2": {"use": "8268.85", "pro": "-655.58", "solar": "0.00"},
}


def test_energy_fallback_meter_is_not_the_grid() -> None:
    """A frame without tariff 2 describes another meter and must not count."""
    energy = EnergySnapshot()
    energy.apply(_grid_frame(), now=0.0)
    assert energy.grid_meter_present
    assert energy.energy_usage_low == 3348.256

    energy.apply(FALLBACK_FRAME, now=60.0)
    assert not energy.grid_meter_present
    # The registers keep the last grid reading instead of the sub-meter's.
    assert energy.energy_usage_low == 3348.256
    assert energy.energy_usage_high == 3798.57
    assert energy.energy_production_low == 1500.375
    # Nonsense peaks and day totals are dropped, and so are old months that
    # the server recorded while it was reading the wrong meter.
    assert energy.peak_month is None
    assert energy.peak_history == {"2026-10": 4.26}
    assert energy.yesterday_usage is None
    assert energy.yesterday_production is None
    # Solar does not depend on the grid meter.
    assert energy.energy_solar_total == 16647.553


def test_energy_grid_meter_comes_back() -> None:
    """Back on the grid meter, the registers carry on from where they were."""
    energy = EnergySnapshot()
    energy.apply(_grid_frame(), now=0.0)
    energy.apply(FALLBACK_FRAME, now=60.0)
    energy.apply(_grid_frame(use_low=3361.2), now=15 * 3600.0)
    assert energy.grid_meter_present
    assert energy.energy_usage_low == 3361.2


def test_energy_register_rejects_glitches() -> None:
    """A register that runs backwards or leaps is a glitch, not a reading."""
    energy = EnergySnapshot()
    energy.apply(_grid_frame(use_low=3348.096), now=0.0)
    # Seen live at 16:38 on 2026-11-23: one frame 0.3 kWh lower.
    energy.apply(_grid_frame(use_low=3347.783), now=60.0)
    assert energy.energy_usage_low == 3348.096
    # 12000 kWh in a minute is not a house.
    energy.apply(_grid_frame(use_low=15365.955), now=120.0)
    assert energy.energy_usage_low == 3348.096
    assert energy.rejected_readings == 2
    # The next genuine reading is accepted.
    energy.apply(_grid_frame(use_low=3348.256), now=180.0)
    assert energy.energy_usage_low == 3348.256


def test_energy_register_accepts_a_long_gap() -> None:
    """After a long outage the meter has legitimately moved on a lot."""
    energy = EnergySnapshot()
    energy.apply(_grid_frame(use_low=2619.643), now=0.0)
    energy.apply(_grid_frame(use_low=3113.5), now=49 * 24 * 3600.0)
    assert energy.energy_usage_low == 3113.5
