import hashlib
import html as html_module
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from string import Formatter
from typing import Any
from urllib.parse import urljoin, urlparse, urldefrag

import psutil
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from requests import Response
from waitress import serve
from werkzeug.exceptions import BadRequest
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from DrissionPage import ChromiumOptions, ChromiumPage
except Exception:  # pragma: no cover - runtime dependency may be absent during local linting
    ChromiumOptions = None
    ChromiumPage = None


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "monitor.db"
ENV_PATH = BASE_DIR / ".env"
BOOTSTRAP_CREDENTIALS_PATH = DATA_DIR / "bootstrap_admin.txt"
SECRET_KEY_PATH = DATA_DIR / ".secret_key"
UTC = timezone.utc

load_dotenv(ENV_PATH if ENV_PATH.exists() else None)


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def now_iso() -> str:
    return now_utc().isoformat(timespec="seconds")


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_or_create_secret_key() -> str:
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    SECRET_KEY_PATH.write_text(secret, encoding="utf-8")
    return secret


SECRET_KEY = os.getenv("SECRET_KEY") or load_or_create_secret_key()
PORTAL_PATH = ""

DEFAULT_APP_PORT = int(os.getenv("APP_PORT", "7777"))
DEFAULT_APP_HOST = os.getenv("APP_HOST", "0.0.0.0").strip() or "0.0.0.0"
DEFAULT_MONITOR_PORT = int(os.getenv("MONITOR_DEBUG_PORT", "9223"))
DEFAULT_TEST_PORT = int(os.getenv("TEST_DEBUG_PORT", "9334"))
DEFAULT_CATALOG_PORT = int(os.getenv("CATALOG_DEBUG_PORT", "9445"))
DEFAULT_POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
DEFAULT_HEADLESS = env_bool("CHROMIUM_HEADLESS", True)
DEFAULT_BROWSER_PATH = os.getenv("CHROMIUM_BINARY", "").strip()
DEFAULT_BROWSER_USER_AGENT = os.getenv("CHROMIUM_USER_AGENT", "").strip()
ENABLE_PROXY_FIX = env_bool("ENABLE_PROXY_FIX", False)
PROXY_FIX_X_FOR = int(os.getenv("PROXY_FIX_X_FOR", "1"))
PROXY_FIX_X_PROTO = int(os.getenv("PROXY_FIX_X_PROTO", "1"))
PROXY_FIX_X_HOST = int(os.getenv("PROXY_FIX_X_HOST", "1"))
PROXY_FIX_X_PORT = int(os.getenv("PROXY_FIX_X_PORT", "1"))
DEPLOY_MODE = (os.getenv("DEPLOY_MODE", "").strip() or "native").lower()
INSTALL_APP_DIR = os.getenv("INSTALL_APP_DIR", "/opt/noaff-monitor").strip() or "/opt/noaff-monitor"
REPO_REF = os.getenv("REPO_REF", "master").strip() or "master"
APP_VERSION_OVERRIDE = os.getenv("APP_VERSION", "").strip()
APP_BRANCH_OVERRIDE = os.getenv("APP_BRANCH", "").strip()
UPGRADE_SERVICE_NAME = os.getenv("UPGRADE_SERVICE_NAME", "noaff-monitor-upgrade.service")
UPGRADE_LOG_PATH = Path(os.getenv("UPGRADE_LOG_PATH", "/var/log/noaff-monitor-upgrade.log"))

LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5 per minute")
GENERAL_MUTATION_LIMIT = os.getenv("GENERAL_MUTATION_LIMIT", "40 per minute")
LIMITER_STORAGE_URI = os.getenv("LIMITER_STORAGE_URI", "memory://")

ALLOWED_BROWSER_HINTS = ("mozilla", "chrome", "safari", "firefox", "edg", "applewebkit")
SOLD_OUT_MARKERS = (
    "sold out",
    "sold-out",
    "out of stock",
    "currently out of stock",
    "not available",
    "unavailable",
    "no stock",
    "stock exhausted",
    "暂无库存",
    "暫無庫存",
    "无库存",
    "無庫存",
    "缺货",
    "缺貨",
    "售罄",
    "已售罄",
    "无货",
    "無貨",
    "补货中",
    "補貨中",
    "已下架",
)

BROWSER_RECOVERY_MARKERS = (
    "browserconnecterror",
    "browser connect",
    "browser connection",
    "cannot connect",
    "connection refused",
    "devtoolsactiveport",
    "disconnected",
    "just a moment",
    "cloudflare",
    "turnstile",
    "cf-turnstile",
    "checking your browser",
    "attention required",
    "remote debugging",
    "timeout",
    "timed out",
    "user data directory",
    "user-data-dir",
    "浏览器连接失败",
    "用户文件夹",
    "无界面系统",
    "调试端口",
)
BROWSER_ERROR_KINDS = {
    "cloudflare_challenge": (
        "cloudflare",
        "turnstile",
        "checking your browser",
        "attention required",
        "verify you are human",
        "just a moment",
        "cf-turnstile",
        "验证页",
    ),
    "timeout": ("timeout", "timed out", "超时"),
    "browser_connection": (
        "browserconnecterror",
        "browser connection",
        "connection refused",
        "disconnected",
        "remote debugging",
        "user data directory",
        "user-data-dir",
        "浏览器连接",
        "调试端口",
        "崩溃",
    ),
}
BROWSER_LOCK_FILENAMES = (
    "DevToolsActivePort",
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
)
DEFAULT_TASK_GROUP = "默认分组"

SETTINGS_DEFAULTS = {
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    "monitor_debug_port": str(DEFAULT_MONITOR_PORT),
    "test_debug_port": str(DEFAULT_TEST_PORT),
    "catalog_debug_port": str(DEFAULT_CATALOG_PORT),
    "poll_interval_seconds": str(DEFAULT_POLL_INTERVAL),
    "request_timeout_seconds": str(DEFAULT_TIMEOUT_SECONDS),
}

DEFAULT_RESTOCK_TEMPLATE = "<b>{name}</b>\n库存：{stock}\n链接：{url}\n检测时间：{checked_at}"
DEFAULT_SOLDOUT_TEMPLATE = "<b>{name}</b>\n已售罄\n最后库存：{stock}\n检测时间：{checked_at}"

