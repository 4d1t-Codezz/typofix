"""Follows what you type and decides when to fix a word. Knows nothing about the OS.

The keyboard hook feeds it characters, backspaces and "the cursor may have moved" resets. When
you press space after a typo it returns a Fix: the hook swallows that space and instead sends
`delete` backspaces followed by `insert` (which ends with the space). Pressing backspace right
after a fix puts your original word back, like iMessage, and the speller learns that word.
"""

import re
from dataclasses import dataclass

# A word (letters and apostrophes) with any punctuation typed straight after it, at the very end.
_WORD = re.compile(r"([A-Za-z][A-Za-z'’]*)([.,!?;:\"”)\]}]*)$")
# What may come right before a word we'll touch. Anything else (/ @ . _ - digits) means the
# "word" is part of a link, email, path, handle or code, so it's left alone.
_OPENERS = set(" \t\n(\"[{“‘'")
_KEEP = 200  # characters of history to remember


@dataclass
class Fix:
    delete: int  # backspaces to send
    insert: str  # then type this
    before: str = ""  # what was there (for the window's "recent fixes" list)
    after: str = ""


def _diff(old, new):
    """The fewest backspaces and keystrokes that turn old into new (when typed at the end)."""
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    return len(old) - p, new[p:]


class Tracker:
    def __init__(self, speller, on_fix=None, on_learn=None):
        self.speller = speller
        self.on_fix = on_fix or (lambda fix: None)
        self.on_learn = on_learn or (lambda word: None)
        self.enabled = True
        self.reset(start_known=True)

    def reset(self, start_known):
        """The cursor may have moved (click, arrows, shortcut). start_known=False means we can't
        be sure the next thing typed starts a new word, e.g. after clicking into the middle of one."""
        self.text = ""
        self.start_known = start_known
        self.undo = None

    def char(self, ch):
        """A typed character. Returns a Fix to apply instead of letting the key through, or None."""
        self.undo = None
        if ch == " " and self.enabled:
            fix = self._try_fix()
            if fix:
                return fix
        if ch == "\n":
            self.reset(start_known=True)
            return None
        self.text += ch
        if len(self.text) > _KEEP:
            cut = self.text.find(" ", len(self.text) - _KEEP // 2)
            self.text = self.text[cut:] if cut != -1 else ""
            self.start_known = cut != -1
        return None

    def backspace(self):
        """Returns a Fix that undoes the last correction, if this backspace came right after one."""
        undo, self.undo = self.undo, None
        if undo and self.enabled and self.text.endswith(undo[1]):
            original, replaced = undo
            delete, insert = _diff(replaced, original)
            self.text = self.text[:-len(replaced)] + original
            word = _WORD.search(original)
            if word:
                self.speller.learn(word.group(1))
                self.on_learn(word.group(1))
            return Fix(delete, insert, replaced.rstrip(), original)
        if self.text:
            self.text = self.text[:-1]
        else:
            self.start_known = False  # deleting text we never saw
        return None

    def _try_fix(self):
        m = _WORD.search(self.text)
        if not m:
            return None
        word, punct = m.group(1), m.group(2)
        while word[-1] in "'’":  # a closing quote, not part of the word
            word, punct = word[:-1], word[-1] + punct
        start = m.start(1)
        if start > 0 and self.text[start - 1] not in _OPENERS:
            return None
        if start == 0 and not self.start_known and len(word) < 4:
            return None  # might be the tail of a word we didn't see
        before = self.text[:start].rstrip(" \t(\"[{“‘'")
        sentence_start = not before or before[-1] in ".!?\n"
        fixed = self.speller.correct(word, sentence_start)
        if not fixed:
            return None
        original, replaced = word + punct, fixed + punct + " "
        delete, insert = _diff(original, replaced)
        self.text = self.text[:start] + replaced
        self.undo = (original, replaced)
        fix = Fix(delete, insert, original, fixed + punct)
        self.on_fix(fix)
        return fix
