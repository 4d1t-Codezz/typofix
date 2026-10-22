"""Runs Typofix: the keyboard hook, the preview bubble, and the two ways to see it, a menu bar
(or tray) icon with quick controls, or the full window. Settings live in a small JSON file.

The real work happens in the keyboard hook's thread; it reports fixes and previews here through
a queue, and everything on screen is updated from Tk's thread.
"""

import json
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from .platforms import get_backend
from .speller import Speller
from .tracker import Tracker
from .ui import theme as T
from .ui.window import MainWindow

if sys.platform == "win32":
    CONFIG = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Typofix")
else:
    CONFIG = os.path.expanduser("~/Library/Application Support/Typofix")
SETTINGS = os.path.join(CONFIG, "settings.json")
PORT_FILE = os.path.join(CONFIG, "instance.port")
DATA = os.path.join(os.path.dirname(__file__), "data")


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    os.makedirs(CONFIG, exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SETTINGS)


def ask_running_copy_to_show():
    """If Typofix is already running, tell it to show its window and return True."""
    try:
        with open(PORT_FILE, encoding="utf-8") as f:
            port = int(f.read().strip())
        with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
            s.sendall(b"show")
            return s.recv(2) == b"ok"
    except (OSError, ValueError):
        return False


def listen_for_show(events):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    os.makedirs(CONFIG, exist_ok=True)
    with open(PORT_FILE, "w", encoding="utf-8") as f:
        f.write(str(server.getsockname()[1]))

    def serve():
        while True:
            conn, _ = server.accept()
            with conn:
                if conn.recv(16) == b"show":
                    conn.sendall(b"ok")
                    events.put(("show", None))

    threading.Thread(target=serve, daemon=True, name="instance").start()


