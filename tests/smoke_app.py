"""Starts the whole app (window, preview bubble, tray icon) with a stand-in keyboard hook, shows a
fix and a preview, opens the tray menu's contents, then quits. CI runs this on Windows and macOS
to catch mistakes in the OS code that unit tests can't reach.  python tests/smoke_app.py"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typofix import app as A  # noqa: E402
from typofix.platforms import get_backend  # noqa: E402
from typofix.tracker import Fix  # noqa: E402

A.CONFIG = tempfile.mkdtemp()
A.SETTINGS = os.path.join(A.CONFIG, "settings.json")
A.PORT_FILE = os.path.join(A.CONFIG, "port")
A.save_settings({"setup_done": True, "hide_explained": True})


class FakeHook:
    def __init__(self, tracker):
        pass

    def start(self):
        return True

    def stop(self):
        pass


Backend = type(get_backend())
Backend.KeyHook = FakeHook
Backend.permission_problem = lambda self, prompt=True: None
Backend.set_login_item = lambda self, on: True

app = A.App()
assert app.bubble is not None, "the preview bubble didn't start"
assert app.tray is not None, "the tray icon didn't start"
steps = []


def step():
    n = len(steps)
    steps.append(n)
    if n == 0:
        app.show()
        app.events.put(("fix", Fix(1, "e", "teh", "the")))
        app.events.put(("preview", ("recieve", "receive")))
    elif n == 1:
        assert app.bubble.visible, "the preview bubble didn't show"
        items = app._tray_items()
        assert items[0]["title"] == "Typofix is on", items[0]
        app.set_preview(False)
        assert not app.bubble.visible
        app.set_mode("window")
        app.set_mode("menubar")
        app.keep_word("teh")
        assert "teh" in app.speller.user_words
    else:
        app.quit()
        return
    app.root.after(700, step)


app.root.after(500, step)
app.run()
print("smoke test passed")
