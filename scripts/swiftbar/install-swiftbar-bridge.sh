#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="$HOME/Library/Application Support/SwiftBar/Plugins"
CONFIG_DIR="$HOME/.config/falconconnect"
CONFIG_FILE="$CONFIG_DIR/bridge.env"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$PLUGIN_DIR" "$CONFIG_DIR"
cp "$SCRIPT_DIR/fc-bridge.5s.py" "$PLUGIN_DIR/fc-bridge.5s.py"
cp "$SCRIPT_DIR/fc-bridge-action.py" "$PLUGIN_DIR/fc-bridge-action.py"
chmod +x "$PLUGIN_DIR/fc-bridge.5s.py" "$PLUGIN_DIR/fc-bridge-action.py"

if [ ! -f "$CONFIG_FILE" ]; then
  cat > "$CONFIG_FILE" <<'EOF'
FC_BASE_URL=https://falconnect.org
FC_MENU_BAR_TOKEN=paste-token-here
EOF
  chmod 600 "$CONFIG_FILE"
fi

cat <<EOF
Installed FalconConnect SwiftBar bridge controls.

Plugin:
  $PLUGIN_DIR/fc-bridge.5s.py
Action helper:
  $PLUGIN_DIR/fc-bridge-action.py
Config:
  $CONFIG_FILE

Next steps:
  1. Set FC_MENU_BAR_TOKEN in Render for FalconConnect.
  2. Put the same token in $CONFIG_FILE.
  3. Open SwiftBar and choose Refresh All.
EOF
