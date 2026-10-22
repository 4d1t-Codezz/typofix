"""Decides whether a finished word is a typo and what it should be.

Like iMessage, it would rather leave a word alone than "fix" it wrong, so a word only changes when:
  - it's in the hand-written list of classic typos and missing apostrophes (teh, dont, recieve), or
  - it isn't a known word, and one known word is a clearly better match than every other.

Candidates come from a symmetric-delete index (the SymSpell trick): every target word is stored
under itself and each of its one-letter deletions, and a typed word looks itself up under its own
one- and two-letter deletions. That finds nearly every word within two edits in microseconds,
which matters because this runs inside the keyboard hook.
"""

import gzip
import math
import os
import re
import threading

DATA = os.path.join(os.path.dirname(__file__), "data")

# Only this many of the most common words are offered as corrections. Every word in the list
# still counts as spelled right; rarer ones just never get suggested.
TARGET_WORDS = 40000

# Words the dictionary lacks but people type all the time, so they never get "corrected".
SLANG = set("""
ok okay kk lol lmao lmfao rofl omg idk idc tbh btw imo imho ngl smh brb ttyl gtg irl fr rn lmk
ya yah yea yeah nah nope yep yup gonna wanna gotta kinda sorta dunno lemme gimme bruh bro sis
ty thx pls plz hmm hmmm haha hehe wtf tho cuz sus vibe vibes emoji emojis selfie selfies
google googled googling youtube youtuber instagram tiktok snapchat iphone ipad macbook wifi
app apps email emails emailed texting texted online covid zoom vs etc
""".split())

# Keyboard rows for spotting fat-finger substitutions (hitting a neighbouring key).
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_OFFSET = (0.0, 0.25, 0.75)
_POS = {ch: (x + _OFFSET[y], y) for y, row in enumerate(_ROWS) for x, ch in enumerate(row)}
_VOWELS = set("aeiouy")


def _adjacent(a, b):
    pa, pb = _POS.get(a), _POS.get(b)
    return bool(pa and pb) and math.hypot(pa[0] - pb[0], pa[1] - pb[1]) < 1.3


def _sub_cost(a, b):
    if a == b:
        return 0.0
    if _adjacent(a, b):
        return 0.5
    if a in _VOWELS and b in _VOWELS:
        return 0.6  # seperate / definate: the wrong vowel is a spelling slip, not a different word
    return 1.0


def _indel_cost(word, i, missing=False):
    """Cost of an extra or missing word[i]. Doubled letters (ocasion, untill) are cheap, and so is
    a vowel the typist skipped (wrld), since fast typing drops vowels far more than consonants."""
    ch = word[i]
    if (i > 0 and word[i - 1] == ch) or (i + 1 < len(word) and word[i + 1] == ch):
        return 0.4
    if missing and ch in _VOWELS:
        return 0.7
    return 1.0


def typo_cost(typed, word):
    """Damerau-Levenshtein distance weighted toward the mistakes people actually make."""
    n, m = len(typed), len(word)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = d[i - 1][0] + _indel_cost(typed, i - 1)
    for j in range(1, m + 1):
        d[0][j] = d[0][j - 1] + _indel_cost(word, j - 1, missing=True)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = min(d[i - 1][j] + _indel_cost(typed, i - 1),
                       d[i][j - 1] + _indel_cost(word, j - 1, missing=True),
                       d[i - 1][j - 1] + _sub_cost(typed[i - 1], word[j - 1]))
            if i > 1 and j > 1 and typed[i - 1] == word[j - 2] and typed[i - 2] == word[j - 1]:
                best = min(best, d[i - 2][j - 2] + 0.6)  # swapped letters: teh, recieve
            d[i][j] = best
    return d[n][m]


def _deletes(word, depth):
    out, frontier = set(), {word}
    for _ in range(depth):
        frontier = {w[:i] + w[i + 1:] for w in frontier for i in range(len(w)) if len(w) > 1}
        out |= frontier
    return out


