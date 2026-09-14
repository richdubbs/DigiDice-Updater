"""
digidice_package.py — loads, checks and writes an already-encrypted app package

**There is no AES key in this file, and none anywhere in the Windows app.**
That is the point of it. Encryption happens once, in-house, with
`encrypt_app.py`; what gets handed out — to this app, to a release host, to a
customer — is the encrypted pair:

    app.bin.enc   [4B orig_size LE][16B IV][AES-128-CBC, PKCS7-padded]
    app.ver       the MD5 of the *original* .bin, 32 hex chars + newline

This module's whole job is to move that pair onto the card intact. It
understands the container's shape well enough to reject a damaged one, which
needs no key at all, and it deliberately cannot produce or read the plaintext.

Previously the app held `LAUNCHER_KEY` and encrypted a raw `.bin` locally. That
put the key inside every copy of the .exe, and a PyInstaller bundle is trivial
to unpack — so anyone given the updater could forge firmware the device would
accept. Keeping the key out of here is the only thing that actually changes
that.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass

ENC_NAME = "app.bin.enc"
VER_NAME = "app.ver"

HEADER_LEN = 4 + 16          # orig_size + IV, before any ciphertext
AES_BLOCK = 16
# ota_1 is 4 MB in partitions.csv. Launcher bounds-checks orig_size against the
# real partition size before it erases anything; matching that here means a bad
# header is caught on the PC instead of halfway through a flash.
OTA1_MAX = 4 * 1024 * 1024

_VER_RE = re.compile(r"^[0-9a-f]{32}$")


class PackageError(Exception):
    """A package that should not be written to a card. Message is for a person."""


@dataclass
class AppPackage:
    """The two files, in memory, verified as far as they can be without the key."""
    enc_bytes: bytes
    ver_token: str      # 32 lowercase hex chars, no newline
    orig_size: int      # decrypted size, straight out of the header
    src_dir: str = ""

    @property
    def ver_bytes(self) -> bytes:
        # LF, not CRLF: encrypt_app.py writes it this way and Launcher's
        # readVer() compares the string it finds against its stored NVS copy.
        return (self.ver_token + "\n").encode("ascii")


def check(enc_bytes: bytes, ver_text: str) -> "tuple[str, int]":
    """Validate the pair without decrypting anything. Returns (token, size).

    Everything here is derivable from the container's structure. It catches the
    failure that actually bites -- a truncated app.bin.enc, which is what an
    unejected card or a half-finished copy leaves behind, and what used to make
    Launcher divide by zero after it had already erased ota_1.
    """
    token = ver_text.strip().lower()
    if not _VER_RE.match(token):
        raise PackageError(
            f"{VER_NAME} should be 32 hex characters (an MD5); got {ver_text.strip()!r}.")

    if len(enc_bytes) < HEADER_LEN + AES_BLOCK:
        raise PackageError(
            f"{ENC_NAME} is only {len(enc_bytes)} bytes — too short to be an "
            "app image. It looks truncated.")

    orig_size = struct.unpack("<I", enc_bytes[:4])[0]
    if orig_size == 0:
        raise PackageError(
            f"{ENC_NAME} declares a size of 0. The device rejects this — the "
            "file is corrupt.")
    if orig_size > OTA1_MAX:
        raise PackageError(
            f"{ENC_NAME} declares {orig_size} bytes, which will not fit the "
            f"{OTA1_MAX // (1024 * 1024)} MB ota_1 partition.")

    ciphertext = enc_bytes[HEADER_LEN:]
    if len(ciphertext) % AES_BLOCK:
        raise PackageError(
            f"{ENC_NAME}'s ciphertext is {len(ciphertext)} bytes, not a "
            f"multiple of {AES_BLOCK}. It looks truncated.")

    # PKCS7 always adds 1..16 bytes, so the padded length is exactly this.
    expected = (orig_size // AES_BLOCK + 1) * AES_BLOCK
    if len(ciphertext) != expected:
        raise PackageError(
            f"{ENC_NAME} is inconsistent: its header says {orig_size} bytes, "
            f"which should give {expected} bytes of ciphertext, but there are "
            f"{len(ciphertext)}. Truncated or not an app image.")

    return token, orig_size


def load(enc_path: str, ver_path: str | None = None) -> AppPackage:
    """Read an app.bin.enc plus the app.ver beside it (or one named explicitly).

    The two always travel together, so picking the image is enough to find the
    token -- and a pair that has been split up is a mistake worth reporting
    rather than papering over.
    """
    enc_path = os.path.abspath(enc_path)
    if not os.path.isfile(enc_path):
        raise PackageError(f"{enc_path} does not exist.")

    src_dir = os.path.dirname(enc_path)
    if ver_path is None:
        ver_path = os.path.join(src_dir, VER_NAME)
    if not os.path.isfile(ver_path):
        raise PackageError(
            f"No {VER_NAME} next to {os.path.basename(enc_path)}. The two files "
            f"are produced together by encrypt_app.py and have to stay together "
            f"— expected it at {ver_path}.")

    with open(enc_path, "rb") as f:
        enc_bytes = f.read()
    with open(ver_path, "r", encoding="ascii", errors="replace") as f:
        ver_text = f.read()

    token, orig_size = check(enc_bytes, ver_text)
    return AppPackage(enc_bytes=enc_bytes, ver_token=token,
                      orig_size=orig_size, src_dir=src_dir)


def _write_synced(path: str, data: bytes) -> None:
    """Writes `data` to `path` and does not return until it is actually on the
    device, not merely sitting in Windows' cache."""
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def write_to_drive(pkg: AppPackage, drive_root: str) -> None:
    """Copies the pair onto the DigiDice's SD card (mounted as `drive_root`,
    e.g. 'D:\\'). That's the entire job — Launcher notices the new files and
    flashes itself on the next normal boot.

    Both writes are fsync'd. Windows normally uses write-through caching on
    removable volumes, but "normally" is not good enough here: a cached write
    lost to an immediate power-cycle leaves a truncated app.bin.enc on the
    card, and that is exactly the input that used to make Launcher's flash
    loop divide by zero partway through erasing ota_1.

    app.ver is written second, so the two files can never be committed out of
    order. Worst case on a yanked cable is a new image carrying an old version
    token, which just means Launcher skips it -- never a new version token
    pointing at half an image.
    """
    _write_synced(os.path.join(drive_root, ENC_NAME), pkg.enc_bytes)
    _write_synced(os.path.join(drive_root, VER_NAME), pkg.ver_bytes)


def card_version(drive_root: str) -> str | None:
    """The token already on the card, or None. Lets the UI say "this card
    already has this build" instead of writing it again."""
    try:
        with open(os.path.join(drive_root, VER_NAME), "r",
                  encoding="ascii", errors="replace") as f:
            token = f.read().strip().lower()
        return token if _VER_RE.match(token) else None
    except OSError:
        return None
