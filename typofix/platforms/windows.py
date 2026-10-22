"""Windows: a low-level keyboard hook that sees every key (and can swallow one), SendInput to type.

Only ctypes and user32. Low-level hooks need no special permission. Keys typed into other apps
running as administrator are invisible to a normal-user hook, so those apps don't get fixes.
Also here: the tray icon (Shell_NotifyIcon) and a preview bubble that never takes focus.
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

VK_BACK, VK_TAB, VK_RETURN, VK_ESCAPE, VK_SPACE = 0x08, 0x09, 0x0D, 0x1B, 0x20
VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL = 0x10, 0x11, 0x12, 0x14
VK_LWIN, VK_RWIN = 0x5B, 0x5C
# Modifier and lock keys on their own change nothing.
VK_QUIET = {VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL, VK_LWIN, VK_RWIN, 0x90, 0x91,
            0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
# Keys that move the cursor somewhere we can't follow: page up/down, end, home, arrows,
# insert, delete, and F1-F24.
VK_MOVES = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, *range(0x70, 0x88)}


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


def press(vk):
    scan = user32.MapVirtualKeyW(vk, 0)
    arr = (INPUT * 2)(_key_input(vk, scan), _key_input(vk, scan, KEYEVENTF_KEYUP))
    user32.SendInput(2, arr, ctypes.sizeof(INPUT))


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
        elif vk == VK_RETURN:
            fix = t.char("\n")
            if fix:
                apply_fix(fix)
                press(VK_RETURN)  # then the Return itself, so a chat message sends already fixed
                return False
            return True
        elif vk == VK_ESCAPE:
            if t.escape():
                return False  # it closed the preview; don't also close the app's popup or dialog
            t.reset(start_known=False)
            return True
        elif vk == VK_TAB:
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


# ---------------------------------------------------------------------------
# Where the text cursor is (apps that use the system caret: most classic Windows apps)
# ---------------------------------------------------------------------------

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD), ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND), ("rcCaret", wintypes.RECT)]


user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]


def caret_rect():
    """(x, y, width, height) of the text cursor in screen pixels, or None if the app has none."""
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)) or not info.hwndCaret:
        return None
    pt = wintypes.POINT(info.rcCaret.left, info.rcCaret.top)
    user32.ClientToScreen(info.hwndCaret, ctypes.byref(pt))
    return pt.x, pt.y, 1, max(info.rcCaret.bottom - info.rcCaret.top, 1)


# ---------------------------------------------------------------------------
# The preview bubble: a Tk window that's never activated. It's shown once, off screen, and from
# then on only moved with SWP_NOACTIVATE, so typing in the app underneath carries on.
# ---------------------------------------------------------------------------

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT = 0x08000000, 0x80, 0x8, 0x20
SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_NOOWNERZORDER = 0x10, 0x40, 0x200
HWND_TOPMOST = wintypes.HWND(-1)


class Bubble:
    def __init__(self, root, colors):
        import tkinter as tk
        self.root, self.visible = root, False
        top = self.top = tk.Toplevel(root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=colors["border_hover"])
        inner = tk.Frame(top, bg=colors["raised"], padx=12, pady=6)
        inner.pack(padx=1, pady=1)
        self.word = tk.Label(inner, bg=colors["raised"], fg=colors["text"], font=("Segoe UI Semibold", 12),
                             anchor="w")
        self.word.pack(fill="x")
        self.hint = tk.Label(inner, bg=colors["raised"], fg=colors["muted"], font=("Segoe UI", 9), anchor="w")
        self.hint.pack(fill="x")
        top.geometry("+-20000+-20000")
        top.update_idletasks()
        self.hwnd = int(top.wm_frame(), 16)
        ex = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE,
                              ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT)
        top.deiconify()  # only ever shown here, off screen
        top.update_idletasks()

    def _place(self, x, y, w, h):
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, int(x), int(y), int(w), int(h),
                            SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOOWNERZORDER)

    def show(self, typed, fixed, rect):
        self.word.configure(text=f"→  {fixed}")
        self.hint.configure(text=f"space to fix  ·  esc keeps “{typed}”")
        self.top.update_idletasks()
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if rect:
            x, y = rect[0] - 12, rect[1] + rect[3] + 6
            if y + h > sh - 4:
                y = rect[1] - h - 6
        else:  # the app won't say where its cursor is: bottom middle of the screen
            x, y = (sw - w) / 2, sh - h - 110
        self._place(min(max(x, 4), sw - w - 4), y, w, h)
        self.visible = True

    def hide(self):
        if self.visible:
            self._place(-20000, -20000, 10, 10)
            self.visible = False


# ---------------------------------------------------------------------------
# The tray icon. Its messages arrive at a small hidden window; Tk's own message loop runs on the
# same thread, so they're dispatched without any extra loop of ours. The menu is a Tk menu.
# ---------------------------------------------------------------------------

class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


shell32 = ctypes.WinDLL("shell32", use_last_error=True)
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                              wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
WM_TRAY = 0x8000 + 17  # WM_APP + 17
WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x202, 0x203, 0x205


class TrayIcon:
    """A tray icon whose menu is built from get_items() each time it's clicked.

    Items: None for a separator, or dicts with "title" and optionally "action" (no action means
    a grey label), "checked", or "submenu" (a list of items)."""

    def __init__(self, root, get_items, image_path, on_double_click=None):
        self.root, self.get_items, self.on_double_click = root, get_items, on_double_click
        data = os.path.dirname(image_path)
        self.icons = {p: user32.LoadImageW(None, os.path.join(data, name), 1, 16, 16, 0x10)  # LR_LOADFROMFILE
                      for p, name in ((False, "Typofix.ico"), (True, "TypofixPaused.ico"))}
        self.paused = False
        # Set before the window exists: Windows sends it messages while CreateWindowExW runs.
        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._proc = WNDPROC(self._wndproc)
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="TypofixTray")
        user32.RegisterClassW(ctypes.byref(wc))
        # A plain hidden window (not message-only) so it can take the foreground for the menu.
        self.hwnd = user32.CreateWindowExW(0, "TypofixTray", "Typofix", 0x80000000, 0, 0, 0, 0,  # WS_POPUP
                                           None, None, hinst, None)
        self._notify(NIM_ADD)

    def _data(self):
        nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1,
                              uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP, uCallbackMessage=WM_TRAY,
                              hIcon=self.icons[self.paused])
        nid.szTip = "Typofix (paused)" if self.paused else "Typofix"
        return nid

    def _notify(self, op):
        nid = self._data()
        shell32.Shell_NotifyIconW(op, ctypes.byref(nid))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                if lparam in (WM_LBUTTONUP, WM_RBUTTONUP):
                    self.root.after(1, self._popup)
                elif lparam == WM_LBUTTONDBLCLK and self.on_double_click:
                    self.root.after(1, self.on_double_click)
                return 0
            if msg == self.taskbar_created:  # Explorer restarted: put the icon back
                self._notify(NIM_ADD)
                return 0
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _build(self, items):
        import tkinter as tk
        menu = tk.Menu(self.root, tearoff=False)
        for entry in items:
            if entry is None:
                menu.add_separator()
            elif entry.get("submenu") is not None:
                menu.add_cascade(label=entry["title"], menu=self._build(entry["submenu"]))
            elif entry.get("checked") is not None and entry.get("action"):
                var = tk.BooleanVar(value=entry["checked"])
                menu.add_checkbutton(label=entry["title"], variable=var, command=entry["action"])
                menu._vars = getattr(menu, "_vars", []) + [var]
            else:
                menu.add_command(label=entry["title"], command=entry.get("action"),
                                 state="normal" if entry.get("action") else "disabled")
        return menu

    def _popup(self):
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)  # so the menu closes when you click elsewhere
        menu = self._build(self.get_items())
        try:
            menu.tk_popup(pt.x, pt.y)
        finally:
            menu.grab_release()

    def set_paused(self, paused):
        if paused != self.paused:
            self.paused = paused
            self._notify(NIM_MODIFY)

    def remove(self):
        self._notify(NIM_DELETE)
        user32.DestroyWindow(self.hwnd)


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
    Bubble = Bubble
    TrayIcon = TrayIcon
    ui_font = "Segoe UI"
    title_font = "Georgia"
    tray_name = "system tray"
    char_before = None  # Windows apps don't share their text, so after a click we're more careful
    caret_rect = staticmethod(caret_rect)

    def setup_process(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
        except (AttributeError, OSError):
            pass

    def scale(self, root):
        return root.winfo_fpixels("1i") / 96

    def style_window(self, root, bg):
        """Dark title bar on Windows 10/11 so the frame matches the window."""
        try:
            root.update_idletasks()
            hwnd = int(root.wm_frame(), 16)
            h = bg.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            dwm = ctypes.windll.dwmapi
            on, caption = ctypes.c_int(1), ctypes.c_int(b << 16 | g << 8 | r)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)  # immersive dark mode
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)  # caption color (Windows 11)
            root.iconbitmap(default=os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "Typofix.ico"))
        except (AttributeError, OSError, ValueError, Exception):  # noqa: BLE001
            pass

    def set_dock_icon(self, visible):
        pass  # the window's own taskbar button comes and goes with the window

    def activate(self):
        pass

    def permission_problem(self, prompt=True):
        return None  # low-level hooks need no permission

    def open_permission_settings(self):
        pass

    can_reset_permission = False

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
