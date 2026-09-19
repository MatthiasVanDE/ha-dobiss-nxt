"""Binary sensor platform for the Dobiss NXT integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DobissOutput, IconId, SubjectType
from .const import CONF_INVERT_BINARY_SENSOR, DEFAULT_INVERT_BINARY_SENSOR
from .coordinator import DobissConfigEntry, DobissHub
from .entity import DobissEntity, DobissOutputEntity

_DEVICE_CLASS_BY_ICON = {
    IconId.CONTACT: BinarySensorDeviceClass.OPENING,
    IconId.WATER: BinarySensorDeviceClass.MOISTURE,
    IconId.FIRE: BinarySensorDeviceClass.SMOKE,
}


def _is_binary_sensor(output: DobissOutput) -> bool:
    """Whether an output belongs on the binary sensor platform."""
    info = output.info
    if info.subject_type is SubjectType.CONDITION:
        return True
    # A counter is a number, not a state, and is handled elsewhere.
    return info.is_input and info.icon is not IconId.COUNTER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DobissConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Dobiss binary sensors."""
    hub = entry.runtime_data
    entities: list[BinarySensorEntity] = [DobissConnectivity(hub)]
    entities.extend(
        DobissBinarySensor(hub, output)
        for output in hub.client.outputs.values()
        if _is_binary_sensor(output) and not hub.is_ignored(output.info.address)
    )
    async_add_entities(entities)


class DobissConnectivity(DobissEntity, BinarySensorEntity):
    """Whether Home Assistant is talking to the NXT server.

    This also anchors the device that represents the server, which every other
    Dobiss device hangs under.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connectivity"

    def __init__(self, hub: DobissHub) -> None:
        """Bind to the hub rather than to any single output."""
        super().__init__(hub, [])
        self._attr_unique_id = f"{hub.host}_connectivity"
        self._attr_device_info = hub.server_device_info

    @property
    def available(self) -> bool:
        """Always available: reporting the outage is the whole point."""
        return True

    @property
    def is_on(self) -> bool:
        """Whether the server is answering."""
        return self._hub.available


class DobissBinarySensor(DobissOutputEntity, BinarySensorEntity):
    """An input contact, or one of the logical conditions of the NXT.

    Logical conditions are what the Dobiss programming itself branches on, for
    example "the sun is up" or "the children's sensors may switch on". Reading
    them lets Home Assistant follow the same reasoning rather than duplicate it.
    """

    def __init__(self, hub: DobissHub, output: DobissOutput) -> None:
        """Pick a device class that matches the icon."""
        super().__init__(hub, output)
        if output.info.subject_type is SubjectType.CONDITION:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif (device_class := _DEVICE_CLASS_BY_ICON.get(output.info.icon)) is not None:
            self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        """Whether the contact is closed, honouring the invert option."""
        state = self._output.is_on
        if state is None:
            return None
        if self._output.info.subject_type is SubjectType.CONDITION:
            # Inverting is meant for wiring, not for logic.
            return state
        if self._hub.option(CONF_INVERT_BINARY_SENSOR, DEFAULT_INVERT_BINARY_SENSOR):
            return not state
        return state
