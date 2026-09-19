"""Shared entity behaviour for the Dobiss NXT integration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity

from .api import ICON_BY_ID, DobissOutput, SubscriptionKey
from .coordinator import DobissHub, signal_availability


class DobissEntity(Entity):
    """Base for everything this integration creates.

    Entities are push-driven: the server tells us when something changes, so
    nothing is polled.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hub: DobissHub, keys: Iterable[SubscriptionKey]) -> None:
        """Remember which state keys this entity cares about."""
        self._hub = hub
        self._keys = list(keys)

    async def async_added_to_hass(self) -> None:
        """Subscribe to the state we depend on."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._hub.client.subscribe(self._keys, self._handle_update)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_availability(self._hub.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        """Write the new state to Home Assistant."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Whether the NXT server is reachable."""
        return self._hub.available


class DobissOutputEntity(DobissEntity, RestoreEntity):
    """An entity backed by a single Dobiss output.

    Restoring state is deliberate. Modules on addresses 0 and 1 report a sparse
    status: the server leaves channels out of the status response entirely and
    only mentions them once they change. Without restoring, those entities would
    sit at "unknown" after every restart until somebody touched the switch. The
    original integration reported them as "off" instead, which is convenient but
    untrue - a light that is on would read as off until it changed.
    """

    _attr_name = None

    def __init__(self, hub: DobissHub, output: DobissOutput) -> None:
        """Wrap one output."""
        super().__init__(hub, [output.info.key])
        self._output = output
        self._attr_unique_id = output.info.unique_id
        self._attr_device_info: DeviceInfo = hub.child_device_info(
            output.info.unique_id, output.info.name
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last known state when the server has not told us yet."""
        await super().async_added_to_hass()
        if self._output.value is not None:
            return
        if (last_state := await self.async_get_last_state()) is None:
            return
        if last_state.state == "on":
            self._output.value = self._restored_on_value(last_state.attributes)
        elif last_state.state == "off":
            self._output.value = 0

    @staticmethod
    def _restored_on_value(attributes: dict[str, Any]) -> int:
        """Value to restore for an entity that was on."""
        return 100

    @property
    def icon(self) -> str | None:
        """Icon that matches how the output is programmed in Dobiss."""
        if self._output.info.icon is None:
            return None
        return ICON_BY_ID.get(self._output.info.icon)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Where this output lives in the Dobiss programming."""
        return {
            "dobiss_group": self._output.info.group,
            "address": self._output.info.address,
            "channel": self._output.info.channel,
            "tags": f"{self._output.info.address}.{self._output.info.channel + 1}",
        }
