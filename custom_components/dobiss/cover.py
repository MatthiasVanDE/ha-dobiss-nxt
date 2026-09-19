"""Cover platform for the Dobiss NXT integration.

A Dobiss cover is two relays and nothing else. There is no position feedback and
no end-stop signal, so Home Assistant can only know where a cover is by watching
how long each relay was energised. Two modes are offered:

**basic**
    Report open or closed only when a run lasted long enough to have reached an
    end stop, and say nothing otherwise. Honest, and needs no calibration beyond
    a single threshold.

**position**
    Keep a running estimate and offer a position slider. Needs the real travel
    time of the cover, which is not the same as the time the Dobiss relay stays
    energised: a tubular motor stops itself at its limit switch while the relay
    keeps running for its configured duration.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .api import DobissCover, TravelCalculator
from .const import COVER_MODE_POSITION
from .coordinator import DobissConfigEntry, DobissHub
from .entity import DobissEntity

#: How often the position is refreshed while a cover is moving. The original
#: integration did this ten times a second per cover, which writes a state to
#: the recorder about ten thousand times for one "close everything" run.
_TICK = timedelta(seconds=1)

ATTR_LAST_DIRECTION_UP = "last_direction_up"
ATTR_LAST_RUN_SECONDS = "last_run_seconds"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DobissConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Dobiss covers."""
    hub = entry.runtime_data
    settings = hub.cover_settings
    positional = settings.mode == COVER_MODE_POSITION

    async_add_entities(
        DobissPositionCover(hub, cover) if positional else DobissBasicCover(hub, cover)
        for cover in hub.client.covers.values()
        if not hub.is_ignored(cover.up.info.address)
    )


class DobissCoverBase(DobissEntity, RestoreEntity):
    """Shared plumbing for both cover modes."""

    _attr_name = None
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_assumed_state = True

    def __init__(self, hub: DobissHub, cover: DobissCover) -> None:
        """Watch both relays of this cover."""
        super().__init__(hub, [cover.up.info.key, cover.down.info.key])
        self._cover = cover
        self._attr_unique_id = cover.unique_id
        self._attr_device_info = hub.child_device_info(
            cover.up.info.unique_id, cover.name
        )
        self._was_moving_up = False
        self._was_moving_down = False

    @property
    def is_opening(self) -> bool:
        """Whether the raise relay is energised."""
        return self._cover.is_moving_up

    @property
    def is_closing(self) -> bool:
        """Whether the lower relay is energised."""
        return self._cover.is_moving_down

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Where this cover sits in the Dobiss programming."""
        return {
            "dobiss_group": self._cover.up.info.group,
            "address": self._cover.up.info.address,
            "up_channel": self._cover.up.info.channel,
            "down_channel": self._cover.down.info.channel,
        }

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Drive the cover up."""
        await self._hub.client.async_turn_on(
            self._cover.up.info.address, self._cover.up.info.channel
        )

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Drive the cover down."""
        await self._hub.client.async_turn_on(
            self._cover.down.info.address, self._cover.down.info.channel
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Drop both relays, which stops the motor."""
        await self._hub.client.async_turn_off(
            self._cover.up.info.address, self._cover.up.info.channel
        )
        await self._hub.client.async_turn_off(
            self._cover.down.info.address, self._cover.down.info.channel
        )


