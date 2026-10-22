"""The full Typofix window, in Docs Typer's style: an on/off switch, recent fixes you can keep,
the words it leaves alone, and settings. The App (app.py) owns all state; this only shows it."""

import os
import tkinter as tk
import tkinter.font as tkfont

from . import theme as T
from .motion import Tweens, Value, mix
from .widgets import Button, Check, Chips, FixList, Segmented, Switch

C = T.C
DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class Card(tk.Frame):
    def __init__(self, parent, s, **kw):
        super().__init__(parent, bg=C["raised"], highlightthickness=1, highlightbackground=C["border"],
                         padx=int(14 * s), pady=int(12 * s), **kw)


class MainWindow:
    def __init__(self, root, app, scale):
        self.root, self.app, self.s = root, app, scale
        s = scale
        root.configure(bg=C["bg"])
        root.resizable(False, False)
        self.width = int(440 * s)
        inner_w = self.width - int(2 * 22 * s) - int(2 * 15 * s)

        pad = tk.Frame(root, bg=C["bg"], padx=int(22 * s), pady=int(20 * s))
        pad.pack(fill="both", expand=True)

        # Header: icon, name, the big switch.
        head = tk.Frame(pad, bg=C["bg"])
        head.pack(fill="x")
        try:
            self.icon = tk.PhotoImage(file=os.path.join(DATA, "icon.png"))
            tk.Label(head, image=self.icon, bg=C["bg"]).pack(side="left", padx=(0, int(12 * s)))
        except tk.TclError:
            pass
        names = tk.Frame(head, bg=C["bg"])
        names.pack(side="left", fill="x", expand=True)
        tk.Label(names, text="Typofix", bg=C["bg"], fg=C["text"],
                 font=(T.TITLE_FONT, 24)).pack(anchor="w")
        tk.Label(names, text="Fixes typos as you type, in every app.", bg=C["bg"], fg=C["muted"],
                 font=(T.FONT, 11)).pack(anchor="w")
        self.switch = Switch(head, app.tracker.enabled, app.set_enabled, scale=s)
        self.switch.pack(side="right")

        # Status.
        self.status = Card(pad, s)
        self.status.pack(fill="x", pady=(int(16 * s), 0))
        row = tk.Frame(self.status, bg=C["raised"])
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=int(12 * s), height=int(12 * s), bg=C["raised"], highlightthickness=0)
        self.dot.pack(side="left", padx=(0, int(10 * s)))
        self.dot_id = self.dot.create_oval(1, 1, int(11 * s), int(11 * s), fill=C["faint"], outline="")
        self.headline = tk.Label(row, bg=C["raised"], fg=C["text"], font=(T.FONT, 12, "bold"), anchor="w")
        self.headline.pack(side="left", fill="x", expand=True)
        self.detail = tk.Label(self.status, bg=C["raised"], fg=C["muted"], font=(T.FONT, 10), anchor="w",
                               justify="left", wraplength=inner_w)
        self.detail.pack(fill="x", pady=(int(4 * s), 0))
        self.settings_btn = Button(self.status, "Open System Settings", app.backend.open_permission_settings,
                                   kind="primary", scale=s)
        self.settings_btn.configure(bg=C["raised"])
        self.pulse = Value(Tweens(self.dot), "pulse", self._draw_dot)

        # Recent fixes.
        self._section(pad, "RECENT FIXES")
        card = Card(pad, s)
        card.pack(fill="x")
        self.fixes = FixList(card, inner_w, app.keep_word, scale=s)
        self.fixes.configure(bg=C["raised"])
        self.fixes.pack(fill="x")

        # Words left alone.
        self._section(pad, "WORDS IT LEAVES ALONE")
        card = Card(pad, s)
        card.pack(fill="x")
        self.chips = Chips(card, inner_w, app.remove_word, scale=s)
        self.chips.configure(bg=C["raised"])
        self.chips.pack(fill="x")
        add = tk.Frame(card, bg=C["raised"])
        add.pack(fill="x", pady=(int(8 * s), 0))
        self.entry = tk.Entry(add, bg=C["field"], fg=C["text"], insertbackground=C["text"], relief="flat",
                              font=(T.FONT, 11), highlightthickness=1, highlightbackground=C["border"],
                              highlightcolor=C["accent"])
        self.entry.pack(side="left", fill="x", expand=True, ipady=int(5 * s))
        self.entry.bind("<Return>", lambda e: self._add())
        add_btn = Button(add, "Add", self._add, scale=s)
        add_btn.configure(bg=C["raised"])
        add_btn.pack(side="left", padx=(int(4 * s), 0))

        # Settings.
        self._section(pad, "SETTINGS")
        card = Card(pad, s)
        card.pack(fill="x")
        self.preview_var = tk.BooleanVar(value=app.tracker.preview)
        self._check(card, "Show fixes before they happen", self.preview_var,
                    lambda: app.set_preview(self.preview_var.get()),
                    "A bubble by your cursor shows the fix. Esc keeps your word instead.")
        self.login_var = tk.BooleanVar(value=app.backend.login_item())
        self._check(card, "Open Typofix when I log in", self.login_var,
                    lambda: app.set_login(self.login_var.get()))
        live = tk.Frame(card, bg=C["raised"])
        live.pack(fill="x", pady=(int(8 * s), 0))
        tk.Label(live, text="Live in", bg=C["raised"], fg=C["text"], font=(T.FONT, 11)).pack(side="left")
        self.modes = ["Menu bar" if app.backend.name == "macos" else "Tray", "Window"]
        seg = Segmented(live, self.modes, self.modes[0 if app.mode == "menubar" else 1],
                        lambda label: app.set_mode("menubar" if label == self.modes[0] else "window"), scale=s)
        seg.configure(bg=C["raised"])
        seg.pack(side="right")
        self.mode_hint = tk.Label(card, bg=C["raised"], fg=C["faint"], font=(T.FONT, 9), anchor="w",
                                  justify="left", wraplength=inner_w)
        self.mode_hint.pack(fill="x", pady=(int(4 * s), 0))

        # Footer.
        foot = tk.Frame(pad, bg=C["bg"])
        foot.pack(fill="x", pady=(int(14 * s), 0))
        tk.Label(foot, text="Backspace right after a fix undoes it.", bg=C["bg"], fg=C["faint"],
                 font=(T.FONT, 9)).pack(side="left")
        Button(foot, "Quit Typofix", app.quit, scale=s).pack(side="right")

        self.refresh()

    # -- building blocks
    def _section(self, parent, text):
        tk.Label(parent, text=text, bg=C["bg"], fg=C["muted"],
                 font=tkfont.Font(family=T.FONT, size=9, weight="bold")).pack(anchor="w", pady=(int(16 * self.s), int(6 * self.s)))

    def _check(self, parent, text, var, command, hint=None):
        box = tk.Frame(parent, bg=C["raised"])
        box.pack(fill="x")
        check = Check(box, text, var, command, scale=self.s)
        for w in (check, check.box, check.label):
            w.configure(bg=C["raised"])
        check.pack(anchor="w")
        if hint:
            tk.Label(box, text=hint, bg=C["raised"], fg=C["faint"], font=(T.FONT, 9), anchor="w").pack(
                anchor="w", padx=(int(37 * self.s), 0))
        return check

    def _add(self):
        word = self.entry.get().strip().lower()
        self.entry.delete(0, "end")
        if word and " " not in word:
            self.app.add_word(word)

    def _draw_dot(self):
        color = self.dot_color
        if self.pulse.v > 0.01:
            color = mix(color, "#FFFFFF", 0.35 * self.pulse.v)
        self.dot.itemconfig(self.dot_id, fill=color)

    # -- updates from the app
    def refresh(self):
        app = self.app
        if app.problem:
            self.dot_color = C["warn"]
            self.headline.configure(text="One more step")
            self.detail.configure(text=app.problem)
            self.settings_btn.pack(anchor="w", pady=(int(8 * self.s), 0))
        elif not app.hook:
            self.dot_color = C["faint"]
            self.headline.configure(text="Starting…")
            self.detail.configure(text="")
            self.settings_btn.pack_forget()
        elif app.tracker.enabled:
            self.dot_color = C["ok"]
            self.headline.configure(text="On")
            self.detail.configure(text="Fixing typos in every app as you type.")
            self.settings_btn.pack_forget()
        else:
            self.dot_color = C["faint"]
            self.headline.configure(text="Paused")
            self.detail.configure(text="Your typing is left exactly as it is.")
            self.settings_btn.pack_forget()
        self.switch.set(app.tracker.enabled, enabled=bool(app.hook))
        self._draw_dot()
        self.chips.set(app.speller.user_words)
        where = "menu bar" if app.backend.name == "macos" else "system tray"
        if app.mode == "menubar":
            self.mode_hint.configure(text=f"Typofix sits in the {where}. Click its icon for quick controls "
                                          f"and this window.")
        else:
            self.mode_hint.configure(text="Typofix shows this window when it opens"
                                          + (" and stays in the Dock." if app.backend.name == "macos" else "."))

    def added_fix(self, fix):
        self.fixes.add(fix.before, fix.after)
        self.pulse.v = 1.0
        self.pulse.to(0.0, ms=600)

    def undid_fix(self):
        self.fixes.drop_first()
