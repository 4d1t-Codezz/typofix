"""Types into a pretend text box and checks what ends up on screen."""

import unittest

from typofix.speller import Speller
from typofix.tracker import Tracker

SPELLER = Speller()


class Box:
    """A text field that applies the tracker's fixes the way the OS hooks do."""

    def __init__(self, char_before=None):
        self.speller = Speller.__new__(Speller)
        self.speller.__dict__.update(SPELLER.__dict__, user_words=set())
        self.previews = []
        self.tracker = Tracker(self.speller, char_before=char_before,
                               on_preview=lambda typed, fixed: self.previews.append((typed, fixed)))
        self.text = ""

    def type(self, keys):
        for ch in keys:
            if ch == "\b":
                fix = self.tracker.backspace()
                if not fix:
                    self.text = self.text[:-1]
            elif ch == "\x1b":
                fix = None
                self.tracker.escape()
            else:
                fix = self.tracker.char(ch)
                if not fix:
                    self.text += ch
            if fix:  # the key was swallowed; send the fix instead, then the key if it's Return
                self.text = self.text[:len(self.text) - fix.delete] + fix.insert + fix.key
        return self


class TrackerTest(unittest.TestCase):
    def test_fixes_on_space(self):
        self.assertEqual(Box().type("i dont know teh answer ").text, "I don't know the answer ")

    def test_keeps_punctuation(self):
        self.assertEqual(Box().type("wait, recieve. ").text, "wait, receive. ")
        self.assertEqual(Box().type("is it wierd? ").text, "is it weird? ")

    def test_nothing_happens_before_space(self):
        self.assertEqual(Box().type("teh").text, "teh")

    def test_capital_at_sentence_start(self):
        self.assertEqual(Box().type("Teh end. Teh ").text, "The end. The ")

    def test_backspace_right_after_a_fix_undoes_it(self):
        box = Box().type("teh \b")
        self.assertEqual(box.text, "teh")
        self.assertIn("teh", box.speller.user_words)
        self.assertEqual(box.type(" ").text, "teh ")  # and it's not fixed again

    def test_backspace_later_is_just_backspace(self):
        self.assertEqual(Box().type("teh x\b\b").text, "the")

    def test_backspace_edits_are_followed(self):
        self.assertEqual(Box().type("thw\be ").text, "the ")
        self.assertEqual(Box().type("hellp\bo wrld ").text, "hello world ")

    def test_links_emails_and_code_are_left_alone(self):
        for text in ("see example.com/teh ", "mail me@teh ", "my_teh ", "#teh ", "2teh "):
            self.assertEqual(Box().type(text).text, text)

    def test_unknown_start_skips_short_fragments(self):
        box = Box()
        box.tracker.reset(start_known=False)  # e.g. clicked into the middle of a word
        self.assertEqual(box.type("teh ").text, "teh ")

    def test_unknown_start_asks_the_app(self):
        box = Box(char_before=lambda n: "")  # clicked into an empty box
        box.tracker.reset(start_known=False)
        self.assertEqual(box.type("teh ").text, "the ")
        box = Box(char_before=lambda n: "x")  # clicked right after some letters
        box.tracker.reset(start_known=False)
        self.assertEqual(box.type("recieve ").text, "recieve ")

    def test_enter_fixes_the_last_word_of_a_message(self):
        self.assertEqual(Box().type("see you tomorow\n").text, "see you tomorrow\n")

    def test_enter_leaves_a_lone_word_alone(self):
        self.assertEqual(Box().type("monkee\n").text, "monkee\n")  # could be a password

    def test_preview_and_escape(self):
        box = Box()
        box.tracker.preview = True
        box.type("teh")
        self.assertEqual(box.previews[-1], ("teh", "the"))
        box.type("\x1b ")
        self.assertEqual(box.text, "teh ")  # kept as typed
        self.assertEqual(box.previews[-1], (None, None))

    def test_curly_apostrophes_stay_curly(self):
        self.assertEqual(Box().type("i’ve been ").text, "I’ve been ")

    def test_paused(self):
        box = Box()
        box.tracker.enabled = False
        self.assertEqual(box.type("teh ").text, "teh ")

    def test_enter_starts_fresh(self):
        self.assertEqual(Box().type("ok\nteh ").text, "ok\nthe ")

    def test_quotes(self):
        self.assertEqual(Box().type('he said "teh" ').text, 'he said "the" ')


if __name__ == "__main__":
    unittest.main()
