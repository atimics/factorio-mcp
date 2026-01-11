#!/bin/bash

# Start Factorio with RCON enabled
# Usage: ./start_factorio.sh [save_file]

FACTORIO_DIR="/Applications/factorio.app/Contents/MacOS"
SAVE_DIR="$HOME/Library/Application Support/factorio/saves"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Default to most recent save if not specified
if [ -z "$1" ]; then
    SAVE_FILE=$(ls -t "$SAVE_DIR"/*.zip 2>/dev/null | head -1)
    if [ -z "$SAVE_FILE" ]; then
        echo "No save files found. Creating a new game..."
        SAVE_ARG="--create new-game"
    else
        echo "Using most recent save: $(basename "$SAVE_FILE")"
        SAVE_ARG="--start-server \"$SAVE_FILE\""
    fi
else
    SAVE_FILE="$SAVE_DIR/$1"
    if [ ! -f "$SAVE_FILE" ]; then
        echo "Save file not found: $SAVE_FILE"
        exit 1
    fi
    SAVE_ARG="--start-server \"$SAVE_FILE\""
fi

# Load RCON password from .env
source "$SCRIPT_DIR/.env" 2>/dev/null
RCON_PW="${RCON_PASSWORD:-factorio_mcp_password}"
RCON_PT="${RCON_PORT:-27015}"

echo "Starting Factorio server with RCON enabled..."
echo "RCON Port: $RCON_PT"
echo "RCON Password: $RCON_PW"

# Start Factorio with RCON
eval "$FACTORIO_DIR/factorio" \
    $SAVE_ARG \
    --server-settings "$SCRIPT_DIR/server-settings.json" \
    --rcon-port "$RCON_PT" \
    --rcon-password "$RCON_PW"
