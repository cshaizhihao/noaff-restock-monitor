#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME:-noaff-monitor}"
SERVICE_USER="${SERVICE_USER:-noaffmon}"
APP_DIR="${APP_DIR:-/opt/noaff-monitor}"
REPO_URL="${REPO_URL:-https://github.com/cshaizhihao/noaff-restock-monitor.git}"
REPO_REF="${REPO_REF:-master}"
GIT_AUTH_TOKEN="${GIT_AUTH_TOKEN:-${GH_TOKEN:-}}"

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-7777}"
PUBLIC_HTTP_PORT="${PUBLIC_HTTP_PORT:-80}"
PUBLIC_HTTPS_PORT="${PUBLIC_HTTPS_PORT:-443}"

MONITOR_DEBUG_PORT="${MONITOR_DEBUG_PORT:-9223}"
TEST_DEBUG_PORT="${TEST_DEBUG_PORT:-9334}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-45}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-25}"

ADMIN_USERNAME="${ADMIN_USERNAME:-operator}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
SECRET_KEY="${SECRET_KEY:-}"
PORTAL_PATH="${PORTAL_PATH:-}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

FQDN="${FQDN:-}"
TLS_DOMAINS="${TLS_DOMAINS:-}"
CF_ZONE_NAME="${CF_ZONE_NAME:-}"
CF_ZONE_ID="${CF_ZONE_ID:-}"
CF_API_TOKEN="${CF_API_TOKEN:-}"
CF_RECORD_PROXIED="${CF_RECORD_PROXIED:-true}"
CF_SSL_MODE="${CF_SSL_MODE:-strict}"
CF_DNS_PROPAGATION_SECONDS="${CF_DNS_PROPAGATION_SECONDS:-60}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
LETSENCRYPT_STAGING="${LETSENCRYPT_STAGING:-false}"
ORIGIN_IPV4="${ORIGIN_IPV4:-}"
ORIGIN_IPV6="${ORIGIN_IPV6:-}"
ORIGIN_LOCKDOWN_TO_CLOUDFLARE="${ORIGIN_LOCKDOWN_TO_CLOUDFLARE:-true}"

CHROMIUM_BINARY="${CHROMIUM_BINARY:-}"
CHROMIUM_HEADLESS="${CHROMIUM_HEADLESS:-true}"

LIMITER_STORAGE_URI="${LIMITER_STORAGE_URI:-redis://127.0.0.1:6379/0}"
SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-true}"
ENABLE_PROXY_FIX="${ENABLE_PROXY_FIX:-true}"
PROXY_FIX_X_FOR="${PROXY_FIX_X_FOR:-1}"
PROXY_FIX_X_PROTO="${PROXY_FIX_X_PROTO:-1}"
PROXY_FIX_X_HOST="${PROXY_FIX_X_HOST:-1}"
PROXY_FIX_X_PORT="${PROXY_FIX_X_PORT:-1}"

CF_CREDENTIALS_PATH="/root/.secrets/certbot/cloudflare.ini"
CF_REALIP_SNIPPET="/etc/nginx/snippets/noaff-cloudflare-realip.conf"
CF_ALLOW_SNIPPET="/etc/nginx/snippets/noaff-cloudflare-allow.conf"
SSL_SNIPPET="/etc/nginx/snippets/noaff-monitor-ssl.conf"
NGINX_SITE_PATH="/etc/nginx/sites-available/${APP_NAME}.conf"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/${APP_NAME}.conf"
CERTBOT_VENV="/opt/certbot"
CERTBOT_BIN="${CERTBOT_VENV}/bin/certbot"
CERTBOT_RENEW_SCRIPT="/usr/local/bin/${APP_NAME}-cert-renew.sh"
CERTBOT_RENEW_SERVICE="/etc/systemd/system/${APP_NAME}-cert-renew.service"
CERTBOT_RENEW_TIMER="/etc/systemd/system/${APP_NAME}-cert-renew.timer"
CF_SUPPORTED_HTTP_PORTS=(80 8080 8880 2052 2082 2086 2095)
CF_SUPPORTED_HTTPS_PORTS=(443 2053 2083 2087 2096 8443)

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

