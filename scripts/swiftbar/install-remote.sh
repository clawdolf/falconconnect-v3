#!/usr/bin/env bash
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/clawdolf/falconnect/main/scripts/swiftbar"
PLUGIN_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
CONFIG_DIR="$HOME/.config/falconconnect"
CONFIG_FILE="$CONFIG_DIR/bridge.env"
APPDIR="$HOME/Applications"

mkdir -p "$PLUGIN_DIR" "$CONFIG_DIR" "$APPDIR"

curl -fsSL "$REPO_RAW/fc-bridge.5s.py" -o "$PLUGIN_DIR/fc-bridge.5s.py"
curl -fsSL "$REPO_RAW/fc-bridge-action.py" -o "$PLUGIN_DIR/fc-bridge-action.py"
chmod +x "$PLUGIN_DIR/fc-bridge.5s.py" "$PLUGIN_DIR/fc-bridge-action.py"

if [ -n "${FC_MENU_BAR_TOKEN:-}" ]; then
  cat > "$CONFIG_FILE" <<EOF
FC_BASE_URL=${FC_BASE_URL:-https://falconnect.org}
FC_MENU_BAR_TOKEN=$FC_MENU_BAR_TOKEN
EOF
  chmod 600 "$CONFIG_FILE"
elif [ ! -f "$CONFIG_FILE" ]; then
  cat > "$CONFIG_FILE" <<'EOF'
FC_BASE_URL=https://falconnect.org
FC_MENU_BAR_TOKEN=paste-token-here
EOF
  chmod 600 "$CONFIG_FILE"
fi

if ! mdfind 'kMDItemCFBundleIdentifier == "com.ameba.SwiftBar"' >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew list --cask swiftbar >/dev/null 2>&1 || brew install --cask --appdir="$APPDIR" swiftbar || true
  fi
fi

if [ -d "$APPDIR/SwiftBar.app" ]; then
  open "$APPDIR/SwiftBar.app" || true
elif [ -d "/Applications/SwiftBar.app" ]; then
  open "/Applications/SwiftBar.app" || true
fi

cat <<EOF
Installed FalconConnect SwiftBar bridge controls for $USER.
Plugin: $PLUGIN_DIR/fc-bridge.5s.py
Config: $CONFIG_FILE
If SwiftBar asks for a plugin folder, choose:
$PLUGIN_DIR
EOF
