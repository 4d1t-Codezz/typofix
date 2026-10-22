"""macOS: a Quartz event tap that sees every key (and can swallow one), and CGEventPost to type.

Only ctypes and system frameworks. The tap is an active one (not listen-only) so it can drop the
space that triggers a fix and send the corrected word in its place; that needs Accessibility
access, which also lets us ask the focused app where its text cursor is (for the preview bubble).
Password fields turn on Secure Input, which hides their keys from every tap, so passwords are
never seen or touched.
"""

import ctypes
import os
import subprocess
import threading

from . import mac_objc as oc
from .mac_objc import CGRect, CGPoint, CGSize, send

_cg = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
_cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

MAGIC = 0x7F0F1C5  # tags our own synthetic events so the tap lets them through untouched
kCGEventSourceUserData = 42
kCGKeyboardEventKeycode = 9
kCGHIDEventTap = 0
kCGSessionEventTap = 1
kCGHeadInsertEventTap = 0
kCGEventTapOptionDefault = 0
kCGEventSourceStatePrivate = -1

FLAG_CONTROL, FLAG_OPTION, FLAG_COMMAND = 0x40000, 0x80000, 0x100000
KEY_DOWN = 10
MOUSE_DOWN = (1, 3, 25)
TAP_DISABLED = (0xFFFFFFFE, 0xFFFFFFFF)

KC_SPACE, KC_DELETE, KC_ESCAPE = 49, 51, 53
KC_NEW_LINE = (36, 76)  # return, keypad enter
KC_TAB = 48
# Keys that move the cursor somewhere we can't follow: arrows, home/end, page up/down,
# forward delete, and F1-F12.
KC_MOVES = {123, 124, 125, 126, 115, 119, 116, 121, 117,
            122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111}

TAPCALLBACK = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)

_cg.CGEventSourceCreate.argtypes = [ctypes.c_int32]
_cg.CGEventSourceCreate.restype = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
_cg.CGEventCreateCopy.argtypes = [ctypes.c_void_p]
_cg.CGEventCreateCopy.restype = ctypes.c_void_p
_cg.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
_cg.CGEventKeyboardGetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                                ctypes.POINTER(ctypes.c_uint16)]
_cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
_cg.CGEventGetFlags.argtypes = [ctypes.c_void_p]
_cg.CGEventGetFlags.restype = ctypes.c_uint64
_cg.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64]
_cg.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
_cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cg.CGEventTapCreate.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64,
                                 TAPCALLBACK, ctypes.c_void_p]
_cg.CGEventTapCreate.restype = ctypes.c_void_p
_cg.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
_cg.AXIsProcessTrusted.restype = ctypes.c_bool
_cg.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
_cg.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool

_cf.CFRelease.argtypes = [ctypes.c_void_p]
_cf.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
_cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
_cf.CFMachPortInvalidate.argtypes = [ctypes.c_void_p]
_cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
_cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_cf.CFRunLoopRun.restype = None
_cf.CFRunLoopStop.argtypes = [ctypes.c_void_p]
_cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
_cf.CFDictionaryCreate.restype = ctypes.c_void_p
kCFRunLoopCommonModes = ctypes.c_void_p.in_dll(_cf, "kCFRunLoopCommonModes").value
kCFBooleanTrue = ctypes.c_void_p.in_dll(_cf, "kCFBooleanTrue").value
kAXTrustedCheckOptionPrompt = ctypes.c_void_p.in_dll(_cg, "kAXTrustedCheckOptionPrompt").value

_source = _cg.CGEventSourceCreate(kCGEventSourceStatePrivate)


