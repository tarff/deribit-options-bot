#!/bin/bash
# Control script for the options trading bot and dashboard services
# Run this ON the Raspberry Pi
#
# Usage: ./deploy/pi-control.sh [command] [service]
# Commands: start, stop, restart, status, logs, follow, enable, disable
# Services: bot, dashboard, all (default: all)

BOT_SERVICE="options-bot"
DASHBOARD_SERVICE="options-dashboard"

# Get project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Parse arguments
CMD="${1:-status}"
TARGET="${2:-all}"

# Helper function to run command on service(s)
run_on_services() {
    local action="$1"

    case "$TARGET" in
        bot)
            $action "$BOT_SERVICE"
            ;;
        dashboard)
            $action "$DASHBOARD_SERVICE"
            ;;
        all)
            $action "$BOT_SERVICE"
            $action "$DASHBOARD_SERVICE"
            ;;
        *)
            echo "Unknown service: $TARGET"
            echo "Use: bot, dashboard, or all"
            exit 1
            ;;
    esac
}

case "$CMD" in
    start)
        echo "Starting services..."
        run_on_services "sudo systemctl start"
        sleep 2
        run_on_services "sudo systemctl status --no-pager -l"
        ;;

    stop)
        echo "Stopping services..."
        run_on_services "sudo systemctl stop"
        echo "Stopped."
        ;;

    restart)
        echo "Restarting services..."
        run_on_services "sudo systemctl restart"
        sleep 2
        run_on_services "sudo systemctl status --no-pager -l"
        ;;

    status)
        echo "=== Service Status ==="
        echo ""
        echo "Trading Bot ($BOT_SERVICE):"
        sudo systemctl status $BOT_SERVICE --no-pager -l 2>/dev/null || echo "  Not installed"
        echo ""
        echo "Dashboard ($DASHBOARD_SERVICE):"
        sudo systemctl status $DASHBOARD_SERVICE --no-pager -l 2>/dev/null || echo "  Not installed"
        echo ""
        # Show dashboard URL
        PI_IP=$(hostname -I | awk '{print $1}')
        echo "Dashboard URL: http://$PI_IP:8000"
        ;;

    enable)
        echo "Enabling auto-start on boot..."
        run_on_services "sudo systemctl enable"
        echo "Enabled."
        ;;

    disable)
        echo "Disabling auto-start..."
        run_on_services "sudo systemctl disable"
        echo "Disabled."
        ;;

    logs)
        case "$TARGET" in
            bot)
                tail -n 100 "$PROJECT_DIR/logs/bot.log"
                ;;
            dashboard)
                tail -n 100 "$PROJECT_DIR/logs/dashboard.log"
                ;;
            all)
                echo "=== Bot Logs (last 50 lines) ==="
                tail -n 50 "$PROJECT_DIR/logs/bot.log" 2>/dev/null || echo "No bot logs yet"
                echo ""
                echo "=== Dashboard Logs (last 50 lines) ==="
                tail -n 50 "$PROJECT_DIR/logs/dashboard.log" 2>/dev/null || echo "No dashboard logs yet"
                ;;
        esac
        ;;

    follow)
        case "$TARGET" in
            bot)
                echo "Following bot logs... (Ctrl+C to stop)"
                tail -f "$PROJECT_DIR/logs/bot.log"
                ;;
            dashboard)
                echo "Following dashboard logs... (Ctrl+C to stop)"
                tail -f "$PROJECT_DIR/logs/dashboard.log"
                ;;
            all)
                echo "Following all logs... (Ctrl+C to stop)"
                tail -f "$PROJECT_DIR/logs/bot.log" "$PROJECT_DIR/logs/dashboard.log"
                ;;
        esac
        ;;

    journal)
        case "$TARGET" in
            bot)
                sudo journalctl -u $BOT_SERVICE -n 100 --no-pager
                ;;
            dashboard)
                sudo journalctl -u $DASHBOARD_SERVICE -n 100 --no-pager
                ;;
            all)
                echo "=== Bot Journal ==="
                sudo journalctl -u $BOT_SERVICE -n 50 --no-pager
                echo ""
                echo "=== Dashboard Journal ==="
                sudo journalctl -u $DASHBOARD_SERVICE -n 50 --no-pager
                ;;
        esac
        ;;

    backup)
        echo "Backing up databases..."
        cd "$PROJECT_DIR"
        "$PROJECT_DIR/venv/bin/python3" "$PROJECT_DIR/deploy/backup_db.py"
        ;;

    url)
        PI_IP=$(hostname -I | awk '{print $1}')
        echo "Dashboard URL:"
        echo "  http://$PI_IP:8000"
        echo "  http://$(hostname).local:8000"
        ;;

    *)
        echo "Options Trading Bot Control"
        echo ""
        echo "Usage: $0 [command] [service]"
        echo ""
        echo "Commands:"
        echo "  start    - Start service(s)"
        echo "  stop     - Stop service(s)"
        echo "  restart  - Restart service(s)"
        echo "  status   - Show service status (default)"
        echo "  enable   - Enable auto-start on boot"
        echo "  disable  - Disable auto-start"
        echo "  logs     - Show last 100 lines of logs"
        echo "  backup   - Backup databases (7-day rotation)"
        echo "  follow   - Follow logs in real-time"
        echo "  journal  - View systemd journal"
        echo "  url      - Show dashboard URL"
        echo ""
        echo "Services:"
        echo "  bot       - Trading bot only"
        echo "  dashboard - Dashboard only"
        echo "  all       - Both services (default)"
        echo ""
        echo "Examples:"
        echo "  $0 start           # Start both services"
        echo "  $0 restart bot     # Restart only the trading bot"
        echo "  $0 follow dashboard # Follow dashboard logs"
        echo "  $0 logs bot        # View bot logs"
        ;;
esac
