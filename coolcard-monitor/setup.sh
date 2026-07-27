#!/bin/bash
# Setup script for the Coolcard product monitor.
# Run once on the VM after cloning/pulling the repo:
#   cd ~/NotSoCoolCard/coolcard-monitor
#   bash setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="coolcard-monitor"
CURRENT_USER="$(whoami)"

echo "=== [1/4] Installing Python dependencies ==="
pip3 install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "=== [2/4] Checking .env file ==="
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo "  Created .env from .env.example"
    echo "  >>> ACTION REQUIRED: edit $SCRIPT_DIR/.env and set DISCORD_WEBHOOK_URL <<<"
else
    echo "  .env already exists — skipping"
fi

echo ""
echo "=== [3/4] Installing systemd service ==="
# Replace YOURUSER and YOURPATH placeholders with actual runtime values
sed \
    -e "s|YOURUSER|$CURRENT_USER|g" \
    -e "s|YOURPATH|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/$SERVICE_NAME.service" \
    | sudo tee "/etc/systemd/system/$SERVICE_NAME.service" > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo ""
echo "=== [4/4] Service status ==="
sudo systemctl status "$SERVICE_NAME" --no-pager -l

echo ""
echo "Done!"
echo "  View logs:       journalctl -u $SERVICE_NAME -f"
echo "  Stop monitor:    sudo systemctl stop $SERVICE_NAME"
echo "  Restart monitor: sudo systemctl restart $SERVICE_NAME"
