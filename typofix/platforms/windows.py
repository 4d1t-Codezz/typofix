"""Windows: a low-level keyboard hook that sees every key (and can swallow one), SendInput to type.

Only ctypes and user32. Low-level hooks need no special permission. Keys typed into other apps
running as administrator are invisible to a normal-user hook, so those apps don't get fixes.
"""

import ctypes
import os
import subprocess
import sys
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t
MAGIC = 0x7F0F1C5  # tags our own synthetic input so the hook lets it through untouched

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_UNICODE = 0x4
WM_KEYDOWN, WM_SYSKEYDOWN = 0x100, 0x104
MOUSE_DOWNS = (0x201, 0x204, 0x207, 0x20B)  # left, right, middle, x button

VK_BACK, VK_TAB, VK_RETURN, VK_SPACE = 0x08, 0x09, 0x0D, 0x20
VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL = 0x10, 0x11, 0x12, 0x14
VK_LWIN, VK_RWIN = 0x5B, 0x5C
# Modifier and lock keys on their own change nothing.
VK_QUIET = {VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL, VK_LWIN, VK_RWIN, 0x90, 0x91,
            0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
# Keys that move the cursor somewhere we can't follow: escape, page up/down, end, home, arrows,
# insert, delete, and F1-F24.
VK_MOVES = {0x1B, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, *range(0x70, 0x88)}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.argtypes = [ctypes.c_int]
user32.GetKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
user32.GetKeyboardLayout.restype = wintypes.HKL
user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte), wintypes.LPWSTR,
                               ctypes.c_int, wintypes.UINT, wintypes.HKL]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def _key_input(vk=0, scan=0, flags=0):
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=MAGIC)
    return inp


def apply_fix(fix):
    scan = user32.MapVirtualKeyW(VK_BACK, 0)
    inputs = []
    for _ in range(fix.delete):
        inputs += [_key_input(VK_BACK, scan), _key_input(VK_BACK, scan, KEYEVENTF_KEYUP)]
    units = fix.insert.encode("utf-16-le")
    for i in range(0, len(units), 2):
        code = int.from_bytes(units[i:i + 2], "little")
        inputs += [_key_input(scan=code, flags=KEYEVENTF_UNICODE),
                   _key_input(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _down(vk):
    return user32.GetAsyncKeyState(vk) & 0x8000


def _typed_text(vk, scan):
    """The character this key makes on the current keyboard layout, without disturbing dead keys."""
    state = (ctypes.c_ubyte * 256)()
    if _down(VK_SHIFT):
        state[VK_SHIFT] = 0x80
    if user32.GetKeyState(VK_CAPITAL) & 1:
        state[VK_CAPITAL] = 0x01
    thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    buf = ctypes.create_unicode_buffer(8)
    n = user32.ToUnicodeEx(vk, scan, state, buf, 8, 0x4, user32.GetKeyboardLayout(thread))  # 0x4: keep state
    return buf.value[:n] if n > 0 else ""


class KeyHook:
    """Feeds the tracker from low-level keyboard and mouse hooks on their own thread."""

    def __init__(self, tracker):
        self.tracker = tracker
        self.thread_id = None

    def start(self):
        ok = []
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready, ok), daemon=True, name="key-hook").start()
        ready.wait(3)
        return bool(ok)

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
        self.thread_id = None

    def _on_key(self, vk, scan, sys_key):
        """Returns False to swallow the key."""
        t = self.tracker
        if vk in VK_QUIET:
            return True
        if sys_key or _down(VK_CONTROL) or _down(VK_MENU) or _down(VK_LWIN) or _down(VK_RWIN):
            t.reset(start_known=False)  # a shortcut (paste, undo, switch window...)
            return True
        if vk == VK_BACK:
            fix = t.backspace()
        elif vk in (VK_RETURN, VK_TAB):
            t.reset(start_known=True)
            return True
        elif vk in VK_MOVES:
            t.reset(start_known=False)
            return True
        else:
            text = " " if vk == VK_SPACE else _typed_text(vk, scan)
            if len(text) != 1 or not text.isprintable():
                return True
            fix = t.char(text)
        if fix:
            apply_fix(fix)
            return False
        return True

    def _run(self, ready, ok):
        self.thread_id = kernel32.GetCurrentThreadId()

        def kb(code, wparam, lparam):
            try:
                if code == 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    if info.dwExtraInfo != MAGIC and not self._on_key(info.vkCode, info.scanCode,
                                                                      wparam == WM_SYSKEYDOWN):
                        return 1
            except Exception:  # noqa: BLE001 - never let a bug eat the user's keystrokes
                import traceback
                traceback.print_exc()
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def mouse(code, wparam, lparam):
            if code == 0 and wparam in MOUSE_DOWNS:
                self.tracker.reset(start_known=False)
            return user32.CallNextHookEx(None, code, wparam, lparam)

        # Keep references alive for the lifetime of the hooks.
        self._kb_proc, self._mouse_proc = HOOKPROC(kb), HOOKPROC(mouse)
        hmod = kernel32.GetModuleHandleW(None)
        hooks = [user32.SetWindowsHookExW(13, self._kb_proc, hmod, 0),  # WH_KEYBOARD_LL
                 user32.SetWindowsHookExW(14, self._mouse_proc, hmod, 0)]  # WH_MOUSE_LL
        if hooks[0]:
            ok.append(True)
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        for h in hooks:
            if h:
                user32.UnhookWindowsHookEx(h)


STARTUP_LINK = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup",
                            "Typofix.lnk")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pythonw():
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return w if os.path.exists(w) else exe


class Backend:
    name = "windows"
    KeyHook = KeyHook
    ui_font = "Segoe UI"

    def permission_problem(self, prompt=True):
        return None  # low-level hooks need no permission

    def open_permission_settings(self):
        pass

    # -- open at login, via a shortcut in the Startup folder
    def app_path(self):
        return REPO

    def login_item(self):
        return os.path.exists(STARTUP_LINK)

    def set_login_item(self, on):
        if not on:
            if os.path.exists(STARTUP_LINK):
                os.remove(STARTUP_LINK)
            return True
        ps = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LINK); "
              "$s.TargetPath = $env:TARGET; $s.Arguments = '-m typofix --background'; "
              "$s.WorkingDirectory = $env:REPO; $s.IconLocation = $env:ICON; $s.Save()")
        env = dict(os.environ, LINK=STARTUP_LINK, TARGET=_pythonw(), REPO=REPO,
                   ICON=os.path.join(REPO, "assets", "Typofix.ico"))
        result = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                                creationflags=0x08000000)  # CREATE_NO_WINDOW
        return result.returncode == 0