def _load_typos():
    typos = {}
    with open(os.path.join(DATA, "typos.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if "->" in line:
                wrong, right = (part.strip() for part in line.split("->", 1))
                typos[wrong.lower()] = right
    return typos


def _max_cost(length):
    """How far a word of this length may be from its correction."""
    if length <= 3:
        return 0.6
    if length == 4:
        return 1.0
    if length <= 7:
        return 1.6
    return 2.0


# The winner must be at least this much more likely than the runner-up (log10 units, so 1.0 is
# "ten times more likely"), or the word is too ambiguous to touch.
MARGIN = 0.8
# One unit of typo_cost is worth this many orders of magnitude of word frequency.
EDIT_WEIGHT = 3.0

_REPEATS = re.compile(r"(.)\1\1")  # sooo, yesss: stretched on purpose
_LAUGH = re.compile(r"^(?:[ha]*h[ae]h[ha]*|(?:he)+h?|lo+l)$")

# A known word with one of these attached is a real word the list happens to lack (unhabitual,
# steamless). -ing, -ed and -s aren't here: the list already has those forms of common words,
# so "stoping" should still become "stopping".
PREFIXES = ("un", "re", "in", "im", "dis", "non", "anti", "sub", "pre", "over", "under", "mis", "de",
            "multi", "semi", "inter", "super", "out", "co")
SUFFIXES = ("ly", "ness", "ment", "ments", "ity", "able", "ible", "al", "ally", "ic", "ical", "less",
            "ful", "ish", "ism", "ist", "ists", "ize", "ise", "ization", "ation", "ive", "ship", "hood")
COMMON_WORDS = 20000  # how common both halves of a joined word (gunpower) must be


class Speller:
    def __init__(self, user_words=()):
        self.counts = {}
        with gzip.open(os.path.join(DATA, "words.txt.gz"), "rt", encoding="utf-8") as f:
            for line in f:
                word, _, count = line.partition(" ")
                self.counts[word] = int(count)
        self.typos = _load_typos()
        self.user_words = {w.lower() for w in user_words}
        self._lock = threading.Lock()
        ranked = list(self.counts)
        self.common = set(ranked[:COMMON_WORDS])
        self.index = {}
        for word in ranked[:TARGET_WORDS]:
            if len(word) < 2:
                continue
            for key in {word} | _deletes(word, 1):
                bucket = self.index.get(key)
                if bucket is None:
                    self.index[key] = word
                elif isinstance(bucket, str):
                    self.index[key] = [bucket, word]
                else:
                    bucket.append(word)

    # -- the user's own words (learned when they undo a fix, or added in the window)
    def learn(self, word):
        with self._lock:
            self.user_words.add(word.lower())

    def forget(self, word):
        with self._lock:
            self.user_words.discard(word.lower())

    def is_known(self, lw):
        if lw in self.counts or lw in SLANG or lw in self.user_words:
            return True
        if lw.endswith("'s") or lw.endswith("’s"):
            return self.is_known(lw[:-2])
        if lw.endswith("s") and len(lw) > 3 and (lw[:-1] in self.counts or lw[:-1] in self.user_words):
            return True  # plurals of words the list only has in the singular
        return self._derived(lw)

    def _derived(self, lw):
        """True for a word built from known parts: un+habitual, steam+less, gun+power."""
        for p in PREFIXES:
            if lw.startswith(p) and len(lw) - len(p) >= 4 and lw[len(p):] in self.counts:
                return True
        for sfx in SUFFIXES:
            stem = lw[:-len(sfx)]
            if lw.endswith(sfx) and len(stem) >= 4 and (stem in self.counts or stem + "e" in self.counts):
                return True
        if len(lw) >= 7:
            for i in range(3, len(lw) - 2):
                if lw[:i] in self.common and lw[i:] in self.common:
                    return True
        return False

    def suggest(self, lw):
        """The best correction for a lowercase unknown word, or None if nothing is clearly best."""
        keys = {lw} | _deletes(lw, 2 if len(lw) >= 5 else 1)
        found = set()
        for key in keys:
            bucket = self.index.get(key)
            if bucket is None:
                continue
            if isinstance(bucket, str):
                found.add(bucket)
            else:
                found.update(bucket)
        limit = _max_cost(len(lw))
        scored = []
        for cand in found:
            if abs(len(cand) - len(lw)) > 2:
                continue
            if len(lw) - len(cand) >= 2 and cand in lw:
                continue  # absolvent isn't a typo of solvent: chopping off letters makes a new word
            cost = typo_cost(lw, cand)
            if cost <= 2.0:
                scored.append((math.log10(self.counts[cand]) - EDIT_WEIGHT * cost, cost, cand))
        if not scored:
            return None
        scored.sort(reverse=True)
        score, cost, best = scored[0]
        if cost > limit:
            return None
        if len(scored) > 1 and score - scored[1][0] < MARGIN:
            return None
        return best

    def correct(self, word, sentence_start=True):
        """Returns the corrected word, or None to leave it alone. Keeps the word's capitalisation."""
        lw = word.lower().replace("’", "'")
        if word == "i":
            return "I"
        if lw in self.user_words:
            return None
        if len(word) > 1 and word.isupper():
            return None  # NASA, LOL: shouting or an acronym
        if any(ch.isupper() for ch in word[1:]):
            return None  # iPhone, McDonald, camelCase
        if lw in self.typos:
            fixed = self.typos[lw]
        else:
            if len(lw) < 3 or self.is_known(lw) or _REPEATS.search(lw) or _LAUGH.match(lw):
                return None
            if word[0].isupper() and not sentence_start:
                return None  # a capitalised unknown word mid-sentence is probably a name
            fixed = self.suggest(lw)
            if fixed is None:
                return None
        if word[0].isupper() and fixed[0].islower():
            fixed = fixed[0].upper() + fixed[1:]
        return fixed if fixed != word else None