def _post_key(keycode, text=None):
    for down in (True, False):
        ev = _cg.CGEventCreateKeyboardEvent(_source, keycode, down)
        if text is not None:
            units = text.encode("utf-16-le")
            arr = (ctypes.c_uint16 * (len(units) // 2)).from_buffer_copy(units)
            _cg.CGEventKeyboardSetUnicodeString(ev, len(arr), arr)
        _cg.CGEventSetFlags(ev, 0)  # ignore whatever modifier the user is still holding
        _cg.CGEventSetIntegerValueField(ev, kCGEventSourceUserData, MAGIC)
        _cg.CGEventPost(kCGHIDEventTap, ev)
        _cf.CFRelease(ev)


def apply_fix(fix):
    for _ in range(fix.delete):
        _post_key(KC_DELETE)
    for ch in fix.insert:
        _post_key(KC_SPACE if ch == " " else 0, ch)


def _repost(event):
    """Sends a copy of a key we swallowed, after the fix (keeps its modifiers, e.g. shift+Return)."""
    ev = _cg.CGEventCreateCopy(event)
    _cg.CGEventSetIntegerValueField(ev, kCGEventSourceUserData, MAGIC)
    _cg.CGEventPost(kCGHIDEventTap, ev)
    _cf.CFRelease(ev)


def _typed_text(event):
    buf = (ctypes.c_uint16 * 8)()
    n = ctypes.c_ulong(0)
    _cg.CGEventKeyboardGetUnicodeString(event, 8, ctypes.byref(n), buf)
    return bytes(buf)[:n.value * 2].decode("utf-16-le", errors="ignore")


# ---------------------------------------------------------------------------
# Accessibility: where the text cursor is, and what's just before it
# ---------------------------------------------------------------------------

class CFRange(ctypes.Structure):
    _fields_ = [("location", ctypes.c_long), ("length", ctypes.c_long)]


_cg.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
_cg.AXUIElementSetMessagingTimeout.argtypes = [ctypes.c_void_p, ctypes.c_float]
_cg.AXUIElementCopyAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_cg.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
_cg.AXUIElementCopyParameterizedAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                                           ctypes.POINTER(ctypes.c_void_p)]
_cg.AXUIElementCopyParameterizedAttributeValue.restype = ctypes.c_int32
_cg.AXValueCreate.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
_cg.AXValueCreate.restype = ctypes.c_void_p
_cg.AXValueGetValue.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
_cg.AXValueGetValue.restype = ctypes.c_bool
_cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
_cf.CFStringCreateWithCString.restype = ctypes.c_void_p
_cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
_cf.CFStringGetLength.restype = ctypes.c_long
_cf.CFStringGetCharacters.argtypes = [ctypes.c_void_p, CFRange, ctypes.POINTER(ctypes.c_uint16)]
AX_CGRECT, AX_CFRANGE = 3, 4
_names = {n: _cf.CFStringCreateWithCString(None, n.encode(), 0x08000100) for n in
          ("AXFocusedUIElement", "AXSelectedTextRange", "AXBoundsForRange", "AXStringForRange")}


def _copy(element, attr, param=None):
    out = ctypes.c_void_p()
    if param is None:
        err = _cg.AXUIElementCopyAttributeValue(element, _names[attr], ctypes.byref(out))
    else:
        err = _cg.AXUIElementCopyParameterizedAttributeValue(element, _names[attr], param, ctypes.byref(out))
    return out.value if err == 0 else None


def _with_cursor(fn):
    """Calls fn(element, CFRange of the selection) for the focused text field; None if unavailable."""
    system = _cg.AXUIElementCreateSystemWide()
    _cg.AXUIElementSetMessagingTimeout(system, 0.1)
    try:
        element = _copy(system, "AXFocusedUIElement")
        if not element:
            return None
        try:
            value = _copy(element, "AXSelectedTextRange")
            if not value:
                return None
            selected = CFRange()
            ok = _cg.AXValueGetValue(value, AX_CFRANGE, ctypes.byref(selected))
            _cf.CFRelease(value)
            return fn(element, selected) if ok else None
        finally:
            _cf.CFRelease(element)
    finally:
        _cf.CFRelease(system)


def _ranged(element, attr, location, length, kind=None):
    rng = CFRange(location, length)
    param = _cg.AXValueCreate(AX_CFRANGE, ctypes.byref(rng))
    try:
        value = _copy(element, attr, param)
    finally:
        _cf.CFRelease(param)
    if not value:
        return None
    try:
        if kind == "rect":
            rect = CGRect()
            return rect if _cg.AXValueGetValue(value, AX_CGRECT, ctypes.byref(rect)) else None
        n = _cf.CFStringGetLength(value)
        buf = (ctypes.c_uint16 * max(n, 1))()
        _cf.CFStringGetCharacters(value, CFRange(0, n), buf)
        return bytes(buf)[:n * 2].decode("utf-16-le", errors="ignore")
    finally:
        _cf.CFRelease(value)


def char_before(typed):
    """The character in the focused field just before the last `typed` characters, "" if they
    start the field, or None if the app won't say."""
    def look(element, sel):
        if sel.length:
            return None
        i = sel.location - typed - 1
        return "" if i < 0 else _ranged(element, "AXStringForRange", i, 1)
    try:
        return _with_cursor(look)
    except OSError:
        return None


def caret_rect():
    """(x, y, width, height) of the text cursor, in screen points from the top-left, or None."""
    def look(element, sel):
        start = sel.location + sel.length
        rect = _ranged(element, "AXBoundsForRange", max(start - 1, 0), 1 if start else 0, "rect")
        if rect is None or rect.size.height <= 0 or (rect.origin.x == 0 and rect.origin.y == 0):
            return None
        return rect.origin.x + (rect.size.width if start else 0), rect.origin.y, 1, rect.size.height
    try:
        return _with_cursor(look)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# The keyboard hook
# ---------------------------------------------------------------------------

class KeyHook:
    """Feeds the tracker from a session-wide event tap on its own thread."""

    def __init__(self, tracker):
        self.tracker = tracker
        self.loop = None
        self.tap = None

    def start(self):
        """Returns True once the tap is running, False if macOS refused (no Accessibility access)."""
        ok = []
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready, ok), daemon=True, name="key-hook").start()
        ready.wait(3)
        return bool(ok)

    def stop(self):
        if self.tap:
            _cg.CGEventTapEnable(self.tap, False)
        if self.loop:
            _cf.CFRunLoopStop(self.loop)
        self.loop = None

    def _on_key(self, event):
        """Returns False to swallow the key."""
        t = self.tracker
        flags = _cg.CGEventGetFlags(event)
        code = _cg.CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if flags & (FLAG_COMMAND | FLAG_CONTROL | FLAG_OPTION):
            t.reset(start_known=False)  # a shortcut (paste, undo, switch app...)
            return True
        if code == KC_DELETE:
            fix = t.backspace()
        elif code in KC_NEW_LINE:
            fix = t.char("\n")
            if fix:
                apply_fix(fix)
                _repost(event)  # then the Return itself, so a chat message sends already fixed
                return False
            return True
        elif code == KC_ESCAPE:
            if t.escape():
                return False  # it closed the preview; don't also close the app's popup or dialog
            t.reset(start_known=False)
            return True
        elif code == KC_TAB:
            t.reset(start_known=True)
            return True
        elif code in KC_MOVES:
            t.reset(start_known=False)
            return True
        else:
            text = _typed_text(event)
            if len(text) != 1 or not text.isprintable():
                return True
            fix = t.char(text)
        if fix:
            apply_fix(fix)
            return False
        return True

    def _run(self, ready, ok):
        def callback(proxy, etype, event, user):
            try:
                if etype in TAP_DISABLED:  # macOS turns slow taps off; turn it back on
                    if self.tap:
                        _cg.CGEventTapEnable(self.tap, True)
                elif _cg.CGEventGetIntegerValueField(event, kCGEventSourceUserData) == MAGIC:
                    pass
                elif etype == KEY_DOWN:
                    if not self._on_key(event):
                        return None
                elif etype in MOUSE_DOWN:
                    self.tracker.reset(start_known=False)
            except Exception:  # noqa: BLE001 - never let a bug eat the user's keystrokes
                import traceback
                traceback.print_exc()
            return event

        self._callback = TAPCALLBACK(callback)  # keep a reference for the tap's lifetime
        mask = 1 << KEY_DOWN
        for t in MOUSE_DOWN:
            mask |= 1 << t
        tap = _cg.CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
                                   mask, self._callback, None)
        if not tap:
            ready.set()
            return
        self.tap = tap
        src = _cf.CFMachPortCreateRunLoopSource(None, tap, 0)
        self.loop = _cf.CFRunLoopGetCurrent()
        _cf.CFRunLoopAddSource(self.loop, src, kCFRunLoopCommonModes)
        _cg.CGEventTapEnable(tap, True)
        ok.append(True)
        ready.set()
        _cf.CFRunLoopRun()
        _cf.CFMachPortInvalidate(tap)
        _cf.CFRelease(src)
        _cf.CFRelease(tap)
        self.tap = None


