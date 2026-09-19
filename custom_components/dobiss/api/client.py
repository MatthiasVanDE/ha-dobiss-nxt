"""Async client for the Dobiss NXT local API.

The server exposes exactly four things and nothing more: ``discover``,
``status`` and ``jwtsecret`` over GET, ``action`` over POST, and a websocket
that pushes every state change. Any other path answers with
``Action 'getXxx' was not found on handler 'local'``, which is how that surface
was mapped exhaustively.

This module has no third-party dependencies. The JWT is signed with hmac from
the standard library, and aiohttp is provided by Home Assistant itself.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable, Iterable
from typing import Any, Final

import aiohttp

from .const import (
    API_PATH,
    DEFAULT_REQUEST_TIMEOUT,
    HEARTBEAT_TIMEOUT,
    MAX_DELAY_MINUTES,
    MAX_DELAY_SECONDS,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    TOKEN_RENEW_MARGIN_SECONDS,
    TOKEN_TTL_SECONDS,
    WEBSOCKET_PATH,
    WEBSOCKET_PROTOCOL,
    Action,
    DelayUnit,
    SubjectType,
)
from .exceptions import (
    DobissAuthError,
    DobissConnectionError,
    DobissResponseError,
)
from .models import (
    AudioZone,
    DobissCover,
    DobissOutput,
    EnergySnapshot,
    SubjectInfo,
    TemperatureZone,
    as_int,
)

_LOGGER = logging.getLogger(__name__)

#: Key under which the energy meter is published to subscribers.
ENERGY_KEY: Final[tuple[int, int]] = (int(SubjectType.ENERGY), 0)

#: Suffix pairs used to match an up output to its down output when the server
#: is too old to tell us through the ``locks`` field. Dobiss installers name
#: Velux pairs this way in Dutch.
_BUDDY_SUFFIXES: Final[tuple[tuple[str, str], ...]] = (
    (" op", " neer"),
    (" open", " dicht"),
)

SubscriptionKey = tuple[int, int]


def _b64(raw: bytes) -> bytes:
    """Base64url without padding, as JWT requires."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


