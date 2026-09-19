"""Runtime hub for one Dobiss NXT server."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .api import (
    DobissAuthError,
    DobissClient,
    DobissError,
    SubjectType,
)
from .const import (
    CONF_COVER_CLOSE_TIME,
    CONF_COVER_MODE,
    CONF_COVER_OVERRIDES,
    CONF_COVER_TRAVEL_DOWN,
    CONF_COVER_TRAVEL_UP,
    CONF_IGNORE_ZIGBEE,
    CONF_SECRET,
    CONF_SECURE,
    DEFAULT_COVER_CLOSE_TIME,
    DEFAULT_COVER_MODE,
    DEFAULT_COVER_TRAVEL,
    DEFAULT_IGNORE_ZIGBEE,
    DOMAIN,
    MANUFACTURER,
    SILENCE_BEFORE_RECONNECT,
    WATCHDOG_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type DobissConfigEntry = ConfigEntry[DobissHub]


def signal_availability(entry_id: str) -> str:
    """Dispatcher signal carrying connection changes for one entry."""
    return f"{DOMAIN}_availability_{entry_id}"


@dataclass(slots=True)
class CoverSettings:
    """Per-cover behaviour, resolved from the options."""

    mode: str
    close_time: int
    travel_up: float
    travel_down: float
    overrides: dict[str, dict[str, float]] = field(default_factory=dict)

    def for_cover(self, unique_id: str) -> tuple[float, float]:
        """Travel times for one cover, falling back to the global values."""
        override = self.overrides.get(unique_id) or {}
        return (
            float(override.get(CONF_COVER_TRAVEL_UP, self.travel_up)),
            float(override.get(CONF_COVER_TRAVEL_DOWN, self.travel_down)),
        )


class DobissHub:
    """Owns the client, the connection state and the shared device info."""

    def __init__(self, hass: HomeAssistant, entry: DobissConfigEntry) -> None:
        """Create the hub. Nothing is contacted yet."""
        self.hass = hass
        self.entry = entry
        self.client = DobissClient(
            entry.data[CONF_HOST],
            entry.data[CONF_SECRET],
            secure=entry.data.get(CONF_SECURE, False),
            session=async_get_clientsession(hass),
        )
        self._unsub_watchdog: Any = None
        self._server_device_id: str | None = None
        self._shutting_down = False

    # -- lifecycle ---------------------------------------------------------
    async def async_setup(self) -> None:
        """Connect, discover and start listening."""
        try:
            await self.client.async_discover()
            await self.client.async_refresh()
        except DobissAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DobissError as err:
            # Telling Home Assistant the entry is "not ready" makes it retry
            # with a backoff. Raising anything else parks the entry in
            # SETUP_ERROR until someone reloads it by hand, which is how a
            # server that boots slower than Home Assistant takes the whole
            # integration down.
            raise ConfigEntryNotReady(str(err)) from err

        # Register the server as a real device first, so every output can
        # point at it with via_device_id and the device page shows a tree
        # instead of a flat list of a hundred entries.
        registry = dr.async_get(self.hass)
        server = registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={self.server_device_id},
            manufacturer=MANUFACTURER,
            model="NXT server",
            name=f"Dobiss NXT ({self.client.host})",
            configuration_url=f"http://{self.client.host}/",
        )
        self._server_device_id = server.id

        self.client.add_connection_listener(self._handle_connection_change)
        await self.client.async_start_listening()

        self._unsub_watchdog = async_track_time_interval(
            self.hass,
            self._async_watchdog,
            timedelta(seconds=WATCHDOG_INTERVAL),
        )

        # Home Assistant does not unload config entries when it shuts down, so
        # without this the socket closing on the way out is reported as an
        # outage in the log.
        self.entry.async_on_unload(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._handle_hass_stop
            )
        )

    @callback
    def _handle_hass_stop(self, _event: Any) -> None:
        """Stop treating a dropped connection as news."""
        self._shutting_down = True

    async def async_shutdown(self) -> None:
        """Stop everything this hub started."""
        # Losing the connection because we asked for it is not news.
        self._shutting_down = True
        if self._unsub_watchdog is not None:
            self._unsub_watchdog()
            self._unsub_watchdog = None
        await self.client.async_stop()

    @callback
    def _handle_connection_change(self, connected: bool) -> None:
        """Tell the entities that availability changed."""
        if self._shutting_down:
            return
        if connected:
            _LOGGER.debug("Connected to the Dobiss NXT server at %s", self.client.host)
        else:
            _LOGGER.warning(
                "Lost the connection to the Dobiss NXT server at %s; entities are "
                "unavailable until it answers again",
                self.client.host,
            )
        async_dispatcher_send(self.hass, signal_availability(self.entry.entry_id))

    async def _async_watchdog(self, _now: Any = None) -> None:
        """Cycle a connection that is open but has gone quiet.

        The server pushes at least once a minute. A socket that stays open
        while nothing arrives is wedged, and only a reconnect clears it.
        """
        if not self.client.connected:
            return
        if self.client.seconds_since_last_message < SILENCE_BEFORE_RECONNECT:
            return
        _LOGGER.info(
            "No news from %s for %.0f seconds; reconnecting",
            self.client.host,
            self.client.seconds_since_last_message,
        )
        await self.client.async_stop()
        await self.client.async_start_listening()

    # -- state -------------------------------------------------------------
    @property
    def available(self) -> bool:
        """Whether the server is currently reachable."""
        return self.client.connected

    @property
    def host(self) -> str:
        """Host of the NXT server."""
        return self.client.host

    # -- options -----------------------------------------------------------
    def option(self, key: str, default: Any) -> Any:
        """Read one option with its default."""
        return self.entry.options.get(key, default)

    @property
    def ignore_zigbee(self) -> bool:
        """Whether Zigbee devices proxied by Dobiss should be skipped."""
        return bool(self.option(CONF_IGNORE_ZIGBEE, DEFAULT_IGNORE_ZIGBEE))

    @property
    def cover_settings(self) -> CoverSettings:
        """Cover behaviour as configured in the options."""
        return CoverSettings(
            mode=str(self.option(CONF_COVER_MODE, DEFAULT_COVER_MODE)),
            close_time=int(
                self.option(CONF_COVER_CLOSE_TIME, DEFAULT_COVER_CLOSE_TIME)
            ),
            travel_up=float(self.option(CONF_COVER_TRAVEL_UP, DEFAULT_COVER_TRAVEL)),
            travel_down=float(
                self.option(CONF_COVER_TRAVEL_DOWN, DEFAULT_COVER_TRAVEL)
            ),
            overrides=dict(self.option(CONF_COVER_OVERRIDES, {}) or {}),
        )

    # -- devices -----------------------------------------------------------
    @property
    def server_device_id(self) -> tuple[str, str]:
        """Identifier of the device that represents the NXT server itself."""
        return (DOMAIN, f"nxt_{self.client.host}")

    @property
    def server_device_info(self) -> DeviceInfo:
        """Device entry for the NXT server itself.

        At least one entity has to live on this device. A device that carries no
        entities is treated as an orphan and swept away, and every via_device_id
        pointing at it is cleared with it.
        """
        return DeviceInfo(
            identifiers={self.server_device_id},
            manufacturer=MANUFACTURER,
            model="NXT server",
            name=f"Dobiss NXT ({self.client.host})",
            configuration_url=f"http://{self.client.host}/",
        )

    def child_device_info(self, identifier: str, name: str) -> DeviceInfo:
        """Device entry for one output, hanging under the NXT server.

        The identifier deliberately matches what the original integration used,
        so an existing installation keeps its device ids. Automations and
        scripts that address a Dobiss output by device keep working.
        """
        info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            manufacturer=MANUFACTURER,
            name=name,
        )
        if self._server_device_id is not None:
            info["via_device_id"] = self._server_device_id
        return info

    def energy_device_info(self) -> DeviceInfo:
        """Device entry that groups the energy meter sensors."""
        info = DeviceInfo(
            identifiers={(DOMAIN, f"energy_{self.client.host}")},
            manufacturer=MANUFACTURER,
            model="NXT energy meter",
            name="Dobiss energy",
        )
        if self._server_device_id is not None:
            info["via_device_id"] = self._server_device_id
        return info

    # -- helpers -----------------------------------------------------------
    def is_ignored(self, address: int) -> bool:
        """Whether an address should be skipped because of the options."""
        return self.ignore_zigbee and address in (
            SubjectType.ZIGBEE_OUTPUT,
            SubjectType.ZIGBEE_SENSOR,
        )
