#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME:-noaff-monitor}"
SERVICE_USER="${SERVICE_USER:-noaffmon}"
APP_DIR="${APP_DIR:-/opt/noaff-monitor}"
if [[ "$APP_DIR" == "/opt/noaff-monitor" && ! -e "$APP_DIR" && -e "/opt/noaff_monitor" ]]; then
  APP_DIR="/opt/noaff_monitor"
fi
REPO_URL="${REPO_URL:-https://github.com/cshaizhihao/noaff-restock-monitor.git}"
REPO_REF="${REPO_REF:-master}"
GIT_AUTH_TOKEN="${GIT_AUTH_TOKEN:-${GH_TOKEN:-}}"
DEPLOY_MODE="${DEPLOY_MODE:-native}"

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-7777}"
PUBLIC_APP_PORT="${PUBLIC_APP_PORT:-$APP_PORT}"
DOCKER_BIND_HOST="${DOCKER_BIND_HOST:-0.0.0.0}"
PUBLIC_HTTP_PORT="${PUBLIC_HTTP_PORT:-80}"
PUBLIC_HTTPS_PORT="${PUBLIC_HTTPS_PORT:-443}"
ACCESS_MODE="${ACCESS_MODE:-}"
ENABLE_NGINX="${ENABLE_NGINX:-true}"
ENABLE_TLS="${ENABLE_TLS:-true}"
CERT_MODE="${CERT_MODE:-auto}"
INTERACTIVE_INSTALL="${INTERACTIVE_INSTALL:-auto}"

MONITOR_DEBUG_PORT="${MONITOR_DEBUG_PORT:-9223}"
TEST_DEBUG_PORT="${TEST_DEBUG_PORT:-9334}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-45}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-25}"

ADMIN_USERNAME="${ADMIN_USERNAME:-operator}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
SECRET_KEY="${SECRET_KEY:-}"
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
APP_STARTUP_TIMEOUT_SECONDS="${APP_STARTUP_TIMEOUT_SECONDS:-90}"

LIMITER_STORAGE_URI="${LIMITER_STORAGE_URI:-redis://127.0.0.1:6379/0}"
SESSION_COOKIE_SECURE="${SESSION_COOKIE_SECURE:-true}"
ENABLE_PROXY_FIX="${ENABLE_PROXY_FIX:-true}"
PROXY_FIX_X_FOR="${PROXY_FIX_X_FOR:-1}"
PROXY_FIX_X_PROTO="${PROXY_FIX_X_PROTO:-1}"
PROXY_FIX_X_HOST="${PROXY_FIX_X_HOST:-1}"
PROXY_FIX_X_PORT="${PROXY_FIX_X_PORT:-1}"
INSTALL_VALIDATE_ONLY=false
DOCKER_UPGRADE_ONLY=false
PASSWORD_RESET_ONLY=false
UNINSTALL_ONLY=false
SKIP_INTERACTIVE_WIZARD=false
RECONFIGURE_EXISTING_INSTALL=false

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
UPGRADE_SCRIPT="/usr/local/bin/${APP_NAME}-upgrade.sh"
UPGRADE_SERVICE="/etc/systemd/system/${APP_NAME}-upgrade.service"
UPGRADE_LOG="/var/log/${APP_NAME}-upgrade.log"
CLI_SCRIPT="${CLI_SCRIPT:-/usr/local/bin/noaff}"
ACME_WEBROOT="/var/www/${APP_NAME}-acme"
INSTALL_LOG="/var/log/${APP_NAME}-install.log"
CF_SUPPORTED_HTTP_PORTS=(80 8080 8880 2052 2082 2086 2095)
CF_SUPPORTED_HTTPS_PORTS=(443 2053 2083 2087 2096 8443)
CURRENT_STEP=0
TOTAL_STEPS=1
HEALTHCHECK_LAST_URL=""
HEALTHCHECK_LAST_STATUS=""
HEALTHCHECK_LAST_BODY=""

if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_DIM=$'\033[2m'
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_BLUE=$'\033[34m'
  C_MAGENTA=$'\033[35m'
  C_CYAN=$'\033[36m'
else
  C_RESET=""
  C_BOLD=""
  C_DIM=""
  C_RED=""
  C_GREEN=""
  C_YELLOW=""
  C_BLUE=""
  C_MAGENTA=""
  C_CYAN=""
fi

log() {
  printf '\n%s[%s]%s %s\n' "$C_CYAN" "$(date '+%Y-%m-%d %H:%M:%S')" "$C_RESET" "$*"
}

warn() {
  printf '\n%s[提示]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2
}

die() {
  printf '\n%s[错误]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2
  exit 1
}

banner() {
  cat <<EOF
${C_CYAN}${C_BOLD}
 _   _  ___    _    _____ _____
| \ | |/ _ \  / \  |  ___|  ___|
|  \| | | | |/ _ \ | |_  | |_
| |\  | |_| / ___ \|  _| |  _|
|_| \_|\___/_/   \_\_|   |_|
${C_RESET}${C_BOLD}NOAFF 补货监控助手 · 中文交互安装向导${C_RESET}
EOF
}

progress_bar() {
  local current="$1"
  local total="$2"
  local width=24
  local filled=$(( current * width / total ))
  local empty=$(( width - filled ))
  printf '%s[' "$C_BLUE"
  printf '%*s' "$filled" '' | tr ' ' '#'
  printf '%*s' "$empty" '' | tr ' ' '-'
  printf ']%s %s/%s' "$C_RESET" "$current" "$total"
}

run_step() {
  local title="$1"
  shift
  CURRENT_STEP=$((CURRENT_STEP + 1))
  printf '\n%s==>%s %s  %s%s%s\n' "$C_MAGENTA" "$C_RESET" "$(progress_bar "$CURRENT_STEP" "$TOTAL_STEPS")" "$C_BOLD" "$title" "$C_RESET"
  "$@"
}

usage() {
  cat <<'EOF'
NOAFF Restock Monitor installer

Usage:
  bash install.sh
  bash install.sh [--validate-only]
  bash install.sh --docker-upgrade
  bash install.sh --reset-password
  bash install.sh --uninstall
  bash install.sh --help

Interactive mode:
  Run without required variables to enter a full Chinese installer wizard.

Install modes:
  ACCESS_MODE=ip             IP + port test mode
  ACCESS_MODE=domain-direct  Domain direct mode without Cloudflare orange-cloud
  ACCESS_MODE=domain-cf      Domain mode with Cloudflare orange-cloud

Deploy modes:
  DEPLOY_MODE=native          Native systemd deployment
  DEPLOY_MODE=docker          Docker Compose isolated deployment, high-port only

Common optional environment:
  DEPLOY_MODE=native
  APP_PORT=7777
  PUBLIC_APP_PORT=7777
  DOCKER_BIND_HOST=0.0.0.0
  PUBLIC_HTTP_PORT=80
  PUBLIC_HTTPS_PORT=443
  FQDN=monitor.example.com
  TLS_DOMAINS=monitor.example.com,www.monitor.example.com
  CERTBOT_EMAIL=your-real-email@gmail.com
  CERT_MODE=http|dns|none|auto
  CF_ZONE_NAME=example.com
  CF_API_TOKEN=cf_xxx
  MONITOR_DEBUG_PORT=9223
  TEST_DEBUG_PORT=9334
  APP_STARTUP_TIMEOUT_SECONDS=90
  CF_RECORD_PROXIED=true
  REPO_REF=master

Modes:
  --validate-only  Validate required variables and Cloudflare-compatible ports without installing.
  --docker-upgrade Pull latest code, refresh Docker env, rebuild containers, and verify health.
  --reset-password Reset the panel administrator password in the local SQLite database.
  --uninstall      Stop services and clean NOAFF-managed system files; data deletion is confirmed separately.
  --help           Show this help.
EOF
}

parse_args() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --validate-only)
        INSTALL_VALIDATE_ONLY=true
        shift
        ;;
      --docker-upgrade)
        DOCKER_UPGRADE_ONLY=true
        DEPLOY_MODE=docker
        INTERACTIVE_INSTALL=false
        shift
        ;;
      --reset-password)
        PASSWORD_RESET_ONLY=true
        INTERACTIVE_INSTALL=false
        shift
        ;;
      --uninstall|--clean)
        UNINSTALL_ONLY=true
        INTERACTIVE_INSTALL=false
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

has_tty() {
  [[ -r /dev/tty && -w /dev/tty ]]
}

prompt_read() {
  local prompt="$1"
  local answer=""
  if has_tty; then
    read -r -p "$prompt" answer </dev/tty
  else
    read -r -p "$prompt" answer
  fi
  printf '%s' "$answer"
}

prompt_default() {
  local label="$1"
  local default_value="$2"
  local answer
  answer="$(prompt_read "${label} [${default_value}]: ")"
  if [[ -z "$answer" ]]; then
    printf '%s' "$default_value"
  else
    printf '%s' "$answer"
  fi
}

prompt_secret_optional() {
  local label="$1"
  local answer=""
  if has_tty; then
    read -r -s -p "$label" answer </dev/tty
    printf '\n' >/dev/tty
  else
    read -r -s -p "$label" answer
    printf '\n'
  fi
  printf '%s' "$answer"
}

prompt_yes_no() {
  local label="$1"
  local default_value="${2:-Y}"
  local answer normalized
  answer="$(prompt_read "${label} [${default_value}]: ")"
  answer="${answer:-$default_value}"
  normalized="${answer,,}"
  [[ "$normalized" == "y" || "$normalized" == "yes" || "$normalized" == "1" || "$normalized" == "true" ]]
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

normalize_domain_input() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit

raw = sys.argv[1].strip()
if not raw:
    print("")
    raise SystemExit
candidate = raw if "://" in raw else f"http://{raw}"
parsed = urlsplit(candidate)
host = parsed.hostname or raw.split("/", 1)[0].split(":", 1)[0]
print((host or "").strip().strip("."))
PY
}

normalize_domain_list() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit

seen = set()
result = []
for raw in sys.argv[1].split(","):
    value = raw.strip()
    if not value:
        continue
    candidate = value if "://" in value else f"http://{value}"
    parsed = urlsplit(candidate)
    host = (parsed.hostname or value.split("/", 1)[0].split(":", 1)[0]).strip().strip(".")
    if host and host not in seen:
        seen.add(host)
        result.append(host)
