"""Tests for the cover travel calculator."""

from __future__ import annotations

import pytest
from api.travel import TravelCalculator, TravelStatus


class FakeClock(TravelCalculator):
    """A calculator whose clock we drive by hand."""

    def __init__(self, down: float, up: float) -> None:
        """Start the clock at zero."""
        self.now = 0.0
        super().__init__(down, up)

    def _now(self) -> float:
        """Return the time we set."""
        return self.now


@pytest.fixture
def calculator() -> FakeClock:
    """Build a cover that takes 20 seconds each way."""
    return FakeClock(20.0, 20.0)


def test_starts_closed_and_unconfirmed(calculator: FakeClock) -> None:
    """Nothing is known until the cover has been somewhere."""
    assert calculator.current_position() == 0
    assert calculator.is_closed()
    assert not calculator.position_known


def test_full_travel_up(calculator: FakeClock) -> None:
    """Twenty seconds of travel reaches the top."""
    calculator.start_travel_up()
    assert calculator.status is TravelStatus.OPENING
    calculator.now = 10.0
    assert calculator.current_position() == 50
    calculator.now = 20.0
    assert calculator.current_position() == 100
    assert calculator.position_reached()


def test_stopping_halfway_keeps_the_position(calculator: FakeClock) -> None:
    """A partial run leaves the cover where it stopped."""
    calculator.start_travel_up()
    calculator.now = 6.0
    calculator.stop()
    assert calculator.current_position() == 30
    assert not calculator.is_traveling
    # Stopping halfway proves nothing about where the cover really is.
    assert not calculator.position_known


def test_reaching_an_end_stop_confirms_the_position(calculator: FakeClock) -> None:
    """The motor's own limit switch is the one reliable reference."""
    calculator.start_travel_up()
    calculator.now = 25.0
    calculator.stop()
    assert calculator.current_position() == 100
    assert calculator.position_known
    assert calculator.is_open()


def test_travel_to_a_target(calculator: FakeClock) -> None:
    """Travelling to a target stops there, not at the end."""
    calculator.set_position(100)
    calculator.start_travel(40)
    assert calculator.status is TravelStatus.CLOSING
    calculator.now = 12.0
    assert calculator.current_position() == 40
    assert calculator.position_reached()


def test_position_never_leaves_the_range(calculator: FakeClock) -> None:
    """Running past an end stop does not produce 120 percent."""
    calculator.start_travel_up()
    calculator.now = 1000.0
    assert calculator.current_position() == 100
    calculator.start_travel_down()
    calculator.now = 2000.0
    assert calculator.current_position() == 0


def test_asymmetric_travel_times() -> None:
    """Many covers close faster than they open."""
    calculator = FakeClock(10.0, 20.0)
    calculator.start_travel_up()
    calculator.now = 10.0
    assert calculator.current_position() == 50
    calculator.stop()
    calculator.start_travel_down()
    calculator.now = 15.0
    assert calculator.current_position() == 0


def test_a_zero_travel_time_does_not_divide_by_zero() -> None:
    """A misconfigured travel time must not crash the entity."""
    calculator = FakeClock(0.0, 0.0)
    calculator.start_travel_up()
    calculator.now = 1.0
    assert calculator.current_position() == 100
