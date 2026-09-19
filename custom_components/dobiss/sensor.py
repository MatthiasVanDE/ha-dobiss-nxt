"""Sensor platform for the Dobiss NXT integration.

Most of this file is the energy meter on address 209. The NXT pushes a full
energy picture once a minute whether or not anyone is listening, so exposing it
costs nothing: no polling, no extra load on the server.

The peak figures are what the Belgian capacity tariff is billed on. The server
works out the running quarter-hour peak, the highest peak of the month and a
forecast for the quarter in progress, and hands them over ready to use.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import ENERGY_KEY, EnergySnapshot, TemperatureZone
from .coordinator import DobissConfigEntry, DobissHub
from .entity import DobissEntity


@dataclass(frozen=True, kw_only=True)
class DobissEnergySensorDescription(SensorEntityDescription):
    """Describes one figure of the energy meter."""

    value_fn: Callable[[EnergySnapshot], float | None]
    available_fn: Callable[[EnergySnapshot], bool] = lambda _: True
    attributes_fn: Callable[[EnergySnapshot], dict[str, Any]] | None = None


ENERGY_SENSORS: tuple[DobissEnergySensorDescription, ...] = (
    DobissEnergySensorDescription(
        key="power_usage",
        translation_key="power_usage",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.power_usage,
    ),
    DobissEnergySensorDescription(
        key="power_production",
        translation_key="power_production",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.power_production,
    ),
    DobissEnergySensorDescription(
        key="power_solar",
        translation_key="power_solar",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.power_solar,
        available_fn=lambda e: e.has_solar,
    ),
    DobissEnergySensorDescription(
        key="energy_usage_high",
        translation_key="energy_usage_high",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda e: e.energy_usage_high,
    ),
    DobissEnergySensorDescription(
        key="energy_usage_low",
        translation_key="energy_usage_low",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda e: e.energy_usage_low,
    ),
    DobissEnergySensorDescription(
        key="energy_production_high",
        translation_key="energy_production_high",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda e: e.energy_production_high,
    ),
    DobissEnergySensorDescription(
        key="energy_production_low",
        translation_key="energy_production_low",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda e: e.energy_production_low,
    ),
    DobissEnergySensorDescription(
        key="energy_solar_total",
        translation_key="energy_solar_total",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda e: e.energy_solar_total,
        available_fn=lambda e: e.has_solar,
    ),
    DobissEnergySensorDescription(
        key="peak_current",
        translation_key="peak_current",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.peak_current,
    ),
    DobissEnergySensorDescription(
        key="peak_forecast",
        translation_key="peak_forecast",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.peak_forecast,
    ),
    DobissEnergySensorDescription(
        key="peak_month",
        translation_key="peak_month",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.peak_month,
        attributes_fn=lambda e: {
            "reached_at": e.peak_month_at,
            "history": dict(e.peak_history),
        },
    ),
    DobissEnergySensorDescription(
        key="today_usage",
        translation_key="today_usage",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda e: e.today_usage,
    ),
    DobissEnergySensorDescription(
        key="today_production",
        translation_key="today_production",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda e: e.today_production,
    ),
    DobissEnergySensorDescription(
        key="yesterday_usage",
        translation_key="yesterday_usage",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: e.yesterday_usage,
    ),
    DobissEnergySensorDescription(
        key="yesterday_production",
        translation_key="yesterday_production",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: e.yesterday_production,
    ),
    DobissEnergySensorDescription(
        key="self_consumption",
        translation_key="self_consumption",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.own_percentage,
        available_fn=lambda e: e.has_solar,
    ),
    DobissEnergySensorDescription(
        key="battery_power",
        translation_key="battery_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.battery_power,
        available_fn=lambda e: e.battery_available,
    ),
    DobissEnergySensorDescription(
        key="battery_soc",
        translation_key="battery_soc",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda e: e.battery_soc,
        available_fn=lambda e: e.battery_available,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DobissConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Dobiss sensors."""
    hub = entry.runtime_data
    entities: list[SensorEntity] = []

    energy = hub.client.energy
    if energy.has_data:
        entities.extend(
            DobissEnergySensor(hub, description)
            for description in ENERGY_SENSORS
            if description.available_fn(energy)
        )

    entities.extend(
        DobissTemperatureSensor(hub, zone)
        for zone in hub.client.temperature_zones.values()
        if not hub.is_ignored(zone.info.address)
    )

    async_add_entities(entities)


class DobissEnergySensor(DobissEntity, SensorEntity):
    """One figure of the NXT energy meter."""

    entity_description: DobissEnergySensorDescription

    def __init__(
        self, hub: DobissHub, description: DobissEnergySensorDescription
    ) -> None:
        """Bind the sensor to the energy element."""
        super().__init__(hub, [ENERGY_KEY])
        self.entity_description = description
        self._attr_unique_id = f"{hub.host}_energy_{description.key}"
        self._attr_device_info = hub.energy_device_info()

    @property
    def native_value(self) -> float | None:
        """Current value of this figure."""
        return self.entity_description.value_fn(self._hub.client.energy)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Extra context, such as the monthly peak history."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self._hub.client.energy)


class DobissTemperatureSensor(DobissEntity, SensorEntity):
    """The measured temperature of one zone."""

    _attr_name = None
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hub: DobissHub, zone: TemperatureZone) -> None:
        """Bind the sensor to one temperature zone."""
        super().__init__(hub, [zone.info.key])
        self._zone = zone
        self._attr_unique_id = zone.info.unique_id
        self._attr_device_info = hub.child_device_info(
            f"climatecontrol_{zone.info.unique_id}", zone.info.name
        )

    @property
    def native_value(self) -> float | None:
        """Measured temperature."""
        return self._zone.current
