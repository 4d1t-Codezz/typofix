"""macOS: a Quartz event tap that sees every key (and can swallow one), and CGEventPost to type.

Only ctypes and system frameworks. The tap is an active one (not listen-only) so it can drop the
space that triggers a fix and send the corrected word in its place; that needs Accessibility
access. Password fields turn on Secure Input, which hides their keys from every tap, so
passwords are never seen or touched.
"""

import ctypes
import os
import subprocess
import threading

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

KC_SPACE, KC_DELETE = 49, 51
KC_NEW_LINE = (36, 76)  # return, keypad enter
KC_TAB = 48
# Keys that move the cursor somewhere we can't follow: arrows, home/end, page up/down,
# forward delete, escape, and F1-F12.
KC_MOVES = {123, 124, 125, 126, 115, 119, 116, 121, 117, 53,
            122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111}

TAPCALLBACK = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)

_cg.CGEventSourceCreate.argtypes = [ctypes.c_int32]
_cg.CGEventSourceCreate.restype = ctypes.c_void_p
_cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
_cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
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


def _typed_text(event):
    buf = (ctypes.c_uint16 * 8)()
    n = ctypes.c_ulong(0)
    _cg.CGEventKeyboardGetUnicodeString(event, 8, ctypes.byref(n), buf)
    return bytes(buf)[:n.value * 2].decode("utf-16-le", errors="ignore")


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
        elif code in KC_NEW_LINE or code == KC_TAB:
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


SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
AGENT = os.path.expanduser("~/Library/LaunchAgents/local.typofix.plist")


class Backend:
    name = "macos"
    KeyHook = KeyHook
    ui_font = "Helvetica Neue"

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
                "System Settings → Privacy & Security → Accessibility.")

    def open_permission_settings(self):
        subprocess.Popen(["open", SETTINGS_URL])

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