STOCK_LABEL = (
    r"(?:库存|庫存|可用|可售|有货|有貨|现货|現貨|剩余|剩餘|余量|餘量|还剩|還剩|数量|數量|"
    r"available|availability|in\s*stock|stock|qty|quantity|inventory|remaining|left|units?)"
)
STOCK_HTML_GAP = r"(?:\s|&nbsp;|&#\d+;|&[a-z]+;|[:：=()（）\[\]【】\-_/]|<!--.*?-->|<[^>]{1,240}>){0,40}"
STOCK_PATTERNS = [
    re.compile(
        rf"{STOCK_LABEL}{STOCK_HTML_GAP}(?P<count>\d{{1,6}})",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"(?P<count>\d{{1,6}}){STOCK_HTML_GAP}{STOCK_LABEL}",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"(?:only|仅剩|僅剩){STOCK_HTML_GAP}(?P<count>\d{{1,6}}){STOCK_HTML_GAP}"
        rf"(?:left|available|stock|件|台|个|個)?",
        re.IGNORECASE | re.DOTALL,
    ),
]
JSON_SCRIPT_PATTERN = re.compile(r"<script\b[^>]*>(?P<body>.*?)</script>", re.IGNORECASE | re.DOTALL)
JSON_STOCK_KEYS = {
    "stock",
    "stocklevel",
    "stockquantity",
    "stockqty",
    "quantity",
    "qty",
    "inventory",
    "inventorylevel",
    "inventoryquantity",
    "inventoryqty",
    "availablequantity",
    "availablestock",
    "remaining",
    "left",
    "onhand",
    "onhandquantity",
}
JSON_AVAILABILITY_KEYS = {
    "availability",
    "availabilitystatus",
    "availablestatus",
    "available",
    "isavailable",
    "instock",
    "stockstatus",
    "inventorystatus",
    "orderable",
    "canpurchase",
    "canbuy",
}
JSON_RESTOCK_KEYS = {
    "restockdate",
    "availabilitydate",
    "backinstockdate",
    "backorderdate",
    "expecteddate",
    "shipdate",
    "releasedate",
    "availabledate",
    "deliverydate",
    "eta",
}
JSON_IN_STOCK_TOKENS = {
    "instock",
    "limitedavailability",
    "preorder",
    "backorder",
    "availablefororder",
    "backinstock",
    "availablenow",
    "readytoship",
    "现货",
    "有货",
    "可购买",
    "可下单",
    "预售",
    "预订",
    "預售",
    "預訂",
    "补货中",
    "補貨中",
    "到货",
    "到貨",
    "即将到货",
    "即將到貨",
}
JSON_OUT_OF_STOCK_TOKENS = {
    "outofstock",
    "soldout",
    "discontinued",
    "unavailable",
    "notavailable",
    "temporarilyunavailable",
    "缺货",
    "缺貨",
    "无货",
    "無貨",
    "暂无库存",
    "暫無庫存",
    "售罄",
    "已售罄",
}
RESTOCK_HINT_PATTERNS = [
    re.compile(
        r"(?:availabilityDate|restockDate|backInStockDate|backOrderDate|expectedDate|shipDate|releaseDate|"
        r"availableDate|deliveryDate|eta)['\"]?\s*[:=]\s*['\"]?(?P<hint>[^'\"<>\s,;]{4,40})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:预计|預計|预计于|預計於|补货|補貨|到货|到貨|restock(?:ed|ing)?|back\s*in\s*stock|"
        r"coming\s*soon|available\s*on|ships?\s*on|ship\s*date|availability\s*date|availabilityDate|"
        r"restockDate|backInStockDate|backOrderDate|expectedDate|shipDate|releaseDate|availableDate|"
        r"deliveryDate|pre[-\s]?order|"
        r"back[-\s]?order)[^\n<]{0,80}(?P<hint>(?:(?<!\d)\d{4}[./-]\d{1,2}[./-]\d{1,2}(?!\d)|"
        r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?!\d)|\d{4}年\d{1,2}月\d{1,2}日|today|tomorrow|tonight|"
        r"this week|next week|soon|coming soon|"
        r"即将到货|即將到貨|近期|稍后|稍後))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:预计|預計|补货|補貨|到货|到貨|restock(?:ed|ing)?|back\s*in\s*stock|availability\s*date|"
        r"availabilityDate|restockDate|backInStockDate|backOrderDate|expectedDate|shipDate|releaseDate|"
        r"availableDate|deliveryDate|back[-\s]?order)[^\n<]{0,80}(?P<hint>[^<\n]{1,80})",
        re.IGNORECASE,
    ),
]
STRUCTURED_STOCK_PATTERNS = [
    re.compile(
        r"\b(?:data-(?:stock|qty|quantity|inventory|inventory-quantity|inventory_quantity|"
        r"available|available-stock|available_stock|stock-level|stock_level|stock-quantity|stock_quantity)"
        r"|stock|qty|quantity|inventory|inventoryQuantity|inventory_quantity|inventoryLevel|inventory_level|"
        r"availableQuantity|available_quantity|availableStock|available_stock|stockLevel|stock_level|"
        r"remaining|left|onHand|on_hand)\s*=\s*['\"](?P<count>\d{1,6})['\"]",
        re.IGNORECASE,
    ),
    re.compile(
        r"['\"](?:stock|qty|quantity|inventory|inventoryQuantity|inventory_quantity|inventoryLevel|inventory_level|"
        r"availableQuantity|available_quantity|availableStock|available_stock|stockLevel|stock_level|"
        r"remaining|left|onHand|on_hand)['\"]\s*:\s*['\"]?(?P<count>\d{1,6})",
        re.IGNORECASE,
    ),
]
IN_STOCK_AVAILABILITY_PATTERNS = [
    re.compile(
        r"['\"]availability['\"]\s*:\s*['\"][^'\"]*(?:InStock|LimitedAvailability|PreOrder|BackOrder|BackInStock|AvailableForOrder|OnlineOnly|InStoreOnly)[^'\"]*['\"]",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:content|href)\s*=\s*['\"][^'\"]*(?:InStock|LimitedAvailability|PreOrder|BackOrder|BackInStock|AvailableForOrder|OnlineOnly|InStoreOnly)[^'\"]*['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"['\"](?:available|isAvailable|inStock|instock)['\"]\s*:\s*(?:true|1)", re.IGNORECASE),
    re.compile(r"\bdata-(?:available|in-stock|instock)\s*=\s*['\"](?:true|1|yes)['\"]", re.IGNORECASE),
]
OUT_OF_STOCK_AVAILABILITY_PATTERNS = [
    re.compile(
        r"['\"]availability['\"]\s*:\s*['\"][^'\"]*(?:OutOfStock|SoldOut|Discontinued|Unavailable|NotAvailable|TemporarilyUnavailable)[^'\"]*['\"]",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:content|href)\s*=\s*['\"][^'\"]*(?:OutOfStock|SoldOut|Discontinued|Unavailable|NotAvailable|TemporarilyUnavailable)[^'\"]*['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"['\"](?:available|isAvailable|inStock|instock)['\"]\s*:\s*(?:false|0)", re.IGNORECASE),
    re.compile(r"\bdata-(?:available|in-stock|instock)\s*=\s*['\"](?:false|0|no)['\"]", re.IGNORECASE),
]
ORDERABLE_PATTERNS = [
    re.compile(
        r"\b(?:order\s*now|configure|add\s*to\s*cart|buy\s*now|checkout|purchase|"
        r"pre[-\s]?order|back[-\s]?order|back\s*in\s*stock|available\s*now|coming\s*soon)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:立即(?:订购|訂購|购买|購買|下单|下單)|加入(?:购物车|購物車)|现在购买|現在購買|可下单|可下單|"
        r"可购买|可購買|选择套餐|選擇套餐|订购|訂購|预售|預售|预订|預訂|预约|預約|补货|補貨|到货通知|到貨通知|"
        r"即将到货|即將到貨|现货|現貨|有货|有貨)",
    ),
    re.compile(r"(?:cart\.php\?a=add|/cart/add|/checkout|/order)", re.IGNORECASE),
]


class SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def safe_format(template: str, values: dict[str, Any]) -> str:
    formatter = Formatter()
    buffer: list[str] = []
    safe_values = SafeDict({key: str(value) for key, value in values.items()})
    for literal_text, field_name, format_spec, conversion in formatter.parse(template or ""):
        buffer.append(literal_text)
        if field_name is None:
            continue
        replacement = safe_values[field_name]
        buffer.append(replacement)
    return "".join(buffer).strip()


def normalize_task_group(value: Any) -> str:
    group_name = re.sub(r"\s+", " ", str(value or "").strip())
    return (group_name or DEFAULT_TASK_GROUP)[:48]


def is_browser_user_agent(user_agent: str | None) -> bool:
    if not user_agent:
        return False
    normalized = user_agent.lower()
    return any(hint in normalized for hint in ALLOWED_BROWSER_HINTS)


def is_same_origin(req) -> bool:
    origin = req.headers.get("Origin", "").strip()
    if not origin:
        return True
    parsed_origin = urlparse(origin)
    if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.hostname:
        return False

    def first_header(value: str | None) -> str:
        return (value or "").split(",", 1)[0].strip()

    def parse_host(value: str | None) -> tuple[str, str]:
        raw_value = first_header(value)
        if not raw_value:
            return "", ""
        parsed = urlparse(raw_value if "://" in raw_value else f"//{raw_value}")
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return "", ""
        try:
            port = parsed.port
        except ValueError:
            port = None
        netloc = f"{hostname}:{port}" if port else hostname
        return hostname, netloc

    def is_internal_host(hostname: str) -> bool:
        if hostname in {"localhost", "0.0.0.0", "127.0.0.1", "::1"}:
            return True
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return address.is_loopback or address.is_private or address.is_link_local

    try:
        origin_port = parsed_origin.port
    except ValueError:
        return False
    origin_hostname = parsed_origin.hostname.lower()
    origin_netloc = f"{origin_hostname}:{origin_port}" if origin_port else origin_hostname

    forwarded_proto = first_header(req.headers.get("X-Forwarded-Proto"))
    forwarded_host = first_header(req.headers.get("X-Forwarded-Host"))
    forwarded_port = first_header(req.headers.get("X-Forwarded-Port"))

    expected_origins = {req.host_url.rstrip("/")}
    if forwarded_proto and forwarded_host:
        host_for_origin = forwarded_host
        if forwarded_port and ":" not in forwarded_host:
            default_port = "443" if forwarded_proto == "https" else "80"
            if forwarded_port != default_port:
                host_for_origin = f"{forwarded_host}:{forwarded_port}"
        expected_origins.add(f"{forwarded_proto}://{host_for_origin}".rstrip("/"))
    if origin.rstrip("/") in expected_origins:
        return True

    accepted_hosts: set[tuple[str, str]] = set()
    for candidate in (
        req.host,
        req.headers.get("Host"),
        forwarded_host,
        os.getenv("FQDN", ""),
        os.getenv("PUBLIC_HOST", ""),
    ):
        hostname, netloc = parse_host(candidate)
        if hostname:
            accepted_hosts.add((hostname, netloc))

    if any(origin_hostname == hostname or origin_netloc == netloc for hostname, netloc in accepted_hosts):
        return True

    # Some reverse proxies accidentally pass the upstream loopback host to Flask.
    # CSRF + X-Requested-With still protect mutations, so do not break valid HTTPS logins.
    if accepted_hosts and all(is_internal_host(hostname) for hostname, _ in accepted_hosts):
        return True

    return False


def issue_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    return token


def ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = issue_csrf_token()
    return token


def is_valid_csrf(req) -> bool:
    expected = session.get("csrf_token")
    supplied = req.headers.get("X-CSRF-Token") or req.headers.get("X-Csrf-Token") or ""
    return bool(expected) and secrets.compare_digest(expected, supplied)


def require_ajax_header(req) -> bool:
    return req.headers.get("X-Requested-With") == "XMLHttpRequest"


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def run_short_command(args: list[str], timeout: int = 4) -> str:
    try:
        completed = subprocess.run(
            args,
            cwd=BASE_DIR,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def tail_file(path: Path, lines: int = 12) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


def upgrade_service_exists() -> bool:
    return any(
        Path(base, UPGRADE_SERVICE_NAME).exists()
        for base in ("/etc/systemd/system", "/lib/systemd/system", "/usr/lib/systemd/system")
    )


def docker_upgrade_command() -> str:
    return f"cd {INSTALL_APP_DIR} && bash install.sh --docker-upgrade"


def upgrade_mode_payload() -> dict[str, str | bool]:
    if shutil.which("systemctl") and upgrade_service_exists():
        return {
            "upgrade_mode": "panel",
            "upgrade_supported": True,
            "upgrade_state": "一键升级可用",
            "upgrade_hint": "将通过 systemd 在后台拉取最新代码并自动重启服务。",
            "upgrade_command": f"systemctl start {UPGRADE_SERVICE_NAME}",
        }
    if DEPLOY_MODE == "docker":
        return {
            "upgrade_mode": "manual",
            "upgrade_supported": False,
            "upgrade_state": "Docker 手动升级",
            "upgrade_hint": "Docker 隔离部署为了安全起见，不直接从面板接管宿主机 Docker。请复制命令到服务器执行。",
            "upgrade_command": docker_upgrade_command(),
        }
    return {
        "upgrade_mode": "unsupported",
        "upgrade_supported": False,
        "upgrade_state": "当前环境不支持",
        "upgrade_hint": "未检测到安装脚本注册的升级服务。",
        "upgrade_command": "",
    }


def system_payload() -> dict[str, Any]:
    commit = run_short_command(["git", "rev-parse", "--short", "HEAD"])
    branch = run_short_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    tag = run_short_command(["git", "describe", "--tags", "--exact-match", "HEAD"])
    payload = {
        "version": tag or commit or APP_VERSION_OVERRIDE or "unknown",
        "branch": branch or APP_BRANCH_OVERRIDE or "",
        "commit": commit or "",
        "deploy_mode": DEPLOY_MODE,
        "upgrade_service": UPGRADE_SERVICE_NAME,
        "upgrade_log": tail_file(UPGRADE_LOG_PATH),
    }
    payload.update(upgrade_mode_payload())
    return payload


BACKUP_SCHEMA_VERSION = 1
BACKUP_TABLES = (
    "admins",
    "settings",
    "merchant_sources",
    "merchant_items",
    "tasks",
    "activity_logs",
)
BACKUP_RESTORE_ORDER = (
    "admins",
    "settings",
    "merchant_sources",
    "merchant_items",
    "tasks",
    "activity_logs",
)
BACKUP_AUTOINCREMENT_TABLES = (
    "admins",
    "merchant_sources",
    "merchant_items",
    "tasks",
    "activity_logs",
)


def sql_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if table == "settings":
        raw_rows = connection.execute(
            f"SELECT key, value, updated_at FROM {sql_identifier(table)} ORDER BY key ASC"
        ).fetchall()
        stored_rows = {row["key"]: row for row in raw_rows}
        effective_settings = load_settings(connection)
        backup_timestamp = now_iso()
        ordered_keys = list(SETTINGS_DEFAULTS.keys())
        extra_keys = sorted(
            key for key in effective_settings.keys() if key not in SETTINGS_DEFAULTS
        )
        result: list[dict[str, Any]] = []
        for key in ordered_keys + extra_keys:
            stored_row = stored_rows.get(key)
            result.append(
                {
                    "key": key,
                    "value": effective_settings.get(key, ""),
                    "updated_at": stored_row["updated_at"] if stored_row and stored_row["updated_at"] else backup_timestamp,
                }
            )
        return result

    rows = connection.execute(f"SELECT * FROM {sql_identifier(table)} ORDER BY id ASC").fetchall()
    return [dict(row) for row in rows]


def build_backup_payload(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = {table: table_rows(connection, table) for table in BACKUP_TABLES}
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "exported_at": now_iso(),
        "app": {
            "deploy_mode": DEPLOY_MODE,
            "version": APP_VERSION_OVERRIDE or run_short_command(["git", "rev-parse", "--short", "HEAD"]) or "unknown",
            "branch": APP_BRANCH_OVERRIDE or run_short_command(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or "",
        },
        "tables": tables,
    }


def normalize_backup_tables(payload: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("备份文件格式不正确。")
    schema_version = payload.get("schema_version", BACKUP_SCHEMA_VERSION)
    if not isinstance(schema_version, int) or schema_version < 1:
        raise ValueError("备份文件版本不受支持。")
    raw_tables = payload.get("tables")
    if raw_tables is None:
        raw_tables = {key: value for key, value in payload.items() if key in BACKUP_TABLES}
    if not isinstance(raw_tables, dict):
        raise ValueError("备份文件 tables 结构不正确。")

    normalized: dict[str, list[dict[str, Any]]] = {}
    for table in BACKUP_TABLES:
        rows = raw_tables.get(table, [])
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError(f"{table} 备份内容必须是列表。")
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{table} 备份行必须是对象。")
            normalized_rows.append(row)
        normalized[table] = normalized_rows
    if not normalized["admins"] or not normalized["settings"]:
        raise ValueError("备份文件缺少管理员或设置数据，无法恢复。")
    return normalized


def apply_backup_payload(connection: sqlite3.Connection, payload: Any) -> dict[str, int]:
    tables = normalize_backup_tables(payload)

    connection.execute("PRAGMA foreign_keys=OFF;")
    try:
        for table in BACKUP_RESTORE_ORDER:
            connection.execute(f"DELETE FROM {sql_identifier(table)}")
        try:
            placeholders = ", ".join("?" for _ in BACKUP_AUTOINCREMENT_TABLES)
            connection.execute(
                f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})",
                BACKUP_AUTOINCREMENT_TABLES,
            )
        except sqlite3.OperationalError:
            pass

        restored_counts: dict[str, int] = {}
        for table in BACKUP_RESTORE_ORDER:
            rows = tables.get(table, [])
            if not rows:
                restored_counts[table] = 0
                continue
            column_info = connection.execute(f"PRAGMA table_info({sql_identifier(table)})").fetchall()
            columns = [row["name"] for row in column_info]
            for row in rows:
                row_columns = [column for column in columns if column in row]
                if not row_columns:
                    continue
                quoted_columns = ", ".join(sql_identifier(column) for column in row_columns)
                placeholders = ", ".join("?" for _ in row_columns)
                values = [row[column] for column in row_columns]
                connection.execute(
                    f"INSERT INTO {sql_identifier(table)} ({quoted_columns}) VALUES ({placeholders})",
                    values,
                )
            restored_counts[table] = len(rows)
        connection.commit()
        return restored_counts
    finally:
        connection.execute("PRAGMA foreign_keys=ON;")


def validate_http_url(candidate: str) -> bool:
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def find_browser_binary() -> str:
    if DEFAULT_BROWSER_PATH and Path(DEFAULT_BROWSER_PATH).exists():
        return DEFAULT_BROWSER_PATH

    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "msedge",
        "microsoft-edge",
    ):
        found = shutil.which(name)
        if found:
            return found

    windows_candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for candidate in windows_candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON;")
    connection.execute("PRAGMA busy_timeout=5000;")
    return connection


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def open_connection():
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


def log_activity(level: str, scope: str, message: str) -> None:
    with open_connection() as connection:
        connection.execute(
            """
            INSERT INTO activity_logs (level, scope, message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (level, scope, message[:1200], now_iso()),
        )
        connection.execute(
            """
            DELETE FROM activity_logs
            WHERE id NOT IN (
                SELECT id FROM activity_logs ORDER BY id DESC LIMIT 300
            )
            """
        )
        connection.commit()


def normalize_settings(raw: dict[str, str]) -> dict[str, Any]:
    monitor_port = int(raw.get("monitor_debug_port") or DEFAULT_MONITOR_PORT)
    test_port = int(raw.get("test_debug_port") or DEFAULT_TEST_PORT)
    catalog_port = int(raw.get("catalog_debug_port") or DEFAULT_CATALOG_PORT)
    poll_interval = max(15, min(3600, int(raw.get("poll_interval_seconds") or DEFAULT_POLL_INTERVAL)))
    timeout_seconds = max(10, min(120, int(raw.get("request_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)))
    return {
        "telegram_bot_token": raw.get("telegram_bot_token", "").strip(),
        "telegram_chat_id": raw.get("telegram_chat_id", "").strip(),
        "monitor_debug_port": monitor_port,
        "test_debug_port": test_port,
        "catalog_debug_port": catalog_port,
        "poll_interval_seconds": poll_interval,
        "request_timeout_seconds": timeout_seconds,
    }


def load_settings(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute("SELECT key, value FROM settings").fetchall()
    data = {row["key"]: row["value"] for row in rows}
    for key, value in SETTINGS_DEFAULTS.items():
        data.setdefault(key, value)
    return data


def save_settings(connection: sqlite3.Connection, updates: dict[str, str]) -> None:
    timestamp = now_iso()
    for key, value in updates.items():
        connection.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, timestamp),
        )
    connection.commit()


def initialize_database() -> None:
    with open_connection() as connection:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_name TEXT NOT NULL DEFAULT '默认分组',
                monitor_url TEXT NOT NULL,
                target_keyword TEXT NOT NULL,
                restock_template TEXT NOT NULL,
                soldout_template TEXT NOT NULL,
                button_1_text TEXT DEFAULT '',
                button_1_url TEXT DEFAULT '',
                button_2_text TEXT DEFAULT '',
                button_2_url TEXT DEFAULT '',
                source_item_id INTEGER,
                source_item_key TEXT DEFAULT '',
                source_source_url TEXT DEFAULT '',
                source_source_name TEXT DEFAULT '',
                source_item_url TEXT DEFAULT '',
                source_snapshot TEXT DEFAULT '',
                source_last_sync_at TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_stock INTEGER,
                last_state TEXT NOT NULL DEFAULT 'unknown',
                message_id INTEGER,
                last_checked_at TEXT,
                last_error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                scope TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS merchant_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT NOT NULL UNIQUE,
                source_name TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                discovered_count INTEGER NOT NULL DEFAULT 0,
                last_sync_at TEXT,
                last_error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS merchant_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                title TEXT NOT NULL,
                keyword TEXT NOT NULL,
                monitor_url TEXT NOT NULL,
                item_url TEXT DEFAULT '',
                price_hint TEXT DEFAULT '',
                stock_hint TEXT DEFAULT '',
                restock_hint TEXT DEFAULT '',
                raw_snippet TEXT DEFAULT '',
                raw_payload TEXT DEFAULT '',
                item_state TEXT NOT NULL DEFAULT 'new',
                last_seen_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_id, item_key)
            );
            """
        )
        ensure_column(connection, "tasks", "group_name", "TEXT NOT NULL DEFAULT '默认分组'")
        ensure_column(connection, "tasks", "source_item_id", "INTEGER")
        ensure_column(connection, "tasks", "source_item_key", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_source_url", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_source_name", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_item_url", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_snapshot", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_last_sync_at", "TEXT")

        existing_admin = connection.execute("SELECT id FROM admins LIMIT 1").fetchone()
        if not existing_admin:
            username = os.getenv("ADMIN_USERNAME", "operator").strip() or "operator"
            password = os.getenv("ADMIN_PASSWORD", "").strip() or secrets.token_urlsafe(14)
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO admins (username, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (username, generate_password_hash(password), timestamp, timestamp),
            )
            connection.commit()
            BOOTSTRAP_CREDENTIALS_PATH.write_text(
                f"username={username}\npassword={password}\n",
                encoding="utf-8",
            )
            log_activity("warning", "auth", "首次启动已创建管理员账号，请尽快修改密码并删除 bootstrap_admin.txt。")

        current = load_settings(connection)
        missing = {key: value for key, value in SETTINGS_DEFAULTS.items() if key not in current}
        if missing:
            save_settings(connection, missing)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        admin_id = session.get("admin_id")
        if not admin_id:
            if request.accept_mimetypes.accept_json or request.path.startswith("/api"):
                return jsonify({"ok": False, "message": "未登录或会话已过期。"}), 401
            return redirect("/")
        try:
            admin_id_int = int(admin_id)
        except (TypeError, ValueError):
            session.clear()
            if request.accept_mimetypes.accept_json or request.path.startswith("/api"):
                return jsonify({"ok": False, "message": "未登录或会话已过期。"}), 401
            return redirect("/")
        with open_connection() as connection:
            admin = connection.execute(
                "SELECT id, username FROM admins WHERE id = ?",
                (admin_id_int,),
            ).fetchone()
        if not admin:
            session.clear()
            if request.accept_mimetypes.accept_json or request.path.startswith("/api"):
                return jsonify({"ok": False, "message": "未登录或会话已过期。"}), 401
            return redirect("/")
        session["admin_username"] = admin["username"]
        return view(*args, **kwargs)

    return wrapped


def to_task_payload(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "name": row["name"],
        "group_name": normalize_task_group(row["group_name"] if "group_name" in keys else ""),
        "monitor_url": row["monitor_url"],
        "target_keyword": row["target_keyword"],
        "restock_template": row["restock_template"],
        "soldout_template": row["soldout_template"],
        "button_1_text": row["button_1_text"] or "",
        "button_1_url": row["button_1_url"] or "",
        "button_2_text": row["button_2_text"] or "",
        "button_2_url": row["button_2_url"] or "",
        "source_item_id": row["source_item_id"] if "source_item_id" in keys else None,
        "source_item_key": (row["source_item_key"] or "") if "source_item_key" in keys else "",
        "source_source_url": (row["source_source_url"] or "") if "source_source_url" in keys else "",
        "source_source_name": (row["source_source_name"] or "") if "source_source_name" in keys else "",
        "source_item_url": (row["source_item_url"] or "") if "source_item_url" in keys else "",
        "source_snapshot": (row["source_snapshot"] or "") if "source_snapshot" in keys else "",
        "source_last_sync_at": (row["source_last_sync_at"] or "") if "source_last_sync_at" in keys else "",
        "enabled": bool(row["enabled"]),
        "last_stock": row["last_stock"],
        "last_state": row["last_state"],
        "message_id": row["message_id"],
        "last_checked_at": row["last_checked_at"] or "",
        "last_error": sanitize_telegram_error(row["last_error"] or ""),
        "last_error_kind": classify_browser_error(row["last_error"] or ""),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def to_source_payload(row: sqlite3.Row, item_count: int = 0, linked_count: int = 0) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_url": row["source_url"],
        "source_name": row["source_name"] or "",
        "active": bool(row["active"]),
        "discovered_count": row["discovered_count"],
        "item_count": item_count,
        "linked_count": linked_count,
        "last_sync_at": row["last_sync_at"] or "",
        "last_error": row["last_error"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def to_merchant_item_payload(
    row: sqlite3.Row,
    source_row: sqlite3.Row | None = None,
    task_row: sqlite3.Row | None = None,
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "source_url": source_row["source_url"] if source_row else "",
        "source_name": source_row["source_name"] if source_row else "",
        "item_key": row["item_key"],
        "title": row["title"],
        "keyword": row["keyword"],
        "monitor_url": row["monitor_url"],
        "item_url": row["item_url"] or "",
        "price_hint": row["price_hint"] or "",
        "stock_hint": row["stock_hint"] or "",
        "restock_hint": row["restock_hint"] or "",
        "item_state": row["item_state"],
        "last_seen_at": row["last_seen_at"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "task_id": task_row["id"] if task_row else None,
        "task_name": task_row["name"] if task_row else "",
    }


def read_json() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest("请求体格式错误。")
    return payload


def validate_task_payload(payload: dict[str, Any]) -> tuple[bool, str]:
    required_fields = {
        "name": "商品名称",
        "monitor_url": "监控链接",
        "target_keyword": "精准狙击关键词",
        "restock_template": "TG 推送文案",
        "soldout_template": "售罄文案",
    }
    for field, label in required_fields.items():
        value = str(payload.get(field, "")).strip()
        if not value:
            return False, f"{label}不能为空。"
    if not validate_http_url(str(payload["monitor_url"]).strip()):
        return False, "监控链接必须是有效的 http(s) 地址。"
    for pair in (("button_1_text", "button_1_url"), ("button_2_text", "button_2_url")):
        text = str(payload.get(pair[0], "")).strip()
        url = str(payload.get(pair[1], "")).strip()
        if text and not url:
            return False, "按钮文本已填写时，按钮链接不能为空。"
        if url and not text:
            return False, "按钮链接已填写时，按钮文本不能为空。"
        if url and not validate_http_url(url):
            return False, "按钮链接必须是有效的 http(s) 地址。"
    return True, ""


def optional_int(value: Any) -> int | None:
    if value in ("", None):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_task_source_fields(payload: dict[str, Any], fallback: sqlite3.Row | None = None) -> dict[str, Any]:
    fallback_keys = set(fallback.keys()) if fallback is not None else set()
    return {
        "source_item_id": optional_int(payload.get("source_item_id")) if payload.get("source_item_id") not in (None, "") else (fallback["source_item_id"] if fallback is not None and "source_item_id" in fallback_keys else None),
        "source_item_key": str(payload.get("source_item_key", "")).strip() or (str(fallback["source_item_key"]) if fallback is not None and "source_item_key" in fallback_keys else ""),
        "source_source_url": str(payload.get("source_source_url", "")).strip() or (str(fallback["source_source_url"]) if fallback is not None and "source_source_url" in fallback_keys else ""),
        "source_source_name": str(payload.get("source_source_name", "")).strip() or (str(fallback["source_source_name"]) if fallback is not None and "source_source_name" in fallback_keys else ""),
        "source_item_url": str(payload.get("source_item_url", "")).strip() or (str(fallback["source_item_url"]) if fallback is not None and "source_item_url" in fallback_keys else ""),
        "source_snapshot": str(payload.get("source_snapshot", "")).strip() or (str(fallback["source_snapshot"]) if fallback is not None and "source_snapshot" in fallback_keys else ""),
        "source_last_sync_at": str(payload.get("source_last_sync_at", "")).strip() or (str(fallback["source_last_sync_at"]) if fallback is not None and "source_last_sync_at" in fallback_keys else ""),
    }


def build_task_insert_values(payload: dict[str, Any], source_fields: dict[str, Any], timestamp: str) -> tuple[Any, ...]:
    return (
        str(payload["name"]).strip(),
        normalize_task_group(payload.get("group_name")),
        str(payload["monitor_url"]).strip(),
        str(payload["target_keyword"]).strip(),
        str(payload["restock_template"]).strip() or DEFAULT_RESTOCK_TEMPLATE,
        str(payload["soldout_template"]).strip() or DEFAULT_SOLDOUT_TEMPLATE,
        str(payload.get("button_1_text", "")).strip(),
        str(payload.get("button_1_url", "")).strip(),
        str(payload.get("button_2_text", "")).strip(),
        str(payload.get("button_2_url", "")).strip(),
        source_fields["source_item_id"],
        source_fields["source_item_key"],
        source_fields["source_source_url"],
        source_fields["source_source_name"],
        source_fields["source_item_url"],
        source_fields["source_snapshot"],
        source_fields["source_last_sync_at"] or timestamp,
        1 if payload.get("enabled", True) else 0,
        timestamp,
        timestamp,
    )


def insert_task_record(connection: sqlite3.Connection, payload: dict[str, Any], timestamp: str, fallback: sqlite3.Row | None = None) -> int:
    source_fields = normalize_task_source_fields(payload, fallback)
    cursor = connection.execute(
        """
        INSERT INTO tasks (
            name, group_name, monitor_url, target_keyword, restock_template, soldout_template,
            button_1_text, button_1_url, button_2_text, button_2_url,
            source_item_id, source_item_key, source_source_url, source_source_name, source_item_url,
            source_snapshot, source_last_sync_at, enabled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        build_task_insert_values(payload, source_fields, timestamp),
    )
    connection.commit()
    return int(cursor.lastrowid)


def create_task_from_catalog_item(
    connection: sqlite3.Connection,
    source_id: int,
    source_title: str,
    source_url: str,
    item_id: int,
    item: dict[str, Any],
) -> int:
    timestamp = now_iso()
    payload = {
        "name": item["title"],
        "group_name": source_title,
        "monitor_url": item["monitor_url"],
        "target_keyword": item["keyword"],
        "restock_template": DEFAULT_RESTOCK_TEMPLATE,
        "soldout_template": DEFAULT_SOLDOUT_TEMPLATE,
        "button_1_text": "",
        "button_1_url": "",
        "button_2_text": "",
        "button_2_url": "",
        "enabled": True,
        "source_item_id": item_id,
        "source_item_key": item["source_item_key"],
        "source_source_url": source_url,
        "source_source_name": source_title,
        "source_item_url": item["item_url"],
        "source_snapshot": json.dumps(item, ensure_ascii=False),
        "source_last_sync_at": timestamp,
    }
    task_id = insert_task_record(connection, payload, timestamp)
    return task_id


def sync_task_source_fields(
    connection: sqlite3.Connection,
    task_id: int,
    source_url: str,
    source_title: str,
    item: dict[str, Any],
) -> None:
    timestamp = now_iso()
    connection.execute(
        """
        UPDATE tasks
        SET source_source_url = ?, source_source_name = ?, source_item_url = ?, source_snapshot = ?,
            source_last_sync_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            source_url,
            source_title,
            item["item_url"],
            json.dumps(item, ensure_ascii=False),
            timestamp,
            timestamp,
            task_id,
        ),
    )


@dataclass
class ScrapeResult:
    stock: int | None
    fragment: str
    detail: str
    used_test_browser: bool


@dataclass
class MerchantCatalogItem:
    source_item_key: str
    title: str
    keyword: str
    monitor_url: str
    item_url: str
    price_hint: str
    stock_hint: str
    restock_hint: str
    raw_snippet: str
    raw_payload: str


@dataclass
class MerchantImportResult:
    source_id: int
    source_url: str
    source_name: str
    scanned_count: int
    upserted_count: int
    promoted_count: int
    archived_count: int
    last_sync_at: str
    items: list[dict[str, Any]]


def sanitize_telegram_error(value: str, token: str = "") -> str:
    text = str(value or "")
    if token:
        text = text.replace(token, "<hidden-token>")
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<hidden-token>", text)
    normalized = text.lower()
    if "client error" in normalized and "api.telegram.org/bot<hidden-token>" in normalized:
        method_match = re.search(r"/([A-Za-z]+)(?:\s|$)", text)
        status_match = re.search(r"(\d{3})\s+Client Error", text, re.IGNORECASE)
        method = method_match.group(1) if method_match else "Telegram"
        status = status_match.group(1) if status_match else "400"
        return (
            f"Telegram {method} 失败（HTTP {status}）："
            "请检查 Chat ID、机器人是否已加入群组/频道，以及推送文案 HTML。"
        )
    return text


def telegram_error_hint(description: str) -> str:
    normalized = description.lower()
    if "chat not found" in normalized:
        return "Chat ID 不正确，或机器人没有加入该会话/群组。"
    if "can't parse entities" in normalized or "can't find end tag" in normalized:
        return "TG 推送文案 HTML 格式不合法，请检查 <b>、<a> 等标签是否闭合。"
    if "message text is empty" in normalized:
        return "TG 推送文案为空，请检查补货文案或售罄文案。"
    if "button_url_invalid" in normalized or "wrong http url" in normalized:
        return "TG 底部按钮链接无效，按钮 URL 必须是完整 http/https 地址。"
    if "not enough rights" in normalized or "have no rights" in normalized:
        return "机器人权限不足，请确认它在群组/频道内并拥有发消息权限。"
    if "bot was blocked" in normalized or "blocked by the user" in normalized:
        return "机器人被目标用户或会话屏蔽了。"
    return description or "Telegram API 返回未知错误。"


def telegram_html_value(value: Any) -> str:
    return html_module.escape(str(value if value is not None else ""), quote=False)


class TelegramClient:
    def __init__(self) -> None:
        self.session = requests.Session()

    def _request(self, method: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not token.strip():
            raise RuntimeError("Telegram Bot Token 未配置。")
        if not str(payload.get("chat_id", "")).strip():
            raise RuntimeError("Telegram Chat ID 未配置。")
        if not str(payload.get("text", "")).strip():
            raise RuntimeError("Telegram 推送文案为空，请检查补货文案或售罄文案。")

        url = f"https://api.telegram.org/bot{token}/{method}"
        try:
            response: Response = self.session.post(url, json=payload, timeout=20)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Telegram {method} 网络请求失败：{sanitize_telegram_error(str(exc), token)}"
            ) from exc

        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400 or not data.get("ok"):
            description = str(data.get("description") or response.text or response.reason or "未知错误")
            safe_description = sanitize_telegram_error(description[:500], token)
            hint = telegram_error_hint(safe_description)
            detail = f"Telegram {method} 失败（HTTP {response.status_code}）：{hint}"
            if safe_description and safe_description not in hint:
                detail = f"{detail}；原始提示：{safe_description}"
            raise RuntimeError(detail)
        return data

    def send_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        buttons: list[dict[str, str]] | None = None,
    ) -> int:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[button for button in buttons if button]]}
        data = self._request("sendMessage", token, payload)
        return int(data["result"]["message_id"])

    def edit_message(
        self,
        token: str,
        chat_id: str,
        message_id: int,
        text: str,
        buttons: list[dict[str, str]] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[button for button in buttons if button]]}
        self._request("editMessageText", token, payload)


class BrowserHarness:
    def __init__(self, role: str, port: int, headless: bool, browser_path: str | None = None) -> None:
        self.role = role
        self.port = int(port)
        self.headless = headless
        self.browser_path = browser_path or ""
        self.profile_dir = DATA_DIR / f"browser-{role}"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.page = None

    def update(self, port: int, headless: bool, browser_path: str | None) -> None:
        browser_path = browser_path or ""
        if int(port) == self.port and headless == self.headless and browser_path == self.browser_path:
            return
        self.port = int(port)
        self.headless = headless
        self.browser_path = browser_path
        self.rebuild("runtime configuration changed")

    def build_page(self):
        if ChromiumOptions is None or ChromiumPage is None:
            raise RuntimeError("DrissionPage 未安装，无法启动浏览器引擎。")

        options = ChromiumOptions()
        options.set_local_port(self.port)
        if DEFAULT_BROWSER_USER_AGENT:
            try:
                options.set_user_agent(DEFAULT_BROWSER_USER_AGENT)
            except Exception:
                pass
        options.set_argument("--disable-gpu")
        options.set_argument("--disable-dev-shm-usage")
        options.set_argument("--disable-blink-features=AutomationControlled")
        options.set_argument("--window-size=1440,2200")
        if os.name != "nt":
            options.set_argument("--no-sandbox")
        if self.headless:
            if hasattr(options, "headless"):
                options.headless(True)
            else:
                options.set_argument("--headless=new")
        if hasattr(options, "set_user_data_path"):
            options.set_user_data_path(str(self.profile_dir))
        elif hasattr(options, "set_paths"):
            options.set_paths(user_data_path=str(self.profile_dir))
        if self.browser_path:
            if hasattr(options, "set_browser_path"):
                options.set_browser_path(self.browser_path)
            elif hasattr(options, "set_paths"):
                options.set_paths(browser_path=self.browser_path)
        return ChromiumPage(options)

    def ensure_page(self):
        if self.page is None:
            self.page = self.build_page()
        return self.page

    def fetch_html(self, url: str, timeout_seconds: int) -> str:
        with self.lock:
            page = self.ensure_page()
            ok = page.get(url, timeout=timeout_seconds, retry=1, interval=1)
            if ok is False:
                raise TimeoutError(f"{self.role} browser timed out while opening {url}")

            try:
                page.wait.doc_loaded(timeout=max(3, min(timeout_seconds, 10)))
            except Exception:
                pass

            time.sleep(0.9)
            html_text = page.html or ""
            if not html_text:
                raise RuntimeError(f"{self.role} 浏览器返回了空 HTML")
            page_title = ""
            try:
                page_title = page.title or ""
            except Exception:
                pass
            if looks_like_cloudflare_challenge(html_text, page_title, url):
                for attempt in range(3):
                    log_activity(
                        "warning",
                        f"browser:{self.role}",
                        f"检测到 Cloudflare/Turnstile 挑战页，准备重试第 {attempt + 1} 次：{url}",
                    )
                    time.sleep(1.8 + attempt)
                    try:
                        page.refresh(ignore_cache=True)
                    except Exception:
                        pass
                    try:
                        page.wait.doc_loaded(timeout=max(3, min(timeout_seconds, 10)))
                    except Exception:
                        pass
                    html_text = page.html or ""
                    if not html_text:
                        continue
                    try:
                        page_title = page.title or ""
                    except Exception:
                        page_title = ""
                    if not looks_like_cloudflare_challenge(html_text, page_title, url):
                        return html_text
                raise RuntimeError(f"{self.role} 浏览器被 Cloudflare 验证页拦截：{url}")
            return html_text

    def rebuild(self, reason: str) -> None:
        with self.lock:
            self._shutdown_page()
            self._kill_zombies()
            self._clear_profile_locks()
        log_activity("warning", f"browser:{self.role}", f"浏览器已重建，原因：{reason}")

    def shutdown(self) -> None:
        with self.lock:
            self._shutdown_page()
            self._kill_zombies()
            self._clear_profile_locks()

    def _shutdown_page(self) -> None:
        if self.page is not None:
            try:
                self.page.quit(timeout=3, force=True)
            except Exception:
                pass
            self.page = None

    def _kill_zombies(self) -> None:
        marker = str(self.profile_dir).lower()
        port_flag = f"--remote-debugging-port={self.port}"
        port_value = str(self.port)
        victims: list[psutil.Process] = []
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (process.info["name"] or "").lower()
                cmdline = " ".join(process.info["cmdline"] or []).lower()
                if process.pid == os.getpid():
                    continue
                if not any(token in name for token in ("chrome", "chromium", "edge")):
                    continue
                owns_debug_port = port_flag in cmdline or f"remote-debugging-port {port_value}" in cmdline
                owns_profile = marker in cmdline
                if owns_debug_port or owns_profile:
                    victims.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        for process in victims:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _, alive = psutil.wait_procs(victims, timeout=3)
        for process in alive:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if alive:
            psutil.wait_procs(alive, timeout=2)

    def _clear_profile_locks(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        for filename in BROWSER_LOCK_FILENAMES:
            path = self.profile_dir / filename
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                elif path.exists() or path.is_symlink():
                    path.unlink()
            except OSError:
                continue


class MonitoringEngine:
    def __init__(self, app: Flask) -> None:
        self.app = app
        self.telegram = TelegramClient()
        self.state_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        browser_binary = find_browser_binary()
        self.monitor_browser = BrowserHarness("monitor", DEFAULT_MONITOR_PORT, DEFAULT_HEADLESS, browser_binary)
        self.test_browser = BrowserHarness("test", DEFAULT_TEST_PORT, DEFAULT_HEADLESS, browser_binary)
        self.catalog_browser = BrowserHarness("catalog", DEFAULT_CATALOG_PORT, DEFAULT_HEADLESS, browser_binary)
        self.last_cycle_started = ""
        self.last_cycle_finished = ""
        self.last_exception = ""
        self.last_successful_tasks = 0
        self.cycle_running = False

    def get_runtime_settings(self) -> dict[str, Any]:
        with open_connection() as connection:
            raw = load_settings(connection)
        return normalize_settings(raw)

    def configure_browsers(self, settings_payload: dict[str, Any]) -> None:
        browser_binary = find_browser_binary()
        self.monitor_browser.update(settings_payload["monitor_debug_port"], DEFAULT_HEADLESS, browser_binary)
        self.test_browser.update(settings_payload["test_debug_port"], DEFAULT_HEADLESS, browser_binary)
        self.catalog_browser.update(settings_payload["catalog_debug_port"], DEFAULT_HEADLESS, browser_binary)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run_loop, name="monitor-engine", daemon=True)
        self.thread.start()
        log_activity("info", "engine", "后台监控引擎已启动。")

    def stop(self) -> None:
        self.stop_event.set()
        self.monitor_browser.shutdown()
        self.test_browser.shutdown()
        self.catalog_browser.shutdown()

    def get_status(self) -> dict[str, Any]:
        with self.state_lock:
            return {
                "cycle_running": self.cycle_running,
                "last_cycle_started": self.last_cycle_started,
                "last_cycle_finished": self.last_cycle_finished,
                "last_exception": self.last_exception,
                "last_successful_tasks": self.last_successful_tasks,
            }

    def restart(self, reason: str) -> None:
        self.monitor_browser.rebuild(reason)
        self.test_browser.rebuild(reason)
        self.catalog_browser.rebuild(reason)
        with self.state_lock:
            self.last_exception = ""
        log_activity("warning", "engine", f"已手动重启浏览器引擎：{reason}")

    def process_merchant_sources(self, settings_payload: dict[str, Any]) -> int:
        sync_interval = max(180, int(settings_payload["poll_interval_seconds"]) * 3)
        now = now_utc()
        synced_count = 0

        with open_connection() as connection:
            sources = connection.execute(
                """
                SELECT * FROM merchant_sources
                WHERE active = 1
                ORDER BY updated_at ASC, id ASC
                """
            ).fetchall()

        for source in sources:
            last_sync_at = parse_iso_datetime(source["last_sync_at"] if "last_sync_at" in source.keys() else None)
            if last_sync_at and (now - last_sync_at).total_seconds() < sync_interval:
                continue
            try:
                self.import_merchant_source(
                    source["source_url"],
                    source["source_name"],
                    settings_payload,
                    auto_promote=True,
                )
                synced_count += 1
            except Exception as exc:
                error_message = str(exc)[:1000]
                with open_connection() as connection:
                    connection.execute(
                        "UPDATE merchant_sources SET last_error = ?, updated_at = ? WHERE id = ?",
                        (error_message, now_iso(), source["id"]),
                    )
                    connection.commit()
                log_activity("warning", "catalog", f"同步商家来源 #{source['id']} 失败：{exc}")

        return synced_count

    def run_loop(self) -> None:
        while not self.stop_event.is_set():
            settings_payload = self.get_runtime_settings()
            self.configure_browsers(settings_payload)
            self._mark_cycle_start()
            successful = 0
            try:
                with open_connection() as connection:
                    tasks = connection.execute(
                        """
                        SELECT * FROM tasks
                        WHERE enabled = 1
                        ORDER BY id ASC
                        """
                    ).fetchall()
                for task in tasks:
                    if self.stop_event.is_set():
                        break
                    processed = self.process_task(task, settings_payload, use_test_browser=False)
                    if processed:
                        successful += 1
                self.process_merchant_sources(settings_payload)
                self._mark_cycle_finish(successful, "")
            except Exception as exc:  # pragma: no cover - runtime recovery path
                self._mark_cycle_finish(successful, str(exc))
                log_activity("error", "engine", f"监控循环异常：{exc}")
            self.stop_event.wait(settings_payload["poll_interval_seconds"])

    def _mark_cycle_start(self) -> None:
        with self.state_lock:
            self.cycle_running = True
            self.last_cycle_started = now_iso()

    def _mark_cycle_finish(self, successful: int, error_message: str) -> None:
        with self.state_lock:
            self.cycle_running = False
            self.last_cycle_finished = now_iso()
            self.last_successful_tasks = successful
            self.last_exception = error_message

    def scrape_task(self, task: sqlite3.Row, settings_payload: dict[str, Any], use_test_browser: bool) -> ScrapeResult:
        browser = self.test_browser if use_test_browser else self.monitor_browser
        last_error = ""
        for attempt in range(3):
            try:
                html_text = browser.fetch_html(task["monitor_url"], settings_payload["request_timeout_seconds"])
                fragment = slice_fragment(html_text, task["target_keyword"])
                stock, detail = parse_stock(fragment)
                return ScrapeResult(stock=stock, fragment=fragment, detail=detail, used_test_browser=use_test_browser)
            except Exception as exc:
                last_error = str(exc)
                if should_auto_heal(exc) and attempt < 2:
                    browser.rebuild(last_error)
                    time.sleep(0.6)
                    continue
                break
        return ScrapeResult(stock=None, fragment="", detail=last_error or "抓取失败", used_test_browser=use_test_browser)

    def import_merchant_source(
        self,
        source_url: str,
        source_name: str,
        settings_payload: dict[str, Any],
        auto_promote: bool = True,
    ) -> MerchantImportResult:
        source_url = source_url.strip()
        if not source_url:
            raise RuntimeError("商家页面链接不能为空。")
        if not validate_http_url(source_url):
            raise RuntimeError("商家页面链接必须是有效的 http(s) 地址。")

        last_error = ""
        html_text = ""
        for attempt in range(3):
            try:
                html_text = self.catalog_browser.fetch_html(source_url, settings_payload["request_timeout_seconds"])
                break
            except Exception as exc:
                last_error = str(exc)
                if should_auto_heal(exc) and attempt < 2:
                    self.catalog_browser.rebuild(last_error)
                    time.sleep(0.6)
                    continue
                raise RuntimeError(last_error or "商家页面抓取失败。") from exc

        discovered_items = discover_catalog_items(html_text, source_url)
        source_title = normalize_candidate_title(source_name) or extract_page_title(html_text)
        if not source_title:
            source_title = urlparse(source_url).hostname or source_url

        timestamp = now_iso()
        upserted_count = 0
        promoted_count = 0
        archived_count = 0
        persisted_items: list[dict[str, Any]] = []
        source_id = 0

        with open_connection() as connection:
            source_row = connection.execute("SELECT * FROM merchant_sources WHERE source_url = ?", (source_url,)).fetchone()
            if source_row:
                source_id = int(source_row["id"])
                connection.execute(
                    """
                    UPDATE merchant_sources
                    SET source_name = ?, active = 1, last_sync_at = ?, last_error = '', discovered_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (source_title, timestamp, len(discovered_items), timestamp, source_id),
                )
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO merchant_sources (
                        source_url, source_name, active, discovered_count, last_sync_at, last_error, created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, '', ?, ?)
                    """,
                    (source_url, source_title, len(discovered_items), timestamp, timestamp, timestamp),
                )
                source_id = int(cursor.lastrowid)

            seen_keys: set[str] = set()
            existing_items = {
                row["item_key"]: row
                for row in connection.execute(
                    "SELECT * FROM merchant_items WHERE source_id = ?",
                    (source_id,),
                ).fetchall()
            }

            for item in discovered_items:
                seen_keys.add(item["source_item_key"])
                item_state = "updated" if item["source_item_key"] in existing_items else "new"
                existing = existing_items.get(item["source_item_key"])
                if existing:
                    upserted_count += 1
                    connection.execute(
                        """
                        UPDATE merchant_items
                        SET title = ?, keyword = ?, monitor_url = ?, item_url = ?, price_hint = ?, stock_hint = ?,
                            restock_hint = ?, raw_snippet = ?, raw_payload = ?, item_state = ?, last_seen_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            item["title"],
                            item["keyword"],
                            item["monitor_url"],
                            item["item_url"],
                            item["price_hint"],
                            item["stock_hint"],
                            item["restock_hint"],
                            item["raw_snippet"],
                            item["raw_payload"],
                            item_state,
                            timestamp,
                            timestamp,
                            existing["id"],
                        ),
                    )
                    item_id = int(existing["id"])
                else:
                    cursor = connection.execute(
                        """
                        INSERT INTO merchant_items (
                            source_id, item_key, title, keyword, monitor_url, item_url, price_hint, stock_hint,
                            restock_hint, raw_snippet, raw_payload, item_state, last_seen_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            item["source_item_key"],
                            item["title"],
                            item["keyword"],
                            item["monitor_url"],
                            item["item_url"],
                            item["price_hint"],
                            item["stock_hint"],
                            item["restock_hint"],
                            item["raw_snippet"],
                            item["raw_payload"],
                            item_state,
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    item_id = int(cursor.lastrowid)
                    upserted_count += 1

                task_row = connection.execute(
                    "SELECT id FROM tasks WHERE source_item_id = ? LIMIT 1",
                    (item_id,),
                ).fetchone()
                task_id = None
                if auto_promote and not task_row:
                    task_id = create_task_from_catalog_item(
                        connection,
                        source_id=source_id,
                        source_title=source_title,
                        source_url=source_url,
                        item_id=item_id,
                        item=item,
                    )
                    promoted_count += 1
                elif task_row:
                    task_id = int(task_row["id"])
                    connection.execute(
                        """
                        UPDATE tasks
                        SET source_source_url = ?, source_source_name = ?, source_item_url = ?, source_snapshot = ?,
                            source_last_sync_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            source_url,
                            source_title,
                            item["item_url"],
                            json.dumps(item, ensure_ascii=False),
                            timestamp,
                            timestamp,
                            task_id,
                        ),
                    )

                persisted_items.append(
                    {
                        "id": item_id,
                        "item_key": item["source_item_key"],
                        "title": item["title"],
                        "keyword": item["keyword"],
                        "monitor_url": item["monitor_url"],
                        "item_url": item["item_url"],
                        "price_hint": item["price_hint"],
                        "stock_hint": item["stock_hint"],
                        "restock_hint": item["restock_hint"],
                        "item_state": item_state,
                        "task_id": task_id,
                    }
                )

            if seen_keys:
                for row in connection.execute(
                    "SELECT id, item_key, item_state FROM merchant_items WHERE source_id = ?",
                    (source_id,),
                ).fetchall():
                    if row["item_key"] not in seen_keys and row["item_state"] != "archived":
                        connection.execute(
                            "UPDATE merchant_items SET item_state = 'archived', updated_at = ? WHERE id = ?",
                            (timestamp, row["id"]),
                        )
                        archived_count += 1

            connection.commit()

        return MerchantImportResult(
            source_id=source_id,
            source_url=source_url,
            source_name=source_title,
            scanned_count=len(discovered_items),
            upserted_count=upserted_count,
            promoted_count=promoted_count,
            archived_count=archived_count,
            last_sync_at=timestamp,
            items=persisted_items,
        )

    def process_task(self, task: sqlite3.Row, settings_payload: dict[str, Any], use_test_browser: bool) -> bool:
        result = self.scrape_task(task, settings_payload, use_test_browser)
        if use_test_browser:
            raise RuntimeError("测试推送不应进入 process_task 常规流程。")

        with open_connection() as connection:
            timestamp = now_iso()
            if result.stock is None:
                connection.execute(
                    """
                    UPDATE tasks
                    SET last_checked_at = ?, last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, result.detail[:1000], timestamp, task["id"]),
                )
                connection.commit()
                return False

            buttons = build_buttons(task)
            message_values = message_template_values(task, result.stock)
            message_id = task["message_id"]
            last_stock = task["last_stock"]
            new_state = "in_stock" if result.stock > 0 else "sold_out"
            last_error = ""

            try:
                if result.stock > 0 and not message_id:
                    text = safe_format(task["restock_template"], message_values)
                    new_message_id = self.telegram.send_message(
                        settings_payload["telegram_bot_token"],
                        settings_payload["telegram_chat_id"],
                        text,
                        buttons,
                    )
                    message_id = new_message_id
                    log_activity("info", f"task:{task['id']}", f"{task['name']} 刚补货，已发送新消息。")
                elif result.stock > 0 and message_id and last_stock != result.stock:
                    text = safe_format(task["restock_template"], message_values)
                    self.telegram.edit_message(
                        settings_payload["telegram_bot_token"],
                        settings_payload["telegram_chat_id"],
                        int(message_id),
                        text,
                        buttons,
                    )
                    log_activity("info", f"task:{task['id']}", f"{task['name']} 库存变化为 {result.stock}，已静默编辑消息。")
                elif result.stock <= 0 and message_id:
                    text = safe_format(task["soldout_template"], message_values | {"status": telegram_html_value("sold_out")})
                    self.telegram.edit_message(
                        settings_payload["telegram_bot_token"],
                        settings_payload["telegram_chat_id"],
                        int(message_id),
                        text,
                        buttons,
                    )
                    message_id = None
                    log_activity("warning", f"task:{task['id']}", f"{task['name']} 已售罄，已覆盖原消息。")
            except Exception as exc:
                last_error = sanitize_telegram_error(str(exc), settings_payload["telegram_bot_token"])
                exc = RuntimeError(last_error)
                log_activity("error", f"task:{task['id']}", f"{task['name']} Telegram 推送失败：{exc}")

            connection.execute(
                """
                UPDATE tasks
                SET last_stock = ?,
                    last_state = ?,
                    message_id = ?,
                    last_checked_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (result.stock, new_state, message_id, timestamp, last_error[:1000], timestamp, task["id"]),
            )
            connection.commit()
        return True

    def run_test_push(self, task_id: int) -> dict[str, Any]:
        settings_payload = self.get_runtime_settings()
        self.configure_browsers(settings_payload)
        if not settings_payload["telegram_bot_token"] or not settings_payload["telegram_chat_id"]:
            raise RuntimeError("请先配置 Telegram Bot Token 和 Chat ID。")

        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise RuntimeError("任务不存在。")

        result = self.scrape_task(task, settings_payload, use_test_browser=True)
        stock_text = "未知" if result.stock is None else str(result.stock)
        preview_values = message_template_values(task, result.stock)
        preview_values["status"] = "test"
        preview_text = (
            f"【TEST】{task['name']}\n"
            f"隔离测试端口：{settings_payload['test_debug_port']}\n"
            f"当前识别库存：{stock_text}\n\n"
            f"{safe_format(task['restock_template'], preview_values)}"
        )
        message_id = self.telegram.send_message(
            settings_payload["telegram_bot_token"],
            settings_payload["telegram_chat_id"],
            preview_text,
            build_buttons(task),
        )
        log_activity("info", f"task:{task_id}", f"{task['name']} 已通过测试浏览器发送测试消息（message_id={message_id}）。")
        return {
            "message_id": message_id,
            "stock": result.stock,
            "detail": result.detail,
            "test_port": settings_payload["test_debug_port"],
        }


def build_buttons(task: sqlite3.Row | dict[str, Any]) -> list[dict[str, str]]:
    buttons: list[dict[str, str]] = []
    for index in (1, 2):
        if isinstance(task, dict):
            raw_text = task.get(f"button_{index}_text") or ""
            raw_url = task.get(f"button_{index}_url") or ""
        else:
            raw_text = task[f"button_{index}_text"] or ""
            raw_url = task[f"button_{index}_url"] or ""
        text = str(raw_text).strip()
        url = str(raw_url).strip()
        if text and url:
            buttons.append({"text": text, "url": url})
    return buttons


def message_template_values(task: sqlite3.Row, stock: int | None) -> dict[str, str]:
    checked_at = now_utc().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    source_name = ""
    source_url = ""
    if "source_source_name" in task.keys():
        source_name = str(task["source_source_name"] or "")
    if "source_source_url" in task.keys():
        source_url = str(task["source_source_url"] or "")
    return {
        "name": telegram_html_value(task["name"]),
        "stock": "" if stock is None else telegram_html_value(stock),
        "url": telegram_html_value(task["monitor_url"]),
        "keyword": telegram_html_value(task["target_keyword"]),
        "checked_at": telegram_html_value(checked_at),
        "status": telegram_html_value("in_stock" if (stock or 0) > 0 else "sold_out"),
        "source_name": telegram_html_value(source_name),
        "source_url": telegram_html_value(source_url),
    }


def should_auto_heal(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token.lower() in message for token in BROWSER_RECOVERY_MARKERS)


def looks_like_cloudflare_challenge(html_text: str, title: str = "", url: str = "") -> bool:
    haystack = " ".join(part for part in (html_text[:8000], title, url) if part).lower()
    return any(
        marker in haystack
        for marker in (
            "just a moment",
            "cloudflare",
            "turnstile",
            "cf-turnstile",
            "checking your browser",
            "attention required",
            "verify you are human",
        )
    )


def slice_fragment(html_text: str, keyword: str) -> str:
    if not html_text:
        return ""
    if not keyword:
        return ""
    keyword_candidates = [
        keyword,
        html_module.escape(keyword, quote=False),
        html_module.escape(keyword, quote=True),
    ]
    match = None
    for candidate in dict.fromkeys(candidate for candidate in keyword_candidates if candidate):
        match = re.search(re.escape(candidate), html_text, re.IGNORECASE)
        if match:
            break
    if not match:
        return ""
    start = max(0, match.start() - 50)
    end = min(len(html_text), match.end() + 1200)
    return html_text[start:end]


def clean_fragment_text(fragment: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", fragment)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = html_module.unescape(re.sub(r"<[^>]+>", " ", cleaned))
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_signal_text(value: Any) -> str:
    return re.sub(r"[\s_\-]+", "", html_module.unescape(str(value)).strip().lower())


def classify_browser_error(message: str) -> str:
    lowered = normalize_signal_text(message)
    if not lowered:
        return ""
    for kind, markers in BROWSER_ERROR_KINDS.items():
        if any(marker in lowered for marker in markers):
            return kind
    return ""


def parse_int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value < 0 or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d{1,6}", value.replace(",", ""))
        if match:
            return int(match.group(0))
    return None


def parse_bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        return None
    if isinstance(value, float):
        if value in {0.0, 1.0}:
            return bool(value)
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return None


def normalize_restock_hint(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            hint = normalize_restock_hint(item)
            if hint:
                return hint
        return ""
    text = html_module.unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    date_match = re.search(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", text)
    if not date_match:
        date_match = re.search(r"\d{4}年\d{1,2}月\d{1,2}日", text)
    if date_match:
        return date_match.group(0)
    return text.strip(" ：:，,。.;；")[:80]


def append_restock_hint(detail: str, restock_hint: str) -> str:
    if not restock_hint:
        return detail
    base = detail.rstrip("。.!? ")
    return f"{base}；检测到补货信息：{restock_hint}。"


def scan_json_stock_signal(value: Any) -> tuple[int | None, str] | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = normalize_signal_text(key)
            if normalized_key in JSON_STOCK_KEYS:
                count = parse_int_value(item)
                if count is not None:
                    return count, "匹配到 JSON 库存字段。"
            if normalized_key in JSON_AVAILABILITY_KEYS:
                boolean_value = parse_bool_value(item)
                if boolean_value is not None:
                    return (1 if boolean_value else 0), "匹配到 JSON 可用状态。"
                if isinstance(item, str):
                    normalized_item = normalize_signal_text(item)
                    if any(token in normalized_item for token in JSON_IN_STOCK_TOKENS):
                        return 1, "匹配到 JSON 可购买状态。"
                    if any(token in normalized_item for token in JSON_OUT_OF_STOCK_TOKENS):
                        return 0, "匹配到 JSON 售罄状态。"
            nested = scan_json_stock_signal(item)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = scan_json_stock_signal(item)
            if nested is not None:
                return nested
    return None


def parse_json_scripts(fragment: str) -> tuple[int | None, str]:
    for match in JSON_SCRIPT_PATTERN.finditer(fragment):
        body = html_module.unescape(match.group("body") or "").strip()
        if not body:
            continue
        body = re.sub(r"(?is)^\s*(?:<!--|//<!\[CDATA\[)", "", body).strip()
        body = re.sub(r"(?is)(?:-->|//\]\]>)\s*$", "", body).strip()
        if not body:
            continue
        if "=" in body and not body.lstrip().startswith(("{", "[")):
            body = body.split("=", 1)[1].strip().rstrip(";")
        if not body.startswith(("{", "[")):
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        matched = scan_json_stock_signal(payload)
        if matched is not None:
            return matched
    return None, ""


def extract_restock_hint(fragment: str, cleaned_text: str) -> str:
    haystack = f"{fragment}\n{cleaned_text}"
    for pattern in RESTOCK_HINT_PATTERNS:
        match = pattern.search(haystack)
        if match:
            hint = normalize_restock_hint(match.groupdict().get("hint") or match.group(0))
            if hint:
                return hint
    return ""


def parse_structured_stock(fragment: str, restock_hint: str = "") -> tuple[int | None, str]:
    json_stock, json_detail = parse_json_scripts(fragment)
    if json_stock is not None:
        return json_stock, append_restock_hint(json_detail, restock_hint)

    for pattern in STRUCTURED_STOCK_PATTERNS:
        match = pattern.search(fragment)
        if match:
            return int(match.group("count")), append_restock_hint("匹配到结构化库存字段。", restock_hint)
    for pattern in OUT_OF_STOCK_AVAILABILITY_PATTERNS:
        if pattern.search(fragment):
            return 0, append_restock_hint("匹配到结构化售罄状态。", restock_hint)
    for pattern in IN_STOCK_AVAILABILITY_PATTERNS:
        if pattern.search(fragment):
            return 1, append_restock_hint("匹配到结构化可购买状态。", restock_hint)
    return None, ""


def has_sold_out_marker(cleaned_text: str) -> bool:
    lowered = cleaned_text.lower()
    return any(marker.lower() in lowered for marker in SOLD_OUT_MARKERS)


def has_orderable_marker(fragment: str, cleaned_text: str) -> bool:
    haystack = f"{fragment}\n{cleaned_text}"
    return any(pattern.search(haystack) for pattern in ORDERABLE_PATTERNS)


def is_date_like_context(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"\d{4}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}", text)
        or re.search(r"\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}", text)
        or re.search(r"\d{4}年\d{1,2}月\d{1,2}日", text)
        or any(
            token in lowered
            for token in (
                "availabilitydate",
                "restockdate",
                "backinstockdate",
                "backorderdate",
                "expecteddate",
                "shipdate",
                "releasedate",
                "availabledate",
                "deliverydate",
                "补货",
                "補貨",
                "到货",
                "到貨",
                "restock",
                "back in stock",
                "pre-order",
                "preorder",
            )
        )
    )


def parse_stock(fragment: str) -> tuple[int | None, str]:
    if not fragment:
        return None, "未抓到有效 HTML 片段。"

    cleaned = clean_fragment_text(fragment)
    restock_hint = extract_restock_hint(fragment, cleaned)

    structured_stock, structured_detail = parse_structured_stock(fragment, restock_hint)
    if structured_stock is not None:
        return structured_stock, structured_detail

    for pattern in STOCK_PATTERNS:
        match = pattern.search(fragment)
        if match:
            snippet = fragment[max(0, match.start() - 32) : min(len(fragment), match.end() + 32)]
            if is_date_like_context(html_module.unescape(snippet)) or has_sold_out_marker(html_module.unescape(snippet)):
                continue
            return int(match.group("count")), append_restock_hint("匹配到 HTML 库存数字。", restock_hint)

    text_match = re.search(
        rf"{STOCK_LABEL}[^0-9]{{0,80}}(\d{{1,6}})",
        cleaned,
        re.IGNORECASE,
    )
    if text_match:
        snippet = cleaned[max(0, text_match.start() - 40) : min(len(cleaned), text_match.end() + 40)]
        if not is_date_like_context(snippet):
            return int(text_match.group(1)), append_restock_hint("通过文本降噪提取到库存数字。", restock_hint)

    reverse_text_match = re.search(
        rf"(\d{{1,6}})[^0-9]{{0,80}}{STOCK_LABEL}",
        cleaned,
        re.IGNORECASE,
    )
    if reverse_text_match:
        snippet = cleaned[max(0, reverse_text_match.start() - 40) : min(len(cleaned), reverse_text_match.end() + 40)]
        if not is_date_like_context(snippet):
            return int(reverse_text_match.group(1)), append_restock_hint("通过文本倒序提取到库存数字。", restock_hint)

    if has_sold_out_marker(cleaned):
        return 0, append_restock_hint("命中售罄标记。", restock_hint)

    if has_orderable_marker(fragment, cleaned):
        return 1, append_restock_hint("未显示库存数字，但命中可下单/购买入口，按有货处理。", restock_hint)

    if restock_hint:
        return 0, f"检测到补货信息：{restock_hint}，但未发现明确库存数字。"

    return None, "未找到库存数字或售罄标记。"


DISCOVERY_SKIP_URL_PARTS = (
    "javascript:",
    "mailto:",
    "tel:",
    "#",
    "/login",
    "/logout",
    "/signin",
    "/signup",
    "/register",
    "/account",
    "/cart",
    "/checkout",
    "/contact",
    "/about",
    "/privacy",
    "/terms",
    "/support",
    "/search",
    "/blog",
    "/news",
    "/category",
    "/categories",
)
DISCOVERY_ACTION_TEXTS = {
    "order now",
    "buy now",
    "add to cart",
    "checkout",
    "purchase",
    "view details",
    "more info",
    "learn more",
    "立即订购",
    "立即購買",
    "立即下单",
    "立即下單",
    "加入购物车",
    "加入購物車",
    "现在购买",
    "現在購買",
    "可下单",
    "可下單",
    "可购买",
    "可購買",
    "预售",
    "預售",
    "预订",
    "預訂",
    "到货通知",
    "到貨通知",
}
DISCOVERY_GENERIC_TEXTS = {
    "home",
    "index",
    "about",
    "contact",
    "login",
    "logout",
    "sign in",
    "sign up",
    "register",
    "cart",
    "checkout",
    "support",
    "faq",
    "privacy policy",
    "terms",
    "next",
    "prev",
    "previous",
    "back",
}
HEADING_PATTERN = re.compile(r"<h[1-6]\b[^>]*>(?P<body>.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
ANCHOR_PATTERN = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", re.IGNORECASE | re.DOTALL)
TITLE_ATTR_PATTERN = re.compile(r"\b(?P<key>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)\2", re.DOTALL)
PRICE_PATTERN = re.compile(
    r"(?:￥|¥|CNY|RMB|HK\$|USD|\$|€|£)\s*\d[\d,]*(?:\.\d{1,2})?",
    re.IGNORECASE,
)


def first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = clean_fragment_text(str(value))
        if text:
            return text
    return ""


def parse_tag_attributes(raw_attrs: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for match in TITLE_ATTR_PATTERN.finditer(raw_attrs or ""):
        attributes[match.group("key").lower()] = html_module.unescape(match.group("value") or "").strip()
    return attributes


def normalize_candidate_title(value: Any) -> str:
    text = clean_fragment_text(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n|•·-_/")
    return text[:120]


def normalize_candidate_url(source_url: str, href: str) -> str:
    candidate = href.strip()
    if not candidate:
        return ""
    resolved = urljoin(source_url, candidate)
    resolved, _ = urldefrag(resolved)
    return resolved


def is_action_url(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in ("cart.php?a=add", "/cart/add", "/checkout", "/order", "add-to-cart", "addtocart"))


def is_likely_product_title(title: str) -> bool:
    candidate = normalize_candidate_title(title)
    if len(candidate) < 2:
        return False
    lowered = normalize_signal_text(candidate)
    if lowered in DISCOVERY_GENERIC_TEXTS or lowered in DISCOVERY_ACTION_TEXTS:
        return False
    if any(token in lowered for token in ("next", "previous", "breadcrumb", "menu", "login", "cart", "checkout")) and len(candidate) < 24:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", candidate))


def extract_page_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(?P<body>.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if match:
        title = normalize_candidate_title(match.group("body"))
        if title:
            return title
    heading = HEADING_PATTERN.search(html_text)
    if heading:
        title = normalize_candidate_title(heading.group("body"))
        if title:
            return title
    return ""


def extract_price_hint(fragment: str) -> str:
    match = PRICE_PATTERN.search(html_module.unescape(fragment))
    if match:
        return normalize_candidate_title(match.group(0))
    return ""


def infer_source_item_key(source_url: str, title: str, monitor_url: str, item_url: str) -> str:
    raw = f"{source_url}|{title}|{monitor_url}|{item_url}".lower().encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[:20]


def extract_heading_before(match_start: int, html_text: str, limit: int = 700) -> str:
    segment = html_text[max(0, match_start - limit) : match_start]
    titles = []
    for heading in HEADING_PATTERN.finditer(segment):
        title = normalize_candidate_title(heading.group("body"))
        if title and is_likely_product_title(title):
            titles.append(title)
    return titles[-1] if titles else ""


def extract_jsonld_catalog_candidates(html_text: str, source_url: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    def add_candidate(title: str, monitor_url: str, item_url: str, price_hint: str, stock_hint: str, restock_hint: str, raw_payload: Any) -> None:
        normalized_title = normalize_candidate_title(title)
        if not is_likely_product_title(normalized_title):
            return
        monitor_url = normalize_candidate_url(source_url, monitor_url) if monitor_url else source_url
        item_url = normalize_candidate_url(source_url, item_url) if item_url else monitor_url
        key = infer_source_item_key(source_url, normalized_title, monitor_url, item_url)
        candidates.append(
            {
                "source_item_key": key,
                "title": normalized_title,
                "keyword": normalized_title,
                "monitor_url": monitor_url or source_url,
                "item_url": item_url or monitor_url or source_url,
                "price_hint": price_hint[:120],
                "stock_hint": stock_hint[:80],
                "restock_hint": restock_hint[:120],
                "raw_payload": json.dumps(raw_payload, ensure_ascii=False)[:4000],
            }
        )

    for match in JSON_SCRIPT_PATTERN.finditer(html_text):
        body = html_module.unescape(match.group("body") or "").strip()
        if not body:
            continue
        body = re.sub(r"(?is)^\s*(?:<!--|//<!\[CDATA\[)", "", body).strip()
        body = re.sub(r"(?is)(?:-->|//\]\]>)\s*$", "", body).strip()
        if "=" in body and not body.lstrip().startswith(("{", "[")):
            body = body.split("=", 1)[1].strip().rstrip(";")
        if not body.startswith(("{", "[")):
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                type_value = normalize_signal_text(value.get("@type"))
                if type_value in {"product", "itemlist", "listitem", "offer", "aggregateoffer"} or any(
                    key in value for key in ("name", "title", "url", "offers")
                ):
                    offers = value.get("offers") if isinstance(value.get("offers"), dict) else {}
                    title = first_non_empty(value.get("name"), value.get("title"), value.get("headline"))
                    url = first_non_empty(value.get("url"), value.get("mainEntityOfPage"), value.get("item", {}).get("url") if isinstance(value.get("item"), dict) else "")
                    price_hint = first_non_empty(
                        value.get("price"),
                        offers.get("price") if isinstance(offers, dict) else "",
                        value.get("priceRange"),
                    )
                    stock_hint = first_non_empty(
                        offers.get("availability") if isinstance(offers, dict) else "",
                        value.get("availability"),
                        value.get("stock"),
                    )
                    restock_hint = first_non_empty(
                        offers.get("availabilityDate") if isinstance(offers, dict) else "",
                        value.get("availabilityDate"),
                        value.get("restockDate"),
                        value.get("backOrderDate"),
                    )
                    if title:
                        add_candidate(title, url or source_url, url or source_url, price_hint, stock_hint, restock_hint, value)
                if "itemListElement" in value and isinstance(value["itemListElement"], list):
                    for element in value["itemListElement"]:
                        if isinstance(element, dict):
                            item_value = element.get("item") if isinstance(element.get("item"), dict) else element
                            visit(item_value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)

    return candidates


def discover_catalog_items(html_text: str, source_url: str) -> list[dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}
    source_url = source_url.strip()
    if not html_text or not source_url:
        return []

    page_title = extract_page_title(html_text)
    price_hint_global = extract_price_hint(html_text)

    def register_candidate(
        title: str,
        monitor_url: str,
        item_url: str,
        snippet: str,
        raw_payload: Any,
        price_hint: str = "",
        stock_hint: str = "",
        restock_hint: str = "",
    ) -> None:
        normalized_title = normalize_candidate_title(title)
        if not is_likely_product_title(normalized_title):
            return
        normalized_monitor = normalize_candidate_url(source_url, monitor_url) if monitor_url else source_url
        normalized_item = normalize_candidate_url(source_url, item_url) if item_url else normalized_monitor
        key = infer_source_item_key(source_url, normalized_title, normalized_monitor, normalized_item)
        if key in candidates:
            existing = candidates[key]
            if len(snippet) > len(existing.get("raw_snippet", "")):
                existing["raw_snippet"] = snippet[:4000]
            if price_hint and not existing.get("price_hint"):
                existing["price_hint"] = price_hint[:120]
            if stock_hint and not existing.get("stock_hint"):
                existing["stock_hint"] = stock_hint[:80]
            if restock_hint and not existing.get("restock_hint"):
                existing["restock_hint"] = restock_hint[:120]
            return
        candidates[key] = {
            "source_item_key": key,
            "title": normalized_title,
            "keyword": normalized_title,
            "monitor_url": normalized_monitor or source_url,
            "item_url": normalized_item or normalized_monitor or source_url,
            "price_hint": (price_hint or price_hint_global)[:120],
            "stock_hint": stock_hint[:80],
            "restock_hint": restock_hint[:120],
            "raw_snippet": snippet[:4000],
            "raw_payload": json.dumps(raw_payload, ensure_ascii=False)[:4000],
        }

    for json_candidate in extract_jsonld_catalog_candidates(html_text, source_url):
        register_candidate(
            json_candidate["title"],
            json_candidate["monitor_url"],
            json_candidate["item_url"],
            json_candidate.get("raw_payload", ""),
            json_candidate,
            json_candidate.get("price_hint", ""),
            json_candidate.get("stock_hint", ""),
            json_candidate.get("restock_hint", ""),
        )

    for anchor in ANCHOR_PATTERN.finditer(html_text):
        attrs = parse_tag_attributes(anchor.group("attrs") or "")
        href = (attrs.get("href") or "").strip()
        if not href:
            continue
        lowered_href = href.lower()
        if any(part in lowered_href for part in DISCOVERY_SKIP_URL_PARTS) and not is_action_url(lowered_href):
            continue
        item_url = normalize_candidate_url(source_url, href)
        monitor_url = source_url if is_action_url(href) else item_url
        snippet_start = max(0, anchor.start() - 500)
        snippet_end = min(len(html_text), anchor.end() + 1200)
        snippet = html_text[snippet_start:snippet_end]
        heading_title = extract_heading_before(anchor.start(), html_text)
        body_title = normalize_candidate_title(anchor.group("body"))
        title = first_non_empty(
            attrs.get("data-title"),
            attrs.get("aria-label"),
            attrs.get("title"),
            heading_title,
            body_title,
        )
        if not title:
            continue
        cleaned_snippet = clean_fragment_text(snippet)
        stock_value, stock_detail = parse_stock(snippet)
        stock_hint = "" if stock_value is None else str(stock_value)
        restock_hint = ""
        if "补货" in stock_detail or "restock" in stock_detail.lower() or "到货" in stock_detail:
            restock_hint = stock_detail
        price_hint = extract_price_hint(snippet)
        register_candidate(
            title,
            monitor_url,
            item_url,
            snippet,
            {
                "href": href,
                "text": body_title,
                "heading": heading_title,
                "snippet_text": cleaned_snippet,
            },
            price_hint,
            stock_hint,
            restock_hint,
        )

    if not candidates and page_title:
        register_candidate(
            page_title,
            source_url,
            source_url,
            html_text[:2000],
            {"fallback": True, "page_title": page_title},
            price_hint_global,
            "",
            "",
        )

    return list(candidates.values())


def make_app() -> Flask:
    app = Flask(__name__)
    if ENABLE_PROXY_FIX:
        app.wsgi_app = ProxyFix(  # type: ignore[assignment]
            app.wsgi_app,
            x_for=PROXY_FIX_X_FOR,
            x_proto=PROXY_FIX_X_PROTO,
            x_host=PROXY_FIX_X_HOST,
            x_port=PROXY_FIX_X_PORT,
        )
    app.secret_key = SECRET_KEY
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE", False),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    app.json.ensure_ascii = False

    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=[],
        storage_uri=LIMITER_STORAGE_URI,
    )
    app.extensions["limiter"] = limiter
    app.extensions["monitor_engine"] = MonitoringEngine(app)

    @app.before_request
    def harden_requests():
        if request.path == "/favicon.ico":
            return "", 204
        if request.endpoint == "static":
            return None
        if not is_browser_user_agent(request.headers.get("User-Agent")):
            return ("Not Found", 404)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if not is_same_origin(request):
                return ("Not Found", 404)
            if not require_ajax_header(request):
                return ("Not Found", 404)
            if not is_valid_csrf(request):
                return ("Not Found", 404)
        return None

    @app.after_request
    def inject_security_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @app.route("/assets/<path:filename>", methods=["GET"])
    def asset_file(filename: str):
        return send_from_directory(ASSETS_DIR, filename)

    @app.errorhandler(429)
    def rate_limited(error):
        if request.accept_mimetypes.accept_json or request.path.startswith("/api"):
            return jsonify({"ok": False, "message": "请求过于频繁，请稍后再试。"}), 429
        return "Too Many Requests", 429

    @app.errorhandler(400)
    def bad_request(error):
        if request.accept_mimetypes.accept_json or request.path.startswith("/api"):
            return jsonify({"ok": False, "message": getattr(error, "description", "请求格式错误。")}), 400
        return "Bad Request", 400

    @app.route("/", methods=["GET"])
    def portal():
        csrf_token = ensure_csrf_token()
        authenticated = bool(session.get("admin_id"))
        return render_template(
            "portal.html",
            csrf_token=csrf_token,
            logged_in=authenticated,
            masked_bot_token="",
        )

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify({"ok": True, "service": "noaff-monitor"})

    @app.route("/gate", methods=["POST"])
    @limiter.limit(LOGIN_RATE_LIMIT)
    def login_gate():
        payload = read_json()
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", "")).strip()
        with open_connection() as connection:
            admin = connection.execute(
                "SELECT * FROM admins WHERE username = ?",
                (username,),
            ).fetchone()
        if not admin or not check_password_hash(admin["password_hash"], password):
            log_activity("warning", "auth", f"登录失败：{username or '<empty>'}")
            return jsonify({"ok": False, "message": "用户名或密码错误。"}), 401

        session.clear()
        session.permanent = True
        session["admin_id"] = admin["id"]
        session["admin_username"] = admin["username"]
        csrf_token = issue_csrf_token()
        log_activity("info", "auth", f"管理员 {admin['username']} 已登录。")
        return jsonify({"ok": True, "message": "登录成功。", "csrf_token": csrf_token})

    @app.route("/logout", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def logout_gate():
        username = session.get("admin_username", "")
        session.clear()
        log_activity("info", "auth", f"管理员 {username} 已退出。")
        return jsonify({"ok": True, "message": "已安全退出。"})

    @app.route("/api/snapshot", methods=["GET"])
    @login_required
    def dashboard_snapshot():
        with open_connection() as connection:
            settings_payload = normalize_settings(load_settings(connection))
            tasks = connection.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
            source_rows = connection.execute("SELECT * FROM merchant_sources ORDER BY id DESC").fetchall()
            item_rows = connection.execute("SELECT * FROM merchant_items ORDER BY updated_at DESC, id DESC LIMIT 120").fetchall()
            task_source_rows = connection.execute(
                "SELECT id, name, source_item_id FROM tasks WHERE source_item_id IS NOT NULL"
            ).fetchall()
            source_item_counts = {
                row["source_id"]: row["count"]
                for row in connection.execute(
                    "SELECT source_id, COUNT(*) AS count FROM merchant_items GROUP BY source_id"
                ).fetchall()
            }
            linked_counts = {
                row["source_id"]: row["count"]
                for row in connection.execute(
                    """
                    SELECT mi.source_id AS source_id, COUNT(*) AS count
                    FROM merchant_items mi
                    JOIN tasks t ON t.source_item_id = mi.id
                    GROUP BY mi.source_id
                    """
                ).fetchall()
            }
            logs = connection.execute(
                """
                SELECT level, scope, message, created_at
                FROM activity_logs
                ORDER BY id DESC
                LIMIT 30
                """
            ).fetchall()
        task_lookup = {
            int(row["source_item_id"]): row
            for row in task_source_rows
            if row["source_item_id"] is not None
        }
        source_rows_by_id = {row["id"]: row for row in source_rows}
        catalog_sources = [
            to_source_payload(
                row,
                source_item_counts.get(row["id"], 0),
                linked_counts.get(row["id"], 0),
            )
            for row in source_rows
        ]
        catalog_items = [
            to_merchant_item_payload(
                row,
                source_rows_by_id.get(row["source_id"]),
                task_lookup.get(int(row["id"])),
            )
            for row in item_rows
        ]
        in_stock_count = sum(1 for task in tasks if task["last_state"] == "in_stock")
        sold_out_count = sum(1 for task in tasks if task["last_state"] == "sold_out")
        unknown_count = sum(1 for task in tasks if task["last_state"] not in {"in_stock", "sold_out"})
        catalog_new_count = sum(1 for item in item_rows if item["item_state"] == "new")
        catalog_updated_count = sum(1 for item in item_rows if item["item_state"] == "updated")
        catalog_archived_count = sum(1 for item in item_rows if item["item_state"] == "archived")

        return jsonify(
            {
                "ok": True,
                "tasks": [to_task_payload(task) for task in tasks],
                "merchant": {
                    "sources": catalog_sources,
                    "items": catalog_items,
                    "metrics": {
                        "total_sources": len(source_rows),
                        "active_sources": sum(1 for row in source_rows if row["active"]),
                        "total_items": len(item_rows),
                        "new_items": catalog_new_count,
                        "updated_items": catalog_updated_count,
                        "archived_items": catalog_archived_count,
                        "linked_tasks": len(task_lookup),
                    },
                },
                "settings": {
                    "telegram_bot_token_masked": mask_secret(settings_payload["telegram_bot_token"]),
                    "telegram_chat_id": settings_payload["telegram_chat_id"],
                    "monitor_debug_port": settings_payload["monitor_debug_port"],
                    "test_debug_port": settings_payload["test_debug_port"],
                    "catalog_debug_port": settings_payload["catalog_debug_port"],
                    "poll_interval_seconds": settings_payload["poll_interval_seconds"],
                    "request_timeout_seconds": settings_payload["request_timeout_seconds"],
                    "telegram_ready": bool(
                        settings_payload["telegram_bot_token"] and settings_payload["telegram_chat_id"]
                    ),
                },
                "admin": {
                    "username": session.get("admin_username", ""),
                },
                "metrics": {
                    "total": len(tasks),
                    "in_stock": in_stock_count,
                    "sold_out": sold_out_count,
                    "unknown": unknown_count,
                    "enabled": sum(1 for task in tasks if task["enabled"]),
                },
                "engine": app.extensions["monitor_engine"].get_status(),
                "system": system_payload(),
                "logs": [
                    {
                        "level": row["level"],
                        "scope": row["scope"],
                        "message": sanitize_telegram_error(row["message"], settings_payload["telegram_bot_token"]),
                        "created_at": row["created_at"],
                    }
                    for row in logs
                ],
                "csrf_token": ensure_csrf_token(),
            }
        )

    @app.route("/api/tasks", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def create_task():
        payload = read_json()
        valid, message = validate_task_payload(payload)
        if not valid:
            return jsonify({"ok": False, "message": message}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            task_id = insert_task_record(connection, payload, timestamp)
        log_activity("info", "tasks", f"已创建任务 #{task_id}。")
        return jsonify({"ok": True, "message": "任务已创建。", "task_id": task_id})

    @app.route("/api/tasks/<int:task_id>", methods=["PUT"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def update_task(task_id: int):
        payload = read_json()
        valid, message = validate_task_payload(payload)
        if not valid:
            return jsonify({"ok": False, "message": message}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            existing = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not existing:
                return jsonify({"ok": False, "message": "任务不存在。"}), 404
            source_fields = normalize_task_source_fields(payload, existing)
            connection.execute(
                """
                UPDATE tasks
                SET name = ?, group_name = ?, monitor_url = ?, target_keyword = ?, restock_template = ?,
                    soldout_template = ?, button_1_text = ?, button_1_url = ?,
                    button_2_text = ?, button_2_url = ?, source_item_id = ?, source_item_key = ?,
                    source_source_url = ?, source_source_name = ?, source_item_url = ?, source_snapshot = ?,
                    source_last_sync_at = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(payload["name"]).strip(),
                    normalize_task_group(payload.get("group_name")),
                    str(payload["monitor_url"]).strip(),
                    str(payload["target_keyword"]).strip(),
                    str(payload["restock_template"]).strip() or DEFAULT_RESTOCK_TEMPLATE,
                    str(payload["soldout_template"]).strip() or DEFAULT_SOLDOUT_TEMPLATE,
                    str(payload.get("button_1_text", "")).strip(),
                    str(payload.get("button_1_url", "")).strip(),
                    str(payload.get("button_2_text", "")).strip(),
                    str(payload.get("button_2_url", "")).strip(),
                    source_fields["source_item_id"],
                    source_fields["source_item_key"],
                    source_fields["source_source_url"],
                    source_fields["source_source_name"],
                    source_fields["source_item_url"],
                    source_fields["source_snapshot"],
                    source_fields["source_last_sync_at"] or timestamp,
                    1 if payload.get("enabled", True) else 0,
                    timestamp,
                    task_id,
                ),
            )
            connection.commit()
        log_activity("info", "tasks", f"已更新任务 #{task_id}。")
        return jsonify({"ok": True, "message": "任务已更新。"})

    @app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def delete_task(task_id: int):
        with open_connection() as connection:
            task = connection.execute("SELECT name FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                return jsonify({"ok": False, "message": "任务不存在。"}), 404
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            connection.commit()
        log_activity("warning", "tasks", f"已删除任务 #{task_id} ({task['name']})。")
        return jsonify({"ok": True, "message": "任务已删除。"})

    @app.route("/api/tasks/<int:task_id>/toggle", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def toggle_task(task_id: int):
        payload = read_json()
        enabled = bool(payload.get("enabled", True))
        with open_connection() as connection:
            task = connection.execute("SELECT name FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                return jsonify({"ok": False, "message": "任务不存在。"}), 404
            connection.execute(
                "UPDATE tasks SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, now_iso(), task_id),
            )
            connection.commit()
        log_activity("info", "tasks", f"任务 #{task_id} 已{'启用' if enabled else '停用'}。")
        return jsonify({"ok": True, "message": "任务状态已切换。"})

    @app.route("/api/test-push/<int:task_id>", methods=["POST"])
    @login_required
    @limiter.limit("8 per minute")
    def test_push(task_id: int):
        try:
            result = app.extensions["monitor_engine"].run_test_push(task_id)
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        return jsonify({"ok": True, "message": "测试消息已发送。", "result": result})

    @app.route("/api/merchant/import", methods=["POST"])
    @login_required
    @limiter.limit("6 per minute")
    def import_merchant_source():
        payload = read_json()
        source_url = str(payload.get("source_url", "")).strip()
        source_name = str(payload.get("source_name", "")).strip()
        auto_promote = bool(payload.get("auto_promote", True))
        if not source_url:
            return jsonify({"ok": False, "message": "商家页面链接不能为空。"}), 400
        if not validate_http_url(source_url):
            return jsonify({"ok": False, "message": "商家页面链接必须是有效的 http(s) 地址。"}), 400

        try:
            result = app.extensions["monitor_engine"].import_merchant_source(
                source_url,
                source_name,
                app.extensions["monitor_engine"].get_runtime_settings(),
                auto_promote=auto_promote,
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400

        log_activity(
            "info",
            "catalog",
            f"已导入商家来源 {result.source_name}，发现 {result.scanned_count} 个候选商品，自动生成 {result.promoted_count} 个任务。",
        )
        return jsonify(
            {
                "ok": True,
                "message": "商家页面已导入。",
                "result": {
                    "source_id": result.source_id,
                    "source_url": result.source_url,
                    "source_name": result.source_name,
                    "scanned_count": result.scanned_count,
                    "upserted_count": result.upserted_count,
                    "promoted_count": result.promoted_count,
                    "archived_count": result.archived_count,
                    "last_sync_at": result.last_sync_at,
                    "items": result.items,
                },
            }
        )

    @app.route("/api/merchant/sources/<int:source_id>/sync", methods=["POST"])
    @login_required
    @limiter.limit("6 per minute")
    def resync_merchant_source(source_id: int):
        payload = read_json()
        auto_promote = bool(payload.get("auto_promote", True))
        with open_connection() as connection:
            source = connection.execute("SELECT * FROM merchant_sources WHERE id = ?", (source_id,)).fetchone()
        if not source:
            return jsonify({"ok": False, "message": "商家来源不存在。"}), 404
        try:
            result = app.extensions["monitor_engine"].import_merchant_source(
                source["source_url"],
                source["source_name"],
                app.extensions["monitor_engine"].get_runtime_settings(),
                auto_promote=auto_promote,
            )
        except Exception as exc:
            with open_connection() as connection:
                connection.execute(
                    "UPDATE merchant_sources SET last_error = ?, updated_at = ? WHERE id = ?",
                    (str(exc)[:1000], now_iso(), source_id),
                )
                connection.commit()
            return jsonify({"ok": False, "message": str(exc)}), 400

        log_activity("info", "catalog", f"已同步商家来源 #{source_id}，发现 {result.scanned_count} 个候选商品。")
        return jsonify(
            {
                "ok": True,
                "message": "商家来源已同步。",
                "result": {
                    "source_id": result.source_id,
                    "source_url": result.source_url,
                    "source_name": result.source_name,
                    "scanned_count": result.scanned_count,
                    "upserted_count": result.upserted_count,
                    "promoted_count": result.promoted_count,
                    "archived_count": result.archived_count,
                    "last_sync_at": result.last_sync_at,
                    "items": result.items,
                },
            }
        )

    @app.route("/api/merchant/sources/<int:source_id>/toggle", methods=["POST"])
    @login_required
    @limiter.limit("8 per minute")
    def toggle_merchant_source(source_id: int):
        payload = read_json()
        active = bool(payload.get("active", True))
        with open_connection() as connection:
            source = connection.execute("SELECT id, source_name, active FROM merchant_sources WHERE id = ?", (source_id,)).fetchone()
            if not source:
                return jsonify({"ok": False, "message": "商家来源不存在。"}), 404
            connection.execute(
                "UPDATE merchant_sources SET active = ?, updated_at = ? WHERE id = ?",
                (1 if active else 0, now_iso(), source_id),
            )
            connection.commit()
        log_activity("info", "catalog", f"商家来源 #{source_id} 已{'启用' if active else '停用'}。")
        return jsonify({"ok": True, "message": "商家来源状态已更新。", "result": {"source_id": source_id, "active": active}})

    @app.route("/api/merchant/items/<int:item_id>/promote", methods=["POST"])
    @login_required
    @limiter.limit("8 per minute")
    def promote_merchant_item(item_id: int):
        read_json()
        with open_connection() as connection:
            item = connection.execute(
                """
                SELECT mi.*, ms.source_url, ms.source_name
                FROM merchant_items mi
                JOIN merchant_sources ms ON ms.id = mi.source_id
                WHERE mi.id = ?
                """,
                (item_id,),
            ).fetchone()
            if not item:
                return jsonify({"ok": False, "message": "商家商品不存在。"}), 404
            existing_task = connection.execute(
                "SELECT * FROM tasks WHERE source_item_id = ? LIMIT 1",
                (item_id,),
            ).fetchone()

            if existing_task:
                sync_task_source_fields(
                    connection,
                    int(existing_task["id"]),
                    item["source_url"],
                    item["source_name"],
                    {
                        "item_url": item["item_url"] or item["monitor_url"],
                        "source_item_key": item["item_key"],
                        "title": item["title"],
                        "keyword": item["keyword"],
                        "monitor_url": item["monitor_url"],
                        "price_hint": item["price_hint"] or "",
                        "stock_hint": item["stock_hint"] or "",
                        "restock_hint": item["restock_hint"] or "",
                        "raw_snippet": item["raw_snippet"] or "",
                        "raw_payload": item["raw_payload"] or "",
                        "item_state": item["item_state"],
                    },
                )
                connection.commit()
                task_id = int(existing_task["id"])
                task_name = str(existing_task["name"])
            else:
                item_payload = {
                    "source_item_key": item["item_key"],
                    "title": item["title"],
                    "keyword": item["keyword"],
                    "monitor_url": item["monitor_url"],
                    "item_url": item["item_url"] or item["monitor_url"],
                    "price_hint": item["price_hint"] or "",
                    "stock_hint": item["stock_hint"] or "",
                    "restock_hint": item["restock_hint"] or "",
                    "raw_snippet": item["raw_snippet"] or "",
                    "raw_payload": item["raw_payload"] or "",
                    "item_state": item["item_state"],
                }
                task_id = create_task_from_catalog_item(
                    connection,
                    source_id=int(item["source_id"]),
                    source_title=str(item["source_name"] or item["source_url"]),
                    source_url=str(item["source_url"]),
                    item_id=int(item["id"]),
                    item=item_payload,
                )
                task_name = str(item["title"])
                connection.commit()

        log_activity("info", "catalog", f"已将商家商品 #{item_id} 生成/关联为任务 #{task_id}。")
        return jsonify(
            {
                "ok": True,
                "message": "商家商品已生成任务。",
                "result": {
                    "item_id": item_id,
                    "task_id": task_id,
                    "task_name": task_name,
                    "already_linked": bool(existing_task),
                },
            }
        )

    @app.route("/api/settings/telegram", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def update_settings():
        payload = read_json()
        updates: dict[str, str] = {}
        current_settings = app.extensions["monitor_engine"].get_runtime_settings()

        bot_token = str(payload.get("telegram_bot_token", "")).strip()
        if bot_token:
            updates["telegram_bot_token"] = bot_token

        chat_id = str(payload.get("telegram_chat_id", "")).strip()
        if chat_id:
            updates["telegram_chat_id"] = chat_id

        for key in ("monitor_debug_port", "test_debug_port", "catalog_debug_port"):
            if key in payload:
                try:
                    port = int(payload[key])
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "message": "端口必须是整数。"}), 400
                if port < 1024 or port > 65535:
                    return jsonify({"ok": False, "message": "端口必须位于 1024-65535。"}), 400
                updates[key] = str(port)

        monitor_port = int(updates.get("monitor_debug_port", current_settings["monitor_debug_port"]))
        test_port = int(updates.get("test_debug_port", current_settings["test_debug_port"]))
        catalog_port = int(updates.get("catalog_debug_port", current_settings["catalog_debug_port"]))
        if len({monitor_port, test_port, catalog_port}) < 3:
            return jsonify({"ok": False, "message": "三个浏览器调试端口不能重复。"}), 400
        if DEFAULT_APP_PORT in {monitor_port, test_port, catalog_port}:
            return jsonify({"ok": False, "message": "浏览器调试端口不能与面板监听端口相同。"}), 400

        for key, minimum, maximum in (
            ("poll_interval_seconds", 15, 3600),
            ("request_timeout_seconds", 10, 120),
        ):
            if key in payload:
                try:
                    value = int(payload[key])
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "message": "配置项必须是整数。"}), 400
                if value < minimum or value > maximum:
                    return jsonify({"ok": False, "message": f"{key} 超出允许范围。"}), 400
                updates[key] = str(value)

        if not updates:
            return jsonify({"ok": False, "message": "没有可更新的设置。"}), 400

        with open_connection() as connection:
            save_settings(connection, updates)

        app.extensions["monitor_engine"].configure_browsers(app.extensions["monitor_engine"].get_runtime_settings())
        log_activity("info", "settings", "Telegram / 引擎配置已更新。")
        return jsonify({"ok": True, "message": "设置已保存。"})

    @app.route("/api/settings/profile", methods=["POST"])
    @login_required
    @limiter.limit("10 per minute")
    def update_profile():
        payload = read_json()
        current_password = str(payload.get("current_password", "")).strip()
        new_username = str(payload.get("new_username", "")).strip() or session.get("admin_username", "")
        new_password = str(payload.get("new_password", "")).strip()
        confirm_password = str(payload.get("confirm_password", "")).strip()

        with open_connection() as connection:
            admin = connection.execute("SELECT * FROM admins WHERE id = ?", (session["admin_id"],)).fetchone()
            if not admin or not check_password_hash(admin["password_hash"], current_password):
                return jsonify({"ok": False, "message": "当前密码错误。"}), 400
            if new_password:
                if len(new_password) < 10:
                    return jsonify({"ok": False, "message": "新密码至少需要 10 位。"}), 400
                if new_password != confirm_password:
                    return jsonify({"ok": False, "message": "两次输入的新密码不一致。"}), 400
            try:
                connection.execute(
                    """
                    UPDATE admins
                    SET username = ?, password_hash = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        new_username,
                        generate_password_hash(new_password) if new_password else admin["password_hash"],
                        now_iso(),
                        admin["id"],
                    ),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                return jsonify({"ok": False, "message": "用户名已存在，请更换一个新的用户名。"}), 400

        session["admin_username"] = new_username
        issue_csrf_token()
        if BOOTSTRAP_CREDENTIALS_PATH.exists():
            BOOTSTRAP_CREDENTIALS_PATH.unlink(missing_ok=True)
        log_activity("info", "auth", "管理员凭据已更新。")
        return jsonify({"ok": True, "message": "管理员凭据已更新。", "csrf_token": session["csrf_token"]})

    @app.route("/api/engine/restart", methods=["POST"])
    @login_required
    @limiter.limit("10 per minute")
    def restart_engine():
        app.extensions["monitor_engine"].restart("panel action")
        return jsonify({"ok": True, "message": "浏览器引擎已重启。"})

    @app.route("/api/system/upgrade", methods=["POST"])
    @login_required
    @limiter.limit("3 per hour")
    def start_system_upgrade():
        system = system_payload()
        if system["upgrade_mode"] == "manual":
            return jsonify(
                {
                    "ok": False,
                    "message": "Docker 部署请复制下方升级命令后在服务器上执行。",
                    "system": system,
                }
            ), 400
        if not system["upgrade_supported"]:
            return jsonify({"ok": False, "message": "当前环境暂不支持自动升级。", "system": system}), 400
        try:
            completed = subprocess.run(
                ["systemctl", "start", UPGRADE_SERVICE_NAME],
                text=True,
                capture_output=True,
                timeout=12,
                check=False,
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": f"升级服务启动失败：{exc}"}), 500
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "升级命令执行失败。").strip()
            return jsonify({"ok": False, "message": message}), 500
        log_activity("warning", "system", f"管理员 {session.get('admin_username', '')} 已触发系统升级。")
        return jsonify({"ok": True, "message": "升级任务已触发，服务会在后台自动重启。", "system": system_payload()})

    @app.route("/api/system/backup", methods=["GET"])
    @login_required
    def export_system_backup():
        with open_connection() as connection:
            payload = build_backup_payload(connection)
        exported_at = payload["exported_at"].replace(":", "").replace("-", "").replace("+00:00", "Z")
        filename = f"noaff-backup-{exported_at}.json"
        response = app.response_class(
            json.dumps(payload, ensure_ascii=False, indent=2),
            mimetype="application/json",
        )
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.route("/api/system/backup", methods=["POST"])
    @login_required
    @limiter.limit("3 per hour")
    def restore_system_backup():
        backup_file = request.files.get("backup_file")
        if not backup_file or not getattr(backup_file, "filename", ""):
            return jsonify({"ok": False, "message": "请先选择要恢复的备份文件。"}), 400
        raw_text = backup_file.read()
        if not raw_text:
            return jsonify({"ok": False, "message": "备份文件为空。"}), 400
        try:
            payload = json.loads(raw_text.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return jsonify({"ok": False, "message": "备份文件不是有效的 JSON。"}), 400

        try:
            with open_connection() as connection:
                restored_counts = apply_backup_payload(connection, payload)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        except sqlite3.Error as exc:
            return jsonify({"ok": False, "message": f"恢复备份失败：{exc}"}), 500

        app.extensions["monitor_engine"].configure_browsers(app.extensions["monitor_engine"].get_runtime_settings())
        log_activity("warning", "system", f"管理员 {session.get('admin_username', '')} 已恢复系统备份。")
        return jsonify(
            {
                "ok": True,
                "message": "备份已恢复，页面将刷新以同步最新数据。",
                "restored": restored_counts,
            }
        )

    return app


initialize_database()
app = make_app()


def start_engine_if_needed(flask_app: Flask) -> None:
    if flask_app.extensions["monitor_engine"].thread and flask_app.extensions["monitor_engine"].thread.is_alive():
        return
    flask_app.extensions["monitor_engine"].start()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    start_engine_if_needed(app)

    def shutdown_handler(signum, frame):  # pragma: no cover - signal-based shutdown
        app.extensions["monitor_engine"].stop()
        raise SystemExit(0)

    if os.name != "nt":
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGINT, shutdown_handler)

    serve(app, host=DEFAULT_APP_HOST, port=DEFAULT_APP_PORT)


if __name__ == "__main__":
    main()
