# Building digidice_app.py into a standalone .exe

1. Install Python 3.10+ on Windows (from python.org — check "Add to PATH").
2. Open a terminal in this `windows_app` folder and run:

   ```
   pip install -r requirements.txt pyinstaller
   ```

3. Run it directly first to make sure everything works before packaging:

   ```
   python digidice_app.py
   ```

4. Build using the checked-in specification. It bundles the drag-and-drop
   runtime and the DigiDice logo in `assets/`:

   ```
   pyinstaller --noconfirm "DigiDice Updater.spec"
   ```

   The finished executable will be in `dist\DigiDice Updater.exe`. That single
   file is all you need to copy/share — it has no external Python
   dependency once built.

5. If this build is going on the release host, bump `APP_VERSION` in
   `digidice_app.py` **before** step 4 and publish the matching
   `version.json` afterwards — see `release_host.md`. The Updates tab
   compares the host's version against that constant and nothing else, so a
   new .exe carrying the old number will never be offered to anyone.

Notes:
- The guided UI has two screens: Updates and Tokens. Both manual and online
  device updates live in Updates, alongside a separate Windows app update row.
- Screen transitions take 120 ms; button hover transitions take 90 ms. Presses
  respond immediately. Windows' Animation effects preference is respected.
- Run `python -m unittest test_guided_ui -v` before packaging. It uses
  temporary drives and simulated downloads; it does not update a physical
  DigiDice. (The full pipeline also has a maintainer-side integration test
  that seals a real image with the private repo's key and confirms this app
  copies it byte-for-byte — not included here since it needs that key.)
- `--windowed` suppresses the console window (this is a GUI app).
- If `tkinterdnd2` isn't installed at all (not even for the `python
  digidice_app.py` run), drag-and-drop on the Tokens tab is disabled
  automatically and a "Browse image..." button is used instead — everything
  else still works. This is different from the `--add-data` issue above,
  which only bites once you package it.
- If Windows SmartScreen flags the freshly-built .exe (common for unsigned,
  freshly-built binaries), click "More info" → "Run anyway". Code-signing it
  is out of scope here but possible later if this becomes annoying.
