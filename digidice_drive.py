"""
digidice_drive.py — find the DigiDice's SD card once it shows up as a
Windows drive letter (USB Drive Mode / MSC).

Uses only ctypes + the Win32 API (no pywin32 dependency, keeps PyInstaller
packaging simple). No-ops harmlessly on non-Windows platforms so the rest of
the app can still be imported/tested elsewhere.
"""

from __future__ import annotations

import ctypes
import os
import platform
from dataclasses import dataclass
from typing import List, Optional

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3

# Windows caps volume labels at 32 chars; MAX_PATH+1 is the conventional buffer.
_VOLUME_NAME_CHARS = 261

TOKENS_DIR_NAME = "Tokens"

# Files/folders that indicate a drive is very likely the DigiDice SD card,
# in priority order (checked in order, first match wins for "confidence").
_MARKERS = ["Tokens", "app.ver", "app.bin.enc"]


@dataclass
class DriveInfo:
    letter: str          # e.g. "D:\\"
    label: str
    is_likely_digidice: bool


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _kernel32():
    """kernel32 with the three functions we use fully declared. ctypes guesses
    otherwise, which silently truncates pointers on 64-bit."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetLogicalDrives.argtypes = []
    k.GetLogicalDrives.restype = ctypes.c_uint32
    k.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    k.GetDriveTypeW.restype = ctypes.c_uint32
    k.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p,                    # lpRootPathName
        ctypes.c_wchar_p,                    # lpVolumeNameBuffer
        ctypes.c_uint32,                     # nVolumeNameSize (in CHARACTERS)
        ctypes.POINTER(ctypes.c_uint32),     # lpVolumeSerialNumber
        ctypes.POINTER(ctypes.c_uint32),     # lpMaximumComponentLength
        ctypes.POINTER(ctypes.c_uint32),     # lpFileSystemFlags
        ctypes.c_wchar_p,                    # lpFileSystemNameBuffer
        ctypes.c_uint32,                     # nFileSystemNameSize
    ]
    k.GetVolumeInformationW.restype = ctypes.c_int
    return k


def list_removable_drives() -> List[DriveInfo]:
    """Lists candidate drives: everything Windows calls removable, plus any
    fixed disk that already looks like a DigiDice card.

    The fixed-disk pass matters because a TinyUSB mass-storage device does not
    reliably report itself as removable; when it doesn't, a perfectly healthy
    DigiDice used to be invisible here and the dropdown came up empty.
    """
    if not _is_windows():
        return []

    k = _kernel32()
    drives: List[DriveInfo] = []
    bitmask = k.GetLogicalDrives()
    for i in range(26):
        if not (bitmask & (1 << i)):
            continue
        letter = f"{chr(65 + i)}:\\"
        drive_type = k.GetDriveTypeW(letter)
        if drive_type not in (DRIVE_REMOVABLE, DRIVE_FIXED):
            continue

        likely = any(os.path.exists(os.path.join(letter, m)) for m in _MARKERS)
        if drive_type == DRIVE_FIXED and not likely:
            continue  # never offer the user their own C: drive

        drives.append(DriveInfo(letter=letter, label=_volume_label(letter, k),
                                is_likely_digidice=likely))

    return drives


def _volume_label(letter: str, k=None) -> str:
    if not _is_windows():
        return ""
    k = k or _kernel32()
    buf = ctypes.create_unicode_buffer(_VOLUME_NAME_CHARS)
    # nVolumeNameSize is in CHARACTERS, not bytes. Passing ctypes.sizeof(buf)
    # (522) told Windows it could write twice the buffer's real capacity.
    ok = k.GetVolumeInformationW(letter, buf, _VOLUME_NAME_CHARS,
                                 None, None, None, None, 0)
    return buf.value if ok else ""


def guess_digidice_drive() -> Optional[DriveInfo]:
    """Best-effort single guess. Returns None if there's no clear winner —
    callers should fall back to letting the user pick from
    list_removable_drives()."""
    candidates = [d for d in list_removable_drives() if d.is_likely_digidice]
    if len(candidates) == 1:
        return candidates[0]
    return None


def read_card_version(drive_letter: str):
    """The version token sitting in <drive>\app.ver, or None if the card has
    no firmware on it yet (or is not readable).

    That token is the MD5 of the *unencrypted* .bin -- see
    digidice_package.write_to_drive -- which is exactly what a release host can
    publish alongside a download, so "is this card already up to date?" is a
    string comparison and not a guess.
    """
    path = os.path.join(drive_letter, "app.ver")
    try:
        with open(path, "r", encoding="ascii", errors="replace") as f:
            token = f.read(64).strip()
    except OSError:
        return None
    return token or None


def ensure_tokens_folder(drive_letter: str) -> str:
    """Creates <drive>\\Tokens if missing, returns its full path."""
    path = os.path.join(drive_letter, TOKENS_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path
