"""Canvas-drawn controls with hover, press and state animations (from Docs Typer), plus the
switch, fix list and word chips Typofix adds.

Every widget leaves margin inside its canvas for halos and overshoot, so nothing
gets clipped at the edges.
"""

import math
import time
import tkinter as tk
import tkinter.font as tkfont

from . import theme as T
from .motion import (ColorState, Tweens, Value, clamp01, ease_back, ease_in_out, ease_out, mix, partial_path,
                     rounded_rect, ticker)

C = T.C


class Button(tk.Canvas):
    """Rounded button: glowing halo and lifted label on hover, press dip, click flash, breathing."""

    KINDS = {  # fill, hover fill, text, border
        "primary": ("accent", "accent_hover", "ink", "accent"),
        "danger": ("danger", "danger_hover", "#FFFFFF", "danger"),
        "secondary": ("raised", "raised_hover", "text", "border"),
    }

    def __init__(self, parent, text, command, kind="secondary", scale=1.0, min_text="", icon=None):
        super().__init__(parent, highlightthickness=0, bd=0, bg=parent["bg"], cursor="hand2")
        self.command, self.kind, self.text, self.s, self.icon = command, kind, text, scale, icon
        self.m = 8 * scale  # room for the halo
        self.font = tkfont.Font(family=T.FONT, size=10, weight="bold" if kind != "secondary" else "normal")
        self.min_w = self.font.measure(min_text)
        self.enabled, self.hover, self.breathing, self.breath = True, False, False, 0.0
        self.tweens = Tweens(self)
        self.colors = ColorState(self.tweens, "color", self._draw, **self._target())
        self.glow = Value(self.tweens, "glow", self._draw)
        self.press = Value(self.tweens, "press", self._draw)
        self.flash = Value(self.tweens, "flash", self._draw)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._down)
        self.bind("<ButtonRelease-1>", self._up)
        T.on_accent(lambda: (self.colors.colors.update(self._target()), self._draw()))
        self._draw()

    def _target(self):
        fill, hover, fg, border = (C.get(c, c) for c in self.KINDS[self.kind])
        if not self.enabled:
            return {"fill": C["disabled_fill"], "fg": C["disabled_text"], "border": C["disabled_fill"],
                    "halo": C["bg"]}
        halo = C["accent"] if self.kind == "secondary" else fill
        if self.hover:
            fill = hover
            if self.kind == "secondary":
                border = C["border_hover"]
        return {"fill": fill, "fg": fg, "border": border if self.kind == "secondary" else fill, "halo": halo}

    def _set_hover(self, value):
        self.hover = value
        self.colors.fade(**self._target())
        self.glow.to(1.0 if value and self.enabled else 0.0, ms=220)

    def _down(self, _event):
        if self.enabled:
            self.press.to(1.0, ms=80)

    def _up(self, event):
        self.press.to(0.0, ms=280, ease=ease_back)
        if self.enabled and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.flash.v = 1.0
            self.flash.to(0.0, ms=380)
            self.command()

    def set(self, text=None, kind=None, enabled=None, breathing=None):
        changed = False
        if text is not None and text != self.text:
            self.text, changed = text, True
        if kind is not None and kind != self.kind:
            self.kind = kind
            self.font.configure(weight="bold" if kind != "secondary" else "normal")
        if enabled is not None and enabled != self.enabled:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
            if not enabled:
                self.glow.to(0.0)
        if breathing is not None and breathing != self.breathing:
            self.breathing = breathing
            key = f"breathe{id(self)}"
            if breathing:
                t0 = time.perf_counter()

                def breathe(now):
                    self.breath = 0.5 - 0.5 * math.cos((now - t0) * 2.6)
                    self._draw()

                ticker(self).add(key, breathe)
            else:
                ticker(self).remove(key)
                start = self.breath
                self.tweens.run("breath", 300, lambda t: (setattr(self, "breath", start * (1 - t)), self._draw()))
        self.colors.fade(ms=260, **self._target())
        if changed:
            self._draw()

    def _draw(self):
        s, m = self.s, self.m
        bw = max(self.font.measure(self.text), self.min_w) + 40 * s
        bh = self.font.metrics("linespace") + 18 * s
        W, H = int(bw + 2 * m), int(bh + 2 * m)
        if getattr(self, "_size", None) != (W, H):
            self._size = (W, H)
            self.configure(width=W, height=H)
        self.delete("all")
        r = 9 * s
        glow = max(self.glow.v, 0.75 * self.breath if self.enabled else 0)
        if glow > 0.01:
            strength = 0.55 if self.kind == "secondary" else 1.0
            for grow, alpha in ((7, 0.10), (4.5, 0.18), (2.2, 0.30)):
                o = grow * s * glow
                rounded_rect(self, m - o, m - o, m + bw + o, m + bh + o, r + o, outline="",
                             fill=mix(C["bg"], self.colors["halo"], alpha * glow * strength))
        inset = self.press.v * 1.8 * s
        fill = mix(self.colors["fill"], "#FFFFFF", 0.28 * self.flash.v)
        rounded_rect(self, m + inset, m + inset, m + bw - inset, m + bh - inset, r,
                     fill=fill, outline=self.colors["border"])
        lift = self.glow.v * 1.2 * s - self.press.v * 0.8 * s
        self.create_text(m + bw / 2, m + bh / 2 - lift, text=self.text, fill=self.colors["fg"], font=self.font)


