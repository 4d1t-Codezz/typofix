"""Just enough of the Objective-C runtime, over ctypes, for the menu bar icon and preview bubble.

Everything here must run on the main thread (Tk's), which is also AppKit's.
"""

import ctypes
import ctypes.util

_objc = ctypes.CDLL(ctypes.util.find_library("objc") or "/usr/lib/libobjc.A.dylib")
ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
_cg = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")

_objc.objc_getClass.argtypes = [ctypes.c_char_p]
_objc.objc_getClass.restype = ctypes.c_void_p
_objc.sel_registerName.argtypes = [ctypes.c_char_p]
_objc.sel_registerName.restype = ctypes.c_void_p
_objc.objc_allocateClassPair.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
_objc.objc_allocateClassPair.restype = ctypes.c_void_p
_objc.objc_registerClassPair.argtypes = [ctypes.c_void_p]
_objc.class_addMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
_objc.class_addMethod.restype = ctypes.c_bool
_MSG = ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value

_cg.CGColorCreateGenericRGB.argtypes = [ctypes.c_double] * 4
_cg.CGColorCreateGenericRGB.restype = ctypes.c_void_p


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


_cg.CGMainDisplayID.restype = ctypes.c_uint32
_cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
_cg.CGDisplayBounds.restype = CGRect

_sigs = {}


def send(restype, obj, selector, *args, argtypes=()):
    """objc_msgSend with an explicit signature (required on Apple Silicon)."""
    key = (restype, argtypes)
    fn = _sigs.get(key)
    if fn is None:
        fn = _sigs[key] = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(_MSG)
    return fn(obj, _objc.sel_registerName(selector.encode()), *args)


def sel(name):
    return _objc.sel_registerName(name.encode())


def cls(name):
    return _objc.objc_getClass(name.encode())


def obj(class_name, init="init"):
    return send(ctypes.c_void_p, send(ctypes.c_void_p, cls(class_name), "alloc"), init)


def nsstring(s):
    return send(ctypes.c_void_p, cls("NSString"), "stringWithUTF8String:", s.encode(), argtypes=(ctypes.c_char_p,))


def color(hex_color, alpha=1.0):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return send(ctypes.c_void_p, cls("NSColor"), "colorWithSRGBRed:green:blue:alpha:", r, g, b, alpha,
                argtypes=(ctypes.c_double,) * 4)


def cgcolor(hex_color, alpha=1.0):
    h = hex_color.lstrip("#")
    return _cg.CGColorCreateGenericRGB(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)), alpha)


def main_screen_height():
    return _cg.CGDisplayBounds(_cg.CGMainDisplayID()).size.height


def main_screen_width():
    return _cg.CGDisplayBounds(_cg.CGMainDisplayID()).size.width


ACTION = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_classes = {}


def make_target(on_action, on_menu_opening=None):
    """An object whose act: method calls on_action(tag), and which, as a menu delegate, calls
    on_menu_opening() just before its menu opens. Returns (instance, keepalive)."""
    imps = [ACTION(lambda self, _cmd, sender: on_action(send(ctypes.c_long, sender, "tag"))),
            ACTION(lambda self, _cmd, menu: on_menu_opening and on_menu_opening())]
    name = f"TypofixTarget{len(_classes)}".encode()
    klass = _objc.objc_allocateClassPair(cls("NSObject"), name, 0)
    _objc.class_addMethod(klass, sel("act:"), ctypes.cast(imps[0], ctypes.c_void_p), b"v@:@")
    _objc.class_addMethod(klass, sel("menuNeedsUpdate:"), ctypes.cast(imps[1], ctypes.c_void_p), b"v@:@")
    _objc.objc_registerClassPair(klass)
    _classes[name] = imps  # the IMPs must outlive the class
    return send(ctypes.c_void_p, send(ctypes.c_void_p, klass, "alloc"), "init"), imps


def set_dock_icon(visible):
    app = send(ctypes.c_void_p, cls("NSApplication"), "sharedApplication")
    send(ctypes.c_bool, app, "setActivationPolicy:", 0 if visible else 1, argtypes=(ctypes.c_long,))


def activate():
    app = send(ctypes.c_void_p, cls("NSApplication"), "sharedApplication")
    send(None, app, "activateIgnoringOtherApps:", True, argtypes=(ctypes.c_bool,))
