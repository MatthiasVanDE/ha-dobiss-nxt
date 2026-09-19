# Dobiss NXT for Home Assistant

A Home Assistant integration for the **Dobiss NXT** home automation server. It talks
to the server on your own network over its local developer API, subscribes to the
websocket, and never touches the internet.

[![CI](https://github.com/MatthiasVanDE/ha-dobiss-nxt/actions/workflows/ci.yml/badge.svg)](https://github.com/MatthiasVanDE/ha-dobiss-nxt/actions/workflows/ci.yml)
[![Validate](https://github.com/MatthiasVanDE/ha-dobiss-nxt/actions/workflows/validate.yml/badge.svg)](https://github.com/MatthiasVanDE/ha-dobiss-nxt/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz)

> This is a rewrite of the integration [Kester Aernoudt](https://github.com/kesteraernoudt/dobiss)
> built and maintained from 2020 to 2025. His work is what made any of this possible;
> see [NOTICE](NOTICE). It is not affiliated with Dobiss NV.

## What you get

| Platform | From |
|---|---|
| `light` | outputs programmed as a light, including dimmers |
| `switch` | sockets, ventilation, taps, and the NXT's own flags, scenarios and automations |
| `cover` | up/down relay pairs, in two modes (see below) |
| `binary_sensor` | input contacts, and the NXT's logical conditions |
| `sensor` | **the energy meter**, and temperature zones |
| `climate` | temperature zones |

### The energy meter

The NXT pushes a complete energy picture **once a minute**, whether or not anyone is
listening. This integration exposes it:

- grid draw and injection, in watts;
- the cumulative import and export registers, per tariff, ready for the Home Assistant
  energy dashboard;
- solar production, and battery figures when a battery is configured;
- **the quarter-hour peak, the highest peak of the month with the moment it happened, a
  forecast for the quarter in progress, and twelve months of history** — which is what
  the Belgian capacity tariff is billed on.

None of this costs an extra request: it rides along on the websocket the integration
already keeps open.

### Covers

A Dobiss cover is two relays. There is no position feedback and no end-stop signal, so
where a cover is can only be worked out from how long it ran.

**Basic** (the default) reports `open` or `closed` only after a run long enough to have
reached an end stop, and stays `unknown` otherwise. Set *full travel threshold* just
below the shortest full run your covers make. Zero leaves every cover unknown.

**Position** keeps a running estimate and adds a slider. It follows the physical wall
buttons too, because the relay state arrives over the websocket no matter who pressed
what. It needs the real travel time of each cover, which you have to measure:

> The Dobiss relay stays energised for a fixed, configured time. A tubular motor stops
> itself at its own limit switch well before that. If your relay runs for 59 seconds,
> the cover itself may only move for twenty. Time the cover, not the relay.

Per-cover travel times live under *Options → Cover travel times*.

## Installation

### HACS

1. HACS → three dots → **Custom repositories**.
2. Add `https://github.com/MatthiasVanDE/ha-dobiss-nxt`, category **Integration**.
3. Install **Dobiss NXT**, then restart Home Assistant.

### Manually

Copy `custom_components/dobiss` into your `config/custom_components/` directory and
restart Home Assistant.

## Setup

1. On the NXT server, open **Settings → General → Developer API** and switch it on.
2. Copy the API secret from that page.
3. In Home Assistant: **Settings → Devices & services → Add integration → Dobiss NXT**.
4. Give it the address of your NXT server and the secret.

## Services

| Service | What it does |
|---|---|
| `dobiss.turn_on` | Switch an entity on with the extras the Dobiss API offers: a delay counted down by the server itself, a logical condition, or the motion-detector variant that restarts the Dobiss timer. |
| `dobiss.action` | Send a raw action, for anything the entities do not cover. |
| `dobiss.refresh` | Ask for a full status. Rarely needed. |

A delay passed to `dobiss.turn_on` runs on the Dobiss server, so it survives a Home
Assistant restart:

```yaml
action: dobiss.turn_on
target:
  entity_id: light.hallway
data:
  delay_off: 600   # the NXT switches it off again ten minutes from now
```

## Requirements

- Home Assistant 2025.2 or newer
- A Dobiss NXT server with the developer API enabled (NXT 2.20 and up; developed against
  4.30)
- **No Python dependencies.** The API client lives inside the integration and uses only
  what Home Assistant already ships.

## What is not covered

Audio zones (address 205) and air conditioning (213) are not implemented. Temperature
zones and the climate platform are written to the published API but have **not been
tested against real hardware** — the installation this was developed on has none. If you
have a system with heating zones, a report either way would be very welcome.

## Upgrading from `kesteraernoudt/dobiss`

Entity ids, unique ids and device ids are deliberately unchanged, so automations,
scripts and dashboards keep working. Remove the old repository from HACS first, then
install this one. See [CHANGELOG.md](CHANGELOG.md) for what changed and why.

## Licence

MIT. Copyright Kester Aernoudt for the original work, Matthias Van der Elst for this
rewrite. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