warn() {
  printf '\n[WARN] %s\n' "$*" >&2
}

die() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

bool_is_true() {
  [[ "${1,,}" == "1" || "${1,,}" == "true" || "${1,,}" == "yes" || "${1,,}" == "on" ]]
}

port_in_list() {
  local port="$1"
  shift
  local candidate
  for candidate in "$@"; do
    [[ "$candidate" == "$port" ]] && return 0
  done
  return 1
}

require_root() {
  [[ "$(id -u)" == "0" ]] || die "Please run as root."
}

urlencode() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import quote
print(quote(sys.argv[1], safe=''))
PY
}

random_token() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
}

random_portal_path() {
  python3 - <<'PY'
import secrets
print('/portal_' + secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24])
PY
}

read_env_value() {
  local key="$1"
  local env_file="${2:-$APP_DIR/.env}"
  [[ -f "$env_file" ]] || return 0
  python3 - "$env_file" "$key" <<'PY'
import pathlib
import sys

path, key = sys.argv[1:]
value = ""
for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    left, right = stripped.split("=", 1)
    if left.strip() == key:
        value = right.strip()
print(value)
PY
}

prefer_existing_value() {
  local var_name="$1"
  local default_value="$2"
  local existing_value
  existing_value="$(read_env_value "$var_name")"
  [[ -n "$existing_value" ]] || return 0
  if [[ -z "${!var_name:-}" || "${!var_name}" == "$default_value" ]]; then
    printf -v "$var_name" '%s' "$existing_value"
  fi
}

load_existing_env_defaults() {
  [[ -f "$APP_DIR/.env" ]] || return 0

  prefer_existing_value "APP_HOST" "127.0.0.1"
  prefer_existing_value "APP_PORT" "7777"
  prefer_existing_value "ADMIN_USERNAME" "operator"
  prefer_existing_value "MONITOR_DEBUG_PORT" "9223"
  prefer_existing_value "TEST_DEBUG_PORT" "9334"
  prefer_existing_value "POLL_INTERVAL_SECONDS" "45"
  prefer_existing_value "REQUEST_TIMEOUT_SECONDS" "25"
  prefer_existing_value "CHROMIUM_HEADLESS" "true"
  prefer_existing_value "CHROMIUM_BINARY" ""
  prefer_existing_value "SESSION_COOKIE_SECURE" "true"
  prefer_existing_value "ENABLE_PROXY_FIX" "true"
  prefer_existing_value "PROXY_FIX_X_FOR" "1"
  prefer_existing_value "PROXY_FIX_X_PROTO" "1"
  prefer_existing_value "PROXY_FIX_X_HOST" "1"
  prefer_existing_value "PROXY_FIX_X_PORT" "1"
  prefer_existing_value "LIMITER_STORAGE_URI" "redis://127.0.0.1:6379/0"

  [[ -n "$SECRET_KEY" ]] || SECRET_KEY="$(read_env_value "SECRET_KEY")"
  [[ -n "$PORTAL_PATH" ]] || PORTAL_PATH="$(read_env_value "PORTAL_PATH")"
  [[ -n "$ADMIN_PASSWORD" ]] || ADMIN_PASSWORD="$(read_env_value "ADMIN_PASSWORD")"
  [[ -n "$TELEGRAM_BOT_TOKEN" ]] || TELEGRAM_BOT_TOKEN="$(read_env_value "TELEGRAM_BOT_TOKEN")"
  [[ -n "$TELEGRAM_CHAT_ID" ]] || TELEGRAM_CHAT_ID="$(read_env_value "TELEGRAM_CHAT_ID")"
}

