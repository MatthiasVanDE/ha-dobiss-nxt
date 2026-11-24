"""Typed models for everything the Dobiss NXT server reports."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Final, Self

from .const import (
    COVER_DOWN_ICONS,
    COVER_UP_ICONS,
    INPUT_ICONS,
    LIGHT_ICONS,
    OPENING_ICONS,
    RGB_CHANNEL_ICONS,
    SWITCH_ICONS,
    IconId,
    SubjectType,
)

_FALSEY_STRINGS = frozenset({"", "0", "false", "no", "off", "null", "none"})

#: The most power a household grid connection can plausibly carry, in kW. A
#: three-phase 63 A connection tops out around 43 kW. The NXT has been seen
#: reporting a monthly peak of 35847 kW, which is not a measurement.
MAX_PLAUSIBLE_KW: Final = 60.0
#: Allowance on top of the rate limit for a cumulative register, in kWh, so that
#: rounding and the spacing of frames never reject a genuine reading.
REGISTER_SLACK_KWH: Final = 0.5
#: The cumulative grid registers, as attribute name and payload field.
_GRID_REGISTERS: Final = (
    ("energy_usage_low", "use_low"),
    ("energy_usage_high", "use_high"),
    ("energy_production_low", "pro_low"),
    ("energy_production_high", "pro_high"),
)


def as_enum[EnumT: IntEnum](enum_cls: type[EnumT], value: Any) -> EnumT | None:
    """Map a code onto an enum, or None when we do not know it.

    A Dobiss firmware update can introduce subject types and icons that this
    integration has never heard of. Discovery must carry on regardless, so an
    unknown code becomes None rather than an exception.
    """
    number = as_int(value)
    if number is None:
        return None
    try:
        return enum_cls(number)
    except ValueError:
        return None


def as_bool(value: Any) -> bool:
    """Coerce a Dobiss flag to a bool.

    The NXT is inconsistent: the same field comes back as ``null``, as a real
    bool, or as the strings ``"0"`` and ``"1"``. A plain ``bool()`` turns the
    string ``"0"`` into ``True``, which is how a non-dimmable output ends up
    with a brightness slider.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in _FALSEY_STRINGS
    return bool(value)


def as_int(value: Any, default: int | None = None) -> int | None:
    """Coerce to int, returning ``default`` for anything unusable.

    Outputs that exist in the programming but are not wired up report ``null``,
    and the raw value is sometimes a string.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(float(text))
        except ValueError:
            return default
    return default


def as_float(value: Any, default: float | None = None) -> float | None:
    """Coerce to float, returning ``default`` for anything unusable."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            return default
    return default


@dataclass(frozen=True, slots=True)
class SubjectInfo:
    """Immutable description of one subject, as reported by ``discover``."""

    address: int
    channel: int
    name: str
    group: str
    group_id: int
    subject_type: SubjectType | None
    icon: IconId | None
    dimmable: bool
    readonly: bool
    #: Channel of the opposite direction for a cover, when the server tells us.
    #: Available from NXT 3.0 onward; older servers leave this empty and the
    #: pairing falls back to matching names.
    lock_channel: int | None
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], group: dict[str, Any]) -> Self:
        """Build a subject from one entry of the discovery response."""
        settings = payload.get("settings") or {}
        locks = settings.get("locks") or []
        lock_channel = as_int(locks[0]) if locks else None

        # The pincode of an output is of no use to Home Assistant, and state
        # attributes end up in the database and the frontend. Keep it out.
        raw = {k: v for k, v in payload.items() if k != "settings"}
        raw["settings"] = {k: v for k, v in settings.items() if k != "pincode"}

        return cls(
            address=as_int(payload.get("address"), 0) or 0,
            channel=as_int(payload.get("channel"), 0) or 0,
            name=str(payload.get("name") or "").strip(),
            group=str(group.get("name") or "").strip(),
            group_id=as_int(group.get("id"), 0) or 0,
            subject_type=as_enum(SubjectType, payload.get("type")),
            icon=as_enum(IconId, payload.get("icons_id")),
            dimmable=as_bool(payload.get("dimmable")),
            readonly=as_bool(settings.get("readonly")),
            lock_channel=lock_channel,
            raw=raw,
        )

    @property
    def key(self) -> tuple[int, int]:
        """Address and channel, which together identify a subject."""
        return (self.address, self.channel)

    @property
    def unique_id(self) -> str:
        """Stable id.

        Deliberately identical to the id the original integration used, so an
        existing installation keeps its entity ids and its history.
        """
        return f"dobissid_{self.address}_{self.channel}"

    @property
    def is_cover_up(self) -> bool:
        """Whether this output drives a cover upwards."""
        return self.icon in COVER_UP_ICONS

    @property
    def is_cover_down(self) -> bool:
        """Whether this output drives a cover downwards."""
        return self.icon in COVER_DOWN_ICONS

    @property
    def is_light(self) -> bool:
        """Whether this output should be offered as a light."""
        return self.icon in LIGHT_ICONS

    @property
    def is_switch(self) -> bool:
        """Whether this output should be offered as a switch."""
        return self.icon in SWITCH_ICONS or self.icon in OPENING_ICONS

    @property
    def is_rgb_channel(self) -> bool:
        """Whether this output is one colour channel of a combined fixture."""
        return self.icon in RGB_CHANNEL_ICONS

    @property
    def is_input(self) -> bool:
        """Whether this subject reports a state instead of driving an output."""
        return self.icon in INPUT_ICONS


