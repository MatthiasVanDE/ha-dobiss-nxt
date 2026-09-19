"""Light platform for the Dobiss NXT integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DobissOutput, SubjectType
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

TURN_ON_SCHEMA = {
    vol.Optional("brightness_pct"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    vol.Optional(ATTR_DELAY_ON): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional(ATTR_DELAY_OFF): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional(ATTR_FROM_PIR, default=False): cv.boolean,
    vol.Optional(ATTR_CONDITION_ID): vol.Coerce(int),
    vol.Optional(ATTR_CONDITION_STATE, default=True): cv.boolean,
}


def _is_light(output: DobissOutput) -> bool:
    """Whether an output belongs on the light platform."""
    info = output.info
    if info.is_light:
        return True
    # Anything on a 0-10V module that is not obviously something else is a
    # dimmable light as far as Home Assistant is concerned.
    return info.subject_type is SubjectType.ANALOG_MODULE and not info.is_switch


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DobissConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Dobiss lights."""
    hub = entry.runtime_data
    members = hub.client.cover_member_keys()

    async_add_entities(
        DobissLight(hub, output)
        for output in hub.client.outputs.values()
        if _is_light(output)
        and output.info.key not in members
        and not hub.is_ignored(output.info.address)
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_TURN_ON, TURN_ON_SCHEMA, "async_dobiss_turn_on"
    )


class DobissLight(DobissOutputEntity, LightEntity):
    """A Dobiss output programmed as a light."""

    def __init__(self, hub: DobissHub, output: DobissOutput) -> None:
        """Pick the colour mode that matches how the output is wired."""
        super().__init__(hub, output)
        if output.info.dimmable:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        """Whether the light is on, or None while the server has not said."""
        return self._output.is_on

    @property
    def brightness(self) -> int | None:
        """Brightness on the Home Assistant scale of 0-255."""
        level = self._output.brightness
        if level is None:
            return None
        return round(level * 255 / 100)

    @staticmethod
    def _restored_on_value(attributes: dict[str, Any]) -> int:
        """Restore the dimmer level along with the on state."""
        brightness = attributes.get(ATTR_BRIGHTNESS)
        if isinstance(brightness, (int, float)) and brightness > 0:
            return max(1, min(100, round(float(brightness) * 100 / 255)))
        return 100

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the light on, optionally at a given brightness."""
        brightness: int | None = None
        if self._output.info.dimmable:
            raw = kwargs.get(ATTR_BRIGHTNESS)
            brightness = 100 if raw is None else max(1, round(int(raw) * 100 / 255))
        await self._hub.client.async_turn_on(
            self._output.info.address,
            self._output.info.channel,
            brightness=brightness,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the light off."""
        await self._hub.client.async_turn_off(
            self._output.info.address, self._output.info.channel
        )

    async def async_dobiss_turn_on(self, **kwargs: Any) -> None:
        """Switch on with the extras the Dobiss API offers."""
        brightness = kwargs.get("brightness_pct")
        await self._hub.client.async_turn_on(
            self._output.info.address,
            self._output.info.channel,
            brightness=brightness if self._output.info.dimmable else None,
            delay_on=kwargs.get(ATTR_DELAY_ON),
            delay_off=kwargs.get(ATTR_DELAY_OFF),
            from_pir=kwargs.get(ATTR_FROM_PIR, False),
            condition_id=kwargs.get(ATTR_CONDITION_ID),
            condition_state=kwargs.get(ATTR_CONDITION_STATE, True),
        )
