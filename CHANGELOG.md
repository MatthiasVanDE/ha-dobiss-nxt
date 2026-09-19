# Changelog

All notable changes are recorded here. This project follows
[semantic versioning](https://semver.org/).

## [2.0.1] - 2026-09-19

### Fixed

- A cumulative meter register that the server reports as `null` no longer drops its
  sensor to unknown. A missing field means "no reading right now", not "the meter is at
  zero", and blanking it breaks the long-term statistics the energy dashboard is built
  on. Observed live: an NXT stopped reporting its day-tariff registers while the
  night-tariff one kept counting.
- The connection closing while Home Assistant shuts down is no longer logged as an
  outage. Home Assistant does not unload config entries on the way out, so the hub now
  listens for the stop event itself.

## [2.0.0] - 2026-09-19

First release under new maintenance. A rewrite of
[kesteraernoudt/dobiss](https://github.com/kesteraernoudt/dobiss) v1.13, whose last
functional change was in April 2025.

Entity ids, unique ids and device ids are unchanged, so an existing installation keeps
its history, its automations and its dashboards.

### Added

- **The energy meter on address 209.** Grid draw and injection, the cumulative import
  and export registers per tariff, solar production, battery figures, and the
  quarter-hour peak, monthly peak and peak forecast that the Belgian capacity tariff is
  billed on, with twelve months of history. The server was already pushing all of it
  once a minute; nothing was listening.
- **Logical conditions as binary sensors.** What the Dobiss programming itself branches
  on is now readable from Home Assistant.
- **Real availability.** Entities go unavailable when the server stops answering, rather
  than reporting a stale state as if it were current.
- **Position mode for covers**, with a slider, per-cover travel times, and tracking that
  follows the physical wall buttons.
- Delays, logical conditions and the motion-detector action are reachable from the
  `dobiss.turn_on` service.
- Config flow support for reauthentication and reconfiguration.
- A diagnostics download, with the API secret redacted.
- Dutch translation.
- A device tree: every output now hangs under a device that represents the NXT server.

### Changed

- **The `pydobiss` dependency is gone.** The API client lives inside the integration,
  fully typed. The integration now has **no Python requirements at all**.
- **The `xknx==0.9.4` pin is gone** with it. That 2019 release was pinned only for its
  travel calculator, and conflicted with the version Home Assistant's own KNX
  integration needs. Replaced by an internal implementation.
- Tokens now carry a real `exp` claim. The server enforces it; the previous
  implementation put `expiresIn` in the JWT header, which nothing acts on, so its tokens
  never expired.
- Covers deduce their state from a measured run length rather than a name heuristic, and
  pair up on the server's `locks` field when it offers one.
- While a cover moves, the position is published once a second instead of ten times a
  second. A "close everything" run used to write on the order of ten thousand states.
- Output pincodes are no longer published as entity attributes.
- Services renamed: `action_request` is now `action`, `force_update` is now `refresh`,
  and `status_request` is dropped. `turn_on` is now a proper entity service.

### Fixed

- **A Dobiss server that is unreachable at startup no longer kills the integration.**
  Setup now raises `ConfigEntryNotReady`, so Home Assistant retries with a backoff. It
  used to land in `SETUP_ERROR` permanently, which meant a power cut took every Dobiss
  entity down until somebody reloaded by hand.
- **The websocket listener is stopped on unload.** It used to keep running after a
  reload, leaking a task and an HTTP session each time.
- **Services are removed on unload.**
- **`from_pir` sends action 9.** It used to send action 1 with a `9` in `option1`, which
  a relay ignores, so the Dobiss-side motion timer never restarted.
- **An output whose `dimmable` flag is the string `"0"` is no longer dimmable.** The old
  code used `bool()`, and `bool("0")` is `True` in Python.
- **An unknown icon no longer raises.** The icon lookup was an unguarded dict access and
  the server knows more icons than the table did.
- **A channel the server reports as `null` no longer raises.** It left a traceback in
  the log on every full status frame.
- **An unknown subject type no longer breaks discovery**, which would have happened on
  the first Dobiss firmware that introduced one.
- Outputs on the sparse modules (addresses 0 and 1) restore their last known state
  instead of claiming to be off. Those channels are simply absent from the status
  response until they change.

### Removed

- The `number` platform, which existed only to hold a default duration for the climate
  service. That duration is a parameter of the service now.

### Reported upstream

The defects above that also exist in `kesteraernoudt/dobiss` have been reported on that
project's issue tracker.