clone_url_with_token() {
  local url="$1"
  local token="$2"
  if [[ -z "$token" ]]; then
    printf '%s' "$url"
    return
  fi
  if [[ "$url" =~ ^https://github\.com/ ]]; then
    printf '%s' "${url/https:\/\//https:\/\/x-access-token:${token}@}"
    return
  fi
  printf '%s' "$url"
}

sanitize_git_remote() {
  local url="$1"
  if [[ "$url" =~ ^https://x-access-token:.*@github\.com/ ]]; then
    printf '%s' "$(printf '%s' "$url" | sed -E 's#https://x-access-token:[^@]+@#https://#')"
    return
  fi
  printf '%s' "$url"
}

apt_install() {
  apt-get install -y "$@"
}

validate_port() {
  local label="$1"
  local value="$2"
  local minimum="$3"
  local maximum="$4"
  [[ "$value" =~ ^[0-9]+$ ]] || die "${label} must be an integer."
  (( value >= minimum && value <= maximum )) || die "${label} must be between ${minimum} and ${maximum}."
}

validate_runtime_config() {
  validate_port "APP_PORT" "$APP_PORT" 1024 65535
  validate_port "PUBLIC_HTTP_PORT" "$PUBLIC_HTTP_PORT" 1 65535
  validate_port "PUBLIC_HTTPS_PORT" "$PUBLIC_HTTPS_PORT" 1 65535
  validate_port "MONITOR_DEBUG_PORT" "$MONITOR_DEBUG_PORT" 1024 65535
  validate_port "TEST_DEBUG_PORT" "$TEST_DEBUG_PORT" 1024 65535

  [[ "$MONITOR_DEBUG_PORT" != "$TEST_DEBUG_PORT" ]] || die "MONITOR_DEBUG_PORT and TEST_DEBUG_PORT must be different."
  [[ "$MONITOR_DEBUG_PORT" != "$APP_PORT" ]] || die "MONITOR_DEBUG_PORT must not reuse APP_PORT."
  [[ "$TEST_DEBUG_PORT" != "$APP_PORT" ]] || die "TEST_DEBUG_PORT must not reuse APP_PORT."

  if bool_is_true "$CF_RECORD_PROXIED"; then
    port_in_list "$PUBLIC_HTTP_PORT" "${CF_SUPPORTED_HTTP_PORTS[@]}" || die "PUBLIC_HTTP_PORT=${PUBLIC_HTTP_PORT} is not supported by Cloudflare orange-cloud proxy. Supported HTTP ports: ${CF_SUPPORTED_HTTP_PORTS[*]}"
    port_in_list "$PUBLIC_HTTPS_PORT" "${CF_SUPPORTED_HTTPS_PORTS[@]}" || die "PUBLIC_HTTPS_PORT=${PUBLIC_HTTPS_PORT} is not supported by Cloudflare orange-cloud proxy. Supported HTTPS ports: ${CF_SUPPORTED_HTTPS_PORTS[*]}"
  fi
}

ensure_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt_install git curl ca-certificates nginx redis-server xvfb procps python3 python3-venv python3-pip python3-dev build-essential libssl-dev libffi-dev
  apt_install fonts-noto-cjk fonts-noto-color-emoji || true
}

ensure_browser() {
  if ! command_exists chromium && ! command_exists chromium-browser && ! command_exists google-chrome; then
    apt_install chromium || apt_install chromium-browser || true
  fi
  if [[ -z "$CHROMIUM_BINARY" ]]; then
    CHROMIUM_BINARY="$(command -v chromium || command -v chromium-browser || command -v google-chrome || true)"
  fi
  [[ -n "$CHROMIUM_BINARY" ]] || die "Chromium was not found. Install chromium manually and rerun this script."
}

ensure_service_user() {
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
}

clone_or_update_repo() {
  local clone_url="$REPO_URL"
  local clean_url="$REPO_URL"
  if [[ -z "$REPO_URL" && ! -f "$APP_DIR/app.py" ]]; then
    die "REPO_URL is required unless $APP_DIR already contains the app."
  fi

  if [[ -n "$clone_url" ]]; then
    clone_url="$(clone_url_with_token "$clone_url" "$GIT_AUTH_TOKEN")"
    clean_url="$(sanitize_git_remote "$REPO_URL")"
  fi

  if [[ -d "$APP_DIR/.git" ]]; then
    log "Updating existing checkout in $APP_DIR"
    if [[ -n "$GIT_AUTH_TOKEN" ]]; then
      git -C "$APP_DIR" remote set-url origin "$clone_url"
    fi
    git -C "$APP_DIR" fetch --all --prune
    git -C "$APP_DIR" checkout "$REPO_REF"
    git -C "$APP_DIR" pull --ff-only origin "$REPO_REF"
    if [[ -n "$clean_url" ]]; then
      git -C "$APP_DIR" remote set-url origin "$clean_url"
    fi
  elif [[ -n "$REPO_URL" ]]; then
    if [[ -e "$APP_DIR" && "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)" -gt 0 ]]; then
      die "$APP_DIR exists and is not an empty git checkout. Move it away or set APP_DIR."
    fi
    mkdir -p "$(dirname "$APP_DIR")"
    log "Cloning repository into $APP_DIR"
    git clone --branch "$REPO_REF" "$clone_url" "$APP_DIR"
  fi

  if [[ -d "$APP_DIR/.git" && -n "$clean_url" ]]; then
    git -C "$APP_DIR" remote set-url origin "$clean_url"
  fi
}

setup_python_env() {
  cd "$APP_DIR"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip setuptools wheel
  .venv/bin/pip install -r requirements.txt
}

setup_certbot_env() {
  python3 -m venv "$CERTBOT_VENV"
  "$CERTBOT_VENV/bin/pip" install --upgrade pip setuptools wheel
  "$CERTBOT_VENV/bin/pip" install certbot certbot-dns-cloudflare
}

detect_origin_ips() {
  if [[ -z "$ORIGIN_IPV4" ]]; then
    ORIGIN_IPV4="$(curl -4fsSL --connect-timeout 8 --max-time 20 https://api.ipify.org || true)"
  fi
  if [[ -z "$ORIGIN_IPV6" ]]; then
    ORIGIN_IPV6="$(curl -6fsSL --connect-timeout 8 --max-time 20 https://api64.ipify.org || true)"
  fi
  [[ -n "$ORIGIN_IPV4" || -n "$ORIGIN_IPV6" ]] || die "Could not detect ORIGIN_IPV4 / ORIGIN_IPV6 automatically. Set ORIGIN_IPV4 and rerun."
}

cf_api() {
  local method="$1"
  local endpoint="$2"
  local payload="${3:-}"
  local url="https://api.cloudflare.com/client/v4${endpoint}"

  if [[ -n "$payload" ]]; then
    curl -fsSL -X "$method" "$url" \
      --retry 3 \
      --connect-timeout 10 \
      --max-time 60 \
      -H "Authorization: Bearer ${CF_API_TOKEN}" \
      -H "Content-Type: application/json" \
      --data "$payload"
  else
    curl -fsSL -X "$method" "$url" \
      --retry 3 \
      --connect-timeout 10 \
      --max-time 60 \
      -H "Authorization: Bearer ${CF_API_TOKEN}" \
      -H "Content-Type: application/json"
  fi
}

resolve_zone_id() {
  [[ -n "$CF_API_TOKEN" ]] || die "CF_API_TOKEN is required for Cloudflare DNS and certificate automation."
  [[ -n "$CF_ZONE_ID" || -n "$CF_ZONE_NAME" ]] || die "Set CF_ZONE_NAME or CF_ZONE_ID."

  if [[ -n "$CF_ZONE_ID" ]]; then
    return
  fi

  local encoded_zone
  encoded_zone="$(urlencode "$CF_ZONE_NAME")"
  local response
  response="$(cf_api GET "/zones?name=${encoded_zone}&status=active&per_page=1")"
  CF_ZONE_ID="$(printf '%s' "$response" | python3 - <<'PY'
import json, sys
data = json.load(sys.stdin)
result = data.get("result") or []
print(result[0]["id"] if result else "")
PY
)"
  [[ -n "$CF_ZONE_ID" ]] || die "Cloudflare zone '${CF_ZONE_NAME}' was not found or is not active. Add the zone to Cloudflare and point your nameservers first."
}

upsert_dns_record() {
  local record_name="$1"
  local record_type="$2"
  local record_content="$3"
  local proxied_json="false"
  bool_is_true "$CF_RECORD_PROXIED" && proxied_json="true"

  local encoded_name
  encoded_name="$(urlencode "$record_name")"
  local lookup
  lookup="$(cf_api GET "/zones/${CF_ZONE_ID}/dns_records?type=${record_type}&name=${encoded_name}&per_page=1")"
  local record_id
  record_id="$(printf '%s' "$lookup" | python3 - <<'PY'
import json, sys
data = json.load(sys.stdin)
result = data.get("result") or []
print(result[0]["id"] if result else "")
PY
)"

  local payload
  payload="$(python3 - "$record_type" "$record_name" "$record_content" "$proxied_json" <<'PY'
import json, sys
record_type, record_name, record_content, proxied = sys.argv[1:]
print(json.dumps({
    "type": record_type,
    "name": record_name,
    "content": record_content,
    "ttl": 1,
    "proxied": proxied.lower() == "true",
}))
PY
)"

  if [[ -n "$record_id" ]]; then
    log "Updating Cloudflare ${record_type} record for ${record_name}"
    cf_api PUT "/zones/${CF_ZONE_ID}/dns_records/${record_id}" "$payload" >/dev/null
  else
    log "Creating Cloudflare ${record_type} record for ${record_name}"
    cf_api POST "/zones/${CF_ZONE_ID}/dns_records" "$payload" >/dev/null
  fi
}

