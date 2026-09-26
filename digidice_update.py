"""
digidice_update.py — pulls new builds off the release host.

Two independent things can be updated, and they are not the same shape:

  the app       a single PyInstaller .exe. Windows will not let a running .exe
                be overwritten, but it *will* let one be renamed, so the swap
                is: rename myself to .old, drop the new build in my place,
                launch it, exit. The .old carcass is deleted on the next run
                (see cleanup_previous_exe), because it stays locked until this
                process is actually gone.

  the firmware  the already-encrypted pair, app.bin.enc + app.ver, exactly as
                encrypt_app.py produced it in-house. Both are downloaded and
                handed to the same load-check-write path the Firmware Update
                tab uses (digidice_package). The host serves sealed images and
                this app holds no key, so neither the host nor any copy of the
                .exe can be used to forge firmware.

Everything here is stdlib-only (urllib, hashlib, subprocess) on purpose — the
packaged .exe should not grow a new dependency just to fetch a file.

HOST LAYOUT — serve a version.json next to the files it describes, over HTTPS.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

MANIFEST_NAME = "version.json"

# Where releases live. A public GitHub repo holding only built artifacts —
# never DigiDice2 source, which is where the firmware AES key lives. GitHub's
# ".../releases/latest/download/<name>" URLs 302-redirect to whatever was most
# recently published, so this behaves exactly like the static host below with
# no server of our own and no auth: publishing a new release *is* publishing
# an update.
#
# Overridable at runtime without a rebuild, checked in this order:
#   1. the DIGIDICE_UPDATE_URL environment variable
#   2. update_source.json next to the .exe, {"base_url": "https://..."}
#   3. this constant
DEFAULT_BASE_URL = "https://github.com/richdubbs/DigiDice-Updater/releases/latest/download"
SOURCE_COMPARE_URL = "https://api.github.com/repos/richdubbs/DigiDice-Updater/compare/{revision}...master"

CONFIG_NAME = "update_source.json"
USER_AGENT = "DigiDiceUpdater"
_TOKEN_RE = re.compile(r"[0-9a-f]{32}")   # app.ver: the MD5 of the plain .bin
HTTP_TIMEOUT = 30       # seconds; a stalled socket must not hang the worker
CHUNK = 64 * 1024


class UpdateError(Exception):
    """Anything that went wrong talking to the release host. Carries a message
    meant to be shown to a person, not a stack trace."""


@dataclass
class Release:
    """One entry out of version.json."""
    version: str
    url: str
    sha256: Optional[str] = None
    md5: Optional[str] = None       # integrity of the downloaded file itself
    size: Optional[int] = None
    notes: str = ""
    # firmware only: where app.ver lives. Defaults to app.ver alongside the
    # image, which is how encrypt_app.py emits the pair.
    ver_url: str = ""
    # firmware only: app.ver's contents, as published with this manifest. It
    # ties app.ver to the same release as the sha256 ties app.bin.enc, since
    # the two files are fetched in separate requests (see fetch_firmware_token).
    token: Optional[str] = None


@dataclass
class SourceStatus:
    """How a source checkout relates to the public repository's master branch."""
    relation: str
    local_revision: str
    remote_revision: str
    ahead_by: int = 0
    behind_by: int = 0

    @property
    def update_available(self) -> bool:
        # In GitHub's comparison response, the head is public master. It is
        # "ahead" when public master contains commits the local checkout lacks.
        return self.ahead_by > 0


# ── Where we are on disk ───────────────────────────────────────────────────

