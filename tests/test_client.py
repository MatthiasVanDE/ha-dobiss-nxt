"""Tests for the client's parsing, pairing and command shaping."""

from __future__ import annotations

import base64
import json

import pytest
from api.client import DobissClient
from api.const import Action
from api.models import as_int


@pytest.fixture
def client() -> DobissClient:
    """Build a client that never touches the network in these tests."""
    return DobissClient("192.0.2.10", "s3cr3t", session=object())


def _decode(segment: str) -> dict:
    """Decode one base64url JWT segment."""
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_token_carries_a_real_expiry(client: DobissClient) -> None:
    """The server enforces exp; a token without it never expires."""
    header, payload, signature = client._bearer().split(".")
    assert _decode(header)["alg"] == "HS256"
    claims = _decode(payload)
    assert claims["exp"] > claims["iat"]
    assert signature


def test_token_is_reused_until_it_nears_expiry(client: DobissClient) -> None:
    """A fresh token per request would be pointless work."""
    assert client._bearer() == client._bearer()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, None),
        (0, {"value": 0, "unit": "s"}),
        (120, {"value": 120, "unit": "s"}),
        # Over two minutes the server only accepts whole minutes.
        (121, {"value": 2, "unit": "min"}),
        (600, {"value": 10, "unit": "min"}),
        # And it caps at two hours.
        (99999, {"value": 120, "unit": "min"}),
    ],
)
def test_delay_shaping(seconds, expected) -> None:
    """Delays are expressed the way the API documents them."""
    assert DobissClient._delay(seconds) == expected


def test_discovery_builds_the_registry(client: DobissClient, discover_payload) -> None:
    """Group 0 is skipped, everything else becomes an object."""
    outputs: dict = {}
    from api.models import DobissOutput, SubjectInfo

    for group in discover_payload["groups"]:
        meta = group["group"]
        if as_int(meta["id"]) == 0:
            continue
        for raw in group["subjects"]:
            info = SubjectInfo.from_payload(raw, meta)
            outputs[info.key] = DobissOutput(info)

    # The unassigned relay in group 0 is not offered to Home Assistant.
    assert (0, 19) not in outputs
    assert (2, 7) in outputs
    assert outputs[(3, 2)].info.dimmable is True
    # dimmable "0" must not become True.
    assert outputs[(3, 3)].info.dimmable is False


def test_cover_pairing_prefers_the_lock_field(discover_payload) -> None:
    """The lock field is authoritative and survives typos in names."""
    from api.models import DobissOutput, SubjectInfo

    outputs = {}
    for group in discover_payload["groups"]:
        meta = group["group"]
        if as_int(meta["id"]) == 0:
            continue
        for raw in group["subjects"]:
            info = SubjectInfo.from_payload(raw, meta)
            outputs[info.key] = DobissOutput(info)

    covers = DobissClient._match_covers(outputs)
    by_name = {cover.name: cover for cover in covers.values()}

    assert "Living room shutter" in by_name
    paired = by_name["Living room shutter"]
    assert paired.up.info.channel == 9
    assert paired.down.info.channel == 8
    assert paired.unique_id == "dobissid_7_9-dobissid_7_8"


def test_cover_pairing_falls_back_to_names(discover_payload) -> None:
    """Servers older than NXT 3.0 leave the lock field empty."""
    from api.models import DobissOutput, SubjectInfo

    outputs = {}
    for group in discover_payload["groups"]:
        meta = group["group"]
        if as_int(meta["id"]) == 0:
            continue
        for raw in group["subjects"]:
            info = SubjectInfo.from_payload(raw, meta)
            outputs[info.key] = DobissOutput(info)

    covers = DobissClient._match_covers(outputs)
    names = {cover.name for cover in covers.values()}
    # "Roof window open" and "Roof window dicht" have no locks, so they can
    # only be matched on the Dutch suffix pair the installer used.
    assert "Roof window" in names


def test_status_is_applied_and_nulls_are_skipped(
    client: DobissClient, discover_payload, status_payload
) -> None:
    """A null channel leaves the entity alone instead of raising."""
    from api.models import DobissOutput, SubjectInfo

    for group in discover_payload["groups"]:
        meta = group["group"]
        if as_int(meta["id"]) == 0:
            continue
        for raw in group["subjects"]:
            info = SubjectInfo.from_payload(raw, meta)
            client.outputs[info.key] = DobissOutput(info)

    client._apply(status_payload["status"])

    assert client.outputs[(2, 7)].is_on is True
    assert client.outputs[(3, 2)].value == 60
    assert client.outputs[(206, 3)].is_on is True
    assert client.outputs[(203, 1)].is_on is True
    # The energy element rode along in the same frame.
    assert client.energy.power_usage == 189.0
    assert client.energy.peak_month == 5.33
    assert client.notifications == {"1": "0"}
    assert client.alarm == {"1": {"status": 0}}


def test_a_handshake_frame_is_not_status(client: DobissClient) -> None:
    """The websocket greets us with a WAMP welcome that is not state."""
    client._apply([0, "session-id", 1, "Ratchet/0.4.4"])
    assert not client.energy.has_data


def test_subscriptions_only_fire_for_their_own_key(
    client: DobissClient, discover_payload
) -> None:
    """A hundred entities must not all redraw on every frame."""
    from api.models import DobissOutput, SubjectInfo

    for group in discover_payload["groups"]:
        meta = group["group"]
        if as_int(meta["id"]) == 0:
            continue
        for raw in group["subjects"]:
            info = SubjectInfo.from_payload(raw, meta)
            client.outputs[info.key] = DobissOutput(info)

    # Establish a baseline first: going from "we do not know" to "off" is
    # itself a change, and should be reported.
    client._apply({"2": [0] * 12})

    seen: list[str] = []
    client.subscribe([(2, 7)], lambda: seen.append("hallway"))
    client.subscribe([(2, 8)], lambda: seen.append("socket"))

    client._apply({"2": [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]})
    assert seen == ["hallway"]

    # And an identical frame changes nothing at all.
    client._apply({"2": [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0]})
    assert seen == ["hallway"]


def test_unsubscribing_stops_the_callbacks(client: DobissClient) -> None:
    """Removing an entity must not leave a dangling listener."""
    from api.models import DobissOutput, SubjectInfo

    info = SubjectInfo.from_payload(
        {"name": "x", "address": "2", "channel": "0", "type": "8", "icons_id": "0"},
        {"id": 5, "name": "g"},
    )
    client.outputs[info.key] = DobissOutput(info)

    seen: list[int] = []
    unsubscribe = client.subscribe([info.key], lambda: seen.append(1))
    client._apply({"2": [1]})
    unsubscribe()
    client._apply({"2": [0]})
    assert len(seen) == 1


def test_action_enum_values_match_the_documentation() -> None:
    """These ids are what the server acts on; a typo is silent breakage."""
    assert Action.OFF == 0
    assert Action.ON == 1
    assert Action.TOGGLE == 2
    assert Action.ON_FROM_PIR == 9
    assert Action.ACTIVATE_CALENDAR == 110
