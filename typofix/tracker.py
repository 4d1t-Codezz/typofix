"""Follows what you type and decides when to fix a word. Knows nothing about the OS.

The keyboard hook feeds it characters, backspaces and "the cursor may have moved" resets. When
you press space (or Enter) after a typo it returns a Fix: the hook swallows that key and instead
sends `delete` backspaces followed by `insert`, then the key itself. Pressing backspace right
after a fix puts your original word back, like iMessage, and the speller learns that word.

With the preview on, it also reports the fix it would make for the word you're in the middle of
typing, so the window can show it before you press space. Escape keeps the word as typed.
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
    before: str = ""  # what was there (for the "recent fixes" list)
    after: str = ""
    key: str = ""  # the swallowed key to send afterwards: " " is typed with the text, "\n" is Return


def _diff(old, new):
    """The fewest backspaces and keystrokes that turn old into new (when typed at the end)."""
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    return len(old) - p, new[p:]


class Tracker:
    def __init__(self, speller, on_fix=None, on_learn=None, on_preview=None, char_before=None):
        self.speller = speller
        self.on_fix = on_fix or (lambda fix: None)
        self.on_learn = on_learn or (lambda word: None)
        self.on_preview = on_preview or (lambda typed, fixed: None)
        # Optional: asks the focused app for the character just before the cursor's word, when we
        # didn't see it typed. Returns that character, "" at the start of the field, or None.
        self.char_before = char_before
        self.enabled = True
        self.preview = False
        self.previewing = None
        self.reset(start_known=True)

    def reset(self, start_known):
        """The cursor may have moved (click, arrows, shortcut). start_known=False means we can't
        be sure the next thing typed starts a new word, e.g. after clicking into the middle of one."""
        self.text = ""
        self.start_known = start_known
        self.undo = None
        self.kept = None  # the start of a word the user chose to keep with Escape
        self._show(None)

    def char(self, ch):
        """A typed character. Returns a Fix to apply instead of letting the key through, or None."""
        self.undo = None
        if ch == "\n":
            # Only on a line with a space in it, so a password + Enter is never touched.
            fix = self._try_fix("\n") if self.enabled and " " in self.text.strip() else None
            self.reset(start_known=True)
            return fix
        if ch == " " and self.enabled:
            fix = self._try_fix(" ")
            if fix:
                return fix
        self.text += ch
        if len(self.text) > _KEEP:
            cut = self.text.find(" ", len(self.text) - _KEEP // 2)
            self.text = self.text[cut:] if cut != -1 else ""
            self.start_known = cut != -1
        self._update_preview()
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
        self._update_preview()
        return None

    def escape(self):
        """Keeps the word being typed as it is. Returns True if there was a preview to dismiss
        (so the hook can swallow the key)."""
        if not self.previewing:
            return False
        self.kept = self._word_start()
        self._show(None)
        return True

    # -- deciding
    def _word_start(self):
        m = _WORD.search(self.text)
        return m.start(1) if m else None

    def _candidate(self):
        """(start, word, punct, fixed) for the word at the end of what's been typed, or None."""
        m = _WORD.search(self.text)
        if not m:
            return None
        word, punct = m.group(1), m.group(2)
        while word[-1] in "'’":  # a closing quote, not part of the word
            word, punct = word[:-1], word[-1] + punct
        start = m.start(1)
        if start == self.kept:
            return None
        if start > 0 and self.text[start - 1] not in _OPENERS:
            return None
        if start == 0 and not self.start_known:
            before = self.char_before(len(self.text)) if self.char_before else None
            if before is None:
                if len(word) < 4:
                    return None  # might be the tail of a word we didn't see
            elif before and before not in _OPENERS:
                return None  # it is: there are letters right before it
        head = self.text[:start].rstrip(" \t(\"[{“‘'")
        sentence_start = not head or head[-1] in ".!?\n"
        prev = re.search(r"([A-Za-z']+)\W*$", head)
        prev = prev.group(1).lower() if prev and not sentence_start else None
        fixed = self.speller.correct(word, sentence_start, prev)
        return (start, word, punct, fixed) if fixed else None

    def _try_fix(self, key):
        found = self._candidate()
        self._show(None)
        if not found:
            return None
        start, word, punct, fixed = found
        original = word + punct
        replaced = fixed + punct + (" " if key == " " else "")
        delete, insert = _diff(original, replaced)
        self.text = self.text[:start] + replaced
        self.undo = (original, replaced) if key == " " else None
        fix = Fix(delete, insert, original, fixed + punct, key="\n" if key == "\n" else "")
        self.on_fix(fix)
        return fix

    # -- preview
    def _update_preview(self):
        if not (self.preview and self.enabled) or not self.text or not self.text[-1].isalpha():
            self._show(None)
            return
        found = self._candidate()
        self._show((found[1], found[3]) if found else None)

    def _show(self, pair):
        if pair != self.previewing:
            self.previewing = pair
            self.on_preview(*(pair or (None, None)))