configure_cloudflare_dns() {
  [[ -n "$FQDN" ]] || die "FQDN is required."
  resolve_zone_id
  detect_origin_ips

  local domain_name
  while IFS= read -r domain_name; do
    [[ -n "$domain_name" ]] || continue
    [[ -n "$ORIGIN_IPV4" ]] && upsert_dns_record "$domain_name" "A" "$ORIGIN_IPV4"
    [[ -n "$ORIGIN_IPV6" ]] && upsert_dns_record "$domain_name" "AAAA" "$ORIGIN_IPV6"
  done < <(iter_tls_domains)

  if [[ -n "$CF_SSL_MODE" ]]; then
    local ssl_payload
    ssl_payload="$(python3 - "$CF_SSL_MODE" <<'PY'
import json, sys
print(json.dumps({"value": sys.argv[1]}))
PY
)"
    if ! cf_api PATCH "/zones/${CF_ZONE_ID}/settings/ssl" "$ssl_payload" >/dev/null 2>&1; then
      warn "Could not set Cloudflare SSL mode to '${CF_SSL_MODE}'. Add Zone Settings:Edit permission or configure SSL mode manually."
    fi
  fi
}

write_cloudflare_credentials() {
  mkdir -p "$(dirname "$CF_CREDENTIALS_PATH")"
  cat > "$CF_CREDENTIALS_PATH" <<EOF
dns_cloudflare_api_token = ${CF_API_TOKEN}
EOF
  chmod 600 "$CF_CREDENTIALS_PATH"
}

