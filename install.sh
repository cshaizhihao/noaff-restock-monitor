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
INSTALL_VALIDATE_ONLY=false

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
ACME_WEBROOT="/var/www/${APP_NAME}-acme"
INSTALL_LOG="/var/log/${APP_NAME}-install.log"
CF_SUPPORTED_HTTP_PORTS=(80 8080 8880 2052 2082 2086 2095)
CF_SUPPORTED_HTTPS_PORTS=(443 2053 2083 2087 2096 8443)
CURRENT_STEP=0
TOTAL_STEPS=1

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
  bash install.sh --help

Interactive mode:
  Run without required variables to enter a full Chinese installer wizard.

Install modes:
  ACCESS_MODE=ip             IP + port test mode
  ACCESS_MODE=domain-direct  Domain direct mode without Cloudflare orange-cloud
  ACCESS_MODE=domain-cf      Domain mode with Cloudflare orange-cloud

Common optional environment:
  APP_PORT=7777
  PUBLIC_HTTP_PORT=80
  PUBLIC_HTTPS_PORT=443
  FQDN=monitor.example.com
  TLS_DOMAINS=monitor.example.com,www.monitor.example.com
  CERTBOT_EMAIL=ops@example.com
  CERT_MODE=http|dns|none|auto
  CF_ZONE_NAME=example.com
  CF_API_TOKEN=cf_xxx
  MONITOR_DEBUG_PORT=9223
  TEST_DEBUG_PORT=9334
  CF_RECORD_PROXIED=true
  REPO_REF=master

Modes:
  --validate-only  Validate required variables and Cloudflare-compatible ports without installing.
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

normalize_access_mode() {
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
      CERT_MODE="${CERT_MODE:-auto}"
      ;;
    domain-cf)
      ENABLE_NGINX="true"
      CF_RECORD_PROXIED="${CF_RECORD_PROXIED:-true}"
      APP_HOST="127.0.0.1"
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
    [[ -n "$CERTBOT_EMAIL" ]] || die "CERTBOT_EMAIL is required when TLS is enabled."
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

should_run_interactive_wizard() {
  [[ "$INTERACTIVE_INSTALL" != "false" ]] || return 1
  [[ "$INSTALL_VALIDATE_ONLY" != "true" ]] || return 1
  [[ -z "$ACCESS_MODE" && -z "$FQDN" ]] || return 1
  has_tty
}

prompt_domain() {
  local answer
  while true; do
    answer="$(prompt_read "请输入域名，例如 monitor.example.com：")"
    if [[ -n "$answer" ]]; then
      FQDN="$answer"
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

  APP_PORT="$(prompt_default "[1/8] 请输入应用本机端口" "$APP_PORT")"
  validate_port "APP_PORT" "$APP_PORT" 1024 65535

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
      PUBLIC_HTTPS_PORT="$(prompt_default "[3/8] 请输入 HTTPS 公网端口" "$PUBLIC_HTTPS_PORT")"
      if prompt_yes_no "[4/8] 是否自动申请 Let's Encrypt HTTPS 证书？证书验证需要 80 端口可访问" "Y"; then
        ENABLE_TLS="true"
        CERT_MODE="http"
        CERTBOT_EMAIL="$(prompt_default "请输入 Let's Encrypt 邮箱" "${CERTBOT_EMAIL:-ops@example.com}")"
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
      PUBLIC_HTTPS_PORT="$(prompt_default "[3/8] 请输入 HTTPS 公网端口，Cloudflare 小黄云推荐 443" "$PUBLIC_HTTPS_PORT")"
      if prompt_yes_no "[4/8] 你是否已经在 Cloudflare 开启或准备开启小黄云？" "Y"; then
        CF_RECORD_PROXIED="true"
        ORIGIN_LOCKDOWN_TO_CLOUDFLARE="true"
      else
        CF_RECORD_PROXIED="false"
        ORIGIN_LOCKDOWN_TO_CLOUDFLARE="false"
        ACCESS_MODE="domain-direct"
      fi
      if prompt_yes_no "[5/8] 是否提供 Cloudflare API Token 以启用 DNS-01 全自动证书？普通用户可选 n" "n"; then
        CF_API_TOKEN="$(prompt_secret_optional "请输入 Cloudflare API Token（输入时不显示）：")"
        CF_ZONE_NAME="$(prompt_default "请输入 Cloudflare Zone 名称，例如 example.com" "$CF_ZONE_NAME")"
        CERT_MODE="dns"
      else
        CERT_MODE="http"
      fi
      ENABLE_TLS="true"
      CERTBOT_EMAIL="$(prompt_default "[6/8] 请输入 Let's Encrypt 邮箱" "${CERTBOT_EMAIL:-ops@example.com}")"
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
  case "$ACCESS_MODE" in
    ip)
      access_label="IP + 端口"
      detect_origin_ips
      public_url="http://${ORIGIN_IPV4:-服务器IP}:${APP_PORT}"
      ;;
    domain-direct)
      access_label="域名直连"
      public_url="$(bool_is_true "$ENABLE_TLS" && printf 'https' || printf 'http')://${FQDN}"
      ;;
    domain-cf)
      access_label="Cloudflare 小黄云"
      public_url="https://${FQDN}"
      ;;
  esac
  if bool_is_true "$ENABLE_TLS" && [[ "$PUBLIC_HTTPS_PORT" != "443" ]]; then
    public_url="${public_url}:${PUBLIC_HTTPS_PORT}"
  elif ! bool_is_true "$ENABLE_TLS" && [[ "$ACCESS_MODE" != "ip" && "$PUBLIC_HTTP_PORT" != "80" ]]; then
    public_url="${public_url}:${PUBLIC_HTTP_PORT}"
  fi

  echo
  echo "${C_BOLD}${C_GREEN}安装摘要${C_RESET}"
  echo "访问方式：      ${access_label}"
  echo "面板地址：      ${public_url}${PORTAL_PATH:-/portal_自动生成}"
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

  rm -f /etc/nginx/sites-enabled/default
  ln -sf "$NGINX_SITE_PATH" "$NGINX_SITE_LINK"
  nginx -t
  systemctl enable nginx
  systemctl restart nginx
}

