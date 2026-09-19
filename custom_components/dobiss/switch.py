"""Switch platform for the Dobiss NXT integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DobissOutput, IconId, SubjectType
from .const import (
    ATTR_CONDITION_ID,
    ATTR_CONDITION_STATE,
    ATTR_DELAY_OFF,
    ATTR_DELAY_ON,
    ATTR_FROM_PIR,
    SERVICE_TURN_ON,
)
from .coordinator import DobissConfigEntry, DobissHub
from .entity import DobissOutputEntity
from .light import TURN_ON_SCHEMA

#: Elements of the NXT programming that behave like a switch.
_LOGIC_TYPES = frozenset(
    {SubjectType.FLAG, SubjectType.SCENARIO, SubjectType.AUTOMATION}
)
_OUTLET_ICONS = frozenset({IconId.PLUG, IconId.WASHER, IconId.DRYER, IconId.DISHWASHER})


def _is_switch(output: DobissOutput) -> bool:
    """Whether an output belongs on the switch platform."""
    info = output.info
    return info.is_switch or info.subject_type in _LOGIC_TYPES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DobissConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Dobiss switches."""
    hub = entry.runtime_data
    members = hub.client.cover_member_keys()

    async_add_entities(
        DobissSwitch(hub, output)
        for output in hub.client.outputs.values()
        if _is_switch(output)
        and output.info.key not in members
        and not hub.is_ignored(output.info.address)
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_TURN_ON, TURN_ON_SCHEMA, "async_dobiss_turn_on"
    )


class DobissSwitch(DobissOutputEntity, SwitchEntity):
    """A Dobiss output, flag, scenario or automation."""

    def __init__(self, hub: DobissHub, output: DobissOutput) -> None:
        """Mark real sockets as outlets so Home Assistant shows them as such."""
        super().__init__(hub, output)
        if output.info.icon in _OUTLET_ICONS:
            self._attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        """Whether the output is on, or None while the server has not said."""
        return self._output.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the output on."""
        await self._hub.client.async_turn_on(
            self._output.info.address, self._output.info.channel
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the output off."""
        await self._hub.client.async_turn_off(
            self._output.info.address, self._output.info.channel
        )

    async def async_dobiss_turn_on(self, **kwargs: Any) -> None:
        """Switch on with the extras the Dobiss API offers."""
        await self._hub.client.async_turn_on(
            self._output.info.address,
            self._output.info.channel,
            delay_on=kwargs.get(ATTR_DELAY_ON),
            delay_off=kwargs.get(ATTR_DELAY_OFF),
            from_pir=kwargs.get(ATTR_FROM_PIR, False),
            condition_id=kwargs.get(ATTR_CONDITION_ID),
            condition_state=kwargs.get(ATTR_CONDITION_STATE, True),
        )
