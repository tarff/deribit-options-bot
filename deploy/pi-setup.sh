#!/bin/bash
# Raspberry Pi setup script for options trading bot
# Run this ON the Raspberry Pi after copying the project

set -e

echo "=== Options Trading Bot - Raspberry Pi Setup ==="

# Check we're running on ARM (Pi)
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" && "$ARCH" != "armv7l" ]]; then
    echo "Warning: Not running on ARM architecture ($ARCH)"
    echo "This script is intended for Raspberry Pi"
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Update system
echo "Updating system packages..."
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv

# Check Python version (need 3.9+ for numpy)
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [[ $MAJOR -lt 3 || ($MAJOR -eq 3 && $MINOR -lt 9) ]]; then
    echo "Error: Python 3.9+ required, found $PYTHON_VERSION"
    echo "On Raspberry Pi OS Bullseye or later, Python 3.9+ should be available"
    exit 1
fi

echo "Python version: $PYTHON_VERSION"

# Get project directory (where this script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
echo "Project directory: $PROJECT_DIR"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Create data directory
mkdir -p data

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env template..."
    cat > .env << 'EOF'
# Trading Environment
# Use --config config/settings.testnet.yaml or config/settings.mainnet.yaml
TRADING_ENV=testnet

# Deribit Testnet Credentials (https://test.deribit.com/)
DERIBIT_TESTNET_API_KEY=your_testnet_key_here
DERIBIT_TESTNET_API_SECRET=your_testnet_secret_here

# Deribit Mainnet Credentials (https://www.deribit.com/)
DERIBIT_API_KEY=your_mainnet_key_here
DERIBIT_API_SECRET=your_mainnet_secret_here

# Telegram Notifications (optional)
# Create bot via @BotFather, get chat_id via @userinfobot
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
    echo ""
    echo "IMPORTANT: Edit .env file with your Deribit testnet API credentials"
    echo "  nano $PROJECT_DIR/.env"
fi

# Set up systemd service
echo "Setting up systemd service..."
SERVICE_FILE="/etc/systemd/system/options-bot.service"

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Options Trading Bot (Paper Trading)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/python scripts/run_paper_trading.py --config config/settings.testnet.yaml --interval 60
Restart=always
RestartSec=30

# Logging
StandardOutput=append:$PROJECT_DIR/logs/bot.log
StandardError=append:$PROJECT_DIR/logs/bot.log

# Resource limits (reasonable for Pi)
MemoryMax=512M
CPUQuota=50%

[Install]
WantedBy=multi-user.target
EOF

# Set up dashboard service (React + FastAPI)
echo "Setting up dashboard service..."
DASHBOARD_SERVICE="/etc/systemd/system/options-dashboard.service"

sudo tee "$DASHBOARD_SERVICE" > /dev/null << EOF
[Unit]
Description=Options Trading Dashboard (React + FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/dashboard/backend
Environment="PATH=$PROJECT_DIR/venv/bin"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$PROJECT_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

# Logging
StandardOutput=append:$PROJECT_DIR/logs/dashboard.log
StandardError=append:$PROJECT_DIR/logs/dashboard.log

# Resource limits
MemoryMax=256M
CPUQuota=30%

[Install]
WantedBy=multi-user.target
EOF

# Create logs directory
mkdir -p logs

# Set up logrotate for log management
echo "Setting up log rotation..."
sudo cp "$PROJECT_DIR/deploy/logrotate.conf" /etc/logrotate.d/options-bot
# Update path in logrotate config to match actual project dir
sudo sed -i "s|/home/pi/options-trading-bot|$PROJECT_DIR|g" /etc/logrotate.d/options-bot

# Set up daily database backup via cron (runs at 00:00 UTC)
echo "Setting up daily database backup..."
CRON_CMD="0 0 * * * $PROJECT_DIR/venv/bin/python3 $PROJECT_DIR/deploy/backup_db.py >> $PROJECT_DIR/logs/backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "backup_db.py"; echo "$CRON_CMD") | crontab -

# Reload systemd
sudo systemctl daemon-reload

# Get Pi's IP address for dashboard URL
PI_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit your API credentials:"
echo "   nano $PROJECT_DIR/.env"
echo ""
echo "2. Test the bot manually first:"
echo "   source venv/bin/activate"
echo "   python scripts/run_paper_trading.py --config config/settings.testnet.yaml --dry-run"
echo ""
echo "3. Start both services:"
echo "   sudo systemctl start options-bot options-dashboard"
echo ""
echo "4. Enable auto-start on boot:"
echo "   sudo systemctl enable options-bot options-dashboard"
echo ""
echo "5. Check status:"
echo "   ./deploy/pi-control.sh status"
echo ""
echo "6. View logs:"
echo "   tail -f logs/bot.log        # Trading bot"
echo "   tail -f logs/dashboard.log  # Dashboard"
echo ""
echo "7. Access dashboard from your browser:"
echo "   http://$PI_IP:8000"
echo "   http://$(hostname).local:8000"
echo ""
