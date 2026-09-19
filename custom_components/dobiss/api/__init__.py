"""Client for the Dobiss NXT local API.

Self-contained on purpose: this package replaces the pydobiss dependency, which
has not changed since 2023 and pinned the integration to xknx 0.9.4. Nothing
here needs anything Home Assistant does not already ship.
"""

from __future__ import annotations

from .client import ENERGY_KEY, DobissClient, SubscriptionKey
from .const import (
    ICON_BY_ID,
    MODULE_NAMES,
    ZIGBEE_ADDRESSES,
    Action,
    EnergySubtype,
    IconId,
    SubjectType,
)
from .exceptions import (
    DobissAuthError,
    DobissConnectionError,
    DobissError,
    DobissResponseError,
)
from .models import (
    AudioZone,
    DobissCover,
    DobissOutput,
    EnergySnapshot,
    SubjectInfo,
    TemperatureZone,
)
from .travel import TravelCalculator, TravelStatus

__all__ = [
    "ENERGY_KEY",
    "ICON_BY_ID",
    "MODULE_NAMES",
    "ZIGBEE_ADDRESSES",
    "Action",
    "AudioZone",
    "DobissAuthError",
    "DobissClient",
    "DobissConnectionError",
    "DobissCover",
    "DobissError",
    "DobissOutput",
    "DobissResponseError",
    "EnergySnapshot",
    "EnergySubtype",
    "IconId",
    "SubjectInfo",
    "SubjectType",
    "SubscriptionKey",
    "TemperatureZone",
    "TravelCalculator",
    "TravelStatus",
]