# ---------------------------------------------------------------------------
# The preview bubble: a native panel, because a Tk window would take focus from the app you're
# typing in. A non-activating panel floats above everything without ever becoming active.
# ---------------------------------------------------------------------------

def _label(size, weight, hex_color):
    label = send(ctypes.c_void_p, oc.cls("NSTextField"), "labelWithString:", oc.nsstring(""),
                 argtypes=(ctypes.c_void_p,))
    font = send(ctypes.c_void_p, oc.cls("NSFont"), "systemFontOfSize:weight:", size, weight,
                argtypes=(ctypes.c_double, ctypes.c_double))
    send(None, label, "setFont:", font, argtypes=(ctypes.c_void_p,))
    send(None, label, "setTextColor:", oc.color(hex_color), argtypes=(ctypes.c_void_p,))
    return label


class Bubble:
    def __init__(self, root, colors):
        v = ctypes.c_void_p
        panel = send(v, send(v, oc.cls("NSPanel"), "alloc"), "initWithContentRect:styleMask:backing:defer:",
                     CGRect(CGPoint(0, 0), CGSize(10, 10)), 1 << 7, 2, False,  # borderless, non-activating
                     argtypes=(CGRect, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool))
        send(None, panel, "setLevel:", 101, argtypes=(ctypes.c_long,))  # above other apps' windows
        send(None, panel, "setOpaque:", False, argtypes=(ctypes.c_bool,))
        send(None, panel, "setBackgroundColor:", send(v, oc.cls("NSColor"), "clearColor"), argtypes=(v,))
        send(None, panel, "setHasShadow:", True, argtypes=(ctypes.c_bool,))
        send(None, panel, "setIgnoresMouseEvents:", True, argtypes=(ctypes.c_bool,))
        send(None, panel, "setHidesOnDeactivate:", False, argtypes=(ctypes.c_bool,))
        send(None, panel, "setCollectionBehavior:", 1 | 16 | 256, argtypes=(ctypes.c_ulong,))  # every Space
        view = send(v, panel, "contentView")
        send(None, view, "setWantsLayer:", True, argtypes=(ctypes.c_bool,))
        layer = send(v, view, "layer")
        send(None, layer, "setCornerRadius:", 9.0, argtypes=(ctypes.c_double,))
        send(None, layer, "setBackgroundColor:", oc.cgcolor(colors["raised"]), argtypes=(v,))
        send(None, layer, "setBorderWidth:", 1.0, argtypes=(ctypes.c_double,))
        send(None, layer, "setBorderColor:", oc.cgcolor(colors["border_hover"]), argtypes=(v,))
        self.word = _label(15, 0.3, colors["text"])
        self.hint = _label(11, 0.0, colors["muted"])
        for label in (self.word, self.hint):
            send(None, view, "addSubview:", label, argtypes=(v,))
        self.panel, self.visible = panel, False

    def show(self, typed, fixed, rect):
        v = ctypes.c_void_p
        send(None, self.word, "setStringValue:", oc.nsstring(f"→  {fixed}"), argtypes=(v,))
        send(None, self.hint, "setStringValue:", oc.nsstring(f"space to fix  ·  esc keeps “{typed}”"),
             argtypes=(v,))
        a = send(CGSize, self.word, "fittingSize")
        b = send(CGSize, self.hint, "fittingSize")
        w, h = max(a.width, b.width) + 26, a.height + b.height + 14
        send(None, self.hint, "setFrame:", CGRect(CGPoint(13, 7), CGSize(b.width, b.height)), argtypes=(CGRect,))
        send(None, self.word, "setFrame:", CGRect(CGPoint(13, 7 + b.height), CGSize(a.width, a.height)),
             argtypes=(CGRect,))
        screen_h, screen_w = oc.main_screen_height(), oc.main_screen_width()
        if rect:
            x, y_top = rect[0] - 13, rect[1] + rect[3] + 6
            y = screen_h - y_top - h
            if y < 4:  # no room below the line: go above it
                y = screen_h - rect[1] + 6
        else:  # the app won't say where its cursor is: bottom middle of the screen
            x, y = (screen_w - w) / 2, 110
        x = min(max(x, 4), screen_w - w - 4)
        send(None, self.panel, "setFrame:display:", CGRect(CGPoint(x, y), CGSize(w, h)), True,
             argtypes=(CGRect, ctypes.c_bool))
        send(None, self.panel, "orderFrontRegardless")
        self.visible = True

    def hide(self):
        if self.visible:
            send(None, self.panel, "orderOut:", None, argtypes=(ctypes.c_void_p,))
            self.visible = False


