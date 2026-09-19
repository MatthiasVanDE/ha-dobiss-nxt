"""Constants for the Dobiss NXT integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "dobiss"
MANUFACTURER: Final = "Dobiss"

PLATFORMS: Final[list[Platform]] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONF_SECRET: Final = "secret"
CONF_SECURE: Final = "secure"

# --- options ---------------------------------------------------------------
CONF_IGNORE_ZIGBEE: Final = "ignore_zigbee_devices"
CONF_INVERT_BINARY_SENSOR: Final = "invert_binary_sensor"
CONF_COVER_MODE: Final = "cover_mode"
CONF_COVER_CLOSE_TIME: Final = "cover_closetime"
CONF_COVER_TRAVEL_UP: Final = "cover_travel_up"
CONF_COVER_TRAVEL_DOWN: Final = "cover_travel_down"
CONF_COVER_OVERRIDES: Final = "cover_overrides"

COVER_MODE_BASIC: Final = "basic"
COVER_MODE_POSITION: Final = "position"
COVER_MODES: Final = [COVER_MODE_BASIC, COVER_MODE_POSITION]

DEFAULT_IGNORE_ZIGBEE: Final = False
DEFAULT_INVERT_BINARY_SENSOR: Final = False
DEFAULT_COVER_MODE: Final = COVER_MODE_BASIC
#: A run longer than this counts as a full travel, so the cover is at an end
#: stop. Zero disables the deduction and leaves covers unknown until they are
#: driven to an end.
DEFAULT_COVER_CLOSE_TIME: Final = 0
DEFAULT_COVER_TRAVEL: Final = 55.0

# --- services --------------------------------------------------------------
SERVICE_TURN_ON: Final = "turn_on"
SERVICE_ACTION: Final = "action"
SERVICE_REFRESH: Final = "refresh"

ATTR_ADDRESS: Final = "address"
ATTR_CHANNEL: Final = "channel"
ATTR_ACTION: Final = "action"
ATTR_OPTION1: Final = "option1"
ATTR_OPTION2: Final = "option2"
ATTR_DELAY_ON: Final = "delay_on"
ATTR_DELAY_OFF: Final = "delay_off"
ATTR_FROM_PIR: Final = "from_pir"
ATTR_CONDITION_ID: Final = "condition_id"
ATTR_CONDITION_STATE: Final = "condition_state"

# --- misc ------------------------------------------------------------------
#: How often the watchdog checks that the server is still talking to us.
WATCHDOG_INTERVAL: Final = 60.0
#: Silence longer than this, while the socket claims to be open, means the
#: connection is wedged and should be cycled.
SILENCE_BEFORE_RECONNECT: Final = 180.0