print(",".join(result))
PY
}

random_token() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
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
  prefer_existing_value "PUBLIC_APP_PORT" "7777"
  prefer_existing_value "DOCKER_BIND_HOST" "0.0.0.0"
  prefer_existing_value "DEPLOY_MODE" "native"
  prefer_existing_value "ACCESS_MODE" ""
  prefer_existing_value "ENABLE_NGINX" "true"
  prefer_existing_value "ENABLE_TLS" "true"
  prefer_existing_value "CERT_MODE" "auto"
  prefer_existing_value "PUBLIC_HTTP_PORT" "80"
  prefer_existing_value "PUBLIC_HTTPS_PORT" "443"
  prefer_existing_value "ADMIN_USERNAME" "operator"
  prefer_existing_value "REPO_REF" "master"
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
  prefer_existing_value "CF_RECORD_PROXIED" "true"
  prefer_existing_value "CF_SSL_MODE" "strict"
  prefer_existing_value "ORIGIN_LOCKDOWN_TO_CLOUDFLARE" "true"

  [[ -n "$SECRET_KEY" ]] || SECRET_KEY="$(read_env_value "SECRET_KEY")"
  [[ -n "$ADMIN_PASSWORD" ]] || ADMIN_PASSWORD="$(read_env_value "ADMIN_PASSWORD")"
  [[ -n "$TELEGRAM_BOT_TOKEN" ]] || TELEGRAM_BOT_TOKEN="$(read_env_value "TELEGRAM_BOT_TOKEN")"
  [[ -n "$TELEGRAM_CHAT_ID" ]] || TELEGRAM_CHAT_ID="$(read_env_value "TELEGRAM_CHAT_ID")"
  [[ -n "$FQDN" ]] || FQDN="$(read_env_value "FQDN")"
  [[ -n "$TLS_DOMAINS" ]] || TLS_DOMAINS="$(read_env_value "TLS_DOMAINS")"
  [[ -n "$CERTBOT_EMAIL" ]] || CERTBOT_EMAIL="$(read_env_value "CERTBOT_EMAIL")"
  [[ -n "$CF_ZONE_NAME" ]] || CF_ZONE_NAME="$(read_env_value "CF_ZONE_NAME")"
  [[ -n "$CF_ZONE_ID" ]] || CF_ZONE_ID="$(read_env_value "CF_ZONE_ID")"
  [[ -n "$CF_API_TOKEN" ]] || CF_API_TOKEN="$(read_env_value "CF_API_TOKEN")"
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

mark_git_safe_directory() {
  local directory="$1"
  git config --global --add safe.directory "$directory" >/dev/null 2>&1 || true
}

prepare_git_checkout_permissions() {
  [[ -d "$APP_DIR/.git" ]] || return 0
  mark_git_safe_directory "$APP_DIR"
  if [[ "$(id -u)" == "0" ]]; then
    chown -R root:root "$APP_DIR/.git" || true
    chown root:root "$APP_DIR" || true
  fi
}

apt_install() {
  apt-get install -y "$@"
}

normalize_access_mode() {
  case "$DEPLOY_MODE" in
    native|docker)
      ;;
    *)
      die "DEPLOY_MODE must be native or docker."
      ;;
  esac

  if [[ -n "$FQDN" ]]; then
    FQDN="$(normalize_domain_input "$FQDN")"
    if [[ -n "$TLS_DOMAINS" ]]; then
      TLS_DOMAINS="$(normalize_domain_list "$TLS_DOMAINS")"
    else
      TLS_DOMAINS="$FQDN"
    fi
  fi

  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    ACCESS_MODE="ip"
    ENABLE_NGINX="false"
    ENABLE_TLS="false"
    CERT_MODE="none"
    CF_RECORD_PROXIED="false"
    ORIGIN_LOCKDOWN_TO_CLOUDFLARE="false"
    if [[ -n "$FQDN" ]]; then
      SESSION_COOKIE_SECURE="true"
      ENABLE_PROXY_FIX="true"
    else
      SESSION_COOKIE_SECURE="false"
      ENABLE_PROXY_FIX="false"
    fi
    APP_HOST="0.0.0.0"
    LIMITER_STORAGE_URI="redis://redis:6379/0"
  fi

  if [[ -z "$ACCESS_MODE" ]]; then
    if [[ -n "$FQDN" ]]; then
      if bool_is_true "$CF_RECORD_PROXIED"; then
        ACCESS_MODE="domain-cf"
      else
        ACCESS_MODE="domain-direct"
      fi
    else
      ACCESS_MODE="ip"
    fi
  fi

  case "$ACCESS_MODE" in
    ip)
      ENABLE_NGINX="false"
      ENABLE_TLS="false"
      CERT_MODE="none"
      CF_RECORD_PROXIED="false"
      ORIGIN_LOCKDOWN_TO_CLOUDFLARE="false"
      SESSION_COOKIE_SECURE="false"
      ENABLE_PROXY_FIX="false"
      APP_HOST="0.0.0.0"
      ;;
    domain-direct)
      ENABLE_NGINX="true"
      CF_RECORD_PROXIED="false"
      ORIGIN_LOCKDOWN_TO_CLOUDFLARE="false"
      APP_HOST="127.0.0.1"
      PUBLIC_HTTP_PORT="80"
      PUBLIC_HTTPS_PORT="443"
      CERT_MODE="${CERT_MODE:-auto}"
      ;;
    domain-cf)
      ENABLE_NGINX="true"
      CF_RECORD_PROXIED="${CF_RECORD_PROXIED:-true}"
      APP_HOST="127.0.0.1"
      PUBLIC_HTTP_PORT="80"
      PUBLIC_HTTPS_PORT="443"
      CERT_MODE="${CERT_MODE:-auto}"
      ;;
    *)
      die "ACCESS_MODE must be ip, domain-direct, or domain-cf."
      ;;
  esac

  if [[ "$CERT_MODE" == "auto" ]]; then
    if [[ -n "$CF_API_TOKEN" ]]; then
      CERT_MODE="dns"
    elif bool_is_true "$ENABLE_TLS"; then
      CERT_MODE="http"
    else
      CERT_MODE="none"
    fi
  fi
  if [[ "$CERT_MODE" == "none" ]]; then
    ENABLE_TLS="false"
  fi
}

validate_port() {
  local label="$1"
  local value="$2"
  local minimum="$3"
  local maximum="$4"
  [[ "$value" =~ ^[0-9]+$ ]] || die "${label} must be an integer."
  (( value >= minimum && value <= maximum )) || die "${label} must be between ${minimum} and ${maximum}."
}

is_valid_certbot_email() {
  python3 - "$1" <<'PY'
import re
import sys

email = sys.argv[1].strip()
placeholder_domains = {"example.com", "example.org", "example.net", "invalid", "localhost"}
domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
valid_shape = bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))
raise SystemExit(0 if valid_shape and domain not in placeholder_domains else 1)
PY
}

validate_certbot_email() {
  [[ -n "$CERTBOT_EMAIL" ]] || die "CERTBOT_EMAIL is required when TLS is enabled."
  is_valid_certbot_email "$CERTBOT_EMAIL" || die "CERTBOT_EMAIL must be a real email address. Do not use example.com / example.org placeholders."
}

prompt_certbot_email() {
  local label="$1"
  local answer default_value
  default_value="$CERTBOT_EMAIL"
  while true; do
    if [[ -n "$default_value" ]]; then
      answer="$(prompt_default "$label" "$default_value")"
    else
      answer="$(prompt_read "${label}: ")"
    fi
    CERTBOT_EMAIL="$(printf '%s' "$answer" | xargs)"
    if is_valid_certbot_email "$CERTBOT_EMAIL"; then
      return
    fi
    warn "请输入真实有效的邮箱，不能使用 ops@example.com / example.com 这类占位邮箱。"
  done
}