# ---------------------------------------------------------------------------
# The menu bar icon
# ---------------------------------------------------------------------------

class TrayIcon:
    """A menu bar icon whose menu is rebuilt from get_items() each time it opens.

    Items: None for a separator, or dicts with "title" and optionally "action" (no action means
    a grey label), "checked", or "submenu" (a list of items)."""

    def __init__(self, root, get_items, image_path, on_double_click=None):
        v = ctypes.c_void_p
        self.get_items, self.actions = get_items, {}
        self.target, self._keep = oc.make_target(self._act, self._rebuild)
        bar = send(v, oc.cls("NSStatusBar"), "systemStatusBar")
        self.item = send(v, bar, "statusItemWithLength:", -1.0, argtypes=(ctypes.c_double,))
        send(v, self.item, "retain")
        self.button = send(v, self.item, "button")
        image = send(v, send(v, oc.cls("NSImage"), "alloc"), "initWithContentsOfFile:", oc.nsstring(image_path),
                     argtypes=(v,))
        if image:
            send(None, image, "setSize:", CGSize(18, 18), argtypes=(CGSize,))
            send(None, image, "setTemplate:", True, argtypes=(ctypes.c_bool,))  # follows light/dark menu bar
            send(None, self.button, "setImage:", image, argtypes=(v,))
        else:
            send(None, self.button, "setTitle:", oc.nsstring("Typofix"), argtypes=(v,))
        send(None, self.button, "setToolTip:", oc.nsstring("Typofix"), argtypes=(v,))
        self.menu = oc.obj("NSMenu")
        send(None, self.menu, "setAutoenablesItems:", False, argtypes=(ctypes.c_bool,))
        send(None, self.menu, "setDelegate:", self.target, argtypes=(v,))
        send(None, self.item, "setMenu:", self.menu, argtypes=(v,))

    def _act(self, tag):
        fn = self.actions.get(tag)
        if fn:
            fn()

    def _fill(self, menu, items):
        v = ctypes.c_void_p
        send(None, menu, "removeAllItems")
        for entry in items:
            if entry is None:
                send(None, menu, "addItem:", send(v, oc.cls("NSMenuItem"), "separatorItem"), argtypes=(v,))
                continue
            action = entry.get("action")
            item = send(v, send(v, oc.cls("NSMenuItem"), "alloc"), "initWithTitle:action:keyEquivalent:",
                        oc.nsstring(entry["title"]), oc.sel("act:") if action else None, oc.nsstring(""),
                        argtypes=(v, v, v))
            if action:
                tag = len(self.actions) + 1
                self.actions[tag] = action
                send(None, item, "setTarget:", self.target, argtypes=(v,))
                send(None, item, "setTag:", tag, argtypes=(ctypes.c_long,))
            send(None, item, "setEnabled:", bool(action or entry.get("submenu")), argtypes=(ctypes.c_bool,))
            if entry.get("checked"):
                send(None, item, "setState:", 1, argtypes=(ctypes.c_long,))
            if entry.get("submenu") is not None:
                sub = oc.obj("NSMenu")
                send(None, sub, "setAutoenablesItems:", False, argtypes=(ctypes.c_bool,))
                self._fill(sub, entry["submenu"])
                send(None, item, "setSubmenu:", sub, argtypes=(v,))
                send(None, sub, "release")
            send(None, menu, "addItem:", item, argtypes=(v,))
            send(None, item, "release")

    def _rebuild(self):
        self.actions = {}
        self._fill(self.menu, self.get_items())

    def set_paused(self, paused):
        send(None, self.button, "setAppearsDisabled:", paused, argtypes=(ctypes.c_bool,))

    def remove(self):
        bar = send(ctypes.c_void_p, oc.cls("NSStatusBar"), "systemStatusBar")
        send(None, bar, "removeStatusItem:", self.item, argtypes=(ctypes.c_void_p,))


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
AGENT = os.path.expanduser("~/Library/LaunchAgents/local.typofix.plist")


