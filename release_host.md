# The release host

The Updates tab fetches everything from one base URL, expecting three files
(or however many of them are currently published) sitting side by side:

```
https://<base>/version.json
https://<base>/DigiDice Updater.exe
https://<base>/app.bin.enc   (+ app.ver next to it)
```

Nothing dynamic is required: static files behind HTTPS is the whole protocol.
There is no server-side component to run.

## The live setup: GitHub Releases on the public source-mirror repo

`DEFAULT_BASE_URL` in `digidice_update.py` is baked in and points at

```
https://github.com/richdubbs/DigiDice-Updater/releases/latest/download
```

`richdubbs/DigiDice-Updater` is a **public** repo. Its git tree holds a
source-only mirror of this `windows_app/` directory (published for
transparency and self-building, see that repo's README); its Releases tab
holds the built artifacts this file describes. Combining the two roles in
one repo is fine because neither the app's source nor its built output
contains the AES key.

The main `DigiDice` repo stays private for a different reason:
`encrypt_app.py` / `Launcher.ino` carry the AES key that seals firmware (see
the security note in `CLAUDE.md`), and a base URL the shipped `.exe` talks to
has to be reachable with **no credential embedded in the app** — anything
baked into a distributed `.exe` is recoverable from it. A GitHub token with
read access to the private repo would hand out that repo's source, key
included, to anyone who unpacked the `.exe`. Publishing to a public repo that
never holds the key — whether or not it also holds non-secret source —
sidesteps that entirely.

There used to be a second public repo, `richdubbs/DigiDice-releases`, that
held only artifacts and no source. It's now archived and private — having
two public repos for one small project was more confusing than the extra
separation was worth, once it was clear the source mirror itself was already
safe to combine with release hosting.

GitHub's `.../releases/latest/download/<filename>` URLs 302-redirect (twice)
to whatever asset by that name is attached to the most recently published
release — no API calls, no auth, and it always tracks "latest" automatically.
That is a static host in every way this app cares about, so none of the
generic mechanics below changed to support it.

**Publishing a release** is one command from `windows_app/`:

```
python publish_release.py --notes "what changed"
```

It seals nothing itself — run `encrypt_app.py` first — but takes the
`app.bin.enc`/`app.ver` pair at the repo root, computes the manifest (version
tag = today's date + the current git short hash, sha256, size), and calls
`gh release create` (or `gh release upload --clobber` if that tag already
exists) against `richdubbs/DigiDice-Updater`. Pass `--exe path\to\DigiDice
Updater.exe` to publish a Windows app self-update in the same release; its
version comes from `APP_VERSION` in `digidice_app.py`. Requires the `gh` CLI,
authenticated with push access to that repo. `--dry-run` prints the manifest
and the `gh` command without publishing anything.

## Pointing the app at a different host

Self-hosting instead (an S3/R2 bucket, Netlify, a folder on your own domain)
works exactly the same way — GitHub Releases isn't special-cased anywhere in
`digidice_update.py`, it's just what `DEFAULT_BASE_URL` happens to point at.
Three places are checked, first one wins:

1. `DIGIDICE_UPDATE_URL` in the environment — handy for testing against a
   staging copy without touching anything else.
2. `update_source.json` sitting next to the `.exe`:
   ```json
   { "base_url": "https://your-host/digidice" }
   ```
   Ship this alongside the `.exe` if you want to move hosts later without
   rebuilding.
3. `DEFAULT_BASE_URL` at the top of `digidice_update.py`.

Whatever the host, it should only ever carry the built artifacts — **never the
DigiDice source**, which is where the AES key lives.

Plain `http://` is refused. The manifest's hashes arrive over the same
connection as the files they describe, so they cannot protect a download from
whoever is serving it — TLS is what makes the host's word worth anything, and
the app is about to *run* one of these files. `DIGIDICE_ALLOW_HTTP=1` lifts the
restriction for testing against a box on your own desk.

## version.json

```json
{
  "app": {
    "version": "1.1.0",
    "url": "DigiDice.Updater.exe",
    "sha256": "9f2c...",
    "size": 24117248,
    "notes": "Batch token uploads"
  },
  "firmware": {
    "version": "2026-09-12",
    "url": "app.bin.enc",
    "ver_url": "app.ver",
    "sha256": "1a4b...",
    "size": 1439668,
    "notes": "Hold P or T for the number pad"
  }
}
```

- `version` and `url` are required; everything else is optional.
- `url` may be relative (resolved against `version.json`) or absolute.
- `sha256` is checked after downloading and the file is thrown away if it does
  not match. Leave it out and you lose that check.
- `size` only feeds the progress bar.
- `notes` is shown under the version in the tab. One short line.
- Either section can be omitted if you are not publishing that one yet.
- `ver_url` is firmware-only: where `app.ver` lives. Optional — it defaults to
  `app.ver` next to the image, which is how `encrypt_app.py` emits the pair.

**On GitHub Releases specifically, `url` must be the name the asset was
actually published under, not the local filename.** GitHub rewrites spaces in
uploaded asset names to periods — `DigiDice Updater.exe` is served as
`DigiDice.Updater.exe` — so a naive percent-encoded guess (`DigiDice%20Updater.exe`)
404s even though the real file is right there. `publish_release.py` resolves
this itself (`resolve_asset_name()`, checked against the release's real asset
list after uploading) rather than guessing; do the same by hand if you ever
edit `version.json` directly.

### Versions

`app.version` is compared against `APP_VERSION` in `digidice_app.py`. Dotted
numbers are ordered properly (`1.10` > `1.9`), and anything else — a date, a
build hash — counts as newer whenever it simply differs. **Bump `APP_VERSION`
in the same commit that publishes a new `.exe`**, or the tab will keep offering
an update you already have.

`firmware.version` is a free-form label — a date is fine. It is only compared
for difference, and it is what the tab shows.

### The host serves sealed images

**Publish `app.bin.enc` + `app.ver`, never the raw `.bin`.** Both come out of
`encrypt_app.py`, run in-house:

```bash
python encrypt_app.py Compiled_Binary/DigiDice2.ino.bin
```

`sha256` covers the download of `app.bin.enc` itself. The version token the
device compares against is the *content* of `app.ver`, which is downloaded
rather than computed — the app cannot decrypt the image, so it has no way to
derive it.

This is the whole reason the layout is this way. The app used to download a raw
`.bin` and encrypt it locally, which meant every copy of the `.exe` carried
`LAUNCHER_KEY`; a PyInstaller bundle is trivial to unpack, and the key was
sitting in `digidice_crypto`'s constants as a plain tuple of integers. Anyone
handed the updater could forge firmware the device would accept. Now the key
never leaves the build machine, and neither the host nor the app can produce an
image the device will take.

## Publishing a release

1. Compile the sketch; find `DigiDice2.ino.bin` in the build output.
2. Seal it: `python encrypt_app.py Compiled_Binary/DigiDice2.ino.bin`, which
   writes `app.bin.enc` + `app.ver` **to the repo root**. Those two are what
   get published — the raw `.bin` stays on the build machine.
3. If the Windows app itself changed too: build the `.exe` (see
   `build_instructions.md`), bumping `APP_VERSION` first.
4. From `windows_app/`: `python publish_release.py --notes "what changed"` —
   add `--exe path\to\DigiDice Updater.exe` if step 3 applies. This builds
   `version.json` and publishes everything to `richdubbs/DigiDice-Updater`
   in one shot (see "The live setup" above).

Step 4 is the one that actually ships it — until a new release is published
there, nothing will offer it. On a different host, the equivalent of step 4 is
copying the changed files up and hand-editing `version.json` with the new
version strings, sizes and hashes.

Publishing a release only touches that repo's Releases tab, via `gh
release` — it does not update the source files visible in its git tree. If
`windows_app/` source changed (step 3, or anything else), re-copy the
current files into a checkout of `richdubbs/DigiDice-Updater` and commit
them there separately. See that repo's note in `CLAUDE.md` for why that's a
fresh commit, never a history-preserving merge from this repo.

## How the app update lands

Windows will not let a running `.exe` be overwritten, but it will let one be
renamed. So the app renames itself to `DigiDice Updater.exe.old`, drops the
freshly downloaded build in its place, launches it and closes. The `.old` file
stays locked until this process is gone, so it is deleted at the *start* of the
next run instead.

If the swap fails partway, the original is renamed back before the error is
reported — the one case that cannot be recovered automatically (the new file
cannot be moved in *and* the old one cannot be moved back) prints the exact
path of the `.old` to rename by hand.