validate_runtime_config() {
  normalize_access_mode
  validate_port "APP_PORT" "$APP_PORT" 1024 65535
  if bool_is_true "$ENABLE_NGINX"; then
    validate_port "PUBLIC_HTTP_PORT" "$PUBLIC_HTTP_PORT" 1 65535
    validate_port "PUBLIC_HTTPS_PORT" "$PUBLIC_HTTPS_PORT" 1 65535
  fi
  validate_port "MONITOR_DEBUG_PORT" "$MONITOR_DEBUG_PORT" 1024 65535
  validate_port "TEST_DEBUG_PORT" "$TEST_DEBUG_PORT" 1024 65535

  [[ "$MONITOR_DEBUG_PORT" != "$TEST_DEBUG_PORT" ]] || die "MONITOR_DEBUG_PORT and TEST_DEBUG_PORT must be different."
  [[ "$MONITOR_DEBUG_PORT" != "$APP_PORT" ]] || die "MONITOR_DEBUG_PORT must not reuse APP_PORT."
  [[ "$TEST_DEBUG_PORT" != "$APP_PORT" ]] || die "TEST_DEBUG_PORT must not reuse APP_PORT."

  if [[ "$CERT_MODE" == "http" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
    die "CERT_MODE=http requires PUBLIC_HTTP_PORT=80 because Let's Encrypt HTTP-01 validates on port 80."
  fi

  if [[ "$ACCESS_MODE" == "domain-cf" ]] && bool_is_true "$CF_RECORD_PROXIED"; then
    port_in_list "$PUBLIC_HTTP_PORT" "${CF_SUPPORTED_HTTP_PORTS[@]}" || die "PUBLIC_HTTP_PORT=${PUBLIC_HTTP_PORT} is not supported by Cloudflare orange-cloud proxy. Supported HTTP ports: ${CF_SUPPORTED_HTTP_PORTS[*]}"
    port_in_list "$PUBLIC_HTTPS_PORT" "${CF_SUPPORTED_HTTPS_PORTS[@]}" || die "PUBLIC_HTTPS_PORT=${PUBLIC_HTTPS_PORT} is not supported by Cloudflare orange-cloud proxy. Supported HTTPS ports: ${CF_SUPPORTED_HTTPS_PORTS[*]}"
  fi
}

validate_required_inputs() {
  normalize_access_mode
  if [[ "$ACCESS_MODE" == "ip" ]]; then
    return
  fi

  [[ -n "$FQDN" ]] || die "FQDN is required for domain install mode."
  if bool_is_true "$ENABLE_TLS"; then
    validate_certbot_email
  fi
  if [[ "$CERT_MODE" == "dns" ]]; then
    [[ -n "$CF_ZONE_NAME" || -n "$CF_ZONE_ID" ]] || die "CF_ZONE_NAME or CF_ZONE_ID is required for Cloudflare DNS-01."
    [[ -n "$CF_API_TOKEN" ]] || die "CF_API_TOKEN is required for Cloudflare DNS-01."
  fi
}

print_validation_summary() {
  local domains_csv="-"
  [[ -n "$FQDN" ]] && domains_csv="$(build_tls_domains)"
  echo "NOAFF installer validation passed."
  echo "DEPLOY_MODE:       ${DEPLOY_MODE}"
  echo "ACCESS_MODE:       ${ACCESS_MODE}"
  echo "FQDN:              ${FQDN:-IP mode}"
  echo "TLS_DOMAINS:       ${domains_csv}"
  echo "APP_BIND:          ${APP_HOST}:${APP_PORT}"
  echo "ENABLE_NGINX:      ${ENABLE_NGINX}"
  echo "ENABLE_TLS:        ${ENABLE_TLS}"
  echo "CERT_MODE:         ${CERT_MODE}"
  echo "PUBLIC_HTTP_PORT:  ${PUBLIC_HTTP_PORT}"
  echo "PUBLIC_HTTPS_PORT: ${PUBLIC_HTTPS_PORT}"
  echo "CF_RECORD_PROXIED: ${CF_RECORD_PROXIED}"
  echo "MONITOR/TEST CDP:  ${MONITOR_DEBUG_PORT}/${TEST_DEBUG_PORT}"
}

validate_only() {
  validate_required_inputs
  validate_runtime_config
  print_validation_summary
}

build_public_url() {
  local public_url public_host
  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    if [[ -n "$FQDN" ]]; then
      public_host="$(normalize_domain_input "$FQDN")"
      printf 'http://%s' "$public_host"
      return
    else
      detect_origin_ips
      public_host="${ORIGIN_IPV4:-服务器IP}"
    fi
    printf 'http://%s:%s' "$public_host" "$PUBLIC_APP_PORT"
    return
  fi

  if [[ "$ACCESS_MODE" == "ip" ]]; then
    detect_origin_ips
    printf 'http://%s:%s' "${ORIGIN_IPV4:-服务器IP}" "$APP_PORT"
    return
  fi

  if bool_is_true "$ENABLE_TLS"; then
    public_url="https://${FQDN}"
  else
    public_url="http://${FQDN}"
  fi
  printf '%s' "$public_url"
}

should_run_interactive_wizard() {
  [[ "$SKIP_INTERACTIVE_WIZARD" != "true" ]] || return 1
  [[ "$INTERACTIVE_INSTALL" != "false" ]] || return 1
  [[ "$INSTALL_VALIDATE_ONLY" != "true" ]] || return 1
  if bool_is_true "$RECONFIGURE_EXISTING_INSTALL"; then
    has_tty
    return
  fi
  [[ -z "$ACCESS_MODE" && -z "$FQDN" ]] || return 1
  has_tty
}

needs_interactive_inputs() {
  [[ "$SKIP_INTERACTIVE_WIZARD" != "true" ]] || return 1
  [[ "$INTERACTIVE_INSTALL" != "false" ]] || return 1
  [[ "$INSTALL_VALIDATE_ONLY" != "true" ]] || return 1
  [[ -z "$ACCESS_MODE" && -z "$FQDN" ]]
}

existing_install_detected() {
  [[ -f "$APP_DIR/.env" || -d "$APP_DIR/.git" || -f "$APP_DIR/app.py" || -d "$APP_DIR/data" ]]
}

choose_existing_install_action() {
  existing_install_detected || return 0
  load_existing_env_defaults
  normalize_access_mode

  if [[ "$INTERACTIVE_INSTALL" == "false" ]] || ! has_tty; then
    SKIP_INTERACTIVE_WIZARD=true
    log "Detected existing NOAFF install at ${APP_DIR}; running overwrite update with saved config."
    return 0
  fi

  banner
  echo "${C_BOLD}[已检测到已有安装]${C_RESET}"
  echo "  1) 覆盖更新，保留现有数据和配置（推荐）"
  echo "  2) 重新配置，保留数据但重新走安装向导"
  echo "  3) 重置管理员密码"
  echo "  4) 退出"
  local action
  action="$(prompt_default "请选择" "1")"
  case "$action" in
    1)
      SKIP_INTERACTIVE_WIZARD=true
      log "将使用 ${APP_DIR}/.env 中的现有配置执行覆盖更新。"
      ;;
    2)
      RECONFIGURE_EXISTING_INSTALL=true
      ;;
    3)
      reset_admin_password
      exit 0
      ;;
    4)
      exit 0
      ;;
    *)
      die "已有安装处理方式只能选择 1、2、3 或 4。"
      ;;
  esac
}

prompt_domain() {
  local answer
  while true; do
    answer="$(prompt_read "请输入域名，例如 monitor.example.com：")"
    if [[ -n "$answer" ]]; then
      FQDN="$(normalize_domain_input "$answer")"
      [[ -n "$FQDN" ]] || die "域名格式无效。"
      TLS_DOMAINS="${TLS_DOMAINS:-$FQDN}"
      return
    fi
    warn "域名不能为空；如果没有域名，请在访问方式中选择 IP + 端口。"
  done
}

interactive_wizard() {
  banner
  echo "${C_DIM}脚本会显示每一步进度和命令输出，不会黑盒安装。${C_RESET}"
  echo

  echo "${C_BOLD}[0/9] 选择部署方式${C_RESET}"
  echo "  1) Docker 隔离 + 高位端口，不接管现有 Nginx（推荐已有网站的机器）"
  echo "  2) 原生 systemd + 可选 Nginx，适合干净机器"
  local deploy_choice
  deploy_choice="$(prompt_default "请选择" "1")"
  case "$deploy_choice" in
    1)
      DEPLOY_MODE="docker"
      ;;
    2)
      DEPLOY_MODE="native"
      ;;
    *)
      die "部署方式只能选择 1 或 2。"
      ;;
  esac

  APP_PORT="$(prompt_default "[1/8] 请输入应用本机端口" "$APP_PORT")"
  validate_port "APP_PORT" "$APP_PORT" 1024 65535

  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    ACCESS_MODE="ip"
    PUBLIC_APP_PORT="$(prompt_default "[2/9] 请输入 Docker 对外访问端口" "$PUBLIC_APP_PORT")"
    validate_port "PUBLIC_APP_PORT" "$PUBLIC_APP_PORT" 1024 65535
    DOCKER_BIND_HOST="$(prompt_default "[3/9] 监听地址，0.0.0.0 表示公网可访问" "$DOCKER_BIND_HOST")"
    local docker_domain_default="n"
    [[ -n "$FQDN" ]] && docker_domain_default="Y"
    if prompt_yes_no "[4/9] 是否使用已解析域名生成面板地址？（Docker 不会配置 Nginx/证书）" "$docker_domain_default"; then
      FQDN="$(normalize_domain_input "$(prompt_default "请输入已解析到本机的域名，例如 monitor.example.com" "$FQDN")")"
      [[ -n "$FQDN" ]] || die "域名不能为空；如不使用域名，请选择否。"
      TLS_DOMAINS="${TLS_DOMAINS:-$FQDN}"
    else
      FQDN=""
      TLS_DOMAINS=""
    fi
    echo
    warn "Docker 模式不会修改或重启宿主机 Nginx。已有 Nginx 可手动反代到 ${DOCKER_BIND_HOST}:${PUBLIC_APP_PORT}。"
    if prompt_yes_no "[5/9] 是否现在填写 Telegram Bot Token 和 Chat ID？" "n"; then
      TELEGRAM_BOT_TOKEN="$(prompt_secret_optional "请输入 Telegram Bot Token（输入时不显示）：")"
      TELEGRAM_CHAT_ID="$(prompt_default "请输入 Telegram Chat ID" "$TELEGRAM_CHAT_ID")"
    fi
    normalize_access_mode
    validate_required_inputs
    validate_runtime_config
    print_install_summary
    prompt_yes_no "[6/9] 确认开始 Docker 安装？" "Y" || die "用户取消安装。"
    return
  fi

  echo
  echo "${C_BOLD}[2/8] 选择访问方式${C_RESET}"
  echo "  1) IP + 端口访问，适合测试机"
  echo "  2) 域名直连，不开启 Cloudflare 小黄云"
  echo "  3) 域名访问，开启或已开启 Cloudflare 小黄云"
  local mode_choice
  mode_choice="$(prompt_default "请选择" "1")"
  case "$mode_choice" in
    1)
      ACCESS_MODE="ip"
      ENABLE_NGINX="false"
      ENABLE_TLS="false"
      CERT_MODE="none"
      PUBLIC_HTTP_PORT="$APP_PORT"
      PUBLIC_HTTPS_PORT="$APP_PORT"
      ;;
    2)
      ACCESS_MODE="domain-direct"
      CF_RECORD_PROXIED="false"
      ORIGIN_LOCKDOWN_TO_CLOUDFLARE="false"
      APP_HOST="127.0.0.1"
      prompt_domain
      PUBLIC_HTTP_PORT="80"
      PUBLIC_HTTPS_PORT="443"
      echo "${C_DIM}域名模式固定使用标准公网端口 80/443，面板地址不会带端口。${C_RESET}"
      if prompt_yes_no "[3/8] 是否自动申请 Let's Encrypt HTTPS 证书？证书验证需要 80 端口可访问" "Y"; then
        ENABLE_TLS="true"
        CERT_MODE="http"
        prompt_certbot_email "请输入 Let's Encrypt 邮箱"
      else
        ENABLE_TLS="false"
        CERT_MODE="none"
        SESSION_COOKIE_SECURE="false"
      fi
      ;;
    3)
      ACCESS_MODE="domain-cf"
      APP_HOST="127.0.0.1"
      prompt_domain
      PUBLIC_HTTP_PORT="80"
      PUBLIC_HTTPS_PORT="443"
      echo "${C_DIM}域名模式固定使用标准公网端口 80/443，面板地址不会带端口。${C_RESET}"
      if prompt_yes_no "[3/8] 你是否已经在 Cloudflare 开启或准备开启小黄云？" "Y"; then
        CF_RECORD_PROXIED="true"
        ORIGIN_LOCKDOWN_TO_CLOUDFLARE="true"
      else
        CF_RECORD_PROXIED="false"
        ORIGIN_LOCKDOWN_TO_CLOUDFLARE="false"
        ACCESS_MODE="domain-direct"
      fi
      if prompt_yes_no "[4/8] 是否提供 Cloudflare API Token 以启用 DNS-01 全自动证书？普通用户可选 n" "n"; then
        CF_API_TOKEN="$(prompt_secret_optional "请输入 Cloudflare API Token（输入时不显示）：")"
        CF_ZONE_NAME="$(prompt_default "请输入 Cloudflare Zone 名称，例如 example.com" "$CF_ZONE_NAME")"
        CERT_MODE="dns"
      else
        CERT_MODE="http"
      fi
      ENABLE_TLS="true"
      prompt_certbot_email "[5/8] 请输入 Let's Encrypt 邮箱"
      ;;
    *)
      die "访问方式只能选择 1、2 或 3。"
      ;;
  esac

  echo
  if prompt_yes_no "[7/8] 是否现在填写 Telegram Bot Token 和 Chat ID？" "n"; then
    TELEGRAM_BOT_TOKEN="$(prompt_secret_optional "请输入 Telegram Bot Token（输入时不显示）：")"
    TELEGRAM_CHAT_ID="$(prompt_default "请输入 Telegram Chat ID" "$TELEGRAM_CHAT_ID")"
  fi

  normalize_access_mode
  validate_required_inputs
  validate_runtime_config
  print_install_summary
  prompt_yes_no "[8/8] 确认开始安装？" "Y" || die "用户取消安装。"
}

