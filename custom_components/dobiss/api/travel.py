"""Position bookkeeping for covers driven by two relays.

A Dobiss cover is two relays and nothing else: there is no position feedback and
no end-stop signal. The only way to know where a cover is, is to remember how
long it ran and in which direction.

The original integration borrowed xknx's ``TravelCalculator`` for this, which
pinned the whole integration to xknx 0.9.4 from 2019 and conflicted with the
version Home Assistant's own KNX integration needs. This is the same idea in
about eighty lines, with no dependency.

Positions follow the Home Assistant convention: 0 is fully closed, 100 is fully
open.
"""

from __future__ import annotations

import time
from enum import StrEnum

POSITION_CLOSED = 0
POSITION_OPEN = 100


class TravelStatus(StrEnum):
    """What the cover is doing right now."""

    STOPPED = "stopped"
    OPENING = "opening"
    CLOSING = "closing"


class TravelCalculator:
    """Estimate a cover's position from how long its relays were energised."""

    def __init__(self, travel_time_down: float, travel_time_up: float) -> None:
        """Store the full-travel times, in seconds, for each direction."""
        self.travel_time_down = max(float(travel_time_down), 0.1)
        self.travel_time_up = max(float(travel_time_up), 0.1)

        self._last_known_position: float = POSITION_CLOSED
        self._travel_started_at: float = 0.0
        self._travel_to_position: float = POSITION_CLOSED
        self._status: TravelStatus = TravelStatus.STOPPED
        self._position_confirmed = False

    # -- clock -------------------------------------------------------------
    # Wrapped so tests can freeze time without patching the whole module.
    def _now(self) -> float:
        """Read the monotonic clock, in seconds."""
        return time.monotonic()

    # -- state -------------------------------------------------------------
    @property
    def status(self) -> TravelStatus:
        """Whether the cover is opening, closing or stopped."""
        return self._status

    @property
    def is_traveling(self) -> bool:
        """Whether the cover is currently moving."""
        return self._status is not TravelStatus.STOPPED

    @property
    def is_opening(self) -> bool:
        """Whether the cover is moving towards open."""
        return self._status is TravelStatus.OPENING

    @property
    def is_closing(self) -> bool:
        """Whether the cover is moving towards closed."""
        return self._status is TravelStatus.CLOSING

    @property
    def position_known(self) -> bool:
        """Whether the position is a real measurement rather than a guess.

        False until the cover has completed a full run in one direction, or the
        position was restored from a previous Home Assistant run.
        """
        return self._position_confirmed

    def set_position(self, position: float, *, confirmed: bool = True) -> None:
        """Declare where the cover is, cancelling any travel in progress."""
        self._last_known_position = self._clamp(position)
        self._travel_to_position = self._last_known_position
        self._status = TravelStatus.STOPPED
        self._position_confirmed = confirmed

    def current_position(self) -> int:
        """Where the cover is now, as a whole percentage."""
        return round(self._interpolate())

    def is_closed(self) -> bool:
        """Whether the cover is fully closed."""
        return self.current_position() <= POSITION_CLOSED

    def is_open(self) -> bool:
        """Whether the cover is fully open."""
        return self.current_position() >= POSITION_OPEN

    def position_reached(self) -> bool:
        """Whether the cover has arrived where it was sent."""
        return self._interpolate() == self._travel_to_position

    # -- commands ----------------------------------------------------------
    def start_travel(self, target: float) -> None:
        """Begin travelling towards ``target``."""
        target = self._clamp(target)
        current = self._interpolate()
        self._last_known_position = current
        self._travel_started_at = self._now()
        self._travel_to_position = target
        if target > current:
            self._status = TravelStatus.OPENING
        elif target < current:
            self._status = TravelStatus.CLOSING
        else:
            self._status = TravelStatus.STOPPED

    def start_travel_up(self) -> None:
        """Begin travelling to fully open."""
        self.start_travel(POSITION_OPEN)

    def start_travel_down(self) -> None:
        """Begin travelling to fully closed."""
        self.start_travel(POSITION_CLOSED)

    def stop(self) -> None:
        """Stop where the cover is right now."""
        position = self._interpolate()
        # Reaching an end stop is the one moment the position is certain: the
        # motor's own limit switch defines it, so any accumulated drift is gone.
        if position in (POSITION_CLOSED, POSITION_OPEN):
            self._position_confirmed = True
        self._last_known_position = position
        self._travel_to_position = position
        self._status = TravelStatus.STOPPED

    # -- internals ---------------------------------------------------------
    def _interpolate(self) -> float:
        """Position right now, taking travel in progress into account."""
        if self._status is TravelStatus.STOPPED:
            return self._last_known_position

        elapsed = self._now() - self._travel_started_at
        travel_time = (
            self.travel_time_up
            if self._status is TravelStatus.OPENING
            else self.travel_time_down
        )
        travelled = (elapsed / travel_time) * POSITION_OPEN

        if self._status is TravelStatus.OPENING:
            position = self._last_known_position + travelled
            reached = position >= self._travel_to_position
        else:
            position = self._last_known_position - travelled
            reached = position <= self._travel_to_position

        if reached:
            return self._travel_to_position
        return self._clamp(position)

    @staticmethod
    def _clamp(position: float) -> float:
        """Keep a position inside 0-100."""
        return max(float(POSITION_CLOSED), min(float(POSITION_OPEN), float(position)))