def is_frozen() -> bool:
    """True when running as the packaged .exe. Self-update only makes sense
    there; from source, git is the update mechanism."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """The folder the app lives in — next to the .exe when packaged, next to
    this file when running from source. The new .exe has to land here: os.replace
    is only atomic within one volume, and the swap depends on that."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def cache_dir() -> str:
    """Scratch space for downloaded firmware. Deliberately not next to the
    .exe: that can be a read-only location (Program Files, a network share)
    and firmware downloads have no reason to live there."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "DigiDiceUpdater", "cache")
    os.makedirs(path, exist_ok=True)
    return path


# ── Release host ───────────────────────────────────────────────────────────

def base_url() -> str:
    """The configured release host, without a trailing slash. Empty string
    means nobody has set one yet."""
    env = os.environ.get("DIGIDICE_UPDATE_URL", "").strip()
    if env:
        return env.rstrip("/")

    cfg = os.path.join(app_dir(), CONFIG_NAME)
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            url = str(json.load(f).get("base_url", "")).strip()
        if url:
            return url.rstrip("/")
    except FileNotFoundError:
        pass
    except Exception as e:
        raise UpdateError(f"{CONFIG_NAME} could not be read: {e}")

    return DEFAULT_BASE_URL.rstrip("/")


def _check_url(url: str) -> str:
    """Plain http would let anyone on the path hand us an .exe we are about to
    run, and the manifest's own hashes cannot help with that -- they arrive
    over the same connection. So https is required, with an opt-out for
    testing against a box on your own desk."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and os.environ.get("DIGIDICE_ALLOW_HTTP") == "1":
        return url
    if not parsed.scheme:
        raise UpdateError(f"Update URL has no https:// on the front: {url}")
    raise UpdateError(
        f"Refusing {parsed.scheme}:// for updates - the release host must be "
        "https (set DIGIDICE_ALLOW_HTTP=1 to override for local testing).")


