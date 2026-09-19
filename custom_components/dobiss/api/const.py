"""Constants for the Dobiss NXT local API.

Values are taken from the official Dobiss developer API documentation
(https://support.dobiss.com/books/nl-dobiss-nxt/page/developer-api, revision 29,
updated 27 June 2025) and verified against a live NXT server running 4.30.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final

API_PATH: Final = "/api/local/"
WEBSOCKET_PATH: Final = "/sockets/api"
WEBSOCKET_PROTOCOL: Final = "wamp"

#: How long a freshly minted JWT stays valid. The server enforces ``exp``.
TOKEN_TTL_SECONDS: Final = 3600
#: Renew a little before expiry so a long running request never carries a
#: token that expires mid-flight.
TOKEN_RENEW_MARGIN_SECONDS: Final = 300

DEFAULT_REQUEST_TIMEOUT: Final = 10.0
#: The NXT pushes at least one frame per minute (energy on address 209).
#: Longer silence than this means we should check the connection ourselves.
HEARTBEAT_TIMEOUT: Final = 120.0
RECONNECT_MIN_DELAY: Final = 2.0
RECONNECT_MAX_DELAY: Final = 120.0


class SubjectType(IntEnum):
    """Type of a subject as reported by ``discover``.

    Values below 200 identify a hardware module, values from 200 up identify a
    logical element living inside the NXT server itself.
    """

    NXT_SERVER = 0  # DO5520
    INPUT_MODULE = 1  # DO5480
    DALI_MODULE = 4  # DO5460
    RELAY_MODULE = 8  # DO5411 / DO5475
    DIMMER_MODULE = 16  # DO5450, universal dimmer
    ANALOG_MODULE = 24  # DO5470, 0-10V

    SCENARIO = 201
    AUTOMATION = 202
    CONDITION = 203
    TEMPERATURE = 204
    AUDIO = 205
    FLAG = 206
    RGB = 207
    NOTIFICATION = 208
    ENERGY = 209
    ZIGBEE_OUTPUT = 210
    ZIGBEE_SENSOR = 211
    AIRCO = 213

    ALARM = 251


#: Addresses that only ever show up in ``status`` and never in ``discover``.
#: They carry NXT-server state rather than a configured output.
IMPLICIT_ADDRESSES: Final = frozenset(
    {
        SubjectType.NOTIFICATION,
        SubjectType.ENERGY,
        SubjectType.ALARM,
    }
)

#: Zigbee lives on its own addresses and can be filtered out by the user.
ZIGBEE_ADDRESSES: Final = frozenset({210, 211})


class IconId(IntEnum):
    """Icon assigned to an output in the Dobiss programming.

    Dobiss uses the icon, not the module type, to say what an output *is*, so
    this drives how an output is mapped onto a Home Assistant platform.
    """

    LIGHT = 0
    PLUG = 1
    FAN = 2
    UP = 3
    DOWN = 4
    HEATING = 5
    TABLELAMP = 6
    DOOR = 7
    GARAGE = 8
    GATE = 9
    RED = 10
    GREEN = 11
    BLUE = 12
    WHITE = 13
    RGBW = 14
    RGBWW = 15
    DUALWHITE = 16
    CURTAINS = 17
    TAP = 18
    PLAY = 19
    STOP = 20
    OPEN = 23
    CLOSE = 24
    WARMWHITE = 25
    COLDWHITE = 26
    WASHER = 27
    DRYER = 28
    DISHWASHER = 29
    IN = 30
    OUT = 31

    CONTACT = 100
    ANALOG_INPUT = 101
    FREQUENCY_INPUT = 102
    WATER = 103
    FIRE = 104
    COUNTER = 105

    SCENARIO = 201
    AUTOMATION = 202
    CONDITION = 203
    TEMPERATURE = 204
    AUDIO = 205
    FLAG = 206
    ALARM = 251


#: Icons that mean "this output raises the cover".
COVER_UP_ICONS: Final = frozenset({IconId.UP, IconId.OPEN})
#: Icons that mean "this output lowers the cover".
COVER_DOWN_ICONS: Final = frozenset({IconId.DOWN, IconId.CLOSE})
#: Icons that belong to a colour channel of a combined RGB(W) fixture.
RGB_CHANNEL_ICONS: Final = frozenset(
    {
        IconId.RED,
        IconId.GREEN,
        IconId.BLUE,
        IconId.WHITE,
        IconId.WARMWHITE,
        IconId.COLDWHITE,
    }
)
#: Icons for outputs that behave like a light.
LIGHT_ICONS: Final = (
    frozenset(
        {IconId.LIGHT, IconId.TABLELAMP, IconId.RGBW, IconId.RGBWW, IconId.DUALWHITE}
    )
    | RGB_CHANNEL_ICONS
)
#: Icons for outputs that are better represented as a plain switch.
SWITCH_ICONS: Final = frozenset(
    {
        IconId.PLUG,
        IconId.FAN,
        IconId.HEATING,
        IconId.TAP,
        IconId.PLAY,
        IconId.STOP,
        IconId.IN,
        IconId.OUT,
        IconId.WASHER,
        IconId.DRYER,
        IconId.DISHWASHER,
    }
)
#: Icons that describe a door-like opening driven by a single output.
OPENING_ICONS: Final = frozenset({IconId.DOOR, IconId.GARAGE, IconId.GATE})
#: Icons for inputs that report a state rather than drive an output.
INPUT_ICONS: Final = frozenset(
    {
        IconId.CONTACT,
        IconId.ANALOG_INPUT,
        IconId.FREQUENCY_INPUT,
        IconId.WATER,
        IconId.FIRE,
        IconId.COUNTER,
    }
)


class Action(IntEnum):
    """Action ids accepted by ``POST /api/local/action``."""

    OFF = 0
    ON = 1
    TOGGLE = 2
    START_DIMMING = 3
    STOP_DIMMING = 4
    BLINK_AND_ON = 5
    BLINK_AND_OFF = 6
    BLINK_AND_RESTORE = 7
    ON_FROM_PIR = 9
    ON_MILLISECONDS = 10
    SKIP_SOURCE = 104
    ACTIVATE_CALENDAR = 110


class EnergySubtype(IntEnum):
    """Channels of the energy element on address 209."""

    CURRENT = 0
    TODAY = 1
    YESTERDAY = 2
    TODAY_QUARTERLY = 3
    YESTERDAY_QUARTERLY = 4
    LAST_30_DAYS = 5
    LAST_2_YEARS = 6


class DelayUnit(StrEnum):
    """Unit accepted in the ``delayon``/``delayoff`` object of an action."""

    SECONDS = "s"
    MINUTES = "min"


#: A delay of at most this many seconds is sent as seconds; anything longer is
#: rounded to whole minutes, which is the granularity the server accepts.
MAX_DELAY_SECONDS: Final = 120
#: The server caps delays at 120 minutes.
MAX_DELAY_MINUTES: Final = 120

ICON_BY_ID: Final[dict[IconId, str]] = {
    IconId.LIGHT: "mdi:lightbulb",
    IconId.PLUG: "mdi:power-plug",
    IconId.FAN: "mdi:fan",
    IconId.UP: "mdi:arrow-up",
    IconId.DOWN: "mdi:arrow-down",
    IconId.HEATING: "mdi:radiator",
    IconId.TABLELAMP: "mdi:lamp",
    IconId.DOOR: "mdi:door",
    IconId.GARAGE: "mdi:garage",
    IconId.GATE: "mdi:gate",
    IconId.RED: "mdi:lightbulb",
    IconId.GREEN: "mdi:lightbulb",
    IconId.BLUE: "mdi:lightbulb",
    IconId.WHITE: "mdi:lightbulb",
    IconId.RGBW: "mdi:lightbulb",
    IconId.RGBWW: "mdi:lightbulb",
    IconId.DUALWHITE: "mdi:lightbulb",
    IconId.CURTAINS: "mdi:curtains",
    IconId.TAP: "mdi:water-pump",
    IconId.PLAY: "mdi:play",
    IconId.STOP: "mdi:stop",
    IconId.OPEN: "mdi:window-open",
    IconId.CLOSE: "mdi:window-closed",
    IconId.WARMWHITE: "mdi:lightbulb",
    IconId.COLDWHITE: "mdi:lightbulb",
    IconId.WASHER: "mdi:washing-machine",
    IconId.DRYER: "mdi:tumble-dryer",
    IconId.DISHWASHER: "mdi:dishwasher",
    IconId.IN: "mdi:location-enter",
    IconId.OUT: "mdi:location-exit",
    IconId.CONTACT: "mdi:electric-switch",
    IconId.ANALOG_INPUT: "mdi:sine-wave",
    IconId.FREQUENCY_INPUT: "mdi:sine-wave",
    IconId.WATER: "mdi:water",
    IconId.FIRE: "mdi:fire",
    IconId.COUNTER: "mdi:counter",
    IconId.SCENARIO: "mdi:movie-open",
    IconId.AUTOMATION: "mdi:home-automation",
    IconId.CONDITION: "mdi:help-rhombus-outline",
    IconId.TEMPERATURE: "mdi:thermometer",
    IconId.AUDIO: "mdi:cast-audio",
    IconId.FLAG: "mdi:flag",
    IconId.ALARM: "mdi:shield",
}

MODULE_NAMES: Final[dict[SubjectType, str]] = {
    SubjectType.NXT_SERVER: "NXT server (DO5520)",
    SubjectType.INPUT_MODULE: "Input module (DO5480)",
    SubjectType.DALI_MODULE: "DALI module (DO5460)",
    SubjectType.RELAY_MODULE: "Relay module (DO5411/DO5475)",
    SubjectType.DIMMER_MODULE: "Dimmer module (DO5450)",
    SubjectType.ANALOG_MODULE: "0-10V module (DO5470)",
}
