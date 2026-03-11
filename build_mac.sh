#!/usr/bin/env bash
set -eo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}▶${RESET}  $*"; }
success() { echo -e "${GREEN}✓${RESET}  $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $*"; }
error()   { echo -e "${RED}✗  $*${RESET}"; exit 1; }
header()  { echo -e "\n${BOLD}$*${RESET}"; }

header "QuickBench — macOS App Builder"
[[ "$(uname)" == "Darwin" ]] || error "Must run on macOS."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

for f in QuickBench.py QuickBench.spec QB.png QB.ico; do
    [[ -f "$f" ]] || error "Missing: $f"
done

PYTHON=$(command -v python3 || true)
[[ -n "$PYTHON" ]] || error "python3 not found."
info "Using Python: $($PYTHON --version)"

header "Step 1 — Installing Python dependencies"

install_pkg() {
    PKG=$1
    MOD=${2:-$1}
    if $PYTHON -c "import $MOD" 2>/dev/null; then
        success "$PKG already installed"
    else
        info "Installing $PKG..."
        $PYTHON -m pip install --quiet "$PKG"
        success "$PKG installed"
    fi
}

install_pkg pyinstaller
install_pkg psutil
install_pkg pillow PIL

header "Step 2 — Generating QB.icns"
ICONSET="QuickBench.iconset"
rm -rf "$ICONSET" && mkdir "$ICONSET"
$PYTHON - << 'EOF'
from PIL import Image
import os
src = Image.open("QB.png").convert("RGBA")
for name, size in [
    ("icon_16x16.png",16),("icon_16x16@2x.png",32),
    ("icon_32x32.png",32),("icon_32x32@2x.png",64),
    ("icon_128x128.png",128),("icon_128x128@2x.png",256),
    ("icon_256x256.png",256),("icon_256x256@2x.png",512),
    ("icon_512x512.png",512),("icon_512x512@2x.png",1024)]:
    src.resize((size,size),Image.LANCZOS).save(os.path.join("QuickBench.iconset",name),"PNG")
EOF
iconutil -c icns "$ICONSET" -o QB.icns && rm -rf "$ICONSET"
success "QB.icns created"

header "Step 3 — Building QuickBench.app"
rm -rf build dist
$PYTHON -m PyInstaller --clean --noconfirm QuickBench.spec
APP_PATH="dist/QuickBench.app"
[[ -d "$APP_PATH" ]] || error "Build failed."
success "QuickBench.app built"

header "Step 4 — Code signing"
codesign --force --deep --sign - "$APP_PATH" 2>/dev/null && success "Signed" || warn "Signing skipped"

header "Step 5 — Creating QuickBench.dmg"
STAGING="dist/dmg_staging"
FINAL_DMG="$SCRIPT_DIR/QuickBench.dmg"
rm -rf "$STAGING" && mkdir -p "$STAGING"
cp -r "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
rm -f "$FINAL_DMG"
hdiutil create -volname "QuickBench" -srcfolder "$STAGING" -ov -format UDZO -imagekey zlib-level=9 "$FINAL_DMG"
rm -rf "$STAGING"

header "Build complete!"
success "Output: $FINAL_DMG"
echo ""
echo "  To install: double-click QuickBench.dmg, drag to Applications"
warn "First launch: right-click the app → Open → Open (once only)"
