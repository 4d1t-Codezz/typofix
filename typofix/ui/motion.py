"""Animation primitives for Tk: easing, color blending, tweens and a shared frame clock."""

import math
import time
import tkinter as tk


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


_mix_cache = {}


def mix(a, b, t):
    """Blend two #rrggbb colors; t=0 gives a, t=1 gives b."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    key = (a, b, round(t * 255))
    out = _mix_cache.get(key)
    if out is None:
        ra, rb = _rgb(a), _rgb(b)
        f = key[2] / 255
        out = "#%02x%02x%02x" % tuple(round(x + (y - x) * f) for x, y in zip(ra, rb))
        if len(_mix_cache) > 20000:
            _mix_cache.clear()
        _mix_cache[key] = out
    return out


def clamp01(t):
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_back(t):
    """Overshoots a little, then settles."""
    c = 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def ease_elastic(t):
    if t in (0, 1):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi) / 3) + 1


def linear(t):
    return t


FRAME_MS = 16


class Tweens:
    """One-shot animations. A new tween on a key replaces the running one."""

    def __init__(self, widget):
        self.widget, self.jobs = widget, {}

    def run(self, key, ms, step, ease=ease_out, done=None, delay=0):
        self.cancel(key)

        def begin():
            start = time.perf_counter()

            def frame():
                t = min((time.perf_counter() - start) * 1000 / ms, 1.0) if ms > 0 else 1.0
                try:
                    step(ease(t))
                except tk.TclError:
                    self.jobs.pop(key, None)
                    return
                if t < 1:
                    self.jobs[key] = self.widget.after(FRAME_MS, frame)
                else:
                    self.jobs.pop(key, None)
                    if done:
                        done()

            frame()

        if delay:
            self.jobs[key] = self.widget.after(delay, begin)
        else:
            begin()

    def cancel(self, key):
        job = self.jobs.pop(key, None)
        if job:
            try:
                self.widget.after_cancel(job)
            except tk.TclError:
                pass


class Ticker:
    """A single shared frame clock for looping animations, so they all move in step."""

    def __init__(self, root):
        self.root, self.subs, self.job = root, {}, None

    def add(self, key, fn):
        self.subs[key] = fn
        if self.job is None:
            self.job = self.root.after(FRAME_MS, self._tick)

    def remove(self, key):
        self.subs.pop(key, None)

    def has(self, key):
        return key in self.subs

    def _tick(self):
        now = time.perf_counter()
        for key, fn in list(self.subs.items()):
            try:
                fn(now)
            except tk.TclError:
                self.subs.pop(key, None)
        # Schedule relative to frame budget so slow frames don't pile up.
        spent = (time.perf_counter() - now) * 1000
        self.job = self.root.after(max(1, int(FRAME_MS - spent)), self._tick) if self.subs else None


_tickers = {}


def ticker(widget):
    root = widget._root()
    t = _tickers.get(id(root))
    if t is None:
        t = _tickers[id(root)] = Ticker(root)
    return t


class Value:
    """A number that eases toward targets and calls redraw as it goes."""

    def __init__(self, tweens, key, redraw, value=0.0):
        self.tweens, self.key, self.redraw, self.v = tweens, key, redraw, value
        self.target = value

    def to(self, target, ms=160, ease=ease_out, done=None):
        start = self.v
        self.target = target
        if start == target:
            return

        def step(t):
            self.v = start + (target - start) * t
            self.redraw()

        self.tweens.run(self.key, ms, step, ease=ease, done=done)


class ColorState:
    """Named colors that fade to new targets, calling redraw every frame."""

    def __init__(self, tweens, key, redraw, **colors):
        self.tweens, self.key, self.redraw, self.colors = tweens, key, redraw, dict(colors)

    def __getitem__(self, name):
        return self.colors[name]

    def fade(self, ms=140, **targets):
        start = dict(self.colors)
        if all(start.get(k) == v for k, v in targets.items()):
            return

        def step(t):
            for k, v in targets.items():
                self.colors[k] = mix(start.get(k, v), v, t)
            self.redraw()

        self.tweens.run(self.key, ms, step)


def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def partial_path(points, frac):
    """The first `frac` of a polyline, for strokes that draw themselves."""
    segs = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    left = sum(segs) * clamp01(frac)
    out = [points[0]]
    for i, seg in enumerate(segs):
        if left >= seg:
            out.append(points[i + 1])
            left -= seg
        else:
            f = left / seg if seg else 0
            a, b = points[i], points[i + 1]
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            break
    if len(out) == 1:
        out.append(out[0])
    return [xy for p in out for xy in p]
