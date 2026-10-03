#!/bin/zsh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /usr/bin/open "$SCRIPT_DIR/ArkUnpacker-v5.2.0.app"