print_install_summary() {
  local access_label public_url
  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    if [[ -n "$FQDN" ]]; then
      access_label="域名访问（Docker）"
    else
      access_label="IP + 高位端口（Docker）"
    fi
  else
    case "$ACCESS_MODE" in
      ip)
        access_label="IP + 端口"
        ;;
      domain-direct)
        access_label="域名直连"
        ;;
      domain-cf)
        access_label="Cloudflare 小黄云"
        ;;
    esac
  fi
  public_url="$(build_public_url)"

  echo
  echo "${C_BOLD}${C_GREEN}安装摘要${C_RESET}"
  echo "访问方式：      ${access_label}"
  echo "面板地址：      ${public_url}"
  echo "应用监听：      ${APP_HOST}:${APP_PORT}"
  echo "Nginx：         ${ENABLE_NGINX}"
  echo "HTTPS：         ${ENABLE_TLS}"
  echo "证书模式：      ${CERT_MODE}"
  echo "小黄云代理：    ${CF_RECORD_PROXIED}"
  echo "源站锁定 CF：   ${ORIGIN_LOCKDOWN_TO_CLOUDFLARE}"
  echo "监控/测试端口： ${MONITOR_DEBUG_PORT}/${TEST_DEBUG_PORT}"
  echo
}

ensure_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt_install git curl ca-certificates nginx redis-server xvfb xauth procps iproute2 lsof python3 python3-venv python3-pip python3-dev build-essential libssl-dev libffi-dev
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

ensure_docker() {
  if ! command_exists docker; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt_install docker.io
  fi
  if ! docker compose version >/dev/null 2>&1 && ! command_exists docker-compose; then
    apt_install docker-compose-plugin || apt_install docker-compose
  fi
  if command_exists systemctl; then
    systemctl enable docker
    if systemctl is-active --quiet docker; then
      log "Docker service is already running; leaving existing containers untouched."
    else
      systemctl start docker
    fi
  fi
}

docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

host_tcp_port_is_busy() {
  local port="$1"
  if command_exists ss; then
    ss -ltn "( sport = :${port} )" 2>/dev/null | grep -q LISTEN
    return
  fi
  if command_exists lsof; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi
  return 1
}

print_host_tcp_port_listeners() {
  local port="$1"
  if command_exists ss; then
    ss -ltnp "( sport = :${port} )" 2>/dev/null || true
    return
  fi
  if command_exists lsof; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN || true
  fi
}

host_tcp_port_listener_pids() {
  local port="$1"
  if command_exists lsof; then
    lsof -nP -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | sort -u
    return
  fi
  if command_exists ss; then
    ss -ltnp "( sport = :${port} )" 2>/dev/null \
      | sed -nE 's/.*pid=([0-9]+).*/\1/p' \
      | sort -u
  fi
}

process_is_noaff_runtime() {
  local pid="$1"
  local args
  args="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ -n "$args" ]] || return 1
  [[ "$args" == *"${APP_DIR}/app.py"* || "$args" == *"/opt/noaff-monitor/app.py"* || "$args" == *"/opt/noaff_monitor/app.py"* ]]
}

stop_existing_noaff_container() {
  if ! command_exists docker; then
    return 0
  fi
  if docker inspect noaff-monitor >/dev/null 2>&1; then
    warn "检测到旧 NOAFF Docker 容器，正在停止并移除，避免占用端口 ${APP_PORT}。"
    docker rm -f noaff-monitor >/dev/null 2>&1 || true
  fi
}

release_native_app_port() {
  local port="$APP_PORT"
  local attempt pid pids unknown_owner saw_noaff

  systemctl stop "${APP_NAME}" >/dev/null 2>&1 || true
  systemctl reset-failed "${APP_NAME}" >/dev/null 2>&1 || true
  stop_existing_noaff_container

  for attempt in 1 2 3; do
    if ! host_tcp_port_is_busy "$port"; then
      return 0
    fi

    pids="$(host_tcp_port_listener_pids "$port" | xargs || true)"
    unknown_owner=false
    saw_noaff=false

    if [[ -z "$pids" ]]; then
      warn "检测到端口 ${port} 已被占用，但无法识别进程。"
      print_host_tcp_port_listeners "$port"
      die "APP_PORT=${port} 已被占用。请重新运行安装脚本并选择其他端口，例如 7788。"
    fi

    for pid in $pids; do
      if process_is_noaff_runtime "$pid"; then
        saw_noaff=true
        warn "端口 ${port} 被 NOAFF 残留进程 PID ${pid} 占用，正在停止。"
        kill "$pid" >/dev/null 2>&1 || true
      else
        unknown_owner=true
      fi
    done

    if bool_is_true "$unknown_owner"; then
      warn "端口 ${port} 已被其他服务占用，安装器不会误杀非 NOAFF 进程。"
      print_host_tcp_port_listeners "$port"
      die "APP_PORT=${port} 已被占用。请重新运行安装脚本并选择其他端口，例如 7788。"
    fi

    bool_is_true "$saw_noaff" || break
    sleep 2
  done

  if host_tcp_port_is_busy "$port"; then
    pids="$(host_tcp_port_listener_pids "$port" | xargs || true)"
    for pid in $pids; do
      if process_is_noaff_runtime "$pid"; then
        warn "NOAFF 残留进程 PID ${pid} 未正常退出，正在强制停止。"
        kill -9 "$pid" >/dev/null 2>&1 || true
      fi
    done
    sleep 1
  fi

  if host_tcp_port_is_busy "$port"; then
    warn "端口 ${port} 仍然被占用。"
    print_host_tcp_port_listeners "$port"
    die "APP_PORT=${port} 无法释放。请换一个未占用端口后重试。"
  fi
}

docker_noaff_container_running() {
  if ! command_exists docker; then
    return 1
  fi
  docker inspect -f '{{.State.Running}}' noaff-monitor 2>/dev/null | grep -qx 'true'
}

docker_noaff_container_publishes_port() {
  local port="$1"
  command_exists docker || return 1
  docker port noaff-monitor 2>/dev/null | grep -Eq "(:|\\])${port}$"
}

ensure_docker_publish_port_available() {
  if host_tcp_port_is_busy "$PUBLIC_APP_PORT"; then
    if docker_noaff_container_running && docker_noaff_container_publishes_port "$PUBLIC_APP_PORT"; then
      log "Detected existing NOAFF container on port ${PUBLIC_APP_PORT}; continuing with in-place Docker update."
      return
    fi
    warn "Detected an existing listener on Docker publish port ${PUBLIC_APP_PORT}."
    print_host_tcp_port_listeners "$PUBLIC_APP_PORT"
    die "PUBLIC_APP_PORT=${PUBLIC_APP_PORT} is already in use. Rerun the installer and choose another high port, such as 7788."
  fi
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
    prepare_git_checkout_permissions
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
      local backup_dir failed_dir
      backup_dir="${APP_DIR}.backup.$(date '+%Y%m%d%H%M%S')"
      warn "$APP_DIR exists but is not a git checkout. Moving it to ${backup_dir} before reinstall."
      mv "$APP_DIR" "$backup_dir"
      mkdir -p "$(dirname "$APP_DIR")"
      log "Cloning repository into $APP_DIR"
      if ! git clone --branch "$REPO_REF" "$clone_url" "$APP_DIR"; then
        failed_dir="${APP_DIR}.failed.$(date '+%Y%m%d%H%M%S')"
        [[ ! -e "$APP_DIR" ]] || mv "$APP_DIR" "$failed_dir"
        mv "$backup_dir" "$APP_DIR"
        die "Git clone failed. The previous directory has been restored to $APP_DIR."
      fi
      [[ ! -f "$backup_dir/.env" || -f "$APP_DIR/.env" ]] || cp -a "$backup_dir/.env" "$APP_DIR/.env"
      [[ ! -d "$backup_dir/data" || -d "$APP_DIR/data" ]] || cp -a "$backup_dir/data" "$APP_DIR/data"
      return
    fi
    mkdir -p "$(dirname "$APP_DIR")"
    log "Cloning repository into $APP_DIR"
    git clone --branch "$REPO_REF" "$clone_url" "$APP_DIR"
  fi

  if [[ -d "$APP_DIR/.git" && -n "$clean_url" ]]; then
    prepare_git_checkout_permissions
    git -C "$APP_DIR" remote set-url origin "$clean_url"
  fi
}