class Backend:
    name = "macos"
    KeyHook = KeyHook
    Bubble = Bubble
    TrayIcon = TrayIcon
    ui_font = "Helvetica Neue"
    title_font = "Georgia"
    tray_name = "menu bar"
    char_before = staticmethod(char_before)
    caret_rect = staticmethod(caret_rect)

    def setup_process(self):
        pass

    def scale(self, root):
        return 1.0  # Tk on macOS already works in points

    def style_window(self, root, bg):
        try:
            root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", root._w, "darkaqua")
        except Exception:  # noqa: BLE001 - older Tk versions lack this
            pass

    def set_dock_icon(self, visible):
        oc.set_dock_icon(visible)

    def activate(self):
        oc.activate()

    def permission_problem(self, prompt=True):
        """A message if macOS hasn't allowed us to see and type keys yet (and asks the user)."""
        if _cg.AXIsProcessTrusted():
            return None
        if prompt:
            keys = (ctypes.c_void_p * 1)(kAXTrustedCheckOptionPrompt)
            vals = (ctypes.c_void_p * 1)(kCFBooleanTrue)
            opts = _cf.CFDictionaryCreate(None, keys, vals, 1, None, None)
            _cg.AXIsProcessTrustedWithOptions(opts)
            _cf.CFRelease(opts)
        return ("Typofix needs Accessibility access to fix your typing. Turn Typofix on in "
                "System Settings → Privacy & Security → Accessibility.\n\nAlready on there? That's "
                "an older copy macOS no longer recognizes. Click Reset permission, then turn "
                "Typofix on again.")

    def open_permission_settings(self):
        subprocess.Popen(["open", SETTINGS_URL])

    can_reset_permission = True

    def reset_permission(self):
        """Clears Typofix's old Accessibility entry so macOS asks again for this copy.
        Returns False if macOS wouldn't let us."""
        done = subprocess.run(["tccutil", "reset", "Accessibility", "local.typofix"],
                              capture_output=True).returncode == 0
        self.permission_problem(prompt=True)
        self.open_permission_settings()
        return done

    # -- open at login, via a LaunchAgent that opens the app bundle
    def app_path(self):
        return os.environ.get("TYPOFIX_APP")  # set by the app's launcher; unset when run from source

    def login_item(self):
        return os.path.exists(AGENT)

    def set_login_item(self, on):
        if not on:
            if os.path.exists(AGENT):
                os.remove(AGENT)
            return True
        app = self.app_path()
        if not app:
            return False
        os.makedirs(os.path.dirname(AGENT), exist_ok=True)
        with open(AGENT, "w", encoding="utf-8") as f:
            f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>local.typofix</string>
	<key>ProgramArguments</key>
	<array><string>/usr/bin/open</string><string>-a</string><string>{app}</string>
	<string>--args</string><string>--background</string></array>
	<key>RunAtLoad</key><true/>
</dict>
</plist>
""")
        return True
