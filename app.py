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
from urllib.parse import urlparse

import psutil
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
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
DEFAULT_POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "45"))
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))
DEFAULT_HEADLESS = env_bool("CHROMIUM_HEADLESS", True)
DEFAULT_BROWSER_PATH = os.getenv("CHROMIUM_BINARY", "").strip()
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
SOLD_OUT_MARKERS = ("sold out", "out of stock", "暂无库存", "缺货", "售罄", "无货")

SETTINGS_DEFAULTS = {
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    "monitor_debug_port": str(DEFAULT_MONITOR_PORT),
    "test_debug_port": str(DEFAULT_TEST_PORT),
    "poll_interval_seconds": str(DEFAULT_POLL_INTERVAL),
    "request_timeout_seconds": str(DEFAULT_TIMEOUT_SECONDS),
}

STOCK_HTML_GAP = r"(?:\s|&nbsp;|&#\d+;|&[a-z]+;|[:：=()（）\[\]【】\-_/]|<!--.*?-->|<[^>]{1,240}>){0,40}"
STOCK_PATTERNS = [
    re.compile(
        rf"(?:库存|可用|剩余|available|availability|in\s*stock|stock|qty|quantity)"
        rf"{STOCK_HTML_GAP}(?P<count>\d{{1,6}})",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        rf"(?P<count>\d{{1,6}}){STOCK_HTML_GAP}"
        rf"(?:库存|可用|available|in\s*stock|stock|qty|quantity)",
        re.IGNORECASE | re.DOTALL,
    ),
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
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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
    poll_interval = max(15, min(3600, int(raw.get("poll_interval_seconds") or DEFAULT_POLL_INTERVAL)))
    timeout_seconds = max(10, min(120, int(raw.get("request_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)))
    return {
        "telegram_bot_token": raw.get("telegram_bot_token", "").strip(),
        "telegram_chat_id": raw.get("telegram_chat_id", "").strip(),
        "monitor_debug_port": monitor_port,
        "test_debug_port": test_port,
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
                monitor_url TEXT NOT NULL,
                target_keyword TEXT NOT NULL,
                restock_template TEXT NOT NULL,
                soldout_template TEXT NOT NULL,
                button_1_text TEXT DEFAULT '',
                button_1_url TEXT DEFAULT '',
                button_2_text TEXT DEFAULT '',
                button_2_url TEXT DEFAULT '',
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
            """
        )

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
                f"username={username}\npassword={password}\npanel_path=/\n",
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
        if not session.get("admin_id"):
            if request.accept_mimetypes.accept_json or request.path.startswith("/api"):
                return jsonify({"ok": False, "message": "未登录或会话已过期。"}), 401
            return redirect("/")
        return view(*args, **kwargs)

    return wrapped


def to_task_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "monitor_url": row["monitor_url"],
        "target_keyword": row["target_keyword"],
        "restock_template": row["restock_template"],
        "soldout_template": row["soldout_template"],
        "button_1_text": row["button_1_text"] or "",
        "button_1_url": row["button_1_url"] or "",
        "button_2_text": row["button_2_text"] or "",
        "button_2_url": row["button_2_url"] or "",
        "enabled": bool(row["enabled"]),
        "last_stock": row["last_stock"],
        "last_state": row["last_state"],
        "message_id": row["message_id"],
        "last_checked_at": row["last_checked_at"] or "",
        "last_error": row["last_error"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
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


@dataclass
class ScrapeResult:
    stock: int | None
    fragment: str
    detail: str
    used_test_browser: bool


class TelegramClient:
    def __init__(self) -> None:
        self.session = requests.Session()

    def _request(self, method: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"https://api.telegram.org/bot{token}/{method}"
        response: Response = self.session.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description") or f"Telegram API {method} 失败")
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
            ok = page.get(url, timeout=timeout_seconds)
            if ok is False:
                raise TimeoutError(f"{self.role} browser timed out while opening {url}")
            time.sleep(1.2)
            html_text = page.html or ""
            if not html_text:
                raise RuntimeError(f"{self.role} browser returned empty HTML")
            return html_text

    def rebuild(self, reason: str) -> None:
        with self.lock:
            self._shutdown_page()
            self._kill_zombies()
        log_activity("warning", f"browser:{self.role}", f"浏览器已重建，原因：{reason}")

    def shutdown(self) -> None:
        with self.lock:
            self._shutdown_page()
            self._kill_zombies()

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
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (process.info["name"] or "").lower()
                cmdline = " ".join(process.info["cmdline"] or []).lower()
                if not any(token in name for token in ("chrome", "chromium", "edge")):
                    continue
                if port_flag in cmdline or marker in cmdline:
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
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
        with self.state_lock:
            self.last_exception = ""
        log_activity("warning", "engine", f"已手动重启浏览器引擎：{reason}")

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
        for attempt in range(2):
            try:
                html_text = browser.fetch_html(task["monitor_url"], settings_payload["request_timeout_seconds"])
                fragment = slice_fragment(html_text, task["target_keyword"])
                stock, detail = parse_stock(fragment)
                return ScrapeResult(stock=stock, fragment=fragment, detail=detail, used_test_browser=use_test_browser)
            except Exception as exc:
                last_error = str(exc)
                if should_auto_heal(exc) and attempt == 0:
                    browser.rebuild(last_error)
                    continue
                break
        return ScrapeResult(stock=None, fragment="", detail=last_error or "抓取失败", used_test_browser=use_test_browser)

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
                    text = safe_format(task["soldout_template"], message_values | {"status": "sold_out"})
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
                last_error = str(exc)
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
    return {
        "name": task["name"],
        "stock": "" if stock is None else str(stock),
        "url": task["monitor_url"],
        "keyword": task["target_keyword"],
        "checked_at": checked_at,
        "status": "in_stock" if (stock or 0) > 0 else "sold_out",
    }


def should_auto_heal(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ("disconnected", "timeout", "timed out", "browserconnecterror"))


def slice_fragment(html_text: str, keyword: str) -> str:
    if not html_text:
        return ""
    if not keyword:
        return ""
    match = re.search(re.escape(keyword), html_text, re.IGNORECASE)
    if not match:
        return ""
    start = max(0, match.start() - 50)
    end = min(len(html_text), match.end() + 1200)
    return html_text[start:end]


def parse_stock(fragment: str) -> tuple[int | None, str]:
    if not fragment:
        return None, "未抓到有效 HTML 片段。"

    for pattern in STOCK_PATTERNS:
        match = pattern.search(fragment)
        if match:
            return int(match.group("count")), "匹配到 HTML 库存数字。"

    cleaned = html_module.unescape(re.sub(r"<[^>]+>", " ", fragment))
    cleaned = re.sub(r"\s+", " ", cleaned)
    text_match = re.search(
        r"(?:库存|可用|剩余|available|availability|in\s*stock|stock|qty|quantity)[^0-9]{0,80}(\d{1,6})",
        cleaned,
        re.IGNORECASE,
    )
    if text_match:
        return int(text_match.group(1)), "通过文本降噪提取到库存数字。"

    if any(marker in cleaned.lower() for marker in SOLD_OUT_MARKERS):
        return 0, "命中售罄标记。"

    return None, "未找到库存数字或售罄标记。"


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
            admin = connection.execute("SELECT username FROM admins LIMIT 1").fetchone()
            logs = connection.execute(
                """
                SELECT level, scope, message, created_at
                FROM activity_logs
                ORDER BY id DESC
                LIMIT 30
                """
            ).fetchall()

        in_stock_count = sum(1 for task in tasks if task["last_state"] == "in_stock")
        sold_out_count = sum(1 for task in tasks if task["last_state"] == "sold_out")
        unknown_count = sum(1 for task in tasks if task["last_state"] not in {"in_stock", "sold_out"})

        return jsonify(
            {
                "ok": True,
                "tasks": [to_task_payload(task) for task in tasks],
                "settings": {
                    "telegram_bot_token_masked": mask_secret(settings_payload["telegram_bot_token"]),
                    "telegram_chat_id": settings_payload["telegram_chat_id"],
                    "monitor_debug_port": settings_payload["monitor_debug_port"],
                    "test_debug_port": settings_payload["test_debug_port"],
                    "poll_interval_seconds": settings_payload["poll_interval_seconds"],
                    "request_timeout_seconds": settings_payload["request_timeout_seconds"],
                    "telegram_ready": bool(
                        settings_payload["telegram_bot_token"] and settings_payload["telegram_chat_id"]
                    ),
                },
                "admin": {
                    "username": admin["username"] if admin else "",
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
                "logs": [dict(row) for row in logs],
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
        values = (
            str(payload["name"]).strip(),
            str(payload["monitor_url"]).strip(),
            str(payload["target_keyword"]).strip(),
            str(payload["restock_template"]).strip(),
            str(payload["soldout_template"]).strip(),
            str(payload.get("button_1_text", "")).strip(),
            str(payload.get("button_1_url", "")).strip(),
            str(payload.get("button_2_text", "")).strip(),
            str(payload.get("button_2_url", "")).strip(),
            1 if payload.get("enabled", True) else 0,
            timestamp,
            timestamp,
        )
        with open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, restock_template, soldout_template,
                    button_1_text, button_1_url, button_2_text, button_2_url,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            connection.commit()
            task_id = cursor.lastrowid
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
            existing = connection.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not existing:
                return jsonify({"ok": False, "message": "任务不存在。"}), 404
            connection.execute(
                """
                UPDATE tasks
                SET name = ?, monitor_url = ?, target_keyword = ?, restock_template = ?,
                    soldout_template = ?, button_1_text = ?, button_1_url = ?,
                    button_2_text = ?, button_2_url = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(payload["name"]).strip(),
                    str(payload["monitor_url"]).strip(),
                    str(payload["target_keyword"]).strip(),
                    str(payload["restock_template"]).strip(),
                    str(payload["soldout_template"]).strip(),
                    str(payload.get("button_1_text", "")).strip(),
                    str(payload.get("button_1_url", "")).strip(),
                    str(payload.get("button_2_text", "")).strip(),
                    str(payload.get("button_2_url", "")).strip(),
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

        for key in ("monitor_debug_port", "test_debug_port"):
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
        if monitor_port == test_port:
            return jsonify({"ok": False, "message": "主监控端口和测试推送端口不能相同。"}), 400
        if monitor_port == DEFAULT_APP_PORT or test_port == DEFAULT_APP_PORT:
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
                    "message": "Docker ??????????????????????????? Docker?",
                    "system": system,
                }
            ), 400
        if not system["upgrade_supported"]:
            return jsonify({"ok": False, "message": "????????????????", "system": system}), 400
        try:
            completed = subprocess.run(
                ["systemctl", "start", UPGRADE_SERVICE_NAME],
                text=True,
                capture_output=True,
                timeout=12,
                check=False,
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": f"?????????{exc}"}), 500
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "?????????").strip()
            return jsonify({"ok": False, "message": message}), 500
        log_activity("warning", "system", f"??? {session.get('admin_username', '')} ????????")
        return jsonify({"ok": True, "message": "??????????????????", "system": system_payload()})

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
