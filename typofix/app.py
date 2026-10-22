"""The Typofix window: an on/off switch, recent fixes, and the words it should leave alone.

The real work happens in the keyboard hook's thread; it reports fixes here through a queue.
Closing the window only hides it, so fixes keep happening; open Typofix again to bring it back.
"""

import json
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .platforms import get_backend
from .speller import Speller
from .tracker import Tracker

if sys.platform == "win32":
    CONFIG = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Typofix")
else:
    CONFIG = os.path.expanduser("~/Library/Application Support/Typofix")
SETTINGS = os.path.join(CONFIG, "settings.json")
PORT_FILE = os.path.join(CONFIG, "instance.port")

GREEN, AMBER, GREY = "#34c759", "#ff9f0a", "#8e8e93"


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
        self.settings = load_settings()
        self.events = queue.Queue()
        self.speller = Speller(self.settings.get("user_words", []))
        self.tracker = Tracker(self.speller,
                               on_fix=lambda fix: self.events.put(("fix", fix)),
                               on_learn=lambda word: self.events.put(("learn", word)))
        self.tracker.enabled = self.settings.get("enabled", True)
        self.hook = None
        listen_for_show(self.events)

        self.root = tk.Tk()
        self.root.title("Typofix")
        self.root.minsize(360, 0)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        if self.backend.name == "macos":
            self.root.createcommand("::tk::mac::ReopenApplication", self.show)
            self.root.createcommand("::tk::mac::Quit", self.quit)

        if not self.settings.get("setup_done"):
            # First run: open at login by default, since autocorrect is only useful when it's on.
            self.settings["setup_done"] = True
            if self.backend.app_path():
                self.backend.set_login_item(True)
            self._save()
        self.login_var.set(self.backend.login_item())

        if background and not self.backend.permission_problem(prompt=False):
            self.root.withdraw()
        self.try_start(prompt=True)
        self.root.after(100, self._poll)

    # -- layout
    def _build(self):
        font = self.backend.ui_font
        pad = ttk.Frame(self.root, padding=(20, 18, 20, 16))
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="Typofix", font=(font, 22, "bold")).pack(anchor="w")
        ttk.Label(pad, text="Fixes typos as you type, in any app.", foreground=GREY).pack(anchor="w")

        status = ttk.Frame(pad)
        status.pack(fill="x", pady=(14, 4))
        self.dot = tk.Canvas(status, width=12, height=12, highlightthickness=0, bd=0)
        self.dot.pack(side="left", padx=(0, 8))
        self.dot_id = self.dot.create_oval(1, 1, 11, 11, fill=GREY, outline="")
        self.status = ttk.Label(status, text="Starting…", wraplength=300, justify="left")
        self.status.pack(side="left", fill="x", expand=True)

        buttons = ttk.Frame(pad)
        buttons.pack(fill="x", pady=(4, 12))
        self.toggle_btn = ttk.Button(buttons, text="Pause", command=self.toggle)
        self.toggle_btn.pack(side="left")
        self.settings_btn = ttk.Button(buttons, text="Open System Settings",
                                       command=self.backend.open_permission_settings)

        fixes = ttk.LabelFrame(pad, text="Recent fixes", padding=8)
        fixes.pack(fill="both", expand=True)
        self.fix_list = tk.Listbox(fixes, height=6, activestyle="none", borderwidth=0, highlightthickness=0)
        self.fix_list.pack(fill="both", expand=True)
        ttk.Label(fixes, text="Didn't want a fix? Press backspace right after it. Typofix puts your "
                              "word back and won't change it again.",
                  foreground=GREY, wraplength=300, justify="left").pack(anchor="w", pady=(6, 0))

        words = ttk.LabelFrame(pad, text="Words Typofix leaves alone", padding=8)
        words.pack(fill="both", expand=True, pady=(12, 0))
        self.word_list = tk.Listbox(words, height=5, activestyle="none", borderwidth=0, highlightthickness=0)
        self.word_list.pack(fill="both", expand=True)
        for w in sorted(self.speller.user_words):
            self.word_list.insert("end", w)
        row = ttk.Frame(words)
        row.pack(fill="x", pady=(6, 0))
        self.word_entry = ttk.Entry(row)
        self.word_entry.pack(side="left", fill="x", expand=True)
        self.word_entry.bind("<Return>", lambda e: self.add_word())
        ttk.Button(row, text="Add", command=self.add_word).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Remove", command=self.remove_word).pack(side="left", padx=(6, 0))

        self.login_var = tk.BooleanVar()
        ttk.Checkbutton(pad, text="Open Typofix when I log in", variable=self.login_var,
                        command=self.set_login).pack(anchor="w", pady=(12, 0))

        bottom = ttk.Frame(pad)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="Quit Typofix", command=self.quit).pack(side="right")
        ttk.Button(bottom, text="Hide", command=self.hide).pack(side="right", padx=(0, 6))

    # -- state
    def _save(self):
        self.settings["enabled"] = self.tracker.enabled
        self.settings["user_words"] = sorted(self.speller.user_words)
        save_settings(self.settings)

    def _set_status(self, text, color):
        self.status.config(text=text)
        self.dot.itemconfig(self.dot_id, fill=color)

    def _refresh(self):
        if not self.hook:
            return
        if self.tracker.enabled:
            self._set_status("On. Fixing typos in every app.", GREEN)
            self.toggle_btn.config(text="Pause")
        else:
            self._set_status("Paused. Your typing is left as is.", GREY)
            self.toggle_btn.config(text="Turn on")

    def try_start(self, prompt=False):
        if self.hook:
            return
        problem = self.backend.permission_problem(prompt=prompt)
        if problem:
            self._set_status(problem, AMBER)
            self.settings_btn.pack(side="left", padx=(6, 0))
            self.toggle_btn.config(state="disabled")
            if prompt:
                self.show()
            self.root.after(1500, self.try_start)  # starts by itself once access is granted
            return
        hook = self.backend.KeyHook(self.tracker)
        if not hook.start():
            self._set_status("Typofix couldn't watch the keyboard. Quit and open it again.", AMBER)
            return
        self.hook = hook
        self.settings_btn.pack_forget()
        self.toggle_btn.config(state="normal")
        self._refresh()

    def toggle(self):
        self.tracker.enabled = not self.tracker.enabled
        self._save()
        self._refresh()

    def add_word(self):
        word = self.word_entry.get().strip().lower()
        if word and " " not in word and word not in self.speller.user_words:
            self.speller.learn(word)
            self.word_list.insert("end", word)
            self._save()
        self.word_entry.delete(0, "end")

    def remove_word(self):
        for i in reversed(self.word_list.curselection()):
            self.speller.forget(self.word_list.get(i))
            self.word_list.delete(i)
        self._save()

    def set_login(self):
        if not self.backend.set_login_item(self.login_var.get()):
            self.login_var.set(False)
            messagebox.showinfo("Typofix", "Install Typofix first (see the README), then turn this on.")

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "fix":
                    self.fix_list.insert(0, f"{value.before}  →  {value.after}")
                    self.fix_list.delete(30, "end")
                elif kind == "learn":
                    if value.lower() not in self.word_list.get(0, "end"):
                        self.word_list.insert("end", value.lower())
                    if self.fix_list.size():
                        self.fix_list.delete(0)
                    self._save()
                elif kind == "show":
                    self.show()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # -- window
    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        if not self.settings.get("hide_explained"):
            self.settings["hide_explained"] = True
            self._save()
            where = "click Typofix in the Dock" if self.backend.name == "macos" else "open Typofix from the Start menu"
            messagebox.showinfo("Typofix", f"Typofix keeps fixing typos in the background.\n\n"
                                           f"To see this window again, {where}.")
        self.root.withdraw()

    def quit(self):
        if self.hook:
            self.hook.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if ask_running_copy_to_show():
        return
    App(background="--background" in sys.argv).run()