class DobissClient:
    """Talks to one Dobiss NXT server."""

    def __init__(
        self,
        host: str,
        secret: str,
        *,
        secure: bool = False,
        session: aiohttp.ClientSession,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Prepare a client. Nothing is contacted until a call is made."""
        self._host = host.strip().rstrip("/")
        self._secret = secret.strip()
        self._secure = secure
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)

        scheme = "https" if secure else "http"
        ws_scheme = "wss" if secure else "ws"
        self._url = f"{scheme}://{self._host}{API_PATH}"
        self._ws_url = f"{ws_scheme}://{self._host}{WEBSOCKET_PATH}"

        self._token: str | None = None
        self._token_expires_at: float = 0.0

        self.outputs: dict[SubscriptionKey, DobissOutput] = {}
        self.covers: dict[str, DobissCover] = {}
        self.temperature_zones: dict[SubscriptionKey, TemperatureZone] = {}
        self.audio_zones: dict[SubscriptionKey, AudioZone] = {}
        self.energy = EnergySnapshot()
        self.notifications: dict[str, Any] = {}
        self.alarm: dict[str, Any] = {}
        self.server_version: str | None = None

        self._subscribers: dict[SubscriptionKey, list[Callable[[], None]]] = {}
        self._connection_listeners: list[Callable[[bool], None]] = []
        self._connected = False
        self._last_message_at: float = 0.0

        self._listen_task: asyncio.Task[None] | None = None
        self._closing = False

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------
    @property
    def host(self) -> str:
        """Host this client talks to."""
        return self._host

    @property
    def connected(self) -> bool:
        """Whether the websocket is up and the server is talking to us."""
        return self._connected

    @property
    def seconds_since_last_message(self) -> float:
        """How long ago the server last said anything."""
        if not self._last_message_at:
            return float("inf")
        return time.monotonic() - self._last_message_at

    def _bearer(self) -> str:
        """Return a valid token, minting a new one when needed.

        The server validates ``exp``: a token whose expiry has passed is
        answered with 401. The original library put ``expiresIn`` in the JWT
        *header* instead of an ``exp`` claim in the payload, which no JWT
        implementation acts on, so its tokens never expired at all.
        """
        now = time.time()
        if self._token and now < self._token_expires_at - TOKEN_RENEW_MARGIN_SECONDS:
            return self._token

        issued = int(now)
        expires = issued + TOKEN_TTL_SECONDS
        header = _b64(
            json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
        )
        payload = _b64(
            json.dumps(
                {"name": "home-assistant", "iat": issued, "exp": expires},
                separators=(",", ":"),
            ).encode()
        )
        signing_input = header + b"." + payload
        signature = _b64(
            hmac.new(self._secret.encode(), signing_input, hashlib.sha256).digest()
        )
        self._token = (signing_input + b"." + signature).decode()
        self._token_expires_at = expires
        return self._token

    def _headers(self) -> dict[str, str]:
        """Authorisation header for a request."""
        return {"Authorization": f"Bearer {self._bearer()}"}

    # ------------------------------------------------------------------
    # http
    # ------------------------------------------------------------------
    async def _request(
        self, method: str, action: str, payload: dict[str, Any] | None = None
    ) -> Any:
        """Perform one API call and return the decoded body."""
        url = self._url + action
        try:
            async with self._session.request(
                method,
                url,
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            ) as response:
                if response.status in (401, 403):
                    raise DobissAuthError(
                        "The Dobiss NXT server rejected the API secret. Check the "
                        "secret and make sure the developer API is enabled."
                    )
                if response.status >= 400:
                    raise DobissResponseError(
                        f"{method} {action} returned HTTP {response.status}"
                    )
                body = await response.text()
        except aiohttp.ClientError as err:
            raise DobissConnectionError(f"{method} {action} failed: {err}") from err
        except TimeoutError as err:
            raise DobissConnectionError(f"{method} {action} timed out") from err

        try:
            return json.loads(body)
        except ValueError as err:
            # An unknown action answers HTTP 200 with a plain sentence, which is
            # how the API surface can be probed.
            raise DobissResponseError(
                f"{method} {action} did not return JSON: {body[:120]!r}"
            ) from err

    async def async_authenticate(self) -> None:
        """Verify that host and secret work. Raises on failure."""
        await self._request("GET", "status")

    async def async_fetch_secret(self) -> str:
        """Read the API secret straight from the server.

        Only works during the short window after pressing the button next to
        the API key in the NXT interface.
        """
        url = self._url + "jwtsecret"
        try:
            async with self._session.get(url, timeout=self._timeout) as response:
                if response.status != 200:
                    raise DobissAuthError(
                        "The server did not hand out its secret. Press the button "
                        "next to the API key in the NXT settings and try again."
                    )
                data = await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise DobissConnectionError(f"Could not reach {self._host}: {err}") from err
        secret = (data or {}).get("jwt_secret")
        if not secret:
            raise DobissResponseError("The server's reply contained no secret")
        return str(secret)

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------
    async def async_discover(self) -> None:
        """Read the installation and build the object registry."""
        data = await self._request("GET", "discover")
        if not isinstance(data, dict):
            raise DobissResponseError("discover did not return an object")

        outputs: dict[SubscriptionKey, DobissOutput] = {}
        temperature: dict[SubscriptionKey, TemperatureZone] = {}
        audio: dict[SubscriptionKey, AudioZone] = {}

        for group in data.get("groups") or []:
            meta = group.get("group") or {}
            # Group 0 holds every channel that is not assigned to a room. Those
            # are duplicates of the real groups, or unconfigured channels.
            if as_int(meta.get("id"), -1) == 0:
                continue
            for raw in group.get("subjects") or []:
                info = SubjectInfo.from_payload(raw, meta)
                if info.subject_type is SubjectType.TEMPERATURE:
                    if info.name != "All zones":
                        temperature[info.key] = TemperatureZone(info)
                elif info.subject_type is SubjectType.AUDIO:
                    audio[info.key] = AudioZone(info)
                elif info.subject_type is SubjectType.CONDITION:
                    # Conditions are inputs to the Dobiss logic, not outputs.
                    # They are exposed read-only as binary sensors.
                    outputs[info.key] = DobissOutput(info)
                else:
                    outputs[info.key] = DobissOutput(info)

        # Keep the state we already had, so a rediscovery does not blank out
        # every entity until the next status frame arrives.
        for key, output in outputs.items():
            if previous := self.outputs.get(key):
                output.value = previous.value
                output.extra = previous.extra
        for key, zone in temperature.items():
            if prev_zone := self.temperature_zones.get(key):
                zone.__dict__.update(
                    {k: v for k, v in prev_zone.__dict__.items() if k != "info"}
                )

        self.outputs = outputs
        self.temperature_zones = temperature
        self.audio_zones = audio
        self.covers = self._match_covers(outputs)

    @staticmethod
    def _match_covers(
        outputs: dict[SubscriptionKey, DobissOutput],
    ) -> dict[str, DobissCover]:
        """Pair up/down outputs into covers.

        From NXT 3.0 the server states the pairing in ``settings.locks``, which
        is authoritative and survives typos in output names. Older servers need
        the name heuristic that the original integration used.
        """
        covers: dict[str, DobissCover] = {}
        used: set[SubscriptionKey] = set()

        ups = [o for o in outputs.values() if o.info.is_cover_up]
        downs = [o for o in outputs.values() if o.info.is_cover_down]

        def _display_name(name: str) -> str:
            text = name.strip()
            for suffix, _ in _BUDDY_SUFFIXES:
                if text.lower().endswith(suffix):
                    return text[: -len(suffix)].strip()
            return text

        for up in ups:
            partner: DobissOutput | None = None
            lock = up.info.lock_channel
            if lock is not None:
                partner = outputs.get((up.info.address, lock))
                if partner is not None and not partner.info.is_cover_down:
                    partner = None
            if partner is None:
                wanted = up.info.name.strip()
                for suffix, opposite in _BUDDY_SUFFIXES:
                    if wanted.lower().endswith(suffix):
                        wanted = wanted[: -len(suffix)].strip() + opposite
                        break
                partner = next(
                    (
                        d
                        for d in downs
                        if d.info.name.strip().lower() == wanted.lower()
                        and d.info.key not in used
                    ),
                    None,
                )
            if partner is None or partner.info.key in used:
                _LOGGER.debug("No matching down output for %s", up.info.name)
                continue
            used.add(up.info.key)
            used.add(partner.info.key)
            cover = DobissCover(up=up, down=partner, name=_display_name(up.info.name))
            covers[cover.unique_id] = cover
        return covers

    def cover_member_keys(self) -> set[SubscriptionKey]:
        """Keys of every output that is part of a cover."""
        keys: set[SubscriptionKey] = set()
        for cover in self.covers.values():
            keys.add(cover.up.info.key)
            keys.add(cover.down.info.key)
        return keys

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    async def async_refresh(self) -> None:
        """Fetch the full status and hand it to the subscribers."""
        data = await self._request("GET", "status")
        if not isinstance(data, dict):
            raise DobissResponseError("status did not return an object")
        self._apply(data.get("status"))

    def _apply(self, status: Any) -> None:
        """Apply one status frame and notify whoever is affected."""
        if isinstance(status, list):
            # NXT 3.20 sometimes pushes the NXT module's own status without an
            # address. Anything longer is a WAMP handshake frame, not status.
            if len(status) != 1:
                return
            status = {"0": status[0]}
        if not isinstance(status, dict):
            return

        self._last_message_at = time.monotonic()
        changed: set[SubscriptionKey] = set()

        for raw_address, line in status.items():
            address = as_int(raw_address)
            if address is None:
                continue

            if address == SubjectType.ENERGY:
                if self.energy.apply(line):
                    changed.add(ENERGY_KEY)
                continue
            if address == SubjectType.NOTIFICATION and isinstance(line, dict):
                self.notifications = dict(line)
                continue
            if address == SubjectType.ALARM and isinstance(line, dict):
                self.alarm = dict(line)
                continue

            if isinstance(line, list):
                for channel, value in enumerate(line):
                    if value is None:
                        continue
                    changed |= self._apply_one(address, channel, value)
            elif isinstance(line, dict):
                for raw_channel, value in line.items():
                    channel = as_int(raw_channel)
                    # A configured but unwired channel reports null forever.
                    # Skipping keeps the entity at its last known state, which
                    # is the honest answer: the server does not know either.
                    if channel is None or value is None:
                        continue
                    changed |= self._apply_one(address, channel, value)

        for key in changed:
            self._notify(key)

    def _apply_one(
        self, address: int, channel: int, value: Any
    ) -> set[SubscriptionKey]:
        """Apply one channel value. Returns the keys that changed."""
        key = (address, channel)
        if zone := self.temperature_zones.get(key):
            return {key} if zone.apply(value) else set()
        if audio := self.audio_zones.get(key):
            return {key} if audio.apply(value) else set()
        if output := self.outputs.get(key):
            return {key} if output.apply(value) else set()
        return set()

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------
    @staticmethod
    def _delay(seconds: int | None) -> dict[str, Any] | None:
        """Shape a delay the way the API wants it.

        Up to two minutes it is sent in seconds; beyond that the server only
        accepts whole minutes, capped at two hours.
        """
        if seconds is None:
            return None
        seconds = max(0, int(seconds))
        if seconds <= MAX_DELAY_SECONDS:
            return {"value": seconds, "unit": DelayUnit.SECONDS.value}
        minutes = min(round(seconds / 60), MAX_DELAY_MINUTES)
        return {"value": minutes, "unit": DelayUnit.MINUTES.value}

    async def async_action(
        self,
        address: int,
        channel: int,
        action: Action | int,
        *,
        option1: int | None = None,
        option2: int | None = None,
        delay_on: int | None = None,
        delay_off: int | None = None,
        condition_id: int | None = None,
        condition_state: bool = True,
    ) -> Any:
        """Send one action to the server."""
        payload: dict[str, Any] = {
            "address": int(address),
            "channel": int(channel),
            "action": int(action),
        }
        if option1 is not None:
            payload["option1"] = int(option1)
        if option2 is not None:
            payload["option2"] = int(option2)
        if (delay := self._delay(delay_on)) is not None:
            payload["delayon"] = delay
        if (delay := self._delay(delay_off)) is not None:
            payload["delayoff"] = delay
        if condition_id is not None:
            payload["condition"] = {
                "id": int(condition_id),
                "operator": "true" if condition_state else "false",
            }
        _LOGGER.debug("Sending action %s", payload)
        return await self._request("POST", "action", payload)

    async def async_raw_action(self, payload: dict[str, Any]) -> Any:
        """Send an already-shaped action payload."""
        return await self._request("POST", "action", payload)

    async def async_turn_on(
        self,
        address: int,
        channel: int,
        *,
        brightness: int | None = None,
        delay_on: int | None = None,
        delay_off: int | None = None,
        from_pir: bool = False,
        condition_id: int | None = None,
        condition_state: bool = True,
    ) -> Any:
        """Switch an output on.

        ``from_pir`` uses action 9, which restarts the motion timer inside
        Dobiss instead of switching the output the way a normal command does.
        """
        action = Action.ON_FROM_PIR if from_pir else Action.ON
        return await self.async_action(
            address,
            channel,
            action,
            option1=brightness,
            delay_on=delay_on,
            delay_off=delay_off,
            condition_id=condition_id,
            condition_state=condition_state,
        )

    async def async_turn_off(self, address: int, channel: int) -> Any:
        """Switch an output off."""
        return await self.async_action(address, channel, Action.OFF)

    # ------------------------------------------------------------------
    # subscriptions
    # ------------------------------------------------------------------
    def subscribe(
        self, keys: Iterable[SubscriptionKey], callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Call ``callback`` whenever any of ``keys`` changes.

        Returns a function that cancels the subscription.
        """
        registered = list(keys)
        for key in registered:
            self._subscribers.setdefault(key, []).append(callback)

        def _unsubscribe() -> None:
            for key in registered:
                listeners = self._subscribers.get(key)
                if not listeners:
                    continue
                with contextlib.suppress(ValueError):
                    listeners.remove(callback)
                if not listeners:
                    self._subscribers.pop(key, None)

        return _unsubscribe

    def add_connection_listener(
        self, callback: Callable[[bool], None]
    ) -> Callable[[], None]:
        """Call ``callback`` when the connection comes up or goes down."""
        self._connection_listeners.append(callback)

        def _remove() -> None:
            with contextlib.suppress(ValueError):
                self._connection_listeners.remove(callback)

        return _remove

    def _notify(self, key: SubscriptionKey) -> None:
        """Tell everyone subscribed to ``key`` that it changed."""
        for callback in list(self._subscribers.get(key, ())):
            try:
                callback()
            except Exception:
                _LOGGER.exception("A Dobiss listener raised")

    def _set_connected(self, connected: bool) -> None:
        """Record the connection state and tell the listeners once."""
        if connected == self._connected:
            return
        self._connected = connected
        for callback in list(self._connection_listeners):
            try:
                callback(connected)
            except Exception:
                _LOGGER.exception("A Dobiss connection listener raised")

    # ------------------------------------------------------------------
    # websocket
    # ------------------------------------------------------------------
    async def async_start_listening(self) -> None:
        """Start the websocket listener in the background."""
        if self._listen_task and not self._listen_task.done():
            return
        self._closing = False
        self._listen_task = asyncio.create_task(
            self._listen(), name=f"dobiss-listener-{self._host}"
        )

    async def async_stop(self) -> None:
        """Stop listening and release everything."""
        self._closing = True
        task, self._listen_task = self._listen_task, None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._set_connected(False)

    async def _listen(self) -> None:
        """Keep a websocket open, reconnecting with a growing backoff."""
        delay = RECONNECT_MIN_DELAY
        while not self._closing:
            try:
                async with self._session.ws_connect(
                    self._ws_url,
                    protocols=[WEBSOCKET_PROTOCOL],
                    headers=self._headers(),
                    heartbeat=HEARTBEAT_TIMEOUT,
                ) as websocket:
                    _LOGGER.debug("Websocket to %s is open", self._host)
                    delay = RECONNECT_MIN_DELAY
                    self._last_message_at = time.monotonic()
                    self._set_connected(True)
                    # The server pushes a full frame right after connecting, but
                    # asking makes the state correct even if it ever stops.
                    await self.async_refresh()
                    await self._consume(websocket)
            except asyncio.CancelledError:
                raise
            except DobissAuthError:
                # A wrong secret will not fix itself by retrying in a loop.
                _LOGGER.error(
                    "The Dobiss NXT server rejected our credentials; stopping the "
                    "listener until the integration is reloaded"
                )
                self._set_connected(False)
                return
            except Exception as err:
                _LOGGER.debug("Websocket to %s dropped: %r", self._host, err)
            finally:
                self._set_connected(False)

            if self._closing:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def _consume(self, websocket: aiohttp.ClientWebSocketResponse) -> None:
        """Read frames until the socket closes."""
        async for message in websocket:
            if message.type is not aiohttp.WSMsgType.TEXT:
                if message.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    return
                continue
            try:
                payload = json.loads(message.data)
            except ValueError:
                _LOGGER.debug("Ignoring a frame that was not JSON")
                continue
            self._apply(payload)