build_tls_domains() {
  if [[ -n "$TLS_DOMAINS" ]]; then
    printf '%s' "$TLS_DOMAINS"
    return
  fi
  printf '%s' "$FQDN"
}

iter_tls_domains() {
  python3 - "$(build_tls_domains)" <<'PY'
import sys

seen = set()
for raw in sys.argv[1].split(","):
    domain = raw.strip()
    if not domain or domain in seen:
        continue
    seen.add(domain)
    print(domain)
PY
}

issue_certificate() {
  [[ -n "$CERTBOT_EMAIL" ]] || die "CERTBOT_EMAIL is required for Let's Encrypt."
  write_cloudflare_credentials

  local domains_csv
  domains_csv="$(build_tls_domains)"
  local args=()
  IFS=',' read -r -a domain_items <<< "$domains_csv"
  for domain in "${domain_items[@]}"; do
    domain="$(printf '%s' "$domain" | xargs)"
    [[ -n "$domain" ]] && args+=("-d" "$domain")
  done
  [[ "${#args[@]}" -gt 0 ]] || die "No valid TLS domains were provided."

  local primary_domain
  primary_domain="$(printf '%s' "$domains_csv" | cut -d',' -f1 | xargs)"

  if [[ -f "/etc/letsencrypt/live/${primary_domain}/fullchain.pem" ]]; then
    log "Existing certificate found for ${primary_domain}; running keep-until-expiring renewal check"
  else
    log "Issuing initial Let's Encrypt certificate for ${domains_csv}"
  fi

  local extra_flags=()
  bool_is_true "$LETSENCRYPT_STAGING" && extra_flags+=(--staging)

  "$CERTBOT_BIN" certonly \
    --dns-cloudflare \
    --dns-cloudflare-credentials "$CF_CREDENTIALS_PATH" \
    --dns-cloudflare-propagation-seconds "$CF_DNS_PROPAGATION_SECONDS" \
    --agree-tos \
    --non-interactive \
    --keep-until-expiring \
    --preferred-challenges dns \
    -m "$CERTBOT_EMAIL" \
    "${extra_flags[@]}" \
    "${args[@]}"
}

