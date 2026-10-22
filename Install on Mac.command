#!/bin/bash
# Double-click this file to install Typofix on your Mac.
# It builds the app, puts it in your Applications folder and opens it.
# Run it again any time to update after downloading a newer version.

cd "$(dirname "$0")" || exit 1

echo "Installing Typofix..."
echo

./scripts/build-mac-app.sh
status=$?

if [ $status -eq 2 ]; then
  echo
  echo "Typofix needs Python 3.10 or newer, and this Mac doesn't have a version that works."
  read -r -p "Download and install it now? This takes about a minute. [Y/n] " answer
  case "$answer" in
    [nN]*)
      echo "Okay. Install Python from https://www.python.org/downloads/macos/ and run this again."
      exit 1
      ;;
  esac
  if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh || exit 1
  fi
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  "$UV" python install 3.12 || exit 1
  echo
  ./scripts/build-mac-app.sh
  status=$?
fi
[ $status -eq 0 ] || { echo; echo "Install failed (see the message above)."; exit 1; }

if [ -w /Applications ]; then DEST=/Applications; else DEST="$HOME/Applications"; fi
mkdir -p "$DEST"
osascript -e 'quit app "Typofix"' >/dev/null 2>&1
rm -rf "$DEST/Typofix.app"
cp -R "dist/Typofix.app" "$DEST/"

echo
echo "Done! Typofix is in $DEST. Opening it now..."
echo
echo "The first time, macOS asks for Accessibility access (so Typofix can fix what you type)."
echo "Turn Typofix on in System Settings > Privacy & Security > Accessibility."
echo "Typofix starts working by itself as soon as you do."
echo
echo "If you're updating: macOS treats the new build as a different app. Select Typofix in that"
echo "list, remove it with the minus button, then turn the new one on."
open "$DEST/Typofix.app"