setup_python_env() {
  cd "$APP_DIR"
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip setuptools wheel
  .venv/bin/pip install -r requirements.txt
}

deploy_docker_stack() {
  cd "$APP_DIR"
  ensure_docker_publish_port_available
  mkdir -p data
  chmod 755 "$APP_DIR"
  chmod 777 data
  docker_compose up -d redis
  DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-0}" docker build --pull=false -t "${APP_NAME}-noaff:latest" .
  docker_compose up -d --no-build --force-recreate noaff
}

probe_local_panel() {
  local url tmp_file err_file status host_header forwarded_proto forwarded_port
  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    url="http://127.0.0.1:${PUBLIC_APP_PORT}/healthz"
    forwarded_port="$PUBLIC_APP_PORT"
  else
    url="http://127.0.0.1:${APP_PORT}/healthz"
    forwarded_port="$APP_PORT"
  fi
  if bool_is_true "$ENABLE_TLS"; then
    forwarded_proto="https"
    forwarded_port="$PUBLIC_HTTPS_PORT"
  else
    forwarded_proto="http"
    bool_is_true "$ENABLE_NGINX" && forwarded_port="$PUBLIC_HTTP_PORT"
  fi

  host_header="${FQDN:-localhost}"
  host_header="$(normalize_domain_input "$host_header")"
  [[ -n "$host_header" ]] || host_header="localhost"

  tmp_file="$(mktemp)"
  err_file="$(mktemp)"
  HEALTHCHECK_LAST_URL="$url"
  HEALTHCHECK_LAST_STATUS=""
  HEALTHCHECK_LAST_BODY=""

  status="$(
    curl -sS -o "$tmp_file" -w "%{http_code}" \
      -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/137 Safari/537.36" \
      -H "Accept: application/json,text/plain,*/*" \
      -H "Host: ${host_header}" \
      -H "X-Forwarded-Proto: ${forwarded_proto}" \
      -H "X-Forwarded-Host: ${host_header}" \
      -H "X-Forwarded-Port: ${forwarded_port}" \
      --connect-timeout 3 \
      --max-time 8 \
      "$url" 2>"$err_file" || true
  )"
  HEALTHCHECK_LAST_STATUS="${status:-000}"
  HEALTHCHECK_LAST_BODY="$(
    if [[ -s "$tmp_file" ]]; then
      head -c 1200 "$tmp_file"
    fi
    if [[ -s "$err_file" ]]; then
      printf '\n[curl] '
      head -c 600 "$err_file"
    fi
  )"
  rm -f "$tmp_file" "$err_file"

  [[ "$HEALTHCHECK_LAST_STATUS" =~ ^2[0-9][0-9]$ ]]
}

print_healthcheck_diagnostics() {
  local port
  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    port="$PUBLIC_APP_PORT"
  else
    port="$APP_PORT"
  fi

  echo
  echo "${C_YELLOW}${C_BOLD}健康检查诊断${C_RESET}"
  echo "探测地址: ${HEALTHCHECK_LAST_URL:-未执行}"
  echo "HTTP 状态: ${HEALTHCHECK_LAST_STATUS:-无响应}"
  if [[ -n "$HEALTHCHECK_LAST_BODY" ]]; then
    echo "返回内容:"
    printf '%s\n' "$HEALTHCHECK_LAST_BODY"
  fi
  if host_tcp_port_is_busy "$port"; then
    echo
    echo "端口 ${port} 当前监听进程:"
    print_host_tcp_port_listeners "$port"
  fi
}

wait_for_application_ready() {
  local max_attempts=$(( (APP_STARTUP_TIMEOUT_SECONDS + 1) / 2 ))
  (( max_attempts < 1 )) && max_attempts=1
  local attempt

  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    if [[ "$DEPLOY_MODE" == "docker" ]]; then
      if docker_noaff_container_running && probe_local_panel; then
        return 0
      fi
    else
      if systemctl is-active --quiet "${APP_NAME}" && probe_local_panel; then
        return 0
      fi
    fi
    sleep 2
  done

  warn "Application health check failed after ${APP_STARTUP_TIMEOUT_SECONDS} seconds."
  print_healthcheck_diagnostics
  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    docker_compose ps || true
    docker_compose logs --tail=120 noaff || true
    die "Docker app failed health check. The installer stopped before reporting success."
  fi

  systemctl status "${APP_NAME}" --no-pager || true
  journalctl -u "${APP_NAME}" --no-pager -n 120 -l || true
  die "Native app failed health check. The installer stopped before reporting success."
}

run_docker_deploy_flow() {
  TOTAL_STEPS=7
  run_step "安装 Docker 运行环境" ensure_docker
  run_step "拉取或更新应用源码" clone_or_update_repo
  load_existing_env_defaults
  normalize_access_mode
  run_step "写入 Docker 应用环境配置" write_env_file
  run_step "安装 noaff 快捷管理命令" write_management_cli
  run_step "构建并启动 Docker Compose 服务" deploy_docker_stack
  run_step "验证 Docker 面板启动状态" wait_for_application_ready
  run_step "调整防火墙放行高位端口" adjust_firewall
  final_summary
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
  CF_ZONE_ID="$(python3 - "$response" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
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
  record_id="$(python3 - "$lookup" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
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

issue_certificate_dns() {
  validate_certbot_email
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

write_acme_challenge_nginx() {
  local domains_csv server_names
  domains_csv="$(build_tls_domains)"
  server_names="$(printf '%s' "$domains_csv" | tr ',' ' ')"
  mkdir -p "$ACME_WEBROOT/.well-known/acme-challenge"

  cat > "$NGINX_SITE_PATH" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${server_names};

    location /.well-known/acme-challenge/ {
        root ${ACME_WEBROOT};
        try_files \$uri =404;
    }

    location / {
        return 200 'NOAFF ACME preflight is ready.';
        add_header Content-Type text/plain;
    }
}
EOF

  ln -sf "$NGINX_SITE_PATH" "$NGINX_SITE_LINK"
  restart_nginx_safely
}

issue_certificate_http() {
  validate_certbot_email
  [[ "$PUBLIC_HTTP_PORT" == "80" ]] || die "HTTP-01 certificate mode requires PUBLIC_HTTP_PORT=80."

  local domains_csv args=()
  domains_csv="$(build_tls_domains)"
  IFS=',' read -r -a domain_items <<< "$domains_csv"
  local domain
  for domain in "${domain_items[@]}"; do
    domain="$(printf '%s' "$domain" | xargs)"
    [[ -n "$domain" ]] && args+=("-d" "$domain")
  done
  [[ "${#args[@]}" -gt 0 ]] || die "No valid TLS domains were provided."

  write_acme_challenge_nginx

  local extra_flags=()
  bool_is_true "$LETSENCRYPT_STAGING" && extra_flags+=(--staging)

  if "$CERTBOT_BIN" certonly \
    --webroot \
    --webroot-path "$ACME_WEBROOT" \
    --agree-tos \
    --non-interactive \
    --keep-until-expiring \
    -m "$CERTBOT_EMAIL" \
    "${extra_flags[@]}" \
    "${args[@]}"; then
    return 0
  fi

  print_http_certificate_failure_help
  if offer_http_fallback_after_certificate_failure; then
    return 0
  fi
  die "HTTPS 证书申请失败。请按上方提示修复 80 端口公网访问，或改用 Cloudflare DNS-01 后重新运行安装脚本。"
}

print_http_certificate_failure_help() {
  local domains_csv
  domains_csv="$(build_tls_domains)"

  echo
  echo "${C_YELLOW}${C_BOLD}HTTPS 证书申请失败：公网 HTTP-01 验证没有通过${C_RESET}"
  echo "验证域名:      ${domains_csv}"
  echo "验证地址:      http://<你的域名>/.well-known/acme-challenge/<token>"
  echo "必须满足:      外网可以访问服务器 80/TCP，并且该路径由 Nginx 返回 Certbot 临时文件。"
  echo
  echo "常见原因:"
  echo "  1. 域名没有解析到当前服务器。"
  echo "  2. 云厂商安全组、防火墙或机房策略没有放行 80/TCP。"
  echo "  3. Cloudflare 小黄云开启后，源站 80 端口无法正常回源。"
  echo "  4. 机器上已有 Nginx/面板规则拦截了 /.well-known/acme-challenge/。"
  echo
  detect_origin_ips >/dev/null 2>&1 || true
  echo "当前服务器 IPv4: ${ORIGIN_IPV4:-未检测到}"
  if command_exists getent; then
    echo "域名解析结果:"
    while IFS= read -r domain; do
      printf '  %s -> ' "$domain"
      getent ahosts "$domain" 2>/dev/null | awk '{print $1}' | sort -u | xargs || true
    done < <(iter_tls_domains)
  fi
  if command_exists ss; then
    echo
    echo "当前 80 端口监听:"
    ss -ltnp "( sport = :80 )" 2>/dev/null || true
  fi
  if [[ -f /var/log/letsencrypt/letsencrypt.log ]]; then
    echo
    echo "Let's Encrypt 最近日志:"
    tail -n 25 /var/log/letsencrypt/letsencrypt.log || true
  fi
}

offer_http_fallback_after_certificate_failure() {
  has_tty || return 1
  if prompt_yes_no "是否先关闭 HTTPS，继续完成 HTTP 版本安装？修复 80 端口后可重新运行脚本申请证书" "Y"; then
    ENABLE_TLS="false"
    CERT_MODE="none"
    SESSION_COOKIE_SECURE="false"
    warn "已临时切换为 HTTP 安装。请修复 80 端口公网访问后重新运行脚本启用 HTTPS。"
    return 0
  fi
  return 1
}

issue_certificate() {
  if ! bool_is_true "$ENABLE_TLS"; then
    return
  fi
  case "$CERT_MODE" in
    dns)
      issue_certificate_dns
      ;;
    http)
      issue_certificate_http
      ;;
    none)
      return
      ;;
    *)
      die "Unknown CERT_MODE: $CERT_MODE"
      ;;
  esac
}

fetch_cloudflare_ips() {
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 60 https://api.cloudflare.com/client/v4/ips
}

restart_nginx_safely() {
  nginx -t
  systemctl enable nginx

  if systemctl is-active --quiet nginx; then
    log "检测到 Nginx 已在运行，仅执行 reload，不影响已有连接。"
    systemctl reload nginx && return
    journalctl -u nginx --no-pager -n 60 -l || true
    die "Nginx reload 失败。安装脚本不会重启或清理已有 Nginx，请检查上方日志。"
  fi

  if nginx_managed_ports_are_busy; then
    if nginx_managed_ports_held_only_by_nginx; then
      warn "检测到旧 Nginx 进程占用 80/443，但 systemd 未接管；正在优雅退出旧进程后重新启动。"
      stop_stale_nginx_processes
    else
      warn "检测到 80/443 等公网端口已被非 Nginx 进程占用，安装脚本不会杀掉其他服务。"
      print_nginx_port_listeners
      die "请改用 IP + 高位端口 / Docker 高位端口模式，或手动把现有反代服务指向 ${APP_HOST}:${APP_PORT} 后重试。"
    fi
  fi

  if systemctl start nginx; then
    return
  fi

  journalctl -u nginx --no-pager -n 60 -l || true
  die "Nginx 启动失败。请根据上方日志处理服务错误后重试。"
}

nginx_managed_port_expression() {
  local ports=()
  ports+=("$PUBLIC_HTTP_PORT")
  bool_is_true "$ENABLE_TLS" && ports+=("$PUBLIC_HTTPS_PORT")
  local expression=""
  local port
  for port in "${ports[@]}"; do
    if [[ -z "$expression" ]]; then
      expression="sport = :${port}"
    else
      expression="${expression} or sport = :${port}"
    fi
  done
  printf '%s' "$expression"
}

nginx_managed_ports_are_busy() {
  ss -ltn "( $(nginx_managed_port_expression) )" 2>/dev/null | grep -q LISTEN
}

nginx_managed_ports_held_only_by_nginx() {
  local listeners
  listeners="$(ss -ltnp "( $(nginx_managed_port_expression) )" 2>/dev/null | awk 'NR > 1')"
  [[ -n "$listeners" ]] || return 1
  printf '%s\n' "$listeners" | grep -q 'nginx' || return 1
  ! printf '%s\n' "$listeners" | grep -v 'nginx' | grep -q .
}

stop_stale_nginx_processes() {
  nginx -s quit >/dev/null 2>&1 || true
  sleep 2
  if nginx_managed_ports_are_busy && nginx_managed_ports_held_only_by_nginx; then
    pkill -TERM nginx >/dev/null 2>&1 || true
    sleep 2
  fi
  if nginx_managed_ports_are_busy && nginx_managed_ports_held_only_by_nginx; then
    pkill -KILL nginx >/dev/null 2>&1 || true
    sleep 1
  fi
}

print_nginx_port_listeners() {
  ss -ltnp "( $(nginx_managed_port_expression) )" 2>/dev/null || true
}

write_ssl_nginx_snippet() {
  mkdir -p "$(dirname "$SSL_SNIPPET")"
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

write_cloudflare_nginx_snippets() {
  local ip_json
  ip_json="$(fetch_cloudflare_ips)"
  mkdir -p "$(dirname "$CF_REALIP_SNIPPET")" "$(dirname "$CF_ALLOW_SNIPPET")"

  python3 - "$CF_REALIP_SNIPPET" "$CF_ALLOW_SNIPPET" "$ip_json" <<'PY'
import json
import sys

realip_path, allow_path, raw_payload = sys.argv[1:]
payload = json.loads(raw_payload)
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

  write_ssl_nginx_snippet
}

configure_nginx() {
  if ! bool_is_true "$ENABLE_NGINX"; then
    return
  fi

  local domains_csv primary_domain
  domains_csv="$(build_tls_domains)"
  primary_domain="$(printf '%s' "$domains_csv" | cut -d',' -f1 | xargs)"
  local server_names
  server_names="$(printf '%s' "$domains_csv" | tr ',' ' ')"
  local redirect_target="https://\$host"

  mkdir -p /var/www/html

  if ! bool_is_true "$ENABLE_TLS"; then
    cat > "$NGINX_SITE_PATH" <<EOF
server {
    listen ${PUBLIC_HTTP_PORT};
    listen [::]:${PUBLIC_HTTP_PORT};
    server_name ${server_names};

    client_max_body_size 2m;

    location / {
        proxy_pass http://${APP_HOST}:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto http;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port ${PUBLIC_HTTP_PORT};
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 90;
    }
}
EOF
    ln -sf "$NGINX_SITE_PATH" "$NGINX_SITE_LINK"
    restart_nginx_safely
    return
  fi

  write_ssl_nginx_snippet

  cat > "$NGINX_SITE_PATH" <<EOF
server {
    listen ${PUBLIC_HTTP_PORT};
    listen [::]:${PUBLIC_HTTP_PORT};
    server_name ${server_names};
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_REALIP_SNIPPET")
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_ALLOW_SNIPPET")

    location /.well-known/acme-challenge/ {
        root ${ACME_WEBROOT};
        try_files \$uri =404;
    }

    location / {
        return 301 ${redirect_target}\$request_uri;
    }
}

server {
    listen ${PUBLIC_HTTPS_PORT} ssl;
    listen [::]:${PUBLIC_HTTPS_PORT} ssl;
    http2 on;
    server_name ${server_names};

    ssl_certificate /etc/letsencrypt/live/${primary_domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${primary_domain}/privkey.pem;
    include ${SSL_SNIPPET};
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_REALIP_SNIPPET")
$(bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && printf '    include %s;\n' "$CF_ALLOW_SNIPPET")

    client_max_body_size 2m;

    location /.well-known/acme-challenge/ {
        root ${ACME_WEBROOT};
        try_files \$uri =404;
    }

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

  ln -sf "$NGINX_SITE_PATH" "$NGINX_SITE_LINK"
  restart_nginx_safely
}

should_delete_app_dir() {
  local answer normalized
  case "${DELETE_APP_DIR:-ask}" in
    1|true|TRUE|yes|YES|y|Y)
      return 0
      ;;
    0|false|FALSE|no|NO|n|N)
      return 1
      ;;
  esac
  has_tty || return 1
  read -r -p "是否完全删除 ${APP_DIR}（包含数据库、任务和配置）？[y/N]: " answer </dev/tty
  normalized="${answer,,}"
  [[ "$normalized" == "y" || "$normalized" == "yes" || "$normalized" == "1" || "$normalized" == "true" ]]
}

uninstall_noaff_installation() {
  [[ -n "$APP_DIR" && "$APP_DIR" != "/" ]] || die "APP_DIR 不安全，拒绝卸载。"

  log "开始清理 NOAFF 补货监控助手。"

  if command_exists systemctl; then
    systemctl stop "${APP_NAME}" >/dev/null 2>&1 || true
    systemctl disable "${APP_NAME}" >/dev/null 2>&1 || true
    systemctl stop "${APP_NAME}-upgrade.service" >/dev/null 2>&1 || true
    systemctl disable "${APP_NAME}-upgrade.service" >/dev/null 2>&1 || true
    systemctl stop "$(basename "$CERTBOT_RENEW_TIMER")" >/dev/null 2>&1 || true
    systemctl disable "$(basename "$CERTBOT_RENEW_TIMER")" >/dev/null 2>&1 || true
  fi

  if command_exists docker; then
    if [[ -f "${APP_DIR}/docker-compose.yml" ]]; then
      (cd "$APP_DIR" && docker_compose down --remove-orphans) || true
    fi
    docker rm -f noaff-monitor noaff-redis >/dev/null 2>&1 || true
  fi

  rm -f \
    "/etc/systemd/system/${APP_NAME}.service" \
    "$UPGRADE_SERVICE" \
    "$CERTBOT_RENEW_SERVICE" \
    "$CERTBOT_RENEW_TIMER" \
    "$UPGRADE_SCRIPT" \
    "$CERTBOT_RENEW_SCRIPT"

  if command_exists systemctl; then
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi

  rm -f "$NGINX_SITE_LINK" "$NGINX_SITE_PATH"
  if command_exists nginx && command_exists systemctl; then
    if nginx -t >/dev/null 2>&1; then
      systemctl reload nginx >/dev/null 2>&1 || true
    else
      warn "Nginx 配置检测未通过，已跳过 reload；请手动检查 nginx -t。"
    fi
  fi

  if should_delete_app_dir; then
    rm -rf "$APP_DIR"
    log "已删除应用目录：${APP_DIR}"
  else
    log "已保留应用目录和数据：${APP_DIR}"
  fi

  rm -f "$CLI_SCRIPT"
  log "NOAFF 清理/卸载完成。"
}

reset_admin_password() {
  load_existing_env_defaults
  local db_path="${APP_DIR}/data/monitor.db"
  local bootstrap_path="${APP_DIR}/data/bootstrap_admin.txt"
  [[ -f "$db_path" ]] || die "未找到数据库：${db_path}。请确认已经安装 NOAFF，或设置正确的 APP_DIR。"

  local username new_password confirm_password
  username="${RESET_ADMIN_USERNAME:-}"
  if [[ -z "$username" ]]; then
    username="$(prompt_default "请输入要设置的管理员用户名" "${ADMIN_USERNAME:-operator}")"
  fi
  [[ -n "$username" ]] || die "管理员用户名不能为空。"

  new_password="${RESET_ADMIN_PASSWORD:-}"
  if [[ -n "$new_password" ]]; then
    [[ "${#new_password}" -ge 10 ]] || die "RESET_ADMIN_PASSWORD 至少需要 10 位。"
  else
    if ! has_tty; then
      die "未检测到交互终端。请使用 RESET_ADMIN_USERNAME 和 RESET_ADMIN_PASSWORD，或在 SSH 终端运行。"
    fi
    while true; do
      new_password="$(prompt_secret_optional "请输入新密码（至少 10 位）：")"
      if [[ "${#new_password}" -lt 10 ]]; then
        warn "新密码至少需要 10 位。"
        continue
      fi
      confirm_password="$(prompt_secret_optional "请再次输入新密码：")"
      if [[ "$new_password" != "$confirm_password" ]]; then
        warn "两次输入的新密码不一致。"
        continue
      fi
      break
    done
  fi

  python3 - "$db_path" "$username" "$new_password" "$bootstrap_path" <<'PY'
import datetime as _dt
import hashlib
import pathlib
import secrets
import sqlite3
import sys

db_path, username, password, bootstrap_path = sys.argv[1:]
timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
salt = secrets.token_urlsafe(12)
digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 1_000_000).hex()
password_hash = f"pbkdf2:sha256:1000000${salt}${digest}"

with sqlite3.connect(db_path) as connection:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    row = connection.execute("SELECT id FROM admins WHERE username = ?", (username,)).fetchone()
    if row:
        connection.execute(
            "UPDATE admins SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, timestamp, row[0]),
        )
    else:
        first = connection.execute("SELECT id FROM admins ORDER BY id LIMIT 1").fetchone()
        if first:
            connection.execute(
                "UPDATE admins SET username = ?, password_hash = ?, updated_at = ? WHERE id = ?",
                (username, password_hash, timestamp, first[0]),
            )
        else:
            connection.execute(
                "INSERT INTO admins (username, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, timestamp, timestamp),
            )
    connection.commit()

path = pathlib.Path(bootstrap_path)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(f"username={username}\npassword={password}\npanel_path=/\n", encoding="utf-8")
PY

  chmod 600 "$bootstrap_path" || true
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    chown "${SERVICE_USER}:${SERVICE_USER}" "$bootstrap_path" || true
  fi

  log "管理员密码已重置。"
  echo "用户名:    ${username}"
  echo "临时凭据:  ${bootstrap_path}"
  echo "面板地址:  /"
  warn "请登录后立即在后台修改密码，并删除 ${bootstrap_path}。"
}

write_env_file() {
  [[ -n "$SECRET_KEY" ]] || SECRET_KEY="$(random_token)"
  [[ -n "$ADMIN_PASSWORD" ]] || ADMIN_PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)"
  local app_version app_branch
  app_version="$(git -C "$APP_DIR" describe --tags --exact-match HEAD 2>/dev/null || git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  app_branch="$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$REPO_REF")"

  cat > "$APP_DIR/.env" <<EOF
APP_HOST=${APP_HOST}
APP_PORT=${APP_PORT}
PUBLIC_APP_PORT=${PUBLIC_APP_PORT}
DOCKER_BIND_HOST=${DOCKER_BIND_HOST}
DEPLOY_MODE=${DEPLOY_MODE}
ACCESS_MODE=${ACCESS_MODE}
ENABLE_NGINX=${ENABLE_NGINX}
ENABLE_TLS=${ENABLE_TLS}
CERT_MODE=${CERT_MODE}
PUBLIC_HTTP_PORT=${PUBLIC_HTTP_PORT}
PUBLIC_HTTPS_PORT=${PUBLIC_HTTPS_PORT}
INSTALL_APP_DIR=${APP_DIR}
REPO_REF=${REPO_REF}
APP_VERSION=${app_version}
APP_BRANCH=${app_branch}
UPGRADE_SERVICE_NAME=${APP_NAME}-upgrade.service
UPGRADE_LOG_PATH=${UPGRADE_LOG}
FQDN=${FQDN}
TLS_DOMAINS=${TLS_DOMAINS}
CERTBOT_EMAIL=${CERTBOT_EMAIL}
CF_ZONE_NAME=${CF_ZONE_NAME}
CF_ZONE_ID=${CF_ZONE_ID}
CF_API_TOKEN=${CF_API_TOKEN}
CF_RECORD_PROXIED=${CF_RECORD_PROXIED}
CF_SSL_MODE=${CF_SSL_MODE}
ORIGIN_LOCKDOWN_TO_CLOUDFLARE=${ORIGIN_LOCKDOWN_TO_CLOUDFLARE}
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

write_upgrade_service() {
  cat > "$UPGRADE_SCRIPT" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
exec > >(tee -a "$UPGRADE_LOG") 2>&1
echo
echo "[\$(date '+%Y-%m-%d %H:%M:%S')] 开始升级 ${APP_NAME}"
cd "$APP_DIR"
git fetch origin "$REPO_REF" --prune
git checkout "$REPO_REF"
git pull --ff-only origin "$REPO_REF"
${APP_DIR}/.venv/bin/python -m pip install --upgrade pip setuptools wheel
${APP_DIR}/.venv/bin/pip install -r requirements.txt
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
systemctl restart "$APP_NAME"
echo "[\$(date '+%Y-%m-%d %H:%M:%S')] 升级完成"
EOF
  chmod 755 "$UPGRADE_SCRIPT"
  touch "$UPGRADE_LOG"
  chmod 644 "$UPGRADE_LOG"

  cat > "$UPGRADE_SERVICE" <<EOF
[Unit]
Description=Upgrade NOAFF Restock Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$UPGRADE_SCRIPT
EOF
}

write_systemd_units() {
  write_app_service
  write_upgrade_service
  if bool_is_true "$ENABLE_TLS"; then
    write_certbot_renewal_units
  fi
}

write_management_cli() {
  cat > "$CLI_SCRIPT" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME}"
APP_DIR="${APP_DIR}"
SERVICE_USER="${SERVICE_USER}"
INSTALL_SH="\${APP_DIR}/install.sh"
UPGRADE_SERVICE="${APP_NAME}-upgrade.service"
CERT_RENEW_TIMER="${APP_NAME}-cert-renew.timer"
CERT_RENEW_SERVICE="${APP_NAME}-cert-renew.service"
UPGRADE_SCRIPT="${UPGRADE_SCRIPT}"
CERT_RENEW_SCRIPT="${CERTBOT_RENEW_SCRIPT}"
NGINX_SITE_PATH="${NGINX_SITE_PATH}"
NGINX_SITE_LINK="${NGINX_SITE_LINK}"
CLI_SCRIPT="${CLI_SCRIPT}"

if [[ -t 1 ]]; then
  C_RESET=\$'\\033[0m'
  C_BOLD=\$'\\033[1m'
  C_RED=\$'\\033[31m'
  C_GREEN=\$'\\033[32m'
  C_YELLOW=\$'\\033[33m'
  C_CYAN=\$'\\033[36m'
else
  C_RESET=""
  C_BOLD=""
  C_RED=""
  C_GREEN=""
  C_YELLOW=""
  C_CYAN=""
fi

command_exists() {
  command -v "\$1" >/dev/null 2>&1
}

need_root() {
  if [[ "\$(id -u)" != "0" ]]; then
    echo "\${C_RED}请使用 root 执行：sudo noaff\${C_RESET}" >&2
    return 1
  fi
}

read_env_value() {
  local key="\$1"
  local env_file="\${APP_DIR}/.env"
  [[ -f "\$env_file" ]] || return 0
  awk -F= -v key="\$key" '\$1 == key { sub(/^[^=]*=/, ""); print; exit }' "\$env_file"
}

deploy_mode() {
  local mode
  mode="\$(read_env_value DEPLOY_MODE || true)"
  printf '%s' "\${mode:-native}"
}

docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "\$@"
  else
    docker-compose "\$@"
  fi
}

pause() {
  read -r -p "按回车返回菜单..." _ </dev/tty || true
}

header() {
  clear 2>/dev/null || true
  echo "\${C_CYAN}\${C_BOLD}NOAFF 补货监控助手\${C_RESET}"
  echo "应用目录: \${APP_DIR}"
  echo
}

show_status() {
  header
  local mode
  mode="\$(deploy_mode)"
  echo "部署模式: \${mode}"
  if [[ "\$mode" == "docker" && -f "\${APP_DIR}/docker-compose.yml" ]]; then
    (cd "\$APP_DIR" && docker_compose ps) || true
  else
    systemctl status "\$APP_NAME" --no-pager || true
  fi
}

show_logs() {
  local mode
  mode="\$(deploy_mode)"
  if [[ "\$mode" == "docker" && -f "\${APP_DIR}/docker-compose.yml" ]]; then
    cd "\$APP_DIR"
    docker_compose logs -f noaff
  else
    journalctl -u "\$APP_NAME" -f
  fi
}

restart_service() {
  need_root || return 1
  local mode
  mode="\$(deploy_mode)"
  if [[ "\$mode" == "docker" && -f "\${APP_DIR}/docker-compose.yml" ]]; then
    (cd "\$APP_DIR" && docker_compose restart noaff)
  else
    systemctl restart "\$APP_NAME"
  fi
  echo "\${C_GREEN}已发送重启命令。\${C_RESET}"
}

run_upgrade() {
  need_root || return 1
  [[ -f "\$INSTALL_SH" ]] || { echo "\${C_RED}未找到 \${INSTALL_SH}\${C_RESET}" >&2; return 1; }
  local mode
  mode="\$(deploy_mode)"
  if [[ "\$mode" == "docker" ]]; then
    cd "\$APP_DIR"
    bash "\$INSTALL_SH" --docker-upgrade
  else
    systemctl start "\$UPGRADE_SERVICE"
    echo "\${C_GREEN}已启动升级服务，可使用 noaff logs 查看应用日志。\${C_RESET}"
  fi
}

reset_password() {
  need_root || return 1
  [[ -f "\$INSTALL_SH" ]] || { echo "\${C_RED}未找到 \${INSTALL_SH}\${C_RESET}" >&2; return 1; }
  bash "\$INSTALL_SH" --reset-password
}

uninstall_noaff() {
  need_root || return 1
  header
  echo "\${C_YELLOW}清理/卸载只会处理 NOAFF 自己创建的服务、容器、Nginx 配置和快捷命令。\${C_RESET}"
  echo "\${C_YELLOW}不会删除系统 Docker、不会删除已有 Nginx 站点、不会清空其他服务。\${C_RESET}"
  echo
  read -r -p "确认卸载请输入 NOAFF: " confirm </dev/tty
  if [[ "\$confirm" != "NOAFF" ]]; then
    echo "已取消。"
    return 0
  fi

  local mode
  mode="\$(deploy_mode)"
  if [[ "\$mode" == "docker" && -f "\${APP_DIR}/docker-compose.yml" ]]; then
    echo "停止并移除 NOAFF Docker 容器..."
    (cd "\$APP_DIR" && docker_compose down --remove-orphans) || true
  fi

  echo "停止并移除 NOAFF systemd 单元..."
  systemctl stop "\$APP_NAME" "\$UPGRADE_SERVICE" "\$CERT_RENEW_SERVICE" "\$CERT_RENEW_TIMER" 2>/dev/null || true
  systemctl disable "\$APP_NAME" "\$CERT_RENEW_TIMER" 2>/dev/null || true
  rm -f "/etc/systemd/system/\${APP_NAME}.service" "/etc/systemd/system/\${UPGRADE_SERVICE}" \
        "/etc/systemd/system/\${CERT_RENEW_SERVICE}" "/etc/systemd/system/\${CERT_RENEW_TIMER}"
  rm -f "\$UPGRADE_SCRIPT" "\$CERT_RENEW_SCRIPT"
  systemctl daemon-reload 2>/dev/null || true

  echo "移除 NOAFF Nginx 独立站点配置..."
  rm -f "\$NGINX_SITE_LINK" "\$NGINX_SITE_PATH"
  if command_exists nginx && command_exists systemctl; then
    if nginx -t >/dev/null 2>&1; then
      systemctl reload nginx 2>/dev/null || true
    else
      echo "\${C_YELLOW}Nginx 配置检测未通过，已跳过 reload，请手动检查 nginx -t。\${C_RESET}"
    fi
  fi

  echo
  read -r -p "是否完全删除 \${APP_DIR}（包含数据库和任务）？[y/N]: " delete_app </dev/tty
  case "\${delete_app,,}" in
    y|yes)
      rm -rf "\$APP_DIR"
      echo "已删除应用目录。"
      ;;
    *)
      echo "已保留应用目录和数据：\${APP_DIR}"
      ;;
  esac

  rm -f "\$CLI_SCRIPT"
  echo "\${C_GREEN}NOAFF 清理/卸载完成。\${C_RESET}"
}

menu() {
  while true; do
    header
    echo "  1) 查看状态"
    echo "  2) 查看日志"
    echo "  3) 重启服务"
    echo "  4) 升级程序"
    echo "  5) 重置后台密码"
    echo "  6) 清理/卸载 NOAFF"
    echo "  0) 退出"
    echo
    read -r -p "请选择: " choice </dev/tty
    case "\$choice" in
      1) show_status; pause ;;
      2) show_logs ;;
      3) restart_service; pause ;;
      4) run_upgrade; pause ;;
      5) reset_password; pause ;;
      6) uninstall_noaff; break ;;
      0) exit 0 ;;
      *) echo "无效选项。"; sleep 1 ;;
    esac
  done
}

case "\${1:-menu}" in
  status) show_status ;;
  logs) show_logs ;;
  restart) restart_service ;;
  upgrade) run_upgrade ;;
  reset-password) reset_password ;;
  uninstall|clean) uninstall_noaff ;;
  menu) menu ;;
  *)
    echo "用法: noaff [status|logs|restart|upgrade|reset-password|uninstall]"
    exit 1
    ;;
esac
EOF
  chmod 755 "$CLI_SCRIPT"
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
  release_native_app_port
  systemctl enable redis-server
  systemctl restart redis-server
  systemctl enable "${APP_NAME}"
  systemctl restart "${APP_NAME}"
  if bool_is_true "$ENABLE_TLS"; then
    systemctl enable "$(basename "$CERTBOT_RENEW_TIMER")"
    systemctl restart "$(basename "$CERTBOT_RENEW_TIMER")"
  fi
}

adjust_firewall() {
  if command_exists ufw && ufw status | grep -qi active; then
    if [[ "$DEPLOY_MODE" == "docker" ]]; then
      ufw allow "${PUBLIC_APP_PORT}/tcp" || true
    elif bool_is_true "$ENABLE_NGINX"; then
      ufw allow "${PUBLIC_HTTP_PORT}/tcp" || true
      bool_is_true "$ENABLE_TLS" && ufw allow "${PUBLIC_HTTPS_PORT}/tcp" || true
    else
      ufw allow "${APP_PORT}/tcp" || true
    fi
  fi
}

final_summary() {
  local public_url
  public_url="$(build_public_url)"

  echo
  echo "${C_GREEN}${C_BOLD}NOAFF 补货监控已安装完成。${C_RESET}"
  echo "服务状态:  systemctl status ${APP_NAME} --no-pager"
  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    echo "容器状态:  cd ${APP_DIR} && docker compose ps"
    echo "容器日志:  cd ${APP_DIR} && docker compose logs -f noaff"
    echo "反代提示:  现有 Nginx 可反代到 http://127.0.0.1:${PUBLIC_APP_PORT}"
  else
    echo "服务日志:  journalctl -u ${APP_NAME} -f"
  fi
  bool_is_true "$ENABLE_NGINX" && echo "Nginx 状态: systemctl status nginx --no-pager"
  bool_is_true "$ENABLE_TLS" && echo "证书续期:  systemctl list-timers | grep ${APP_NAME}"
  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    echo "升级命令:  cd ${APP_DIR} && bash install.sh --docker-upgrade"
  else
    echo "升级命令:  systemctl start ${APP_NAME}-upgrade.service"
  fi
  echo "快捷命令:  noaff"
  echo "面板地址:  ${public_url}"
  if ! bool_is_true "$ENABLE_TLS" && [[ -n "$FQDN" ]]; then
    echo "提示:      当前为 HTTP 模式，请直接访问 http://${FQDN}"
    echo "提示:      如果浏览器自动跳转到 https，请清除该域名的 HTTPS-Only / HSTS 记录后再访问。"
  fi
  echo "管理员:    ${ADMIN_USERNAME}"
  if [[ -f "${APP_DIR}/data/bootstrap_admin.txt" ]]; then
    echo "初始密码:  ${ADMIN_PASSWORD}"
  else
    echo "初始密码:  保持不变（沿用当前面板密码）"
  fi
  echo
  if [[ "$ACCESS_MODE" == "domain-cf" ]]; then
    echo "提示:      如果 Cloudflare SSL 模式未自动切换，请手动设为 Full (strict)。"
  fi
  echo "提示:      首次修改密码后，请删除 ${APP_DIR}/data/bootstrap_admin.txt。"
}

set_total_steps() {
  TOTAL_STEPS=10
  bool_is_true "$ENABLE_TLS" && TOTAL_STEPS=$((TOTAL_STEPS + 2))
  [[ "$CERT_MODE" == "dns" ]] && TOTAL_STEPS=$((TOTAL_STEPS + 1))
  bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE" && TOTAL_STEPS=$((TOTAL_STEPS + 1))
  bool_is_true "$ENABLE_NGINX" && TOTAL_STEPS=$((TOTAL_STEPS + 1))
}

main() {
  parse_args "$@"
  if ! bool_is_true "$INSTALL_VALIDATE_ONLY"; then
    require_root
    touch "$INSTALL_LOG"
    chmod 644 "$INSTALL_LOG"
    exec > >(tee -a "$INSTALL_LOG") 2>&1
  fi
  load_existing_env_defaults
  if bool_is_true "$UNINSTALL_ONLY"; then
    uninstall_noaff_installation
    return
  fi
  if bool_is_true "$PASSWORD_RESET_ONLY"; then
    reset_admin_password
    return
  fi
  if bool_is_true "$DOCKER_UPGRADE_ONLY"; then
    normalize_access_mode
    run_docker_deploy_flow
    return
  fi
  if ! bool_is_true "$INSTALL_VALIDATE_ONLY"; then
    choose_existing_install_action
  fi
  if should_run_interactive_wizard; then
    interactive_wizard
  elif needs_interactive_inputs; then
    die "未检测到可交互终端。请直接在 SSH 终端运行 curl 安装命令，或显式传入 ACCESS_MODE=ip/domain-direct/domain-cf。"
  fi
  normalize_access_mode

  if bool_is_true "$INSTALL_VALIDATE_ONLY"; then
    validate_only
    return
  fi

  validate_required_inputs
  validate_runtime_config

  if [[ "$DEPLOY_MODE" == "docker" ]]; then
    run_docker_deploy_flow
    return
  fi

  set_total_steps

  run_step "安装系统依赖" ensure_packages
  run_step "安装/定位 Chromium 浏览器" ensure_browser
  run_step "创建服务用户" ensure_service_user

  run_step "拉取或更新应用源码" clone_or_update_repo
  load_existing_env_defaults
  validate_required_inputs
  validate_runtime_config
  run_step "安装 noaff 快捷管理命令" write_management_cli

  run_step "安装 Python 虚拟环境依赖" setup_python_env

  if bool_is_true "$ENABLE_TLS"; then
    run_step "安装 Certbot 证书运行环境" setup_certbot_env
  fi

  if [[ "$CERT_MODE" == "dns" ]]; then
    run_step "配置 Cloudflare DNS / 小黄云" configure_cloudflare_dns
  fi

  if bool_is_true "$ENABLE_TLS"; then
    run_step "申请或续期 HTTPS 证书" issue_certificate
  fi

  if bool_is_true "$ORIGIN_LOCKDOWN_TO_CLOUDFLARE"; then
    run_step "写入 Cloudflare 回源识别与锁定规则" write_cloudflare_nginx_snippets
  fi

  run_step "写入应用环境配置" write_env_file

  run_step "写入 systemd 服务与升级服务" write_systemd_units

  mkdir -p "${APP_DIR}/data"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}"

  if bool_is_true "$ENABLE_NGINX"; then
    run_step "配置 Nginx 反向代理" configure_nginx
  fi

  run_step "启动并启用系统服务" enable_services
  run_step "验证应用启动状态" wait_for_application_ready

  adjust_firewall
  final_summary
}

if ! bool_is_true "${NOAFF_INSTALL_LIBRARY_MODE:-false}"; then
  main "$@"
fi