fetch_cloudflare_ips() {
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 60 https://api.cloudflare.com/client/v4/ips
}

write_cloudflare_nginx_snippets() {
  local ip_json
  ip_json="$(fetch_cloudflare_ips)"
  mkdir -p /etc/nginx/snippets

  printf '%s' "$ip_json" | python3 - "$CF_REALIP_SNIPPET" "$CF_ALLOW_SNIPPET" <<'PY'
import json
import sys

realip_path, allow_path = sys.argv[1:]
payload = json.load(sys.stdin)
result = payload.get("result") or {}
cidrs = list(result.get("ipv4_cidrs") or []) + list(result.get("ipv6_cidrs") or [])

with open(realip_path, "w", encoding="utf-8") as fh:
    fh.write("real_ip_header CF-Connecting-IP;\n")
    fh.write("real_ip_recursive on;\n")
    for cidr in cidrs:
        fh.write(f"set_real_ip_from {cidr};\n")

with open(allow_path, "w", encoding="utf-8") as fh:
    for cidr in cidrs:
        fh.write(f"allow {cidr};\n")
    fh.write("allow 127.0.0.1;\n")
    fh.write("allow ::1;\n")
    fh.write("deny all;\n")
PY

  cat > "$SSL_SNIPPET" <<'EOF'
ssl_session_timeout 1d;
ssl_session_cache shared:SSL:10m;
ssl_session_tickets off;
ssl_protocols TLSv1.2 TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers HIGH:!aNULL:!MD5;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "same-origin" always;
EOF
}

