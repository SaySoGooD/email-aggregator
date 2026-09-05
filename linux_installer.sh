#!/usr/bin/env sh
# Standalone Linux installer for email-aggregator.
#
# This is the ONLY file a Linux user needs. It clones the source into a
# throwaway temp directory, builds the app there, installs the resulting
# binary into the user's profile, and deletes the cloned source afterwards —
# nothing but the installed program is left behind.
#
# Must be run ON Linux: PyInstaller does not cross-compile, so this can't
# produce a Linux binary from Windows (use windows_installer.bat there,
# which is a dev-side build script, not something end users run).
set -e

# Pinned to the tag matching THIS installer's release, not the moving main
# branch — otherwise a later commit to main would silently change what an
# already-published release builds when someone re-runs it. Bump this to
# match the tag whenever a new version's installer is published.
REPO_URL="https://github.com/SaySoGooD/email-aggregator.git"
VERSION_TAG="v0.1.0"

if [ "$(uname -s)" != "Linux" ]; then
    echo "This installs a Linux binary and must be run on Linux."
    exit 1
fi

if ! command -v git >/dev/null 2>&1; then
    echo "[git] not found. Install it first (e.g. sudo apt install git) and re-run."
    exit 1
fi

echo "=== email-aggregator: Linux install ==="

# --- 1. clone the source into a throwaway directory -------------------------
WORKDIR="$(mktemp -d)"
cleanup() {
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

echo "[clone] fetching $VERSION_TAG into a temp directory..."
git clone --branch "$VERSION_TAG" --depth 1 "$REPO_URL" "$WORKDIR"
cd "$WORKDIR"

# --- 2. uv --------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "[uv] not found, installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        echo "[uv] still not found after install. Open a new shell and re-run this script."
        exit 1
    fi
else
    echo "[uv] found: $(uv --version)"
fi

# --- 3. project dependencies ------------------------------------------------
echo "[uv sync] installing build dependencies..."
uv sync

# --- 4. system Qt/WebEngine libraries ---------------------------------------
# PySide6's QtWebEngine needs several shared libraries most minimal distros
# don't ship by default. Best-effort only: skipped if apt isn't the package
# manager, or if the user has no sudo — a missing lib will just show up as a
# runtime error when the app launches, not as a build failure.
if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    echo "[system libs] installing Qt WebEngine runtime dependencies via apt..."
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        libnss3 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 \
        libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
        libxfixes3 libxi6 libglib2.0-0 || true
else
    echo "[system libs] skipping (no apt-get/sudo) — install Qt WebEngine's runtime libraries manually if the app fails to start."
fi

# --- 5. PyInstaller build ----------------------------------------------------
echo "[pyinstaller] building executable..."
uv run pyinstaller --noconfirm --clean All-in-one-Email.spec

BUNDLE_DIR="dist/All-in-one-Email"
if [ ! -d "$BUNDLE_DIR" ]; then
    echo "[pyinstaller] expected output not found at $BUNDLE_DIR"
    exit 1
fi

# --- 6. install into the user's profile (no root needed) --------------------
INSTALL_DIR="$HOME/.local/opt/email-aggregator"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

echo "[install] copying bundle to $INSTALL_DIR..."
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$ICON_DIR"
cp -r "$BUNDLE_DIR"/. "$INSTALL_DIR"/
chmod +x "$INSTALL_DIR/All-in-one-Email"

ln -sf "$INSTALL_DIR/All-in-one-Email" "$BIN_DIR/email-aggregator"

cp "assets/icons/app.png" "$ICON_DIR/email-aggregator.png" 2>/dev/null || true

cat > "$DESKTOP_DIR/email-aggregator.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=All-in-one Email
Comment=Unified IMAP/SMTP mailbox client
Exec=$INSTALL_DIR/All-in-one-Email
Icon=email-aggregator
Terminal=false
Categories=Network;Email;
EOF

# --- 7. cleanup happens automatically via the EXIT trap ----------------------
# (removes $WORKDIR — the cloned source and build/dist scaffolding — leaving
# only the installed program under $INSTALL_DIR)

echo
echo "=== Done ==="
echo "Installed to: $INSTALL_DIR"
echo "Launch from your app menu (\"All-in-one Email\"), or run: email-aggregator"
echo "(make sure $BIN_DIR is on your PATH)"