@dataclass(slots=True)
class DobissOutput:
    """A subject plus whatever the server last told us about its state."""

    info: SubjectInfo
    value: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_on(self) -> bool | None:
        """Whether the output is on, or ``None`` when the server does not say.

        A configured but unwired channel reports ``null`` forever. Saying
        "unknown" is more honest than reporting it as off.
        """
        if self.value is None:
            return None
        return self.value > 0

    @property
    def brightness(self) -> int | None:
        """Dimmer level on the Dobiss scale of 0-100."""
        if not self.info.dimmable or self.value is None:
            return None
        return max(0, min(100, self.value))

    def apply(self, payload: Any) -> bool:
        """Apply one status value. Returns whether anything changed."""
        extra: dict[str, Any] = {}
        if isinstance(payload, dict):
            value = as_int(payload.get("status"))
            extra = {k: v for k, v in payload.items() if k != "status"}
        else:
            value = as_int(payload)

        if value == self.value and extra == self.extra:
            return False
        self.value = value
        self.extra = extra
        return True


@dataclass(slots=True)
class DobissCover:
    """Two outputs of one module that together drive a single cover."""

    up: DobissOutput
    down: DobissOutput
    name: str

    @property
    def unique_id(self) -> str:
        """Stable id, matching what the original integration used."""
        return f"{self.up.info.unique_id}-{self.down.info.unique_id}"

    @property
    def is_moving_up(self) -> bool:
        """Whether the raise relay is energised."""
        return bool(self.up.is_on)

    @property
    def is_moving_down(self) -> bool:
        """Whether the lower relay is energised."""
        return bool(self.down.is_on)

    @property
    def is_moving(self) -> bool:
        """Whether either relay is energised."""
        return self.is_moving_up or self.is_moving_down


@dataclass(slots=True)
class TemperatureZone:
    """A temperature zone on address 204."""

    info: SubjectInfo
    current: float | None = None
    target: float | None = None
    minutes: int | None = None
    calendar: str | None = None
    status: int | None = None
    cooling_status: int | None = None
    cooling_target: float | None = None

    def apply(self, payload: Any) -> bool:
        """Apply one status entry. Returns whether anything changed."""
        if not isinstance(payload, dict):
            return False
        before = (
            self.current,
            self.target,
            self.minutes,
            self.calendar,
            self.status,
            self.cooling_status,
            self.cooling_target,
        )
        self.current = as_float(payload.get("temp"))
        self.target = as_float(payload.get("asked"))
        self.minutes = as_int(payload.get("time"))
        calendar = payload.get("calendar")
        self.calendar = None if calendar is None else str(calendar)
        self.status = as_int(payload.get("status"))
        self.cooling_status = as_int(payload.get("cooling_status"))
        self.cooling_target = as_float(payload.get("cooling_asked"))
        after = (
            self.current,
            self.target,
            self.minutes,
            self.calendar,
            self.status,
            self.cooling_status,
            self.cooling_target,
        )
        return before != after


@dataclass(slots=True)
class AudioZone:
    """An audio zone on address 205."""

    info: SubjectInfo
    status: int | None = None
    volume: int | None = None
    source: int | None = None
    system: str | None = None
    extra: str | None = None

    def apply(self, payload: Any) -> bool:
        """Apply one status entry. Returns whether anything changed."""
        if not isinstance(payload, dict):
            return False
        before = (self.status, self.volume, self.source, self.system, self.extra)
        self.status = as_int(payload.get("status"))
        self.volume = as_int(payload.get("volume"))
        self.source = as_int(payload.get("source"))
        system = payload.get("system")
        self.system = None if system is None else str(system)
        extra = payload.get("extra")
        self.extra = None if extra is None else str(extra)
        after = (self.status, self.volume, self.source, self.system, self.extra)
        return before != after


