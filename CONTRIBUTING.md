# Contributing

Bug reports from people with hardware I do not have are the most useful thing you can
send. In particular: temperature zones, audio zones, air conditioning, RGB fixtures and
Zigbee devices proxied through Dobiss are all written to the published API and **not
tested against real hardware**.

## Reporting a problem

Attach the diagnostics: **Settings → Devices & services → Dobiss NXT → the three dots →
Download diagnostics**. The API secret and the host address are redacted. It contains
every output the server reports and its current value, which is usually enough to see
what is going on.

## Development

```bash
git clone https://github.com/MatthiasVanDE/ha-dobiss-nxt
cd ha-dobiss-nxt
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-test.txt
ruff check custom_components tests
ruff format --check custom_components tests
pytest
```

The `custom_components/dobiss/api` package deliberately imports nothing from Home
Assistant. That keeps it testable without a Home Assistant test harness, and it is where
most of the logic worth testing lives. Please add a test there for anything you fix.

The Home Assistant layer has no tests yet; adding them with
`pytest-homeassistant-custom-component` is the most valuable open piece of work.

## Layout

```
custom_components/dobiss/
├── api/              the Dobiss NXT client, no Home Assistant imports
│   ├── client.py     REST, websocket, discovery, subscriptions
│   ├── models.py     typed models and the parsing that Dobiss makes necessary
│   ├── travel.py     cover position bookkeeping
│   └── const.py      subject types, icons and action ids from the Dobiss API docs
├── coordinator.py    the runtime hub: connection state, options, devices
├── entity.py         shared entity behaviour
└── <platform>.py     one file per Home Assistant platform
```

## Style

`ruff` decides. Docstrings are required, including on private helpers; a comment should
say why, not what.

## Releasing

1. Bump `version` in `custom_components/dobiss/manifest.json` and in `pyproject.toml`.
2. Write the entry in `CHANGELOG.md`.
3. Tag `vX.Y.Z` and publish a GitHub release. CI checks that the tag matches the
   manifest and attaches `dobiss.zip` for HACS.