class Check(tk.Frame):
    """Checkbox with a hover halo, a fill-and-draw tick, and a ripple when toggled."""

    def __init__(self, parent, text, variable, command=None, scale=1.0):
        super().__init__(parent, bg=parent["bg"], cursor="hand2")
        self.var, self.command, self.s = variable, command, scale
        self.tweens = Tweens(self)
        self.value = Value(self.tweens, "value", self._draw, 1.0 if variable.get() else 0.0)
        self.hover = Value(self.tweens, "hover", self._draw)
        self.ripple = Value(self.tweens, "ripple", self._draw, 1.0)
        self.n, self.m = int(17 * scale), int(10 * scale)
        size = self.n + 2 * self.m
        self.box = tk.Canvas(self, width=size, height=size, highlightthickness=0, bd=0, bg=parent["bg"])
        self.box.pack(side="left")
        self.label = tk.Label(self, text=text, bg=parent["bg"], fg=C["text"], font=(T.FONT, 10))
        self.label.pack(side="left")
        for w in (self, self.box, self.label):
            w.bind("<Button-1>", self._toggle)
            w.bind("<Enter>", lambda e: self._set_hover(True))
            w.bind("<Leave>", lambda e: self._set_hover(False))
        T.on_accent(self._draw)
        self._draw()

    def _set_hover(self, value):
        self.hover.to(1.0 if value else 0.0, ms=180)
        self.label.configure(fg=mix(C["text"], "#FFFFFF", 0.6) if value else C["text"])

    def _toggle(self, _event):
        self.var.set(not self.var.get())
        self.value.to(1.0 if self.var.get() else 0.0, ms=260, ease=ease_in_out)
        self.ripple.v = 0.0
        self.ripple.to(1.0, ms=520)
        if self.command:
            self.command()

    def _draw(self):
        c, n, m, s = self.box, self.n, self.m, self.s
        v, h, rp = self.value.v, self.hover.v, self.ripple.v
        c.delete("all")
        cx = cy = m + n / 2
        if h > 0.01:
            rad = n * 0.5 + 5 * s * h
            c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, outline="",
                          fill=mix(C["bg"], C["accent"], 0.16 * h))
        if rp < 1:
            rad = n * 0.45 + (m - 1) * ease_out(rp)
            c.create_oval(cx - rad, cy - rad, cx + rad, cy + rad, width=max(1, int(2 * s * (1 - rp))),
                          outline=mix(C["accent"], C["bg"], rp))
        squash = math.sin(v * math.pi) * 1.5 * s  # the box squashes a little mid-toggle
        fill = mix(C["field"], C["accent"], v)
        outline = mix(mix(C["border_hover"], C["accent"], h), C["accent"], v)
        rounded_rect(c, m + 1 + squash, m + 1 + squash, m + n - 2 - squash, m + n - 2 - squash, 4.5 * s,
                     fill=fill, outline=outline)
        if v > 0.05:
            pts = [(m + n * 0.26, m + n * 0.52), (m + n * 0.44, m + n * 0.70), (m + n * 0.76, m + n * 0.33)]
            c.create_line(*partial_path(pts, v), fill=C["ink"], width=max(2, int(2.2 * s)),
                          capstyle="round", joinstyle="round")



