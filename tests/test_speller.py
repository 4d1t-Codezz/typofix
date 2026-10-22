import unittest

from typofix.speller import Speller, typo_cost

SPELLER = Speller()


class SpellerTest(unittest.TestCase):
    def check(self, cases):
        for typed, want in cases.items():
            with self.subTest(typed=typed):
                self.assertEqual(SPELLER.correct(typed), want)

    def test_fixes_typos(self):
        self.check({"teh": "the", "recieve": "receive", "speling": "spelling", "langauge": "language",
                    "pepole": "people", "beautifull": "beautiful", "tihs": "this", "gerat": "great",
                    "wrld": "world", "runing": "running", "tge": "the"})

    def test_apostrophes_and_i(self):
        self.check({"dont": "don't", "im": "I'm", "i": "I", "youre": "you're", "i'm": "I'm"})

    def test_keeps_capital(self):
        self.check({"Teh": "The", "Dont": "Don't", "Recieve": "Receive"})

    def test_leaves_real_words_alone(self):
        for word in ("the", "their", "there", "form", "from", "lol", "okay", "gonna", "unhabitual",
                     "steamless", "dogs", "teacher's", "googled"):
            with self.subTest(word=word):
                self.assertIsNone(SPELLER.correct(word))

    def test_leaves_names_acronyms_and_stretched_words_alone(self):
        for word in ("iPhone", "NASA", "LOL", "sooo", "hahaha", "Aditya", "aditya"):
            with self.subTest(word=word):
                self.assertIsNone(SPELLER.correct(word, sentence_start=False))

    def test_american_spellings_are_words(self):
        for word in ("favorite", "labor", "neighbors", "analyze", "traveled", "theater", "mom", "color"):
            with self.subTest(word=word):
                self.assertIsNone(SPELLER.correct(word))

    def test_bounced_key(self):
        self.check({"worrrying": "worrying", "sooo": None, "yesss": None, "cooool": None})

    def test_previous_word_breaks_ties(self):
        self.assertEqual(SPELLER.correct("hwo", prev="tell"), "how")

    def test_ambiguous_words_are_left_alone(self):
        self.assertIsNone(SPELLER.correct("thnk"))  # think or thank?

    def test_user_words(self):
        s = Speller(["tge"])
        self.assertIsNone(s.correct("tge"))
        s.forget("tge")
        self.assertEqual(s.correct("tge"), "the")

    def test_cost_prefers_common_slips(self):
        self.assertLess(typo_cost("teh", "the"), typo_cost("tex", "the"))
        self.assertLess(typo_cost("runing", "running"), 1)


if __name__ == "__main__":
    unittest.main()