configure_nginx() {
  local domains_csv primary_domain
  domains_csv="$(build_tls_domains)"
  primary_domain="$(printf '%s' "$domains_csv" | cut -d',' -f1 | xargs)"
  local server_names
  server_names="$(printf '%s' "$domains_csv" | tr ',' ' ')"
  local redirect_target="https://\$host"
  if [[ "$PUBLIC_HTTPS_PORT" != "443" ]]; then
    redirect_target="${redirect_target}:${PUBLIC_HTTPS_PORT}"
  fi

  mkdir -p /var/www/html

  cat > "$NGINX_SITE_PATH" <<EOF
server {
    listen ${PUBLIC_HTTP_PORT};
    listen [::]:${PUBLIC_HTTP_PORT};
    server_name ${server_names};
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_REALIP_SNIPPET")
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_ALLOW_SNIPPET")

    location / {
        return 301 ${redirect_target}\$request_uri;
    }
}

server {
    listen ${PUBLIC_HTTPS_PORT} ssl http2;
    listen [::]:${PUBLIC_HTTPS_PORT} ssl http2;
    server_name ${server_names};

    ssl_certificate /etc/letsencrypt/live/${primary_domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${primary_domain}/privkey.pem;
    include ${SSL_SNIPPET};
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_REALIP_SNIPPET")
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_ALLOW_SNIPPET")

    client_max_body_size 2m;

    location / {
        proxy_pass http://${APP_HOST}:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port ${PUBLIC_HTTPS_PORT};
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 90;
    }
}
EOF

  rm -f /etc/nginx/sites-enabled/default
  ln -sf "$NGINX_SITE_PATH" "$NGINX_SITE_LINK"
  nginx -t
  systemctl enable nginx
  systemctl restart nginx
}

write_env_file() {
  [[ -n "$SECRET_KEY" ]] || SECRET_KEY="$(random_token)"
  [[ -n "$PORTAL_PATH" ]] || PORTAL_PATH="$(random_portal_path)"
  [[ -n "$ADMIN_PASSWORD" ]] || ADMIN_PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)"

  cat > "$APP_DIR/.env" <<EOF
APP_HOST=${APP_HOST}
APP_PORT=${APP_PORT}
PORTAL_PATH=${PORTAL_PATH}
SECRET_KEY=${SECRET_KEY}
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
MONITOR_DEBUG_PORT=${MONITOR_DEBUG_PORT}
TEST_DEBUG_PORT=${TEST_DEBUG_PORT}
POLL_INTERVAL_SECONDS=${POLL_INTERVAL_SECONDS}
REQUEST_TIMEOUT_SECONDS=${REQUEST_TIMEOUT_SECONDS}
CHROMIUM_HEADLESS=${CHROMIUM_HEADLESS}
CHROMIUM_BINARY=${CHROMIUM_BINARY}
SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE}
ENABLE_PROXY_FIX=${ENABLE_PROXY_FIX}
PROXY_FIX_X_FOR=${PROXY_FIX_X_FOR}
PROXY_FIX_X_PROTO=${PROXY_FIX_X_PROTO}
PROXY_FIX_X_HOST=${PROXY_FIX_X_HOST}
PROXY_FIX_X_PORT=${PROXY_FIX_X_PORT}
LOGIN_RATE_LIMIT=5 per minute
GENERAL_MUTATION_LIMIT=40 per minute
LIMITER_STORAGE_URI=${LIMITER_STORAGE_URI}
EOF

  chmod 600 "$APP_DIR/.env"
}

write_app_service() {
  cat > "/etc/systemd/system/${APP_NAME}.service" <<EOF
[Unit]
Description=NOAFF Restock Monitor
After=network-online.target redis-server.service
Wants=network-online.target redis-server.service

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=/usr/bin/xvfb-run -a --server-args="-screen 0 1920x1080x24" ${APP_DIR}/.venv/bin/python ${APP_DIR}/app.py
Restart=always
RestartSec=6
KillSignal=SIGTERM
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${APP_DIR}

[Install]
WantedBy=multi-user.target
EOF
}