class Segmented(tk.Canvas):
    """A pill of options with an indicator that slides between them."""

    def __init__(self, parent, options, value, command, scale=1.0):
        self.s, self.options, self.command = scale, options, command
        self.font = tkfont.Font(family=T.FONT, size=9, weight="bold")
        self.seg_w = max(self.font.measure(o) for o in options) + 26 * scale
        self.m = 4 * scale
        w = int(self.seg_w * len(options) + 2 * self.m)
        h = int(30 * scale)
        super().__init__(parent, width=w, height=h, highlightthickness=0, bd=0, bg=parent["bg"], cursor="hand2")
        self.w, self.h = w, h
        self.index = options.index(value)
        self.tweens = Tweens(self)
        self.pos = Value(self.tweens, "pos", self._draw, float(self.index))
        self.hover_i = None
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._hover(None))
        T.on_accent(self._draw)
        self._draw()

    def _at(self, x):
        return int(min(max((x - self.m) // self.seg_w, 0), len(self.options) - 1))

    def _motion(self, e):
        self._hover(self._at(e.x))

    def _hover(self, i):
        if i != self.hover_i:
            self.hover_i = i
            self._draw()

    def _click(self, e):
        i = self._at(e.x)
        if i != self.index:
            self.index = i
            self.pos.to(float(i), ms=320, ease=ease_back)
            self.command(self.options[i])

    def _draw(self):
        self.delete("all")
        s, m, sw = self.s, self.m, self.seg_w
        rounded_rect(self, 0, 0, self.w, self.h, self.h / 2, fill=C["field"], outline=C["border"])
        x = m + self.pos.v * sw
        rounded_rect(self, x, m, x + sw, self.h - m, (self.h - 2 * m) / 2, fill=C["accent"], outline=C["accent"])
        for i, opt in enumerate(self.options):
            cx = m + (i + 0.5) * sw
            near = clamp01(1 - abs(self.pos.v - i))
            base = C["text"] if self.hover_i == i else C["muted"]
            self.create_text(cx, self.h / 2, text=opt, font=self.font, fill=mix(base, C["ink"], near))



class Switch(tk.Canvas):
    """An on/off switch: the knob slides with a little overshoot and the track fills with accent."""

    def __init__(self, parent, value, command, scale=1.0):
        self.s, self.command, self.on = scale, command, value
        self.m = 6 * scale
        self.tw, self.th = 52 * scale, 30 * scale
        super().__init__(parent, width=int(self.tw + 2 * self.m), height=int(self.th + 2 * self.m),
                         highlightthickness=0, bd=0, bg=parent["bg"], cursor="hand2")
        self.tweens = Tweens(self)
        self.pos = Value(self.tweens, "pos", self._draw, 1.0 if value else 0.0)
        self.hover = Value(self.tweens, "hover", self._draw)
        self.press = Value(self.tweens, "press", self._draw)
        self.enabled = True
        self.bind("<Enter>", lambda e: self.hover.to(1.0 if self.enabled else 0.0, ms=180))
        self.bind("<Leave>", lambda e: self.hover.to(0.0, ms=220))
        self.bind("<ButtonPress-1>", lambda e: self.enabled and self.press.to(1.0, ms=90))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _click(self, _event):
        self.press.to(0.0, ms=240)
        if self.enabled:
            self.set(not self.on)
            self.command(self.on)

    def set(self, on, enabled=None):
        if enabled is not None and enabled != self.enabled:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        if on != self.on:
            self.on = on
            self.pos.to(1.0 if on else 0.0, ms=320, ease=ease_back)
        self._draw()

    def _draw(self):
        self.delete("all")
        s, m, w, h = self.s, self.m, self.tw, self.th
        v, hv, pr = clamp01(self.pos.v), self.hover.v, self.press.v
        if hv > 0.01:
            for grow, alpha in ((5, 0.10), (2.5, 0.2)):
                o = grow * s * hv
                rounded_rect(self, m - o, m - o, m + w + o, m + h + o, h / 2 + o, outline="",
                             fill=mix(C["bg"], C["accent"], alpha * hv))
        on_color = C["accent"] if self.enabled else C["disabled_fill"]
        track = mix(C["track"], on_color, v)
        rounded_rect(self, m, m, m + w, m + h, h / 2, fill=track, outline=mix(C["border_hover"], on_color, v))
        r = h / 2 - 3 * s
        stretch = pr * 5 * s  # the knob widens while pressed, like iOS
        cx = m + h / 2 + (w - h - stretch) * self.pos.v
        knob = mix(C["muted"], "#FFFFFF", v) if self.enabled else C["disabled_text"]
        rounded_rect(self, cx - r, m + h / 2 - r, cx + r + stretch, m + h / 2 + r, r, fill=knob, outline="")


class FixList(tk.Canvas):
    """The latest fixes, newest on top. Hovering one offers to keep the word as you typed it."""

    ROWS = 5

    def __init__(self, parent, width, on_keep, scale=1.0):
        self.s, self.on_keep, self.w = scale, on_keep, int(width)
        self.row_h = int(34 * scale)
        super().__init__(parent, width=self.w, height=self.row_h * self.ROWS, highlightthickness=0, bd=0,
                         bg=parent["bg"])
        self.items, self.hover_i = [], None
        self.font = tkfont.Font(family=T.FONT, size=11)
        self.strike = tkfont.Font(family=T.FONT, size=11, overstrike=1)
        self.bold = tkfont.Font(family=T.FONT, size=11, weight="bold")
        self.small = tkfont.Font(family=T.FONT, size=9, weight="bold")
        self.tweens = Tweens(self)
        self.slide = Value(self.tweens, "slide", self._draw)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._hover(None))
        self.bind("<Button-1>", self._click)
        self._draw()

    def add(self, before, after):
        self.items.insert(0, (before, after))
        del self.items[self.ROWS:]
        self.slide.v = 1.0
        self.slide.to(0.0, ms=380, ease=ease_out)

    def drop_first(self):
        if self.items:
            self.items.pop(0)
            self._draw()

    def _at(self, y):
        i = int(y // self.row_h)
        return i if 0 <= i < len(self.items) else None

    def _motion(self, e):
        self._hover(self._at(e.y))

    def _hover(self, i):
        if i != self.hover_i:
            self.hover_i = i
            self.configure(cursor="hand2" if i is not None else "")
            self._draw()

    def _click(self, e):
        i = self._at(e.y)
        if i is not None:
            self.on_keep(self.items[i][0])

    def _draw(self):
        self.delete("all")
        s, rh = self.s, self.row_h
        if not self.items:
            self.create_text(self.w / 2, rh * self.ROWS / 2 - 8 * s, text="No fixes yet.",
                             fill=C["muted"], font=self.bold)
            self.create_text(self.w / 2, rh * self.ROWS / 2 + 12 * s, text="Typos you make will show up here.",
                             fill=C["faint"], font=self.font)
            return
        for i, (before, after) in enumerate(self.items):
            y = (i - self.slide.v) * rh  # every row slides down one place; the newest comes in from above
            fade = self.slide.v if i == 0 else 0.0
            if self.hover_i == i:
                rounded_rect(self, 2 * s, y + 2 * s, self.w - 2 * s, y + rh - 2 * s, 8 * s,
                             fill=C["raised_hover"], outline="")
            cy = y + rh / 2
            x = 12 * s
            self.create_text(x, cy, text=before, anchor="w", font=self.strike, fill=mix(C["faint"], C["bg"], fade))
            x += self.strike.measure(before) + 10 * s
            self.create_text(x, cy, text="→", anchor="w", font=self.font, fill=mix(C["accent"], C["bg"], fade))
            x += self.font.measure("→") + 10 * s
            self.create_text(x, cy, text=after, anchor="w", font=self.bold, fill=mix(C["text"], C["bg"], fade))
            if self.hover_i == i:
                self.create_text(self.w - 12 * s, cy, text=f"Keep “{before}”", anchor="e", font=self.small,
                                 fill=C["accent"])
            elif i < len(self.items) - 1:
                self.create_line(12 * s, y + rh, self.w - 12 * s, y + rh, fill=C["border"])


class Chips(tk.Canvas):
    """Words as removable pills that wrap onto new lines."""

    def __init__(self, parent, width, on_remove, scale=1.0):
        self.s, self.on_remove, self.w = scale, on_remove, int(width)
        super().__init__(parent, width=self.w, height=int(40 * scale), highlightthickness=0, bd=0,
                         bg=parent["bg"])
        self.words, self.boxes, self.hover_x = [], [], None
        self.font = tkfont.Font(family=T.FONT, size=10)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._click)

    def set(self, words):
        self.words = sorted(words)
        self._draw()

    def _hit(self, x, y):
        for word, (x1, y1, x2, y2) in self.boxes:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return word
        return None

    def _set_hover(self, word):
        if word != self.hover_x:
            self.hover_x = word
            self.configure(cursor="hand2" if word else "")
            self._draw()

    def _motion(self, e):
        self._set_hover(self._hit(e.x, e.y))

    def _click(self, e):
        word = self._hit(e.x, e.y)
        if word:
            self.on_remove(word)

    def _draw(self):
        self.delete("all")
        s = self.s
        ph, gap = 28 * s, 6 * s
        x = y = 2 * s
        self.boxes = []
        if not self.words:
            self.create_text(4 * s, y + ph / 2, anchor="w", fill=C["faint"], font=self.font,
                             text="Nothing yet. Add names, slang or words from class.")
        for word in self.words:
            w = self.font.measure(word) + 40 * s
            if x + w > self.w - 2 * s and x > 2 * s:
                x, y = 2 * s, y + ph + gap
            hover = self.hover_x == word
            rounded_rect(self, x, y, x + w, y + ph, ph / 2, fill=C["raised_hover"] if hover else C["raised"],
                         outline=C["danger"] if hover else C["border"])
            self.create_text(x + 12 * s, y + ph / 2, text=word, anchor="w", fill=C["text"], font=self.font)
            self.create_text(x + w - 13 * s, y + ph / 2, text="×", fill=C["danger"] if hover else C["muted"],
                             font=self.font)
            self.boxes.append((word, (x, y, x + w, y + ph)))
            x += w + gap
        height = int(y + ph + 2 * s)
        if int(self["height"]) != height:
            self.configure(height=height)
