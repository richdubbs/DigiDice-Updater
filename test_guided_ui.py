"""Exercise UI behavior against temporary drives; never writes to real devices."""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
import digidice_app as gui
import digidice_image
import digidice_update


class GuidedUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.discovery = patch.object(gui.digidice_drive, "list_removable_drives", return_value=[])
        cls.host = patch.object(digidice_update, "base_url", return_value="")
        cls.discovery.start()
        cls.host.start()
        cls.app = gui.App()
        cls.app.root.withdraw()
        cls.app.root.report_callback_exception = lambda *args: cls.callback_errors.append(args)
        cls.callback_errors = []
        cls.drain()

    @classmethod
    def drain(cls, minimum=.25):
        deadline = time.monotonic() + 5
        until = time.monotonic() + minimum
        while cls.app.busy or time.monotonic() < until:
            cls.app.root.update()
            if time.monotonic() > deadline:
                raise AssertionError("UI job did not finish")
            time.sleep(.005)
        cls.app.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.close()
        cls.host.stop()
        cls.discovery.stop()
        if cls.callback_errors:
            raise AssertionError(cls.callback_errors)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.drive = self.base / "card"
        self.drive.mkdir()
        a = self.app
        a.drive_map = {"Test DigiDice": str(self.drive)}
        a.drive_var.set("Test DigiDice")
        a.host = ""
        a.app_release = a.fw_release = a.remote_token = a.package = None
        a.completed_drive = None
        a.checked = False
        a.pending = []
        a.source = "file"
        a.render_previews()
        self.drain()

    def image(self, name, color="blue"):
        path = self.base / name
        Image.new("RGB", (650, 350), color).save(path)
        return str(path)

    def package(self):
        enc = self.base / "app.bin.enc"
        # A structurally valid sealed container is sufficient to test copying.
        enc.write_bytes(struct.pack("<I", 17) + bytes(range(16)) + b"x"*32)
        token = "0123456789abcdef0123456789abcdef"
        (self.base / "app.ver").write_text(token + "\n", encoding="ascii")
        return enc, token

    def test_file_update_and_repeat_confirmation(self):
        enc, token = self.package()
        a = self.app
        a.load_package(str(enc))
        self.drain()
        self.assertTrue(a.update_btn.enabled)
        a.update_btn.invoke()
        self.drain()
        self.assertEqual((self.drive / "app.bin.enc").read_bytes(), enc.read_bytes())
        self.assertEqual((self.drive / "app.ver").read_text().strip(), token)
        self.assertEqual(a.update_steps.active, 2)
        with patch.object(gui.messagebox, "askyesno", return_value=False) as question:
            a.update_device()
            question.assert_called_once()
        self.assertFalse(a.busy)

    def test_invalid_package_clears_previous_choice(self):
        enc, _ = self.package()
        a = self.app
        a.load_package(str(enc))
        self.drain()
        enc.write_bytes(b"broken")
        a.load_package(str(enc))
        self.drain()
        self.assertIsNone(a.package)
        self.assertFalse(a.update_btn.enabled)
        self.assertTrue(a.log_open)
        self.assertIn("could not be loaded", a.file_state.cget("text"))

    def test_preview_matches_upload_crop_and_duplicates_are_skipped(self):
        path = self.image("art.png")
        with Image.open(path) as img:
            expected = digidice_image.resize_token(img)
            expected.thumbnail((108, 150), Image.Resampling.LANCZOS)
        bad = self.base / "bad.png"
        bad.write_text("not an image")
        self.app.add_images([path, path, str(bad)])
        self.drain()
        self.assertEqual(len(self.app.pending), 1)
        self.assertIsNone(ImageChops.difference(self.app.pending[0].preview, expected).getbbox())
        self.assertEqual(len(self.app.preview_refs), 1)
        self.assertTrue(self.app.upload_btn.enabled)
        self.assertIn("1 skipped", self.app.status.cget("text"))

    def test_batch_upload_collisions_and_retry_retains_failure(self):
        first, second, lost = self.image("same.png"), self.image("same.jpg", "red"), self.image("lost.png")
        a = self.app
        a.add_images([first, second, lost])
        self.drain()
        os.remove(lost)
        a.upload_tokens()
        self.drain()
        self.assertEqual(sorted(p.name for p in (self.drive / "Tokens").iterdir()), ["same.jpg", "same_2.jpg"])
        for name in ("same.jpg", "same_2.jpg"):
            with Image.open(self.drive / "Tokens" / name) as img:
                self.assertEqual(img.size, (488, 681))
        self.assertEqual([p.path for p in a.pending], [lost])
        self.assertIn("Uploaded 2 of 3", a.status.cget("text"))
        self.image("lost.png")
        a.upload_tokens()
        self.drain()
        self.assertEqual(a.pending, [])
        self.assertFalse(a.upload_btn.enabled)

    def test_busy_blocks_competing_operations_but_allows_navigation(self):
        a = self.app
        gate = threading.Event()
        try:
            a.run_job("Test operation", lambda: gate.wait(3), lambda result: None)
            self.assertFalse(a.run_job("Second operation", lambda: None, lambda r: None))
            self.assertFalse(a.browse_images_btn.enabled)
            self.assertEqual(str(a.drive_combo.cget("state")), "disabled")
            a.show_screen(1)
            self.assertEqual(a.screens.active, 1)
            a.add_images([self.image("ignored.png")])
            self.assertEqual(a.pending, [])
        finally:
            gate.set()
            self.drain()
        self.assertTrue(a.browse_images_btn.enabled)

    def test_online_check_copy_and_card_comparison(self):
        enc, token = self.package()
        release = digidice_update.Release("2.0.0", "https://example.test/app.bin.enc", md5=hashlib.md5(enc.read_bytes()).hexdigest(), ver_url="https://example.test/app.ver", notes="Test release notes")
        a = self.app
        a.host = "https://example.test"
        with patch.object(digidice_update, "fetch_manifest", return_value=(None, release)), patch.object(digidice_update, "_get", return_value=(token+"\n").encode()):
            a.check_updates()
            self.drain()
        self.assertEqual(a.remote_token, token)
        self.assertTrue(a.notes_btn.enabled)
        a.select_source("online")
        def download(url, destination, **kwargs):
            data = enc.read_bytes() if url.endswith(".enc") else (token+"\n").encode()
            Path(destination).write_bytes(data)
            if kwargs.get("progress"):
                kwargs["progress"](len(data), len(data))
            return destination
        with patch.object(digidice_update, "cache_dir", return_value=str(self.base)), patch.object(digidice_update, "download", side_effect=download):
            a.update_device()
            self.drain()
        self.assertEqual((self.drive / "app.bin.enc").read_bytes(), enc.read_bytes())
        self.assertIn("already on the card", a.firmware_state.cget("text"))

    def test_online_failure_recovers_and_manual_still_works(self):
        a = self.app
        a.host = "https://example.test"
        with patch.object(digidice_update, "fetch_manifest", side_effect=digidice_update.UpdateError("offline")):
            a.check_updates()
            self.drain()
        self.assertFalse(a.busy)
        self.assertTrue(a.check_btn.enabled)
        self.assertTrue(a.browse_update.enabled)
        self.assertIsNone(a.fw_release)

    def test_app_update_downloads_then_restarts(self):
        a = self.app
        a.app_release = digidice_update.Release("9.0.0", "https://example.test/app.exe")
        with patch.object(digidice_update, "is_frozen", return_value=True), patch.object(gui.messagebox, "askokcancel", return_value=True), patch.object(digidice_update, "staged_exe_path", return_value=str(self.base / "app.exe")), patch.object(digidice_update, "download") as download, patch.object(digidice_update, "apply_app_update") as apply, patch.object(a, "close") as close:
            a.update_app()
            self.drain()
            download.assert_called_once()
            apply.assert_called_once_with(str(self.base / "app.exe"))
            close.assert_called_once()

    def test_fast_navigation_and_button_keyboard_disabled_states(self):
        a = self.app
        for i in range(15):
            a.show_screen(i % 2)
        a.show_screen(1)
        self.drain()
        self.assertEqual(a.screens.active, 1)
        self.assertEqual(int(a.tokens_page.place_info()["x"]), 0)
        calls = []
        button = gui.Button(a.root, "Test", lambda: calls.append(1))
        try:
            button._key_press(None)
            button._key_press(None)
            button._key_release(None)
            self.assertEqual(calls, [1])
            button.set_enabled(False)
            button._key_press(None)
            button._key_release(None)
            button.invoke()
            self.assertEqual(calls, [1])
            button.set_enabled(True)
            button._hover(True)
            self.drain()
            self.assertNotEqual(button._fill, button.color)
        finally:
            button.destroy()

    def test_missing_drive_disables_writes_and_offline_is_clear(self):
        a = self.app
        a.drive_var.set("")
        self.drain()
        self.assertFalse(a.update_btn.enabled)
        self.assertFalse(a.upload_btn.enabled)
        self.assertFalse(a.check_btn.enabled)
        self.assertIn("aren't available", a.firmware_state.cget("text"))
        self.assertEqual(a.update_steps.active, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
