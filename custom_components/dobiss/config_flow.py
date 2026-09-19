"""Config and options flow for the Dobiss NXT integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import DobissAuthError, DobissClient, DobissError
from .const import (
    CONF_COVER_CLOSE_TIME,
    CONF_COVER_MODE,
    CONF_COVER_OVERRIDES,
    CONF_COVER_TRAVEL_DOWN,
    CONF_COVER_TRAVEL_UP,
    CONF_IGNORE_ZIGBEE,
    CONF_INVERT_BINARY_SENSOR,
    CONF_SECRET,
    CONF_SECURE,
    COVER_MODE_POSITION,
    COVER_MODES,
    DEFAULT_COVER_CLOSE_TIME,
    DEFAULT_COVER_MODE,
    DEFAULT_COVER_TRAVEL,
    DEFAULT_IGNORE_ZIGBEE,
    DEFAULT_INVERT_BINARY_SENSOR,
    DOMAIN,
)
from .coordinator import DobissConfigEntry

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="off")
        ),
        vol.Required(CONF_SECRET): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="off")
        ),
        vol.Optional(CONF_SECURE, default=False): BooleanSelector(),
    }
)

_SECONDS = NumberSelector(
    NumberSelectorConfig(
        min=0, max=600, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
    )
)


async def _validate(hass: Any, data: dict[str, Any]) -> None:
    """Check that we can reach and authenticate against the server."""
    client = DobissClient(
        data[CONF_HOST],
        data[CONF_SECRET],
        secure=data.get(CONF_SECURE, False),
        session=async_get_clientsession(hass),
    )
    await client.async_authenticate()


class DobissConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user through adding a Dobiss NXT server."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the address and the API secret."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()
            try:
                await _validate(self.hass, {**user_input, CONF_HOST: host})
            except DobissAuthError:
                errors[CONF_SECRET] = "invalid_auth"
            except DobissError:
                errors[CONF_HOST] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while adding a Dobiss NXT server")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Dobiss NXT ({host})",
                    data={**user_input, CONF_HOST: host},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start over when the secret stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API secret."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_SECRET: user_input[CONF_SECRET]}
            try:
                await _validate(self.hass, data)
            except DobissAuthError:
                errors[CONF_SECRET] = "invalid_auth"
            except DobissError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SECRET): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    )
                }
            ),
            description_placeholders={"host": entry.data[CONF_HOST]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user move the server to another address."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                await _validate(self.hass, data)
            except DobissAuthError:
                errors[CONF_SECRET] = "invalid_auth"
            except DobissError:
                errors[CONF_HOST] = "cannot_connect"
            else:
                await self.async_set_unique_id(data[CONF_HOST].strip().lower())
                self._abort_if_unique_id_mismatch(reason="wrong_server")
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, dict(entry.data)
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: DobissConfigEntry) -> DobissOptionsFlow:
        """Return the options flow."""
        return DobissOptionsFlow()


class DobissOptionsFlow(OptionsFlow):
    """Two-part options: general behaviour, and per-cover travel times."""

    def __init__(self) -> None:
        """Start with no cover selected."""
        self._selected_cover: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the choice between general options and cover travel times."""
        if self._covers():
            return self.async_show_menu(
                step_id="init", menu_options=["general", "covers"]
            )
        return await self.async_step_general()

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Behaviour that applies to the whole server."""
        if user_input is not None:
            options = {**self.config_entry.options, **user_input}
            return self.async_create_entry(data=options)

        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_COVER_MODE,
                    default=current.get(CONF_COVER_MODE, DEFAULT_COVER_MODE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=mode, label=mode)
                            for mode in COVER_MODES
                        ],
                        translation_key="cover_mode",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_COVER_CLOSE_TIME,
                    default=current.get(
                        CONF_COVER_CLOSE_TIME, DEFAULT_COVER_CLOSE_TIME
                    ),
                ): _SECONDS,
                vol.Required(
                    CONF_COVER_TRAVEL_UP,
                    default=current.get(CONF_COVER_TRAVEL_UP, DEFAULT_COVER_TRAVEL),
                ): _SECONDS,
                vol.Required(
                    CONF_COVER_TRAVEL_DOWN,
                    default=current.get(CONF_COVER_TRAVEL_DOWN, DEFAULT_COVER_TRAVEL),
                ): _SECONDS,
                vol.Required(
                    CONF_IGNORE_ZIGBEE,
                    default=current.get(CONF_IGNORE_ZIGBEE, DEFAULT_IGNORE_ZIGBEE),
                ): BooleanSelector(),
                vol.Required(
                    CONF_INVERT_BINARY_SENSOR,
                    default=current.get(
                        CONF_INVERT_BINARY_SENSOR, DEFAULT_INVERT_BINARY_SENSOR
                    ),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    async def async_step_covers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the cover whose travel times should be changed."""
        covers = self._covers()
        if user_input is not None:
            self._selected_cover = user_input["cover"]
            return await self.async_step_cover_times()

        return self.async_show_form(
            step_id="covers",
            data_schema=vol.Schema(
                {
                    vol.Required("cover"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=uid, label=name)
                                for uid, name in covers.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_cover_times(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set how long this one cover takes to travel, end to end."""
        assert self._selected_cover is not None
        covers = self._covers()
        overrides = dict(self.config_entry.options.get(CONF_COVER_OVERRIDES, {}) or {})

        if user_input is not None:
            overrides[self._selected_cover] = {
                CONF_COVER_TRAVEL_UP: float(user_input[CONF_COVER_TRAVEL_UP]),
                CONF_COVER_TRAVEL_DOWN: float(user_input[CONF_COVER_TRAVEL_DOWN]),
            }
            options = {
                **self.config_entry.options,
                CONF_COVER_OVERRIDES: overrides,
            }
            return self.async_create_entry(data=options)

        current = overrides.get(self._selected_cover, {})
        defaults = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_COVER_TRAVEL_UP,
                    default=current.get(
                        CONF_COVER_TRAVEL_UP,
                        defaults.get(CONF_COVER_TRAVEL_UP, DEFAULT_COVER_TRAVEL),
                    ),
                ): _SECONDS,
                vol.Required(
                    CONF_COVER_TRAVEL_DOWN,
                    default=current.get(
                        CONF_COVER_TRAVEL_DOWN,
                        defaults.get(CONF_COVER_TRAVEL_DOWN, DEFAULT_COVER_TRAVEL),
                    ),
                ): _SECONDS,
            }
        )
        return self.async_show_form(
            step_id="cover_times",
            data_schema=schema,
            description_placeholders={
                "cover": covers.get(self._selected_cover, self._selected_cover),
                "mode_hint": (
                    ""
                    if self.config_entry.options.get(CONF_COVER_MODE)
                    == COVER_MODE_POSITION
                    else " (only used when covers are set to position mode)"
                ),
            },
        )

    def _covers(self) -> dict[str, str]:
        """Map each cover's unique id onto its display name."""
        hub = getattr(self.config_entry, "runtime_data", None)
        if hub is None:
            return {}
        return {
            cover.unique_id: cover.name
            for cover in sorted(hub.client.covers.values(), key=lambda c: c.name)
        }
