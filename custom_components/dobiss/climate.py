"""Climate platform for the Dobiss NXT integration.

Untested against real hardware: the installation this integration was developed
on has no temperature zones. The behaviour follows the published API. Reports of
what it actually does on a system with heating zones are very welcome.
"""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Action, TemperatureZone
from .coordinator import DobissConfigEntry, DobissHub
from .entity import DobissEntity

#: The API maps 0-250 onto 5.0-30.0 degrees in steps of a tenth.
_MIN_TEMP = 5.0
_MAX_TEMP = 30.0
#: Period 0xFE means "keep this setting until somebody changes it".
_PERIOD_ALWAYS = 0xFE
#: Home Assistant 2026.11 renamed the temperature properties of ClimateEntity to
#: native_*; the old names log a deprecation warning and stop working in 2027.11.
#: Older versions only know the old names, and hacs.json still allows 2025.2.
_NATIVE_TEMPERATURES = hasattr(ClimateEntity, "native_current_temperature")


def _encode_temperature(celsius: float) -> int:
    """Convert degrees to the 0-250 scale the server expects."""
    clamped = max(_MIN_TEMP, min(_MAX_TEMP, float(celsius)))
    return round((clamped - _MIN_TEMP) * 10)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DobissConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a climate entity per temperature zone."""
    hub = entry.runtime_data
    async_add_entities(
        DobissClimate(hub, zone)
        for zone in hub.client.temperature_zones.values()
        if not hub.is_ignored(zone.info.address)
    )


class DobissClimate(DobissEntity, ClimateEntity):
    """One Dobiss temperature zone."""

    _attr_name = None
    _attr_hvac_modes: ClassVar[list[HVACMode]] = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = _MIN_TEMP
    _attr_max_temp = _MAX_TEMP
    _attr_target_temperature_step = 0.5

    def __init__(self, hub: DobissHub, zone: TemperatureZone) -> None:
        """Bind to one zone."""
        super().__init__(hub, [zone.info.key])
        self._zone = zone
        self._attr_unique_id = f"climatecontrol_{zone.info.unique_id}"
        self._attr_device_info = hub.child_device_info(
            f"climatecontrol_{zone.info.unique_id}", zone.info.name
        )

    if _NATIVE_TEMPERATURES:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def native_current_temperature(self) -> float | None:
            """Measured temperature in the zone."""
            return self._zone.current

        @property
        def native_target_temperature(self) -> float | None:
            """Temperature the zone is asking for."""
            return self._zone.target

    else:  # Home Assistant before 2026.11
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def current_temperature(self) -> float | None:
            """Measured temperature in the zone."""
            return self._zone.current

        @property
        def target_temperature(self) -> float | None:
            """Temperature the zone is asking for."""
            return self._zone.target

    @property
    def hvac_mode(self) -> HVACMode:
        """Whether the zone is calling for heat at all."""
        if self._zone.target is None or self._zone.target <= _MIN_TEMP:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """What the zone is doing right now."""
        if self._zone.status is None:
            return None
        return HVACAction.HEATING if self._zone.status else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Calendar and remaining manual time, as the server reports them."""
        return {
            "calendar": self._zone.calendar,
            "minutes_remaining": self._zone.minutes,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature until something changes it."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self._hub.client.async_action(
            self._zone.info.address,
            self._zone.info.channel,
            Action.ON,
            option1=_encode_temperature(temperature),
            option2=_PERIOD_ALWAYS,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Turn the zone off, or back on at its lowest setting."""
        if hvac_mode is HVACMode.OFF:
            await self.async_turn_off()
        else:
            await self.async_turn_on()

    async def async_turn_on(self) -> None:
        """Hand the zone back to its calendar."""
        await self._hub.client.async_action(
            self._zone.info.address, self._zone.info.channel, Action.ON
        )

    async def async_turn_off(self) -> None:
        """Stop the zone from calling for heat."""
        await self._hub.client.async_action(
            self._zone.info.address, self._zone.info.channel, Action.OFF
        )
