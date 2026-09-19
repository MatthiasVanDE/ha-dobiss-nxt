"""The Dobiss NXT integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import Action, DobissError
from .const import (
    ATTR_ACTION,
    ATTR_ADDRESS,
    ATTR_CHANNEL,
    ATTR_CONDITION_ID,
    ATTR_CONDITION_STATE,
    ATTR_DELAY_OFF,
    ATTR_DELAY_ON,
    ATTR_OPTION1,
    ATTR_OPTION2,
    DOMAIN,
    PLATFORMS,
    SERVICE_ACTION,
    SERVICE_REFRESH,
)
from .coordinator import DobissConfigEntry, DobissHub

_LOGGER = logging.getLogger(__name__)

ACTION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ADDRESS): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
        vol.Required(ATTR_CHANNEL): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
        vol.Required(ATTR_ACTION): vol.All(vol.Coerce(int), vol.Range(min=0, max=255)),
        vol.Optional(ATTR_OPTION1): vol.Coerce(int),
        vol.Optional(ATTR_OPTION2): vol.Coerce(int),
        vol.Optional(ATTR_DELAY_ON): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_DELAY_OFF): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional(ATTR_CONDITION_ID): vol.Coerce(int),
        vol.Optional(ATTR_CONDITION_STATE, default=True): cv.boolean,
    }
)

REFRESH_SCHEMA = vol.Schema({})


def _hubs(hass: HomeAssistant) -> list[DobissHub]:
    """Every loaded Dobiss hub."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


async def async_setup_entry(hass: HomeAssistant, entry: DobissConfigEntry) -> bool:
    """Set up a Dobiss NXT server from a config entry."""
    hub = DobissHub(hass, entry)
    await hub.async_setup()
    entry.runtime_data = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DobissConfigEntry) -> bool:
    """Unload a config entry and stop everything it started."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
        # The services belong to the integration, not to one entry.
        if not hass.config_entries.async_loaded_entries(DOMAIN):
            for service in (SERVICE_ACTION, SERVICE_REFRESH):
                hass.services.async_remove(DOMAIN, service)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: DobissConfigEntry) -> None:
    """Reload when the user changes the options."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the integration-wide services once."""
    if hass.services.has_service(DOMAIN, SERVICE_ACTION):
        return

    async def _handle_action(call: ServiceCall) -> None:
        """Send a raw action to every configured server."""
        hubs = _hubs(hass)
        if not hubs:
            raise HomeAssistantError("No Dobiss NXT server is loaded")
        for hub in hubs:
            try:
                await hub.client.async_action(
                    call.data[ATTR_ADDRESS],
                    call.data[ATTR_CHANNEL],
                    Action(call.data[ATTR_ACTION])
                    if call.data[ATTR_ACTION] in iter(Action)
                    else call.data[ATTR_ACTION],
                    option1=call.data.get(ATTR_OPTION1),
                    option2=call.data.get(ATTR_OPTION2),
                    delay_on=call.data.get(ATTR_DELAY_ON),
                    delay_off=call.data.get(ATTR_DELAY_OFF),
                    condition_id=call.data.get(ATTR_CONDITION_ID),
                    condition_state=call.data.get(ATTR_CONDITION_STATE, True),
                )
            except DobissError as err:
                raise HomeAssistantError(f"Dobiss rejected the action: {err}") from err

    async def _handle_refresh(call: ServiceCall) -> None:
        """Ask every server for a full status."""
        for hub in _hubs(hass):
            try:
                await hub.client.async_refresh()
            except DobissError as err:
                raise HomeAssistantError(f"Dobiss refresh failed: {err}") from err

    hass.services.async_register(DOMAIN, SERVICE_ACTION, _handle_action, ACTION_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH, _handle_refresh, REFRESH_SCHEMA
    )


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: DobissConfigEntry, device_entry: Any
) -> bool:
    """Allow removing a device that no longer exists in the Dobiss programming."""
    hub = entry.runtime_data
    known = {hub.server_device_id[1], f"energy_{hub.host}"}
    known |= {output.info.unique_id for output in hub.client.outputs.values()}
    known |= {
        f"climatecontrol_{zone.info.unique_id}"
        for zone in hub.client.temperature_zones.values()
    }
    return not any(
        identifier[1] in known
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    )
