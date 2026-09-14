# DigiDice Updater

The Windows companion app for [DigiDice](https://github.com/richdubbs/DigiDice),
an ESP32-based physical dice device. It installs firmware updates and custom
token images onto the device's SD card over USB Mass Storage.

This app does **not** contain any encryption key and cannot produce firmware
the device will accept. It only ever handles an already-sealed
`app.bin.enc` + `app.ver` pair, downloaded from the release host or dropped
in by hand — see `digidice_package.py` and `release_host.md` for how that
container is validated. Sealing firmware is a separate, in-house step that
happens in the private main repo and is intentionally not part of this app;
see that repo's `CLAUDE.md` for why.

## Building it yourself

See [build_instructions.md](build_instructions.md).

## Releases

This repo's [Releases](../../releases) tab is also the live host the app's
Updates tab pulls new builds from — see `release_host.md` for the exact
layout and `digidice_update.py`'s `DEFAULT_BASE_URL`. Publishing a release
only adds files there; it doesn't change the source checked into this repo,
which is updated separately.

## Windows SmartScreen

A freshly built, unsigned `.exe` will typically trigger "Windows protected
your PC" on first run — that's SmartScreen's reputation check on the binary,
not a sign of anything wrong with it. Click "More info" → "Run anyway", or
build it yourself from this source (a self-built `.exe` was never downloaded,
so it has no Mark-of-the-Web and skips that check entirely).

## License

No license is granted. This source is published for transparency — so
anyone relying on the app (or the physical device it updates) can see
exactly what it does — not for reuse or redistribution. If you'd like to use
any of it, open an issue and ask.
