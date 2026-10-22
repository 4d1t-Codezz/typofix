#!/bin/bash
# Builds "dist/Typofix.app", a double-clickable app that bundles the code and runs it with the
# Python you build it with. Most people should double-click "Install on Mac.command" instead,
# which runs this and puts the app in Applications.
# Usage:  ./scripts/build-mac-app.sh  [path/to/python3]
# Exits with status 2 when no suitable Python is found.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
CHECK='import sys, tkinter; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6; print(sys.executable)'

if [ $# -ge 1 ]; then
  if ! PY="$("$1" -c "$CHECK" 2>/dev/null)"; then
    echo "The Python at $1 needs to be 3.10+ with Tk 8.6+." >&2
    exit 1
  fi
else
  PY=""
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  for c in \
      "$("$UV" python find '>=3.10' 2>/dev/null || true)" \
      /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
      python3.13 python3.12 python3.11 python3.10 python3; do
    [ -n "$c" ] || continue
    if PY="$("$c" -c "$CHECK" 2>/dev/null)"; then break; fi
    PY=""
  done
  if [ -z "$PY" ]; then
    echo "No suitable Python found (needs 3.10+ with Tk 8.6+)." >&2
    echo "Install one from https://www.python.org/downloads/macos/, or: brew install uv && uv python install 3.12" >&2
    exit 2
  fi
fi
echo "Using $PY"

APP="$REPO/dist/Typofix.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"
cp -R "$REPO/typofix" "$APP/Contents/Resources/app/"
find "$APP/Contents/Resources/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
cp "$REPO/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

# The launcher runs Python inside the app's own process, so macOS files the Accessibility
# permission under Typofix (see mac-launcher.c). Without a C compiler, fall back to a script,
# which works but makes macOS ask on behalf of python3 instead.
LIBPY="$("$PY" -c 'import os, sysconfig as s; fw = s.get_config_var("PYTHONFRAMEWORKPREFIX"); ld = s.get_config_var("LDLIBRARY"); print(os.path.join(fw, ld) if fw else os.path.join(s.get_config_var("LIBDIR"), ld))')"
PYHOME="$("$PY" -c 'import sys; print(sys.base_prefix)')"
if [ -f "$LIBPY" ] && xcrun --find cc >/dev/null 2>&1; then
  cc -O2 -Wall -o "$APP/Contents/MacOS/Typofix" "$REPO/scripts/mac-launcher.c" \
    -DLIBPYTHON="\"$LIBPY\"" -DPYTHONHOME_DIR="\"$PYHOME\""
else
  echo "Note: no C compiler (install one with: xcode-select --install), so macOS will list the" >&2
  echo "permission under python3 instead of Typofix." >&2
  cat > "$APP/Contents/MacOS/Typofix" <<EOF
#!/bin/bash
cd "\$(dirname "\$0")/../Resources/app"
export TYPOFIX_APP="\$(cd ../../.. && pwd)"
exec "$PY" -m typofix "\$@"
EOF
  chmod +x "$APP/Contents/MacOS/Typofix"
fi

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key><string>Typofix</string>
	<key>CFBundleIconFile</key><string>AppIcon</string>
	<key>CFBundleIdentifier</key><string>local.typofix</string>
	<key>CFBundleName</key><string>Typofix</string>
	<key>CFBundleDisplayName</key><string>Typofix</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>1.0</string>
	<key>LSMinimumSystemVersion</key><string>11.0</string>
	<key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

xattr -cr "$APP" 2>/dev/null || true  # drop the download quarantine copied from a zipped repo
# Sign it (ad hoc) so macOS can tell it's the same app when you grant it permissions.
codesign --force --sign - --identifier local.typofix "$APP" >/dev/null 2>&1 || true
echo "Built: $APP"