@dataclass(slots=True)
class EnergySnapshot:
    """The live figures of the energy meter on address 209, subtype 0.

    The NXT pushes this once a minute whether or not anyone is listening, which
    makes it free to expose. ``peak_month`` and ``peak_forecast`` are what the
    Belgian capacity tariff is billed on.

    The server does not always describe the grid. When it loses its P1 source
    it falls back to another meter it knows, such as a sub-meter on a heat
    pump, and reports that meter's single register as ``use_low`` with the
    tariff-2 registers null. The grid power, the peaks and the daily totals then
    come from that meter too, while looking perfectly ordinary. Such a frame
    sets ``grid_meter_present`` to False and leaves the grid registers alone.
    """

    timestamp: datetime | None = None
    #: Whether the last frame described the grid connection. See the class doc.
    grid_meter_present: bool = True
    #: How many readings were thrown away as implausible since start-up.
    rejected_readings: int = 0
    #: Instantaneous grid draw in W. Zero while exporting.
    power_usage: float | None = None
    #: Instantaneous grid injection in W. Zero while importing.
    power_production: float | None = None
    #: Instantaneous solar production in W, when an inverter is configured.
    power_solar: float | None = None
    #: Cumulative import/export registers in kWh. ``low`` is tariff 1 (OBIS
    #: 1.8.1 and 2.8.1), which Belgian meters bill as the day tariff; ``high``
    #: is tariff 2, the night and weekend tariff.
    energy_usage_low: float | None = None
    energy_usage_high: float | None = None
    energy_production_low: float | None = None
    energy_production_high: float | None = None
    energy_solar_total: float | None = None
    #: Quarter-hour peaks in kW.
    peak_current: float | None = None
    peak_forecast: float | None = None
    peak_month: float | None = None
    peak_month_at: str | None = None
    peak_history: dict[str, float] = field(default_factory=dict)
    #: Battery figures, all ``None`` unless a battery is configured.
    battery_power: float | None = None
    battery_soc: float | None = None
    battery_charge_total: float | None = None
    battery_discharge_total: float | None = None
    #: Self-consumption.
    own_usage: float | None = None
    own_percentage: float | None = None
    #: Daily totals in kWh, from subtypes 1 (today) and 2 (yesterday).
    today_usage: float | None = None
    today_production: float | None = None
    today_solar: float | None = None
    yesterday_usage: float | None = None
    yesterday_production: float | None = None
    yesterday_solar: float | None = None
    battery_available: bool = False
    #: When each grid register last accepted a reading, on the monotonic clock.
    _register_at: dict[str, float] = field(
        default_factory=dict, repr=False, compare=False
    )

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        """Parse the server's ``YYYY-MM-DD HH:MM:SS`` stamp."""
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    @staticmethod
    def _is_grid_frame(current: dict[str, Any]) -> bool:
        """Whether a frame describes the grid rather than a fallback meter.

        A grid meter always reports both tariffs. A fallback meter has only
        one register, so the tariff-2 fields come through as null.
        """
        tariff_1 = (current.get("use_low"), current.get("pro_low"))
        tariff_2 = (current.get("use_high"), current.get("pro_high"))
        return all(v is None for v in tariff_1) or any(v is not None for v in tariff_2)

    def _accept_register(self, name: str, raw: Any, now: float) -> None:
        """Take a cumulative register reading, unless it cannot be true.

        When the server leaves the field out or sends null it is saying "I have
        no reading right now", not "the meter is at zero", so the last value is
        kept rather than dropping the sensor to unknown and breaking its
        statistics. A reading that goes backwards, or rises faster than a
        household connection can draw, is a glitch and is thrown away too.
        """
        value = as_float(raw)
        if value is None:
            return
        previous = getattr(self, name)
        if previous is not None:
            hours = max(0.0, now - self._register_at.get(name, now)) / 3600
            ceiling = previous + MAX_PLAUSIBLE_KW * hours + REGISTER_SLACK_KWH
            if not previous <= value <= ceiling:
                self.rejected_readings += 1
                return
        setattr(self, name, value)
        self._register_at[name] = now

    @staticmethod
    def _power_kw(raw: Any) -> float | None:
        """Read a power figure in kW, or None when it cannot be a real one."""
        value = as_float(raw)
        if value is None or not 0 <= value <= MAX_PLAUSIBLE_KW:
            return None
        return value

    @staticmethod
    def _power_w(raw: Any) -> float | None:
        """Read a power figure in W, or None when it cannot be a real one."""
        value = as_float(raw)
        if value is None or not 0 <= value <= MAX_PLAUSIBLE_KW * 1000:
            return None
        return value

    @staticmethod
    def _day_total(raw: Any) -> float | None:
        """Read a daily total in kWh, or None when no connection could do that.

        The server works these out as "register now minus register at
        midnight", so a register that jumped or fell back to another meter
        shows up here as thousands of kWh, or as a negative injection.
        """
        value = as_float(raw)
        if value is None or not 0 <= value <= MAX_PLAUSIBLE_KW * 24:
            return None
        return value

    def apply(self, payload: Any, now: float | None = None) -> bool:
        """Apply the address-209 part of a status frame.

        ``now`` is the monotonic clock, for tests. Returns whether anything
        changed.
        """
        if not isinstance(payload, dict):
            return False
        if now is None:
            now = time.monotonic()
        before = self._fingerprint()

        self.battery_available = as_bool(payload.get("battery_available"))

        current = payload.get("0")
        if isinstance(current, dict):
            self.timestamp = self._parse_timestamp(current.get("datetime"))
            self.grid_meter_present = self._is_grid_frame(current)
            self.power_usage = self._power_w(current.get("use"))
            self.power_production = self._power_w(current.get("pro"))
            self.power_solar = self._power_w(current.get("solar"))
            if self.grid_meter_present:
                for name, key in _GRID_REGISTERS:
                    self._accept_register(name, current.get(key), now)
            self.energy_solar_total = as_float(
                current.get("solar_total"), self.energy_solar_total
            )
            self.peak_current = self._power_kw(current.get("peak"))
            self.peak_forecast = self._power_kw(current.get("peak_forecast"))
            self.peak_month = self._power_kw(current.get("peak_month"))
            peak_month_at = current.get("peak_month_datetime")
            self.peak_month_at = None if peak_month_at is None else str(peak_month_at)
            self.battery_power = as_float(current.get("battery_power"))
            self.battery_soc = as_float(current.get("battery_soc"))
            self.battery_charge_total = as_float(current.get("battery_charge_total"))
            self.battery_discharge_total = as_float(
                current.get("battery_discharge_total")
            )
            self.own_usage = as_float(current.get("own"))
            self.own_percentage = as_float(current.get("own_pct"))

            history = current.get("peak_history")
            if isinstance(history, dict):
                labels = history.get("labels") or []
                values = (history.get("data") or {}).get("peak") or []
                # A month that the server recorded while it was reading the
                # wrong meter keeps its nonsense peak for good; leave it out.
                self.peak_history = {
                    str(label): value
                    for label, raw in zip(labels, values, strict=False)
                    if (value := self._power_kw(raw)) is not None
                }

        today = payload.get("1")
        if isinstance(today, dict):
            self.today_usage = self._day_total(today.get("use"))
            self.today_production = self._day_total(today.get("pro"))
            self.today_solar = self._day_total(today.get("solar"))

        yesterday = payload.get("2")
        if isinstance(yesterday, dict):
            self.yesterday_usage = self._day_total(yesterday.get("use"))
            self.yesterday_production = self._day_total(yesterday.get("pro"))
            self.yesterday_solar = self._day_total(yesterday.get("solar"))

        return before != self._fingerprint()

    def _fingerprint(self) -> tuple[Any, ...]:
        """Everything that decides whether listeners need to be told."""
        return (
            self.timestamp,
            self.grid_meter_present,
            self.power_usage,
            self.power_production,
            self.power_solar,
            self.energy_usage_low,
            self.energy_usage_high,
            self.energy_production_low,
            self.energy_production_high,
            self.energy_solar_total,
            self.peak_current,
            self.peak_forecast,
            self.peak_month,
            self.peak_month_at,
            self.battery_power,
            self.battery_soc,
            self.battery_charge_total,
            self.battery_discharge_total,
            self.own_usage,
            self.own_percentage,
            self.today_usage,
            self.today_production,
            self.today_solar,
            self.yesterday_usage,
            self.yesterday_production,
            self.yesterday_solar,
            tuple(sorted(self.peak_history.items())),
        )

    @property
    def has_data(self) -> bool:
        """Whether the server ever sent us usable energy figures."""
        return self.timestamp is not None or self.power_usage is not None

    @property
    def has_solar(self) -> bool:
        """Whether a solar inverter is configured on the NXT."""
        return self.energy_solar_total is not None or self.power_solar is not None