issue_certificate_http() {
  [[ -n "$CERTBOT_EMAIL" ]] || die "CERTBOT_EMAIL is required for Let's Encrypt."
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

  "$CERTBOT_BIN" certonly \
    --webroot \
    --webroot-path "$ACME_WEBROOT" \
    --agree-tos \
    --non-interactive \
    --keep-until-expiring \
    -m "$CERTBOT_EMAIL" \
    "${extra_flags[@]}" \
    "${args[@]}"
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

write_cloudflare_nginx_snippets() {
  local ip_json
  ip_json="$(fetch_cloudflare_ips)"
  mkdir -p /etc/nginx/snippets

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
  if ! bool_is_true "$ENABLE_NGINX"; then
    return
  fi

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
    rm -f /etc/nginx/sites-enabled/default
    ln -sf "$NGINX_SITE_PATH" "$NGINX_SITE_LINK"
    nginx -t
    systemctl enable nginx
    systemctl restart nginx
    return
  fi

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
  if bool_is_true "$ENABLE_TLS"; then
    systemctl enable "$(basename "$CERTBOT_RENEW_TIMER")"
    systemctl restart "$(basename "$CERTBOT_RENEW_TIMER")"
  fi
}

adjust_firewall() {
  if command_exists ufw && ufw status | grep -qi active; then
    if bool_is_true "$ENABLE_NGINX"; then
      ufw allow "${PUBLIC_HTTP_PORT}/tcp" || true
      bool_is_true "$ENABLE_TLS" && ufw allow "${PUBLIC_HTTPS_PORT}/tcp" || true
    else
      ufw allow "${APP_PORT}/tcp" || true
    fi
  fi
}

final_summary() {
  local public_url
  if [[ "$ACCESS_MODE" == "ip" ]]; then
    detect_origin_ips
    public_url="http://${ORIGIN_IPV4:-服务器IP}:${APP_PORT}"
  elif bool_is_true "$ENABLE_TLS"; then
    public_url="https://${FQDN}"
    [[ "$PUBLIC_HTTPS_PORT" != "443" ]] && public_url="${public_url}:${PUBLIC_HTTPS_PORT}"
  else
    public_url="http://${FQDN}"
    [[ "$PUBLIC_HTTP_PORT" != "80" ]] && public_url="${public_url}:${PUBLIC_HTTP_PORT}"
  fi

  echo
  echo "${C_GREEN}${C_BOLD}NOAFF monitor is installed.${C_RESET}"
  echo "Service:   systemctl status ${APP_NAME} --no-pager"
  echo "Logs:      journalctl -u ${APP_NAME} -f"
  bool_is_true "$ENABLE_NGINX" && echo "Nginx:     systemctl status nginx --no-pager"
  bool_is_true "$ENABLE_TLS" && echo "Cert renew: systemctl list-timers | grep ${APP_NAME}"
  echo "Upgrade:   systemctl start ${APP_NAME}-upgrade.service"
  echo "Panel:     ${public_url}${PORTAL_PATH}"
  echo "Admin:     ${ADMIN_USERNAME}"
  if [[ -f "${APP_DIR}/data/bootstrap_admin.txt" ]]; then
    echo "Password:  ${ADMIN_PASSWORD}"
  else
    echo "Password:  unchanged (use the current panel password)"
  fi
  echo "Portal:    ${PORTAL_PATH}"
  echo
  if [[ "$ACCESS_MODE" == "domain-cf" ]]; then
    echo "If Cloudflare SSL mode was not switched automatically, set it to Full (strict)."
  fi
  echo "Delete ${APP_DIR}/data/bootstrap_admin.txt after first password change."
}

set_total_steps() {
  TOTAL_STEPS=8
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
  if should_run_interactive_wizard; then
    interactive_wizard
  fi
  normalize_access_mode

  if bool_is_true "$INSTALL_VALIDATE_ONLY"; then
    validate_only
    return
  fi

  validate_required_inputs
  validate_runtime_config
  set_total_steps

  run_step "安装系统依赖" ensure_packages
  run_step "安装/定位 Chromium 浏览器" ensure_browser
  run_step "创建服务用户" ensure_service_user

  run_step "拉取或更新应用源码" clone_or_update_repo
  load_existing_env_defaults
  validate_required_inputs
  validate_runtime_config

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

  adjust_firewall
  final_summary
}

if ! bool_is_true "${NOAFF_INSTALL_LIBRARY_MODE:-false}"; then
  main "$@"
fi
