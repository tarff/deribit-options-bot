#!/bin/bash
# Sync project to Raspberry Pi via rsync
# Run this FROM your local machine (not the Pi)
#
# Usage: ./deploy/sync-to-pi.sh [pi-hostname-or-ip]
# Example: ./deploy/sync-to-pi.sh raspberrypi.local
# Example: ./deploy/sync-to-pi.sh 192.168.1.100

set -e

PI_HOST="${1:-raspberrypi.local}"
PI_USER="${PI_USER:-pi}"
REMOTE_DIR="/home/$PI_USER/options-trading-bot"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Syncing to Raspberry Pi ==="
echo "From: $PROJECT_DIR"
echo "To:   $PI_USER@$PI_HOST:$REMOTE_DIR"
echo ""

# Sync project (excluding venv, __pycache__, .git, etc)
rsync -avz --progress \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    --exclude '.mypy_cache/' \
    --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' \
    --exclude 'htmlcov/' \
    --exclude '*.egg-info/' \
    --exclude '.env' \
    --exclude 'data/*.db' \
    --exclude 'logs/' \
    "$PROJECT_DIR/" "$PI_USER@$PI_HOST:$REMOTE_DIR/"

echo ""
echo "=== Sync Complete ==="
echo ""
echo "SSH to the Pi and run setup:"
echo "  ssh $PI_USER@$PI_HOST"
echo "  cd $REMOTE_DIR"
echo "  chmod +x deploy/pi-setup.sh"
echo "  ./deploy/pi-setup.sh"
echo ""
