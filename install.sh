#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME:-noaff-monitor}"
SERVICE_USER="${SERVICE_USER:-noaffmon}"
APP_DIR="${APP_DIR:-/opt/noaff-monitor}"
REPO_URL="${REPO_URL:-}"
APP_PORT="${APP_PORT:-7777}"
MONITOR_DEBUG_PORT="${MONITOR_DEBUG_PORT:-9223}"
TEST_DEBUG_PORT="${TEST_DEBUG_PORT:-9334}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-45}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-25}"
ADMIN_USERNAME="${ADMIN_USERNAME:-operator}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

if [[ "$(id -u)" != "0" ]]; then
  echo "Please run as root."
  exit 1
fi

if [[ -z "$REPO_URL" && ! -f "$APP_DIR/app.py" ]]; then
  echo "REPO_URL is required unless $APP_DIR already contains the app."
  echo "Example: REPO_URL=https://github.com/yourname/noaff-monitor.git bash install.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip git curl ca-certificates xvfb procps
apt-get install -y fonts-noto-cjk fonts-noto-color-emoji || true

if ! command -v chromium >/dev/null 2>&1; then
  apt-get install -y chromium || apt-get install -y chromium-browser || true
fi

CHROMIUM_BINARY="${CHROMIUM_BINARY:-$(command -v chromium || command -v chromium-browser || command -v google-chrome || true)}"
if [[ -z "$CHROMIUM_BINARY" ]]; then
  echo "Chromium was not found. Install chromium manually and rerun this script."
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if [[ -n "$REPO_URL" ]]; then
  if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" fetch --all --prune
    git -C "$APP_DIR" pull --ff-only
  elif [[ -e "$APP_DIR" && "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)" -gt 0 ]]; then
    echo "$APP_DIR exists and is not an empty git checkout. Move it away or set APP_DIR."
    exit 1
  else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone "$REPO_URL" "$APP_DIR"
  fi
fi

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements.txt

SECRET_KEY="${SECRET_KEY:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)}"

PORTAL_PATH="${PORTAL_PATH:-$(python3 - <<'PY'
import secrets
print('/portal_' + secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24])
PY
)}"

ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)}"

if [[ ! -f .env ]]; then
  cat > .env <<EOF
APP_PORT=$APP_PORT
PORTAL_PATH=$PORTAL_PATH
SECRET_KEY=$SECRET_KEY
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD=$ADMIN_PASSWORD
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
MONITOR_DEBUG_PORT=$MONITOR_DEBUG_PORT
TEST_DEBUG_PORT=$TEST_DEBUG_PORT
POLL_INTERVAL_SECONDS=$POLL_INTERVAL_SECONDS
REQUEST_TIMEOUT_SECONDS=$REQUEST_TIMEOUT_SECONDS
CHROMIUM_HEADLESS=true
CHROMIUM_BINARY=$CHROMIUM_BINARY
SESSION_COOKIE_SECURE=false
LOGIN_RATE_LIMIT=5 per minute
GENERAL_MUTATION_LIMIT=40 per minute
LIMITER_STORAGE_URI=memory://
EOF
fi

mkdir -p data
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

cat > "/etc/systemd/system/$APP_NAME.service" <<EOF
[Unit]
Description=NOAFF Restock Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=/usr/bin/xvfb-run -a --server-args="-screen 0 1920x1080x24" $APP_DIR/.venv/bin/python $APP_DIR/app.py
Restart=always
RestartSec=6
KillSignal=SIGTERM
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$APP_NAME"
systemctl restart "$APP_NAME"

if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi active; then
  ufw allow "$APP_PORT/tcp" || true
fi

echo
echo "NOAFF monitor is installed."
echo "Service: systemctl status $APP_NAME --no-pager"
echo "Logs:    journalctl -u $APP_NAME -f"
echo "URL:     http://YOUR_SERVER_IP:$APP_PORT$PORTAL_PATH"
echo "Admin:   $ADMIN_USERNAME"
if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
  echo "Password: $ADMIN_PASSWORD"
fi
echo "Change the password immediately after first login."
