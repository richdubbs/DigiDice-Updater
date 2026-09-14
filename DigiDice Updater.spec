# -*- mode: python ; coding: utf-8 -*-
#
# Build with:  pyinstaller "DigiDice Updater.spec"

import os
import tkinterdnd2

# tkinterdnd2 ships its tkdnd Tcl package as binary data files that PyInstaller
# does not pick up on its own; without them the packaged .exe dies with
# "RuntimeError: Unable to load tkdnd library" the moment it launches (running
# digidice_app.py directly is unaffected, which is what makes it a nasty one).
#
# Resolved at build time on purpose. This used to be a hardcoded absolute path
# into Python312's site-packages, which broke on any other machine and on the
# next Python upgrade.
TKDND_PATH = os.path.join(os.path.dirname(tkinterdnd2.__file__), "tkdnd")

a = Analysis(
    ['digidice_app.py'],
    pathex=[],
    binaries=[],
    datas=[(TKDND_PATH, 'tkinterdnd2/tkdnd'), ('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DigiDice Updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