class App:
    def __init__(self, background=False):
        self.backend = get_backend()
        self.backend.setup_process()
        self.settings = load_settings()
        first_run = not self.settings.get("setup_done")
        self.mode = self.settings.get("mode", "menubar")
        self.events = queue.Queue()
        self.recent = []  # (before, after), newest first, for the tray menu
        self.speller = Speller(self.settings.get("user_words", []))
        self.tracker = Tracker(self.speller,
                               on_fix=lambda fix: self.events.put(("fix", fix)),
                               on_learn=lambda word: self.events.put(("learn", word)),
                               on_preview=lambda typed, fixed: self.events.put(("preview", (typed, fixed))),
                               char_before=self.backend.char_before)
        self.tracker.enabled = self.settings.get("enabled", True)
        self.tracker.preview = self.settings.get("preview", True)
        self.hook, self.problem, self.tray, self.bubble = None, None, None, None
        listen_for_show(self.events)

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Typofix")
        T.configure_fonts(self.backend)
        self.backend.style_window(self.root, T.C["bg"])
        self.window = MainWindow(self.root, self, self.backend.scale(self.root))
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        if self.backend.name == "macos":
            self.root.createcommand("::tk::mac::ReopenApplication", self.show)
            self.root.createcommand("::tk::mac::Quit", self.quit)
        try:
            self.bubble = self.backend.Bubble(self.root, T.C)
        except Exception:  # noqa: BLE001 - fixing typos matters more than the preview
            import traceback
            traceback.print_exc()
        self._apply_mode()

        if first_run:
            # Open at login by default, since autocorrect is only useful when it's running.
            self.settings["setup_done"] = True
            if self.backend.app_path():
                self.backend.set_login_item(True)
            self._save()
        self.window.login_var.set(self.backend.login_item())

        self.try_start(prompt=True)
        if first_run or self.problem or (self.mode == "window" and not background):
            self.show()
        self.root.after(25, self._poll)

    # -- state
    def _save(self):
        self.settings.update(enabled=self.tracker.enabled, preview=self.tracker.preview, mode=self.mode,
                             user_words=sorted(self.speller.user_words))
        save_settings(self.settings)

    def _refresh(self):
        self.window.refresh()
        if self.tray:
            self.tray.set_paused(not self.tracker.enabled)

    def try_start(self, prompt=False):
        if self.hook:
            return
        self.problem = self.backend.permission_problem(prompt=prompt)
        if not self.problem:
            hook = self.backend.KeyHook(self.tracker)
            if hook.start():
                self.hook = hook
            else:
                self.problem = "Typofix couldn't watch the keyboard. Quit it and open it again."
        self._refresh()
        if not self.hook:
            self.root.after(1500, self.try_start)  # starts by itself once access is granted

    def set_enabled(self, on):
        self.tracker.enabled = on
        if not on:
            self._hide_bubble()
        self._save()
        self._refresh()

    def set_preview(self, on):
        self.tracker.preview = on
        self.window.preview_var.set(on)
        if not on:
            self._hide_bubble()
        self._save()

    def set_mode(self, mode):
        self.mode = mode
        self._apply_mode()
        self._save()
        self._refresh()

    def _apply_mode(self):
        """Menu bar mode: just an icon up top (no Dock icon). Window mode: a normal app."""
        menubar = self.mode == "menubar"
        self.backend.set_dock_icon(not menubar)
        if menubar and not self.tray:
            try:
                self.tray = self.backend.TrayIcon(self.root, self._tray_items, os.path.join(DATA, "menubar.png"),
                                                  on_double_click=self.show)
            except Exception:  # noqa: BLE001 - without a tray icon, fall back to the window
                import traceback
                traceback.print_exc()
                self.mode = "window"
                self.backend.set_dock_icon(True)
        elif not menubar and self.tray:
            self.tray.remove()
            self.tray = None
        if self.root.state() == "normal":
            self.backend.activate()

    def keep_word(self, word):
        """Stop fixing this word from now on (it doesn't undo a fix that already happened)."""
        self.speller.learn(word)
        self._save()
        self._refresh()

    def add_word(self, word):
        self.speller.learn(word)
        self._save()
        self._refresh()

    def remove_word(self, word):
        self.speller.forget(word)
        self._save()
        self._refresh()

    def set_login(self, on):
        if not self.backend.set_login_item(on):
            self.window.login_var.set(False)
            messagebox.showinfo("Typofix", "Install Typofix first (see the README), then turn this on.")

    # -- the menu bar / tray menu
    def _tray_items(self):
        on = self.tracker.enabled
        if self.problem:
            status = "Typofix needs permission"
        else:
            status = "Typofix is on" if on else "Typofix is paused"
        recent = [{"title": f"{before}  →  {after}", "action": (lambda b=before: self.keep_word(b))}
                  for before, after in self.recent[:8]]
        recent = ([{"title": "Click a fix to stop making it"}] + recent) if recent else [{"title": "No fixes yet"}]
        return [
            {"title": status},
            {"title": "Pause" if on else "Turn on", "action": lambda: self.set_enabled(not on)},
            {"title": "Show fixes before they happen", "checked": self.tracker.preview,
             "action": lambda: self.set_preview(not self.tracker.preview)},
            None,
            {"title": "Recent fixes", "submenu": recent},
            None,
            {"title": "Open Typofix…", "action": self.show},
            {"title": "Quit Typofix", "action": self.quit},
        ]

    # -- the preview bubble
    def _show_bubble(self, typed, fixed):
        if not self.bubble:
            return
        try:
            self.bubble.show(typed, fixed, self.backend.caret_rect())
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()

    def _hide_bubble(self):
        if self.bubble:
            self.bubble.hide()

    def _poll(self):
        preview = None
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "fix":
                    self.recent.insert(0, (value.before, value.after))
                    del self.recent[20:]
                    self.window.added_fix(value)
                elif kind == "learn":
                    if self.recent:
                        self.recent.pop(0)
                    self.window.undid_fix()
                    self._save()
                    self._refresh()
                elif kind == "preview":
                    preview = value  # only the latest matters
                elif kind == "show":
                    self.show()
        except queue.Empty:
            pass
        if preview is not None:
            if preview[1]:
                self._show_bubble(*preview)
            else:
                self._hide_bubble()
        self.root.after(25, self._poll)

    # -- window
    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.backend.activate()
        self.root.focus_force()

    def hide(self):
        if not self.settings.get("hide_explained"):
            self.settings["hide_explained"] = True
            self._save()
            if self.mode == "menubar":
                where = f"click its icon in the {self.backend.tray_name}"
            elif self.backend.name == "macos":
                where = "click Typofix in the Dock"
            else:
                where = "open Typofix from the Start menu"
            messagebox.showinfo("Typofix", f"Typofix keeps fixing typos in the background.\n\n"
                                           f"To see this window again, {where}.")
        self.root.withdraw()

    def quit(self):
        if self.hook:
            self.hook.stop()
        self._hide_bubble()
        if self.tray:
            self.tray.remove()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if ask_running_copy_to_show():
        return
    App(background="--background" in sys.argv).run()
