<p align="center"><img src="assets/icon.png" width="128" alt="Typofix icon"></p>

# Typofix

Fixes typos as you type, in every app, the way iMessage does. Type `teh ` and it becomes `the `
the moment you press space. It works on **macOS** and **Windows**.

- **Fixes as you go.** When you press space (or Enter at the end of a message), the word you just
  finished is checked. Typos like `recieve`, `pepole` and `wrld`, and missing apostrophes like
  `dont` and `im`, get fixed on the spot.
- **See it coming.** With previews on, a small bubble by your cursor shows the fix before it
  happens. Press **Esc** to keep your word instead. You can turn previews off.
- **Easy to undo.** Didn't want a fix? Press **backspace** right after it. Your word comes back,
  and Typofix remembers it and won't change it again.
- **Careful.** It only changes a word when one fix is clearly the right one, using the word
  before it to break ties (`hwo are` → *how*). It knows American and British spellings, and it
  leaves alone names, slang (`lol`, `gonna`), acronyms (`NASA`), stretched words (`sooo`),
  links, emails, `#hashtags` and code.
- **Private.** Everything runs on your computer. Nothing you type is saved or sent anywhere.

## Install

**1. Download it.** Click **[Download ZIP](https://github.com/4d1t-Codezz/typofix/archive/refs/heads/main.zip)**
(or the green **Code** button → **Download ZIP**), then open the ZIP to unzip it.

**2. Run the installer** in the unzipped folder:

| On a Mac | On Windows |
| --- | --- |
| Double-click **`Install on Mac.command`** | Double-click **`Install on Windows.bat`** |
| It puts **Typofix** in your Applications folder and opens it. If you don't have a suitable Python, it offers to install one for you. | It adds **Typofix** to your desktop and Start menu and opens it. If you don't have Python, it opens the download page. On the installer's first screen, tick **Add python.exe to PATH**, then run `Install on Windows.bat` again. |

**3. Mac only: allow Accessibility.** macOS asks the first time. Turn **Typofix** on in
**System Settings → Privacy & Security → Accessibility**, and Typofix starts working right away.

> **Updated and it's asking again?** macOS treats each new build as a different app. In that
> list, select **Typofix**, click **−** to remove it, then turn the new one on.

If macOS says the installer "can't be opened", right-click it, choose **Open**, then **Open** again.

## Using it

Typofix opens when you log in and runs in the background. Pick how it shows up under
**Settings → Live in**:

- **Menu bar** (Mac) or **Tray** (Windows), the default: just a small ✓ icon by the clock.
  Click it to pause, turn previews on or off, see recent fixes (click one to stop making it), or
  open the window.
- **Window**: a regular app with a Dock icon, which shows its window when it opens.

The window shows your recent fixes (hover one and click to keep the word you typed), the
words it leaves alone (add your own, or click × to remove one), and settings. Closing it just
hides it.

**Mac tip:** macOS has its own autocorrect, but it only works in some apps. It can stay on. If
the two ever fight over a word, turn the Mac one off in **System Settings → Keyboard → Text
Input → Edit → Correct spelling automatically**.

## How it works

- `typofix/speller.py` decides whether a word is a typo. It checks a list of 82,000 English words
  with how often each is used, plus a hand-written list of classic typos in
  [`typofix/data/typos.txt`](typofix/data/typos.txt), which you can add to. Possible fixes come
  from a SymSpell-style index of one-letter deletions, so checking a word takes about a
  millisecond. Fixes are ranked by how common the word is and how natural the slip is: hitting a
  neighbouring key, swapping two letters, missing a doubled letter or a vowel. When two fixes are
  about equally likely (`hwo`: *how* or *who*?), the word is left alone.
- The previous word matters too: a list of 240,000 common word pairs (also from SymSpell)
  decides close calls, like *how* vs *who* after "tell me".
- `typofix/tracker.py` follows what you type. It watches keys and clicks, and resets whenever
  the cursor might have moved (a click, an arrow key, a shortcut), so it never edits text it
  hasn't seen.
- `typofix/platforms/` talks to the OS using only Python's built-in `ctypes`, so there's nothing
  extra to install. On a Mac it uses a Quartz event tap; on Windows, a low-level keyboard hook.
  When a word needs fixing, Typofix holds back that space and sends a few backspaces plus the
  corrected word instead. On a Mac, the preview bubble is a native floating panel (so it never
  steals focus from the app you're typing in), and its position comes from the Accessibility
  API. On Windows it follows apps that show a standard text cursor, and otherwise sits at the
  bottom of the screen.
- `typofix/ui/` is the window, drawn on Tk canvases in the same style as
  [Docs Typer](https://github.com/4d1t-Codezz/docs-typer).

On a Mac, password fields switch on Secure Input, which hides your keys from every app,
Typofix included. A fix only ever happens when you press space, so passwords (which almost never
contain spaces) are safe on Windows too. Enter only triggers a fix when the line has a space in it.

## Development

Needs Python 3.10+ with Tk. There are no other dependencies.

```bash
python3 -m unittest discover -s tests -t .   # tests
python3 -m typofix                           # run from source
./scripts/build-mac-app.sh                   # build dist/Typofix.app
python3 scripts/make_icon.py                 # redraw the icons
```

The word lists are SymSpell's `frequency_dictionary_en_82_765.txt` and
`frequency_bigramdictionary_en_243_342.txt` by Wolf Garbe (MIT license).
Typofix itself is MIT licensed.
