"""Guided DigiDice updates and token uploads. Workers never call Tk.

This application only copies pre-sealed firmware. It carries no encryption key;
the device installs the copied firmware after ejecting and restarting.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ctypes
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import digidice_drive
import digidice_image
import digidice_package
import digidice_update
from digidice_ui import (BG, PANEL, BORDER, TEXT, MUTED, LIME, CYAN, ORANGE,
                         BLUE, PURPLE, RED, Button, Screens, Smoke, StatusBar, label, theme)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

APP_TITLE = "DigiDice Updater"
APP_VERSION = "1.6.0"
UPDATE_PATH = "MENU > SETTINGS > UPDATE"
UPDATE_STEPS = f"open {UPDATE_PATH} and tap RESTART"   # the device asks before rebooting
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
PREVIEW_SIZE = (90, 124)  # largest token thumbnail on the Tokens screen
PREVIEW_PLACEHOLDER = "Your selected images will appear here,\ncropped as they will be on your device."
FINISH_TEXT = "Copied successfully. Eject the drive in Windows, then restart your DigiDice."


@dataclass
class TokenImage:
    path: str
    preview: Image.Image


def prepare_images(paths, existing):
    """Read previews off the UI thread, matching the uploaded image crop."""
    seen = {os.path.normcase(os.path.abspath(p)) for p in existing}
    added, errors = [], []
    for raw in paths:
        path = os.path.abspath(os.path.normpath(str(raw)))
        key = os.path.normcase(path)
        if key in seen:
            continue
        try:
            if Path(path).suffix.lower() not in IMAGE_EXTS:
                raise ValueError("not a supported image")
            with Image.open(path) as source:
                preview = digidice_image.resize_token(source)
                preview.thumbnail(PREVIEW_SIZE, Image.Resampling.LANCZOS)
            added.append(TokenImage(path, preview))
            seen.add(key)
        except Exception as exc:
            errors.append(f"{os.path.basename(path)}: {exc}")
    return added, errors


def token_destination(folder, source, taken):
    stem = Path(source).stem
    name, number = stem + ".jpg", 2
    while name.lower() in taken:
        name = f"{stem}_{number}.jpg"
        number += 1
    taken.add(name.lower())
    return os.path.join(folder, name)


def upload_images(batch, drive, report):
    """Continue after a failed image; report successes for selective removal."""
    folder = digidice_drive.ensure_tokens_folder(drive)
    taken, succeeded, errors = set(), [], []
    for index, item in enumerate(batch, 1):
        report(index-1, len(batch), f"Uploading {index} of {len(batch)}: {Path(item.path).name}")
        try:
            destination = token_destination(folder, item.path, taken)
            digidice_image.resize_token_file(item.path, destination)
            succeeded.append(item.path)
        except Exception as exc:
            errors.append(f"{Path(item.path).name}: {exc}")
        report(index, len(batch), None)
    return succeeded, errors


class App:
    def __init__(self):
        if os.name == "nt":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (AttributeError, OSError):
                pass
        digidice_update.cleanup_previous_exe()
        self.root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
        self.root.title(APP_TITLE)
        theme(self.root)
        self.root.geometry(f"760x{min(440, self.root.winfo_screenheight()-100)}")
        self.root.minsize(700, 420)
        self.events = queue.SimpleQueue()
        self.busy = self.closed = False
        self._pump_id = self._drive_job = None
        self._poll_id = None
        self._scan_running = False
        self.online_busy = ""
        self.online_error = ""
        self._buttons = []
        self.drive_map = {}
        self.drive_var = tk.StringVar(self.root)
        self.package = None
        self.package_path = ""
        self.app_release = self.fw_release = self.remote_token = None
        self.source_status = None
        self.source_check_error = ""
        self.checked = False
        self.completed_drive = None
        self.pending = []
        self.preview_refs = []
        self.log_open = False
        self.log_lines = []
        try:
            self.host = digidice_update.base_url()
        except digidice_update.UpdateError as exc:
            self.host = ""
            self.log_lines.append(str(exc))
        self._build()
        for line in list(self.log_lines):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.configure(state="disabled")
        self.drive_var.trace_add("write", self._schedule_drive_changed)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<MouseWheel>", self._wheel, add="+")
        self.root.bind("<Control-1>", lambda e: self.show_screen(0))
        self.root.bind("<Control-2>", lambda e: self.show_screen(1))
        self.show_screen(0)
        self.refresh_drives()
        self._poll_id = self.root.after(2000, self._poll_drives)
        self._pump()

    def button(self, parent, text, command, **kwargs):
        button = Button(parent, text, command, **kwargs)
        self._buttons.append(button)
        return button

    def _build(self):
        sidebar = tk.Frame(self.root, bg=PANEL, width=168)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(self.root, bg=BORDER, width=1).pack(side="left", fill="y")
        brand = tk.Frame(sidebar, bg="#000000", height=44)
        brand.pack(fill="x")
        brand.pack_propagate(False)
        self._logo(brand)
        self.nav_updates = Button(sidebar, "↑   Updates", lambda: self.show_screen(0),
                                  navigation=True, height=44, size=11)
        self.nav_updates.pack(fill="x", pady=(4, 0))
        self.nav_tokens = Button(sidebar, "▧   Tokens", lambda: self.show_screen(1),
                                 navigation=True, height=44, size=11)
        self.nav_tokens.pack(fill="x")
        self.nav_options = Button(sidebar, "More options", lambda: self.show_screen(2),
                                  navigation=True, height=40, size=10)
        self.nav_options.pack(side="bottom", fill="x", pady=(0, 10))
        tk.Frame(sidebar, bg=BORDER, height=1).pack(side="bottom", fill="x", padx=18, pady=6)
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(side="left", fill="both", expand=True)
        self.smoke = Smoke(self.root)
        self.status_bar = StatusBar(shell, self.smoke)
        self.status_bar.pack(side="bottom", fill="x")
        self.progress, self.status = self.status_bar.progress, self.status_bar.status
        self.screens = Screens(shell, self.smoke)
        self.screens.pack(fill="both", expand=True)
        self.updates_page = self.screens.add()
        self.tokens_page = self.screens.add()
        self.options_page = self.screens.add()
        self._build_updates(self.updates_page)
        self._build_tokens(self.tokens_page)
        self._build_options(self.options_page)

    def _logo(self, parent):
        path = Path(__file__).parent / "assets" / "digidice-logo.png"
        try:
            with Image.open(path) as source:
                # Trim only empty asset margins at display time; retain the original.
                bounds = source.convert("L").point(lambda v: 255 if v > 45 else 0).getbbox()
                image = source.crop(bounds) if bounds else source.copy()
                image.thumbnail((156, 40), Image.Resampling.LANCZOS)
                self.logo = ImageTk.PhotoImage(image, master=self.root)
                icon = source.crop((274, 323, 518, 548))
                icon.thumbnail((32, 32), Image.Resampling.LANCZOS)
                self.app_icon = ImageTk.PhotoImage(icon, master=self.root)
                self.root.iconphoto(True, self.app_icon)
            tk.Label(parent, image=self.logo, bg=parent.cget("bg"),
                     borderwidth=0, highlightthickness=0).pack(fill="both", expand=True)
        except OSError:
            label(parent, "DigiDice", size=17, color=CYAN, bold=True).pack(side="left", padx=12)

    def _build_updates(self, page):
        main = page.card(padding=16)
        row = tk.Frame(main.body, bg=PANEL)
        row.pack(fill="x", pady=(0, 10))
        self.connection = label(row, "", size=10, color=MUTED)
        self.connection.pack(side="left")
        label(row, "  ·  ", size=10, color=BORDER).pack(side="left")
        self.firmware_state = label(row, "", size=14, bold=True)
        self.firmware_state.pack(side="left", fill="x", expand=True)
        self.update_btn = self.button(main.body, "Get the latest update", self.online_action,
                                      color=ORANGE, height=46, size=13)
        self.update_btn.pack(fill="x", pady=(0, 10))
        self.update_hint = label(main.body, "", size=10, color=MUTED, wraplength=500)
        self.update_hint.pack(fill="x")
        main.body.bind("<Configure>", lambda e: self.update_hint.configure(wraplength=max(200, e.width-4)), add="+")

    def _build_options(self, page):
        device = page.card(padding=12, gap=8)
        heading = tk.Frame(device.body, bg=PANEL)
        heading.pack(fill="x", pady=(0, 6))
        label(heading, "Device connection", bold=True, size=11).pack(side="left")
        label(heading, "Detected automatically. Pick yours if needed.", color=MUTED, size=9).pack(side="right")
        row = tk.Frame(device.body, bg=PANEL)
        row.pack(fill="x")
        self.button(row, "Connection help", self.connection_help, width=140, height=32, size=10).pack(side="right", padx=(8, 0))
        self.drive_combo = ttk.Combobox(row, textvariable=self.drive_var, width=24)
        self.drive_combo.pack(side="left", fill="x", expand=True)
        manual = page.card(padding=12, gap=8)
        heading = tk.Frame(manual.body, bg=PANEL)
        heading.pack(fill="x", pady=(0, 6))
        label(heading, "Install from a file", bold=True, size=11).pack(side="left")
        self.file_state = label(heading, "Choose app.bin.enc with its matching app.ver beside it.",
                                color=MUTED, size=9, wraplength=300)
        self.file_state.pack(side="right")
        actions = tk.Frame(manual.body, bg=PANEL)
        actions.pack(fill="x")
        self.browse_update = self.button(actions, "Choose update file…", self.choose_package, width=180, height=32, size=10)
        self.browse_update.pack(side="left")
        self.manual_update_btn = self.button(actions, "Install selected file", lambda: self.update_device("file"),
                                             width=180, height=32, size=10)
        self.manual_update_btn.pack(side="right")
        app = page.card(padding=12, gap=8)
        details = tk.Frame(app.body, bg=PANEL)
        details.pack(side="left", fill="x", expand=True)
        running_label = "Windows app" if digidice_update.is_frozen() else "Python source"
        label(details, f"{running_label} • {APP_VERSION}", bold=True, size=11).pack(fill="x")
        self.app_state = label(details, "", color=MUTED, size=9, wraplength=300)
        self.app_state.pack(fill="x", pady=(2, 0))
        self.app_update_btn = self.button(app.body, "Update & restart", self.update_app, color=PURPLE, width=160, height=34, size=10)
        self.app_update_btn.pack(side="right", padx=(12, 0))
        # On a card rather than the page: a widget's own background can't let
        # the smoke through, so nothing sits on the bare page.
        tools = page.card(padding=12, gap=0).body
        self.log_row = tk.Frame(tools, bg=PANEL)
        self.log_row.pack(fill="x")
        self.log_toggle = Button(self.log_row, "⌄   Activity log", self.toggle_log, width=150, height=32, size=10)
        self.log_toggle.pack(side="left")
        Button(self.log_row, "Support & details", self.support, width=150, height=32, size=10).pack(side="right")
        self.log_frame = tk.Frame(tools, bg=PANEL)
        self.log_text = tk.Text(self.log_frame, bg=PANEL, fg=MUTED, height=6,
                                wrap="word", state="disabled", relief="flat", font=("Consolas", 9))
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _build_tokens(self, page):
        card = page.card(padding=14, gap=0)
        top = tk.Frame(card.body, bg=PANEL)
        top.pack(fill="x", pady=(0, 8))
        self.token_connection = label(top, "", color=MUTED, size=10)
        self.token_connection.pack(side="left")
        label(top, "Fitted to your DigiDice automatically.", size=9, color=MUTED).pack(side="right")
        self.drop = tk.Frame(card.body, bg=PANEL, highlightthickness=1, highlightbackground=MUTED, pady=8)
        self.drop.pack(fill="x")
        drop_heading = tk.Frame(self.drop, bg=PANEL)
        drop_heading.pack()
        drop_icon = tk.Canvas(drop_heading, width=40, height=36, bg=PANEL, highlightthickness=0)
        drop_icon.pack(side="left", padx=(0, 8))
        drop_icon.create_rectangle(4, 3, 35, 30, outline=CYAN, width=2)
        drop_icon.create_line(7, 27, 16, 15, 23, 22, 28, 16, 33, 22, fill=CYAN, width=2)
        drop_icon.create_oval(26, 7, 30, 11, fill=CYAN, outline=CYAN)
        drop_title = label(drop_heading, "Drop images here", size=13, bold=True)
        drop_title.pack(side="left")
        drop_or = label(drop_heading, "  or  ", size=10, color=MUTED)
        drop_or.pack(side="left")
        self.browse_images_btn = self.button(drop_heading, "Browse images", self.browse_images, width=140, height=34, size=10)
        self.browse_images_btn.pack(side="left")
        if HAS_DND:
            for target in (self.drop, drop_heading, drop_icon, drop_title, drop_or, self.browse_images_btn):
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self._drop_images)
        self.preview_canvas = tk.Canvas(card.body, bg=PANEL, height=PREVIEW_SIZE[1] + 44, highlightthickness=0)
        self.preview_canvas.pack(fill="x", pady=(10, 0))
        self.preview_body = tk.Frame(self.preview_canvas, bg=PANEL)
        self.preview_canvas.create_window(0, 0, anchor="nw", window=self.preview_body)
        self.preview_body.bind("<Configure>", lambda e: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all")))
        self.preview_scroll = ttk.Scrollbar(card.body, orient="horizontal", command=self.preview_canvas.xview)
        self.preview_scroll.pack(fill="x", pady=(0, 8))
        self.preview_canvas.configure(xscrollcommand=self._preview_scrollbar)
        label(self.preview_body, PREVIEW_PLACEHOLDER, color=MUTED, size=10).pack(pady=40, padx=16)
        actions = tk.Frame(card.body, bg=PANEL)
        self.token_actions = actions
        actions.pack(fill="x")
        self.queue_label = label(actions, "No images selected", bold=True, size=11)
        self.queue_label.pack(side="left")
        self.upload_btn = self.button(actions, "↑   Upload tokens", self.upload_tokens, color=BLUE, width=200, height=38, size=11)
        self.upload_btn.pack(side="right")
        self.clear_btn = self.button(actions, "Clear", self.clear_images, color=RED, width=90, height=38, size=10)
        self.clear_btn.pack(side="right", padx=(0, 10))

    def _preview_scrollbar(self, first, last):
        self.preview_scroll.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.preview_scroll.pack_forget()
        elif not self.preview_scroll.winfo_manager():
            self.preview_scroll.pack(fill="x", pady=(0, 8), before=self.token_actions)

    def show_screen(self, index):
        self.screens.show(index)
        for i, button in enumerate((self.nav_updates, self.nav_tokens, self.nav_options)):
            button.set_selected(index == i)
        self.root.title(APP_TITLE + " — " + ("Updates", "Tokens", "More options")[index])

    def _wheel(self, event):
        if self.screens.active is not None and event.widget is not self.log_text:
            self.screens.pages[self.screens.active].scroll(-int(event.delta/120))

    def resolve_drive(self):
        raw = self.drive_var.get().strip()
        root = self.drive_map.get(raw, raw.split()[0] if raw else "")
        if len(root) == 2 and root[1] == ":":
            root += "\\"
        return root if root and os.path.isdir(root) else None

    def refresh_drives(self):
        if self.busy or self.closed or self._scan_running:
            return
        self._scan_running = True
        def work():
            try:
                drives = digidice_drive.list_removable_drives()
            except Exception as exc:
                self.post(self._drives_found, None, str(exc))
            else:
                self.post(self._drives_found, drives, "")
        threading.Thread(target=work, daemon=True).start()

    def _drives_found(self, drives, error=""):
        self._scan_running = False
        if self.busy or self.closed:
            return
        if error:
            self.log(f"Device detection: {error}")
            return
        old = self.resolve_drive()
        previous = self.drive_map
        self.drive_map = {f"{d.label or 'Drive'} • {d.letter}": d.letter for d in drives}
        self.drive_combo.configure(values=list(self.drive_map))
        selected = next((name for name, root in self.drive_map.items() if root == old), None)
        likely = [d for d in drives if d.is_likely_digidice]
        if selected:
            selection = selected
        elif old and old not in previous.values():
            selection = old  # Preserve an explicitly entered custom path.
        elif len(likely) == 1:
            selection = next(name for name, root in self.drive_map.items() if root == likely[0].letter)
        else:
            selection = ""  # Never guess between cards, or choose an unrelated USB drive.
        if self.drive_var.get() != selection:
            self.drive_var.set(selection)
        self.sync()

    def _poll_drives(self):
        self._poll_id = None
        if not self.closed:
            self.refresh_drives()
            self._poll_id = self.root.after(2000, self._poll_drives)

    def online_state(self):
        """One button owns the online check, connection wait, and installation."""
        ready = self.resolve_drive()
        hint = "After updating, eject and restart your DigiDice."
        if self.online_busy:
            title = "Checking for updates…" if self.online_busy == "check" else "Updating your DigiDice…"
            return title, title, "Please keep your DigiDice connected." if self.online_busy == "install" else "Looking for the latest release online.", "wait"
        if self.online_error:
            return "Try again", "Couldn't finish the update", self.online_error, "check"
        if ready and self.completed_drive == ready:
            return "Update copied!", "Ready to restart", hint, "check"
        if not self.host:
            return "Online updates unavailable", "Use a local update file", "Open More options to install an update file.", "unavailable"
        if not self.checked:
            return "Get the latest update", "Ready when you are", "Check online for the latest DigiDice update.", "check"
        if not self.fw_release:
            return "Check again", "No update published yet", "You can check again later.", "check"
        if not ready:
            return "Please Connect DigiDice!", "Update available", f"Connect with USB, then {UPDATE_STEPS} on your DigiDice.", "connect"
        on_card = digidice_package.card_version(ready)
        if self.remote_token and on_card == self.remote_token:
            return "Check again", "DigiDice is up to date", "The latest update is already on the card.", "check"
        return "Update DigiDice Now!", "Update available", hint, "install"

    def online_action(self):
        if self.busy:
            return
        action = self.online_state()[3]
        if action == "install":
            self.update_device("online")
        elif action == "connect":
            self.refresh_drives()
            self.connection_help()
        elif action == "check":
            self.check_updates()

    def _schedule_drive_changed(self, *_):
        if self._drive_job:
            self.root.after_cancel(self._drive_job)
        self._drive_job = self.root.after(200, self._drive_changed)

    def _drive_changed(self):
        self._drive_job = None
        self.completed_drive = None
        self.sync()

    def sync(self):
        if self.closed:
            return
        ready = self.resolve_drive()
        connection = "●  DigiDice connected" if ready else "○  DigiDice not connected"
        for widget in (self.connection, self.token_connection):
            widget.configure(text=connection, fg=LIME if ready else MUTED)
        for button in self._buttons:
            button.set_enabled(not self.busy)
        self.drive_combo.configure(state="disabled" if self.busy else "normal")
        caption, title, hint, action = self.online_state()
        self.update_btn.set_text(caption)
        self.update_btn.set_enabled(not self.busy and action not in ("wait", "unavailable"))
        self.firmware_state.configure(text=title, fg=TEXT)
        self.update_hint.configure(text=hint, fg=MUTED)
        self.manual_update_btn.set_enabled(not self.busy and bool(ready and self.package))
        self.app_update_btn.set_enabled(
            not self.busy and digidice_update.is_frozen() and bool(self.app_release)
            and digidice_update.is_newer(self.app_release.version, APP_VERSION))
        self.upload_btn.set_enabled(not self.busy and bool(ready and self.pending))
        self.clear_btn.set_enabled(not self.busy and bool(self.pending))
        count = len(self.pending)
        self.upload_btn.set_text(f"↑   Upload {count} token{'s' if count != 1 else ''}" if count else "↑   Upload tokens")
        self.queue_label.configure(text=f"{count} image{'s' if count != 1 else ''} ready" if count else "No images selected")
        app_color = MUTED
        if not self.host:
            app_text = "Online updates aren't available yet."
        elif not self.checked:
            app_text = "Use Get the latest update on the Updates screen to check."
        else:
            app_text = "No Windows app update is published yet."
            if self.app_release:
                app_text = f"Version {self.app_release.version} available" if digidice_update.is_newer(self.app_release.version, APP_VERSION) else "You're up to date."
                app_color = LIME
            if not digidice_update.is_frozen():
                if self.source_check_error:
                    app_text = "Source version couldn't be checked.\nSee the activity log."
                elif self.source_status:
                    status = self.source_status
                    if status.relation == "diverged":
                        app_text = f"Newer public source available • {status.ahead_by} commit{'s' if status.ahead_by != 1 else ''}\nThis checkout also has local commits."
                        app_color = ORANGE
                    elif status.update_available:
                        app_text = f"Newer source available • {status.ahead_by} commit{'s' if status.ahead_by != 1 else ''}"
                        app_color = ORANGE
                    elif status.relation == "behind":
                        app_text = "This source checkout is ahead of the public repository."
                        app_color = LIME
                    else:
                        app_text = "Source checkout is up to date."
                        app_color = LIME
        self.app_state.configure(text=app_text, fg=app_color)

    def set_status(self, text, error=False):
        self.status.configure(text=text, fg="#ff9a9a" if error else MUTED)

    def post(self, fn, *args):
        self.events.put((fn, args))

    def _pump(self):
        if self.closed:
            return
        for _ in range(100):
            try:
                fn, args = self.events.get_nowait()
            except queue.Empty:
                break
            if self.closed:
                break
            try:
                fn(*args)
            except Exception as exc:
                self.log(f"Interface error: {exc}")
        if not self.closed:
            self._pump_id = self.root.after(16, self._pump)

    def run_job(self, title, work, done):
        if self.busy or self.closed:
            return False
        self.busy = True
        self.set_status(title)
        self.log(title)
        self.status_bar.show_progress(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.sync()
        def worker():
            try:
                result = work()
            except Exception as exc:
                self.post(self._job_finished, done, None, exc)
            else:
                self.post(self._job_finished, done, result, None)
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _job_finished(self, done, result, error):
        self.progress.stop()
        self.status_bar.show_progress(False)
        self.busy = False
        online_job = self.online_busy
        self.online_busy = ""
        try:
            if error:
                if online_job:
                    self.online_error = "Please check your connection and try again. Details are in More options → Activity log."
                self.log(f"ERROR: {error}")
                self.set_status("That didn't finish. Check the activity log for details, then try again.", error=True)
                if not self.log_open:
                    self.toggle_log()
            else:
                done(result)
        finally:
            self.sync()

    def report(self, got, total, text=None):
        self.post(self._progress, got, total, text)

    def _progress(self, got, total, text):
        if total:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=total, value=got)
        elif str(self.progress.cget("mode")) != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        if text:
            self.set_status(text)

    def choose_package(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Choose update file (keep app.ver beside it)", filetypes=[("DigiDice update", "*.enc"), ("All files", "*.*")])
        if path:
            self.load_package(path)

    def load_package(self, path):
        if self.busy:
            return
        self.package = None
        self.package_path = ""
        self.completed_drive = None
        self.file_state.configure(text="Checking update file…", fg=MUTED)
        def done(pkg):
            self.package, self.package_path = pkg, path
            self.file_state.configure(text=f"Ready: {Path(path).name}", fg=LIME)
            self.log(f"Loaded {path}; version {pkg.ver_token}; {pkg.orig_size:,} bytes.")
            self.set_status("Update file ready. Choose Install selected file in More options.")
        def work():
            try:
                return digidice_package.load(path)
            except Exception:
                self.post(self.file_state.configure, {"text": "File could not be loaded.\nChoose another update file.", "fg": "#ff9a9a"})
                raise
        self.run_job("Checking update file…", work, done)

    def check_updates(self):
        if self.busy or not self.host:
            return
        self.app_release = self.fw_release = self.remote_token = None
        self.source_status = None
        self.source_check_error = ""
        self.checked = False
        self.completed_drive = None
        self.online_error = ""
        self.online_busy = "check"
        def work():
            app, firmware = digidice_update.fetch_manifest()
            token = None
            if firmware:
                token = digidice_update.fetch_firmware_token(firmware)
            source_status = None
            source_error = ""
            if not digidice_update.is_frozen():
                try:
                    source_status = digidice_update.fetch_source_status()
                except digidice_update.UpdateError as exc:
                    source_error = str(exc)
            return app, firmware, token, source_status, source_error
        def done(result):
            (self.app_release, self.fw_release, self.remote_token,
             self.source_status, self.source_check_error) = result
            self.checked = True
            if self.source_status:
                status = self.source_status
                self.log(
                    f"Source check: {status.local_revision[:8]} → "
                    f"{status.remote_revision[:8]} ({status.relation}; "
                    f"public +{status.ahead_by}, local +{status.behind_by}).")
            elif self.source_check_error:
                self.log(f"Source check unavailable: {self.source_check_error}")
            self.set_status("Update check complete.")
            self.log("Update check complete.")
        self.run_job("Checking device and Windows app updates…", work, done)

    def update_device(self, source="online"):
        if self.busy:
            return
        drive = self.resolve_drive()
        if not drive:
            self.connection_help()
            return
        if source == "file" and self.package:
            pkg = self.package
            token = pkg.ver_token
        elif source == "online" and self.fw_release:
            pkg = None
            token = self.remote_token
        else:
            return
        if token and digidice_package.card_version(drive) == token:
            if not messagebox.askyesno(APP_TITLE, "This card already has this update. Copy it again?", parent=self.root):
                return
        release = self.fw_release
        self.completed_drive = None
        self.online_error = ""
        if source == "online":
            self.online_busy = "install"
        def work():
            package = pkg
            if package is None:
                cache = digidice_update.cache_dir()
                enc = os.path.join(cache, "downloaded-app.bin.enc")
                ver = os.path.join(cache, "downloaded-app.ver")
                digidice_update.download(release.url, enc, sha256=release.sha256, md5=release.md5, progress=self.report)
                self.post(self.set_status, "Checking downloaded update…")
                digidice_update.download(release.ver_url, ver)
                package = digidice_package.load(enc, ver)
                # The sha256 ties app.bin.enc to the release that was checked;
                # this ties app.ver to it. Fetched separately, they straddle a
                # release published in between, and the device refuses a
                # pair whose halves come from different builds.
                if token and package.ver_token != token:
                    raise digidice_update.UpdateError(
                        "The update changed on the server while it was downloading. "
                        "Nothing was copied; check for updates again.")
            self.report(0, None, "Copying update to your DigiDice. Keep it connected…")
            digidice_package.write_to_drive(package, drive)
            return package.ver_token
        def done(token):
            self.completed_drive = drive
            self.set_status(FINISH_TEXT)
            self.log(f"Update copied to {drive}. Version token: {token}")
            self.log(FINISH_TEXT)
        self.run_job("Preparing your DigiDice update…", work, done)

    def update_app(self):
        if self.busy or not self.app_release or not digidice_update.is_newer(self.app_release.version, APP_VERSION):
            return
        if not digidice_update.is_frozen():
            self.dialog("Windows app update", "This copy is running from source. Use the packaged Windows app to install an update automatically.")
            return
        rel = self.app_release
        if not messagebox.askokcancel(APP_TITLE, f"Install Windows app {rel.version} and restart?\n\nThis window will close and the updated app will open.", parent=self.root):
            return
        def work():
            destination = digidice_update.staged_exe_path()
            digidice_update.download(rel.url, destination, sha256=rel.sha256, progress=self.report)
            self.post(self.set_status, "Restarting the Windows app…")
            digidice_update.apply_app_update(destination)
        self.run_job("Downloading the Windows app update…", work, lambda result: self.close())

    def browse_images(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(parent=self.root, title="Choose token images", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff"), ("All files", "*.*")])
        if paths:
            self.add_images(paths)

    def _drop_images(self, event):
        if self.busy:
            return "none"
        self.add_images(self.root.tk.splitlist(event.data))
        return "copy"

    def add_images(self, paths):
        if self.busy:
            return
        paths = list(paths)
        existing = [item.path for item in self.pending]
        def done(result):
            added, errors = result
            self.pending.extend(added)
            for item in added:
                self.log(f"Queued {item.path}")
            for error in errors:
                self.log("Skipped " + error)
            self.render_previews()
            suffix = f" {len(errors)} skipped; see Activity log." if errors else ""
            self.set_status(f"{len(self.pending)} images ready to upload." + suffix)
        self.run_job("Preparing image previews…", lambda: prepare_images(paths, existing), done)

    def render_previews(self):
        for child in self.preview_body.winfo_children():
            child.destroy()
        self.preview_refs = []
        if not self.pending:
            label(self.preview_body, PREVIEW_PLACEHOLDER, color=MUTED, size=10).pack(pady=40, padx=16)
        for item in self.pending:
            slot = tk.Frame(self.preview_body, bg=PANEL)
            slot.pack(side="left", anchor="n", padx=(0, 10))
            image = ImageTk.PhotoImage(item.preview, master=self.root)
            self.preview_refs.append(image)
            tk.Label(slot, image=image, bg=BG, highlightthickness=1, highlightbackground=BORDER).pack()
            name = Path(item.path).name
            display_name = name if len(name) <= 24 else name[:17] + "…" + Path(name).suffix
            label(slot, display_name, color=MUTED, size=9, wraplength=PREVIEW_SIZE[0], height=2).pack(pady=(5, 0))
        self.preview_canvas.xview_moveto(0)

    def clear_images(self):
        if self.busy:
            return
        self.pending = []
        self.render_previews()
        self.set_status("Image selection cleared.")
        self.sync()

    def upload_tokens(self):
        if self.busy or not self.pending:
            return
        drive = self.resolve_drive()
        if not drive:
            self.connection_help()
            return
        batch = list(self.pending)
        def done(result):
            succeeded, errors = result
            self.pending = [item for item in self.pending if item.path not in succeeded]
            for error in errors:
                self.log("Upload failed: " + error)
            self.render_previews()
            text = f"Uploaded {len(succeeded)} of {len(batch)} images."
            text += " Failed images remain selected; see Activity log." if errors else " Eject the drive in Windows before disconnecting."
            self.set_status(text, error=bool(errors))
            self.log(text)
        self.run_job("Uploading your token images…", lambda: upload_images(batch, drive, self.report), done)

    def log(self, text):
        self.log_lines.append(str(text))
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(text) + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def toggle_log(self):
        self.log_open = not self.log_open
        if self.log_open:
            self.log_frame.pack(fill="x", after=self.log_row, pady=(8, 0))
        else:
            self.log_frame.pack_forget()
        self.log_toggle.set_text(("⌃" if self.log_open else "⌄") + "   Activity log")

    def dialog(self, title, text):
        window = tk.Toplevel(self.root)
        window.title(title)
        window.configure(bg=BG)
        window.transient(self.root)
        window.geometry("610x420")
        window.minsize(460, 300)
        label(window, title, size=19, color=LIME, bold=True).pack(fill="x", padx=22, pady=(20, 12))
        area = tk.Text(window, bg=PANEL, fg=TEXT, wrap="word", relief="flat", font=("Segoe UI", 11), padx=14, pady=14)
        area.pack(fill="both", expand=True, padx=22)
        area.insert("1.0", text)
        area.configure(state="disabled")
        Button(window, "Close", window.destroy, color=BLUE, width=110).pack(anchor="e", padx=22, pady=16)
        window.bind("<Escape>", lambda e: window.destroy())
        window.grab_set()

    def connection_help(self):
        self.dialog("Connect your DigiDice", f"Connect your DigiDice with a USB data cable.\n\nOn the DigiDice, {UPDATE_STEPS}. This makes its SD card appear as a Windows drive.\n\nThe app checks for connected devices automatically. If more than one card is found, choose your DigiDice drive under More options.\n\nAfter an update: eject the drive in Windows, then restart the DigiDice to install it.")

    def support(self):
        try:
            host = digidice_update.base_url() or "Not configured"
        except digidice_update.UpdateError as exc:
            host = str(exc)
        self.dialog("Support & details", f"DigiDice Updater {APP_VERSION}\n\nUpdate source: {host}\n\nOn Updates, Get the latest update checks online immediately. The same orange button then installs the update once your DigiDice is connected.\n\nManual update files: app.bin.enc and its matching app.ver must be in the same folder. Use Install from a file in More options.\n\nToken images: resized and center-cropped to {digidice_image.TOKEN_W} × {digidice_image.TOKEN_H}, then saved as JPEG files in the Tokens folder. Uploading a matching filename replaces that token.\n\nDrag and drop: {'available' if HAS_DND else 'unavailable; use Browse images'}\nAnimations follow the Windows Animation effects setting.\nKeyboard: Tab to navigate, Space or Enter to activate, Ctrl+1 / Ctrl+2 to switch screens.\n\nFor troubleshooting, open More options → Activity log. Existing update_source.json and DIGIDICE_UPDATE_URL configuration are supported.")

    def close(self):
        if self.busy:
            messagebox.showinfo(APP_TITLE, "Please wait for the current operation to finish before closing.", parent=self.root)
            return
        self.closed = True
        for job in (self._pump_id, self._drive_job, self._poll_id):
            if job:
                self.root.after_cancel(job)
        self.smoke.stop()
        self.screens.destroy()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