write_certbot_renewal_units() {
  cat > "$CERTBOT_RENEW_SCRIPT" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
${CERTBOT_BIN} renew --quiet --deploy-hook "systemctl reload nginx"
EOF
  chmod 755 "$CERTBOT_RENEW_SCRIPT"

  cat > "$CERTBOT_RENEW_SERVICE" <<EOF
[Unit]
Description=Renew Let's Encrypt certificates for ${APP_NAME}

[Service]
Type=oneshot
ExecStart=${CERTBOT_RENEW_SCRIPT}
EOF

  cat > "$CERTBOT_RENEW_TIMER" <<EOF
[Unit]
Description=Twice-daily Let's Encrypt renewal check for ${APP_NAME}

[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=900
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

enable_services() {
  systemctl daemon-reload
  systemctl enable redis-server
  systemctl restart redis-server
  systemctl enable "${APP_NAME}"
  systemctl restart "${APP_NAME}"
  systemctl enable "$(basename "$CERTBOT_RENEW_TIMER")"
  systemctl restart "$(basename "$CERTBOT_RENEW_TIMER")"
}

adjust_firewall() {
  if command_exists ufw && ufw status | grep -qi active; then
    ufw allow "${PUBLIC_HTTP_PORT}/tcp" || true
    ufw allow "${PUBLIC_HTTPS_PORT}/tcp" || true
  fi
}

final_summary() {
  local domains_csv primary_domain
  domains_csv="$(build_tls_domains)"
  primary_domain="$(printf '%s' "$domains_csv" | cut -d',' -f1 | xargs)"
  local public_url="https://${primary_domain}"
  if [[ "$PUBLIC_HTTPS_PORT" != "443" ]]; then
    public_url="${public_url}:${PUBLIC_HTTPS_PORT}"
  fi

  echo
  echo "NOAFF monitor is installed."
  echo "Service:   systemctl status ${APP_NAME} --no-pager"
  echo "Logs:      journalctl -u ${APP_NAME} -f"
  echo "Nginx:     systemctl status nginx --no-pager"
  echo "Cert renew: systemctl list-timers | grep ${APP_NAME}"
  echo "Domain:    ${public_url}${PORTAL_PATH}"
  echo "Admin:     ${ADMIN_USERNAME}"
  if [[ -f "${APP_DIR}/data/bootstrap_admin.txt" ]]; then
    echo "Password:  ${ADMIN_PASSWORD}"
  else
    echo "Password:  unchanged (use the current panel password)"
  fi
  echo "Portal:    ${PORTAL_PATH}"
  echo
  echo "If Cloudflare SSL mode was not switched automatically, set it to Full (strict)."
  echo "Delete ${APP_DIR}/data/bootstrap_admin.txt after first password change."
}

main() {
  require_root
  [[ -n "$FQDN" ]] || die "FQDN is required, for example FQDN=monitor.example.com"
  [[ -n "$CF_ZONE_NAME" || -n "$CF_ZONE_ID" ]] || die "CF_ZONE_NAME or CF_ZONE_ID is required"
  [[ -n "$CF_API_TOKEN" ]] || die "CF_API_TOKEN is required"
  [[ -n "$CERTBOT_EMAIL" ]] || die "CERTBOT_EMAIL is required"

  log "Installing system packages"
  ensure_packages
  ensure_browser
  ensure_service_user

  log "Fetching application source"
  clone_or_update_repo
  load_existing_env_defaults
  validate_runtime_config

  log "Installing Python dependencies"
  setup_python_env

  log "Installing certbot DNS-Cloudflare runtime"
  setup_certbot_env

  log "Configuring Cloudflare DNS"
  configure_cloudflare_dns

  log "Issuing or renewing TLS certificate"
  issue_certificate

  log "Writing Cloudflare-aware nginx snippets"
  write_cloudflare_nginx_snippets

  log "Writing application environment"
  write_env_file

  log "Writing systemd service and renewal timer"
  write_app_service
  write_certbot_renewal_units

  mkdir -p "${APP_DIR}/data"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

  log "Configuring nginx reverse proxy"
  configure_nginx

  log "Enabling services"
  enable_services

  adjust_firewall
  final_summary
}

main "$@"