def _get(url: str) -> bytes:
    req = urllib.request.Request(_check_url(url), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise UpdateError(f"Release host answered {e.code} {e.reason} for {url}")
    except urllib.error.URLError as e:
        raise UpdateError(f"Could not reach the release host: {e.reason}")
    except OSError as e:
        raise UpdateError(f"Could not reach the release host: {e}")


def _release_from(section: dict, manifest_url: str, name: str) -> Release:
    if not isinstance(section, dict):
        raise UpdateError(f"{MANIFEST_NAME} has no usable \"{name}\" section.")
    for field in ("version", "url"):
        if not str(section.get(field, "")).strip():
            raise UpdateError(f"{MANIFEST_NAME}: \"{name}\" is missing \"{field}\".")
    token = str(section.get("token", "")).strip().lower() or None
    if token and not _TOKEN_RE.fullmatch(token):
        raise UpdateError(f"{MANIFEST_NAME}: \"{name}\" has a malformed \"token\".")
    return Release(
        token=token,
        version=str(section["version"]).strip(),
        # Relative urls are resolved against the manifest, so a host can be
        # moved or mirrored without rewriting every entry inside it.
        url=urllib.parse.urljoin(manifest_url, str(section["url"]).strip()),
        sha256=(str(section["sha256"]).strip().lower() if section.get("sha256") else None),
        md5=(str(section["md5"]).strip().lower() if section.get("md5") else None),
        size=int(section["size"]) if str(section.get("size", "")).strip().isdigit() else None,
        notes=str(section.get("notes", "")).strip(),
        ver_url=urllib.parse.urljoin(
            manifest_url,
            str(section.get("ver_url", "")).strip()
            or urllib.parse.urljoin(str(section["url"]).strip(), "app.ver")),
    )


def fetch_manifest() -> "tuple[Optional[Release], Optional[Release]]":
    """(app, firmware) as described by the host's version.json. Either can be
    None if the host doesn't publish that one yet."""
    root = base_url()
    if not root:
        raise UpdateError(
            "No release host is configured yet. Set DEFAULT_BASE_URL in "
            f"digidice_update.py, drop a {CONFIG_NAME} next to the .exe, or "
            "set DIGIDICE_UPDATE_URL.")

    manifest_url = f"{root}/{MANIFEST_NAME}"
    raw = _get(manifest_url)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise UpdateError(f"{manifest_url} is not valid JSON: {e}")

    app = _release_from(data["app"], manifest_url, "app") if data.get("app") else None
    fw = _release_from(data["firmware"], manifest_url, "firmware") if data.get("firmware") else None
    return app, fw


def local_source_revision() -> str:
    """Return this checkout's Git revision, or explain why it cannot be read."""
    if is_frozen():
        raise UpdateError("The packaged Windows app is not a source checkout.")
    try:
        result = subprocess.run(
            ["git", "-C", app_dir(), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"Could not read the source revision with Git: {exc}")

    revision = result.stdout.strip().lower()
    if result.returncode or not re.fullmatch(r"[0-9a-f]{40}", revision):
        detail = result.stderr.strip() or "this folder is not a Git checkout"
        raise UpdateError(f"Could not read the source revision: {detail}")
    return revision


def fetch_source_status() -> SourceStatus:
    """Compare a source checkout with the public repository without changing it."""
    local = local_source_revision()
    url = SOURCE_COMPARE_URL.format(revision=local)
    raw = _get(url)
    try:
        data = json.loads(raw.decode("utf-8"))
        relation = str(data["status"]).strip().lower()
        commits = data.get("commits") or []
        # GitHub's compare response lists commits reachable from public master
        # but not the local revision. When there are none, public master is the
        # merge base (the checkouts are identical, or the local one is ahead).
        remote_commit = commits[-1] if commits else data["merge_base_commit"]
        remote = str(remote_commit["sha"]).strip().lower()
        ahead_by = int(data.get("ahead_by", 0))
        behind_by = int(data.get("behind_by", 0))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"The source comparison response could not be read: {exc}")

    if relation not in {"identical", "ahead", "behind", "diverged"}:
        raise UpdateError(f"The source comparison returned an unknown status: {relation}")
    if not re.fullmatch(r"[0-9a-f]{40}", remote):
        raise UpdateError("The source comparison did not include a valid public revision.")
    return SourceStatus(relation, local, remote, ahead_by, behind_by)


# ── Downloading ────────────────────────────────────────────────────────────

ProgressFn = Callable[[int, Optional[int]], None]   # (bytes so far, total or None)


def parse_firmware_token(data: bytes) -> str:
    """app.ver's contents as a version token, or UpdateError."""
    token = data.decode("ascii", errors="replace").strip().lower()
    if not _TOKEN_RE.fullmatch(token):
        raise UpdateError("The published app.ver is not a valid firmware version token.")
    return token


def fetch_firmware_token(release: Release) -> str:
    """Compare the card with app.ver, not the encrypted download's MD5.

    app.ver comes from ".../latest/download/", like everything else, in a
    request of its own. If a new release is published between that request and
    the manifest's, the two describe different releases, and a pair copied on
    that basis is one the device will refuse. The token in version.json, when
    the host publishes one, is what catches it."""
    token = parse_firmware_token(_get(release.ver_url))
    if release.token and token != release.token:
        raise UpdateError(
            "The published app.ver does not belong to the release in "
            f"{MANIFEST_NAME}; a new release may be going up. Try again in a minute.")
    return token


def download(url: str, dst_path: str, sha256: Optional[str] = None,
             md5: Optional[str] = None, progress: Optional[ProgressFn] = None) -> str:
    """Fetch `url` to `dst_path`, verifying whatever hashes the manifest gave
    us. Downloads to a .part file and only moves it into place once it has
    verified, so a dropped connection can never leave a half file sitting
    where something else will pick it up and use it."""
    part = dst_path + ".part"
    req = urllib.request.Request(_check_url(url), headers={"User-Agent": USER_AGENT})
    h_sha, h_md5 = hashlib.sha256(), hashlib.md5()
    got = 0

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            length = resp.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            with open(part, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    h_sha.update(chunk)
                    h_md5.update(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
                f.flush()
                os.fsync(f.fileno())
    except urllib.error.HTTPError as e:
        _quiet_remove(part)
        raise UpdateError(f"Release host answered {e.code} {e.reason} for {url}")
    except (urllib.error.URLError, OSError) as e:
        _quiet_remove(part)
        raise UpdateError(f"Download failed: {e}")

    if sha256 and h_sha.hexdigest() != sha256:
        _quiet_remove(part)
        raise UpdateError("Downloaded file does not match the SHA-256 in "
                          f"{MANIFEST_NAME} - refusing to use it.")
    if md5 and h_md5.hexdigest() != md5:
        _quiet_remove(part)
        raise UpdateError("Downloaded file does not match the MD5 in "
                          f"{MANIFEST_NAME} - refusing to use it.")

    os.replace(part, dst_path)
    return dst_path


def _quiet_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ── Version comparison ─────────────────────────────────────────────────────

def _parts(v: str):
    """1.2.10 -> (1, 2, 10). Returns None for anything that isn't purely
    dotted numbers (a date, a git hash), which the caller then compares by
    equality instead of by order."""
    bits = v.strip().lstrip("vV").split(".")
    try:
        return tuple(int(b) for b in bits)
    except ValueError:
        return None


def is_newer(remote: str, local: str) -> bool:
    """Whether `remote` is worth installing over `local`. Dotted numbers are
    ordered properly; anything else (dates, build hashes) falls back to "it is
    different, so it is new", which is the safe answer for a host that only
    ever publishes forwards."""
    if not remote:
        return False
    if not local:
        return True
    r, l = _parts(remote), _parts(local)
    if r is None or l is None:
        return remote.strip() != local.strip()
    # Pad so 1.2 and 1.2.0 compare equal rather than short-circuiting.
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


# ── Self-update ────────────────────────────────────────────────────────────

def previous_exe_path() -> str:
    return os.path.abspath(sys.executable) + ".old" if is_frozen() else ""


def cleanup_previous_exe() -> None:
    """Delete the .old left behind by the last self-update. Called at startup:
    Windows keeps the renamed image locked for as long as the old process is
    alive, so the only reliable moment to remove it is the *next* launch. A
    failure here is harmless -- try again next time."""
    old = previous_exe_path()
    if old and os.path.exists(old):
        _quiet_remove(old)


def staged_exe_path() -> str:
    """Where a downloaded .exe waits before the swap. Next to the running one,
    so replacing it is a same-volume rename and not a copy."""
    cur = os.path.abspath(sys.executable)
    stem, ext = os.path.splitext(cur)
    return stem + ".new" + ext


def apply_app_update(new_exe: str) -> None:
    """Swap `new_exe` in for the running .exe and start it. Returns once the
    replacement is running; the caller is expected to shut its UI down
    immediately afterwards, because two copies are briefly alive at once.

    Windows will not open a running .exe for writing but will happily rename
    it, which is the whole trick. If the second rename fails we are in the one
    genuinely dangerous spot -- the app has been moved out of the way and
    nothing has taken its place -- so that path puts the original back before
    reporting the failure."""
    if not is_frozen():
        raise UpdateError(
            "This copy is running from source, not a packaged .exe - update it "
            "with git instead.")

    cur = os.path.abspath(sys.executable)
    old = previous_exe_path()
    _quiet_remove(old)

    try:
        os.replace(cur, old)
    except OSError as e:
        raise UpdateError(f"Could not move the current .exe aside: {e}")

    try:
        os.replace(new_exe, cur)
    except OSError as e:
        try:
            os.replace(old, cur)          # put it back; nothing has changed
        except OSError:
            raise UpdateError(
                f"Update failed ({e}) AND the original could not be restored. "
                f"The previous version is sitting at {old} - rename it back to "
                f"{os.path.basename(cur)} by hand.")
        raise UpdateError(f"Could not install the new .exe: {e}")

    try:
        # DETACHED_PROCESS so the new copy is not a child of this one and does
        # not die with it; CREATE_NEW_PROCESS_GROUP so it gets no Ctrl-C from us.
        flags = 0x00000008 | 0x00000200
        subprocess.Popen([cur], close_fds=True, creationflags=flags,
                         cwd=os.path.dirname(cur))
    except OSError as e:
        raise UpdateError(
            f"The new version is installed but would not start ({e}). "
            f"Launch {os.path.basename(cur)} yourself.")
