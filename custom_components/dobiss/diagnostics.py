"""Diagnostics for the Dobiss NXT integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_SECRET
from .coordinator import DobissConfigEntry

TO_REDACT = {CONF_SECRET, CONF_HOST, "configuration_url"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DobissConfigEntry
) -> dict[str, Any]:
    """Return everything useful for a bug report, without the secret."""
    hub = entry.runtime_data
    client = hub.client

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "connection": {
            "connected": client.connected,
            "seconds_since_last_message": round(
                min(client.seconds_since_last_message, 1e6), 1
            ),
        },
        "counts": {
            "outputs": len(client.outputs),
            "covers": len(client.covers),
            "temperature_zones": len(client.temperature_zones),
            "audio_zones": len(client.audio_zones),
            "notifications": len(client.notifications),
        },
        "outputs": [
            {
                "address": output.info.address,
                "channel": output.info.channel,
                "name": output.info.name,
                "group": output.info.group,
                "type": int(t) if (t := output.info.subject_type) is not None else None,
                "icon": int(i) if (i := output.info.icon) is not None else None,
                "dimmable": output.info.dimmable,
                "readonly": output.info.readonly,
                "value": output.value,
            }
            for output in sorted(
                client.outputs.values(),
                key=lambda o: (o.info.address, o.info.channel),
            )
        ],
        "covers": [
            {
                "name": cover.name,
                "unique_id": cover.unique_id,
                "up": list(cover.up.info.key),
                "down": list(cover.down.info.key),
            }
            for cover in client.covers.values()
        ],
        "energy": asdict(client.energy),
        "alarm": client.alarm,
    }