class DobissBasicCover(DobissCoverBase):
    """Open or closed, deduced from how long the last run lasted."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )

    def __init__(self, hub: DobissHub, cover: DobissCover) -> None:
        """Start with nothing known about where the cover is."""
        super().__init__(hub, cover)
        self._last_direction_up: bool | None = None
        self._last_run_seconds: float | None = None
        self._run_started: Any = None

    async def async_added_to_hass(self) -> None:
        """Bring back what we knew before the restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is None:
            return
        attributes = last_state.attributes
        # "last_up" and "delta" are what the integration this one replaces
        # called these, so an existing installation keeps knowing where its
        # covers are instead of going blank until the next full run.
        direction = attributes.get(ATTR_LAST_DIRECTION_UP, attributes.get("last_up"))
        if isinstance(direction, bool):
            self._last_direction_up = direction
        run = attributes.get(ATTR_LAST_RUN_SECONDS, attributes.get("delta"))
        if isinstance(run, (int, float)) and not isinstance(run, bool):
            self._last_run_seconds = float(run)

    @callback
    def _handle_update(self) -> None:
        """Time each run so we can tell a full travel from a nudge."""
        moving_up = self._cover.is_moving_up
        moving_down = self._cover.is_moving_down

        if (moving_up and not self._was_moving_up) or (
            moving_down and not self._was_moving_down
        ):
            self._last_direction_up = moving_up
            self._run_started = dt_util.utcnow()
        elif (
            not moving_up
            and not moving_down
            and (self._was_moving_up or self._was_moving_down)
            and self._run_started is not None
        ):
            self._last_run_seconds = (
                dt_util.utcnow() - self._run_started
            ).total_seconds()
            self._run_started = None

        self._was_moving_up = moving_up
        self._was_moving_down = moving_down
        super()._handle_update()

    @property
    def is_closed(self) -> bool | None:
        """Whether the cover is fully closed, when that can be known.

        Returns None while the cover is moving, and also after a run that was
        too short to have reached an end stop - because then nobody knows.
        """
        if self._cover.is_moving:
            return None
        close_time = self._hub.cover_settings.close_time
        if close_time <= 0 or self._last_direction_up is None:
            return None
        if self._last_run_seconds is None or self._last_run_seconds <= close_time:
            return None
        return not self._last_direction_up

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the reasoning behind the deduced state."""
        return {
            **super().extra_state_attributes,
            ATTR_LAST_DIRECTION_UP: self._last_direction_up,
            ATTR_LAST_RUN_SECONDS: (
                None
                if self._last_run_seconds is None
                else round(self._last_run_seconds, 1)
            ),
        }


class DobissPositionCover(DobissCoverBase):
    """A running position estimate, with a slider."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, hub: DobissHub, cover: DobissCover) -> None:
        """Build a travel calculator with this cover's own timings."""
        super().__init__(hub, cover)
        up_time, down_time = hub.cover_settings.for_cover(cover.unique_id)
        self._travel = TravelCalculator(down_time, up_time)
        self._unsub_tick: Any = None
        self._unsub_autostop: Any = None

    async def async_added_to_hass(self) -> None:
        """Restore the last estimated position."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is None:
            return
        position = last_state.attributes.get("current_position")
        if isinstance(position, (int, float)):
            self._travel.set_position(float(position))

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the timers this entity owns."""
        self._stop_tick()
        self._cancel_autostop()
        await super().async_will_remove_from_hass()

    @property
    def current_cover_position(self) -> int:
        """Where we believe the cover is, 0 closed to 100 open."""
        return self._travel.current_position()

    @property
    def is_closed(self) -> bool:
        """Whether the cover is fully closed."""
        return self._travel.is_closed()

    @callback
    def _handle_update(self) -> None:
        """Follow the relays, whoever operated them.

        This is what makes the estimate survive the physical wall buttons: the
        relay state arrives over the websocket either way.
        """
        moving_up = self._cover.is_moving_up
        moving_down = self._cover.is_moving_down

        if moving_up and not self._was_moving_up:
            self._travel.start_travel_up()
            self._start_tick()
        elif moving_down and not self._was_moving_down:
            self._travel.start_travel_down()
            self._start_tick()
        elif not moving_up and not moving_down and self._travel.is_traveling:
            self._travel.stop()
            self._stop_tick()
            self._cancel_autostop()

        self._was_moving_up = moving_up
        self._was_moving_down = moving_down
        super()._handle_update()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Drive the cover to a position and stop it when it gets there."""
        target = int(kwargs[ATTR_POSITION])
        current = self._travel.current_position()
        if target == current:
            return

        going_up = target > current
        distance = abs(target - current) / 100
        travel_time = (
            self._travel.travel_time_up if going_up else self._travel.travel_time_down
        )
        duration = distance * travel_time

        self._travel.start_travel(target)
        self._start_tick()
        if going_up:
            await self.async_open_cover()
        else:
            await self.async_close_cover()

        # Only stop early for a partial move. Letting a full run finish on its
        # own lets the motor's own limit switch define the end, which is the one
        # moment the position is certain.
        self._cancel_autostop()
        if target not in (0, 100):
            self._unsub_autostop = async_call_later(
                self.hass, duration, self._async_autostop
            )

    async def _async_autostop(self, _now: Any) -> None:
        """Stop the cover once it should have reached the target."""
        self._unsub_autostop = None
        await self.async_stop_cover()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover and freeze the estimate where it is."""
        self._cancel_autostop()
        await super().async_stop_cover(**kwargs)

    def _start_tick(self) -> None:
        """Refresh the position once a second while the cover moves."""
        if self._unsub_tick is not None:
            return
        self._unsub_tick = async_track_time_interval(self.hass, self._async_tick, _TICK)

    def _stop_tick(self) -> None:
        """Stop refreshing."""
        if self._unsub_tick is not None:
            self._unsub_tick()
            self._unsub_tick = None

    def _cancel_autostop(self) -> None:
        """Cancel a pending automatic stop."""
        if self._unsub_autostop is not None:
            self._unsub_autostop()
            self._unsub_autostop = None

    @callback
    def _async_tick(self, _now: Any) -> None:
        """Publish the moving position."""
        self.async_write_ha_state()
        if self._travel.position_reached():
            self._stop_tick()
