import hashlib
import hmac
import html as html_module
import importlib
import importlib.util
import ipaddress
import atexit
import json
import logging
import multiprocessing
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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from string import Formatter
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urldefrag

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

try:
    from lxml import html as lxml_html
except Exception:  # pragma: no cover - optional parser may be absent in minimal installs
    lxml_html = None


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

_SCRAPLING_XVFB_PROCESS = None
_SCRAPLING_XVFB_DISPLAY = ""
_SCRAPLING_XVFB_LOCK = threading.Lock()


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


def settings_bool_text(value: bool) -> str:
    return "true" if value else "false"


def parse_setting_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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
DEFAULT_FIRECRAWL_ENABLED = env_bool("FIRECRAWL_ENABLED", False)
DEFAULT_FIRECRAWL_API_URL = os.getenv("FIRECRAWL_API_URL", "https://api.firecrawl.dev").strip() or "https://api.firecrawl.dev"
DEFAULT_FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "").strip()
DEFAULT_FIRECRAWL_TIMEOUT_SECONDS = int(os.getenv("FIRECRAWL_TIMEOUT_SECONDS", "60"))
DEFAULT_FIRECRAWL_MAX_AGE_MS = int(os.getenv("FIRECRAWL_MAX_AGE_MS", "0"))
DEFAULT_FIRECRAWL_STORE_IN_CACHE = env_bool("FIRECRAWL_STORE_IN_CACHE", False)
DEFAULT_FIRECRAWL_PROXY_MODE = os.getenv("FIRECRAWL_PROXY_MODE", "basic").strip().lower() or "basic"
DEFAULT_FIRECRAWL_ALLOW_AUTO_PROXY = env_bool("FIRECRAWL_ALLOW_AUTO_PROXY", False)
DEFAULT_FIRECRAWL_ALLOW_ENHANCED_PROXY = env_bool("FIRECRAWL_ALLOW_ENHANCED_PROXY", False)
DEFAULT_FIRECRAWL_ZERO_DATA_RETENTION = env_bool("FIRECRAWL_ZERO_DATA_RETENTION", False)
DEFAULT_FIRECRAWL_USE_FOR_MONITOR = env_bool("FIRECRAWL_USE_FOR_MONITOR", False)
DEFAULT_FIRECRAWL_USE_FOR_CATALOG = env_bool("FIRECRAWL_USE_FOR_CATALOG", True)
DEFAULT_FIRECRAWL_CATALOG_LIMIT = int(os.getenv("FIRECRAWL_CATALOG_LIMIT", "50"))
DEFAULT_ENHANCED_COLLECTOR_ENABLED = env_bool("ENHANCED_COLLECTOR_ENABLED", False)
DEFAULT_ENHANCED_COLLECTOR_API_URL = os.getenv("ENHANCED_COLLECTOR_API_URL", "").strip().rstrip("/")
DEFAULT_ENHANCED_COLLECTOR_TIMEOUT_SECONDS = int(os.getenv("ENHANCED_COLLECTOR_TIMEOUT_SECONDS", "90"))
DEFAULT_ENHANCED_COLLECTOR_MAX_RETRIES = int(os.getenv("ENHANCED_COLLECTOR_MAX_RETRIES", "1"))
DEFAULT_ENHANCED_COLLECTOR_USE_FOR_MONITOR = env_bool("ENHANCED_COLLECTOR_USE_FOR_MONITOR", False)
DEFAULT_ENHANCED_COLLECTOR_USE_FOR_CATALOG = env_bool("ENHANCED_COLLECTOR_USE_FOR_CATALOG", True)
DEFAULT_SCRAPLING_ENABLED = env_bool("SCRAPLING_ENABLED", True)
DEFAULT_SCRAPLING_DEFAULT_MODE = os.getenv("SCRAPLING_DEFAULT_MODE", "standard").strip().lower() or "standard"
DEFAULT_SCRAPLING_USE_FOR_MONITOR = env_bool("SCRAPLING_USE_FOR_MONITOR", True)
DEFAULT_SCRAPLING_USE_FOR_CATALOG = env_bool("SCRAPLING_USE_FOR_CATALOG", True)
DEFAULT_SCRAPLING_TIMEOUT_STANDARD = int(os.getenv("SCRAPLING_TIMEOUT_STANDARD", "25"))
DEFAULT_SCRAPLING_TIMEOUT_DYNAMIC = int(os.getenv("SCRAPLING_TIMEOUT_DYNAMIC", "45"))
DEFAULT_SCRAPLING_TIMEOUT_STEALTH = int(os.getenv("SCRAPLING_TIMEOUT_STEALTH", "75"))
DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STANDARD = int(os.getenv("SCRAPLING_DOMAIN_COOLDOWN_STANDARD", "0"))
DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_DYNAMIC = int(os.getenv("SCRAPLING_DOMAIN_COOLDOWN_DYNAMIC", "60"))
DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STEALTH = int(os.getenv("SCRAPLING_DOMAIN_COOLDOWN_STEALTH", "60"))
DEFAULT_SCRAPLING_MAX_CONCURRENCY_STANDARD = int(os.getenv("SCRAPLING_MAX_CONCURRENCY_STANDARD", "3"))
DEFAULT_SCRAPLING_MAX_CONCURRENCY_DYNAMIC = int(os.getenv("SCRAPLING_MAX_CONCURRENCY_DYNAMIC", "2"))
DEFAULT_SCRAPLING_MAX_CONCURRENCY_STEALTH = int(os.getenv("SCRAPLING_MAX_CONCURRENCY_STEALTH", "1"))
DEFAULT_SCRAPLING_SESSION_REUSE = env_bool("SCRAPLING_SESSION_REUSE", True)
DEFAULT_SCRAPLING_ADAPTIVE_SELECTOR = env_bool("SCRAPLING_ADAPTIVE_SELECTOR", True)
DEFAULT_SCRAPLING_HEADLESS = env_bool("SCRAPLING_HEADLESS", True)
DOMAIN_SESSION_TTL_HOURS = int(os.getenv("DOMAIN_SESSION_TTL_HOURS", "24"))
DOMAIN_SESSION_UNLOCK_TIMEOUT_SECONDS = int(os.getenv("DOMAIN_SESSION_UNLOCK_TIMEOUT_SECONDS", "120"))
DOMAIN_SESSION_PROFILE_ROOT = Path(os.getenv("DOMAIN_SESSION_PROFILE_ROOT", str(DATA_DIR / "domain-sessions")))
DEFAULT_CATALOG_DISCOVERY_STRATEGY = os.getenv("CATALOG_DISCOVERY_STRATEGY", "local").strip().lower() or "local"
DEFAULT_CATALOG_SCRAPE_STRATEGY = os.getenv("CATALOG_SCRAPE_STRATEGY", "multi_engine").strip().lower() or "multi_engine"
DEFAULT_CATALOG_FETCH_STRATEGY = os.getenv("CATALOG_DEFAULT_FETCH_STRATEGY", "multi_engine").strip().lower() or "multi_engine"
DEFAULT_CATALOG_EXTRACTOR = os.getenv("CATALOG_DEFAULT_EXTRACTOR", "generic_pricing_table").strip().lower() or "generic_pricing_table"
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
PANEL_UPGRADE_ENABLED = env_bool("PANEL_UPGRADE_ENABLED", False)

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
        "与页面的连接已断开",
        "页面的连接已断开",
        "浏览器已断开连接",
        "连接已断开",
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
DEFAULT_TASK_SUBGROUP = "默认子分组"

SETTINGS_DEFAULTS = {
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
    "telegram_chat_ids": os.getenv("TELEGRAM_CHAT_IDS", "").strip() or os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    "monitor_debug_port": str(DEFAULT_MONITOR_PORT),
    "test_debug_port": str(DEFAULT_TEST_PORT),
    "catalog_debug_port": str(DEFAULT_CATALOG_PORT),
    "poll_interval_seconds": str(DEFAULT_POLL_INTERVAL),
    "request_timeout_seconds": str(DEFAULT_TIMEOUT_SECONDS),
    "firecrawl_enabled": settings_bool_text(DEFAULT_FIRECRAWL_ENABLED),
    "firecrawl_api_url": DEFAULT_FIRECRAWL_API_URL,
    "firecrawl_api_key": DEFAULT_FIRECRAWL_API_KEY,
    "firecrawl_timeout_seconds": str(DEFAULT_FIRECRAWL_TIMEOUT_SECONDS),
    "firecrawl_max_age_ms": str(DEFAULT_FIRECRAWL_MAX_AGE_MS),
    "firecrawl_store_in_cache": settings_bool_text(DEFAULT_FIRECRAWL_STORE_IN_CACHE),
    "firecrawl_proxy_mode": DEFAULT_FIRECRAWL_PROXY_MODE,
    "firecrawl_allow_auto_proxy": settings_bool_text(DEFAULT_FIRECRAWL_ALLOW_AUTO_PROXY),
    "firecrawl_allow_enhanced_proxy": settings_bool_text(DEFAULT_FIRECRAWL_ALLOW_ENHANCED_PROXY),
    "firecrawl_zero_data_retention": settings_bool_text(DEFAULT_FIRECRAWL_ZERO_DATA_RETENTION),
    "firecrawl_use_for_monitor": settings_bool_text(DEFAULT_FIRECRAWL_USE_FOR_MONITOR),
    "firecrawl_use_for_catalog": settings_bool_text(DEFAULT_FIRECRAWL_USE_FOR_CATALOG),
    "firecrawl_catalog_limit": str(DEFAULT_FIRECRAWL_CATALOG_LIMIT),
    "enhanced_collector_enabled": settings_bool_text(DEFAULT_ENHANCED_COLLECTOR_ENABLED),
    "enhanced_collector_api_url": DEFAULT_ENHANCED_COLLECTOR_API_URL,
    "enhanced_collector_timeout_seconds": str(DEFAULT_ENHANCED_COLLECTOR_TIMEOUT_SECONDS),
    "enhanced_collector_max_retries": str(DEFAULT_ENHANCED_COLLECTOR_MAX_RETRIES),
    "enhanced_collector_use_for_monitor": settings_bool_text(DEFAULT_ENHANCED_COLLECTOR_USE_FOR_MONITOR),
    "enhanced_collector_use_for_catalog": settings_bool_text(DEFAULT_ENHANCED_COLLECTOR_USE_FOR_CATALOG),
    "scrapling_enabled": settings_bool_text(DEFAULT_SCRAPLING_ENABLED),
    "scrapling_default_mode": DEFAULT_SCRAPLING_DEFAULT_MODE,
    "scrapling_use_for_monitor": settings_bool_text(DEFAULT_SCRAPLING_USE_FOR_MONITOR),
    "scrapling_use_for_catalog": settings_bool_text(DEFAULT_SCRAPLING_USE_FOR_CATALOG),
    "scrapling_timeout_standard": str(DEFAULT_SCRAPLING_TIMEOUT_STANDARD),
    "scrapling_timeout_dynamic": str(DEFAULT_SCRAPLING_TIMEOUT_DYNAMIC),
    "scrapling_timeout_stealth": str(DEFAULT_SCRAPLING_TIMEOUT_STEALTH),
    "scrapling_domain_cooldown_standard": str(DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STANDARD),
    "scrapling_domain_cooldown_dynamic": str(DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_DYNAMIC),
    "scrapling_domain_cooldown_stealth": str(DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STEALTH),
    "scrapling_max_concurrency_standard": str(DEFAULT_SCRAPLING_MAX_CONCURRENCY_STANDARD),
    "scrapling_max_concurrency_dynamic": str(DEFAULT_SCRAPLING_MAX_CONCURRENCY_DYNAMIC),
    "scrapling_max_concurrency_stealth": str(DEFAULT_SCRAPLING_MAX_CONCURRENCY_STEALTH),
    "scrapling_session_reuse": settings_bool_text(DEFAULT_SCRAPLING_SESSION_REUSE),
    "scrapling_adaptive_selector": settings_bool_text(DEFAULT_SCRAPLING_ADAPTIVE_SELECTOR),
    "scrapling_headless": settings_bool_text(DEFAULT_SCRAPLING_HEADLESS),
    "catalog_discovery_strategy": DEFAULT_CATALOG_DISCOVERY_STRATEGY,
    "catalog_scrape_strategy": DEFAULT_CATALOG_SCRAPE_STRATEGY,
    "catalog_default_fetch_strategy": DEFAULT_CATALOG_FETCH_STRATEGY,
    "catalog_default_extractor": DEFAULT_CATALOG_EXTRACTOR,
    "catalog_default_group": "默认分组",
    "catalog_include_sold_out": "true",
    "catalog_auto_create_tasks": "true",
    "catalog_dedupe_policy": "by_url",
    "catalog_max_discovered_urls": "50",
    "catalog_max_import_items": "50",
    "catalog_timeout_seconds": str(DEFAULT_TIMEOUT_SECONDS),
}

DEFAULT_RESTOCK_TEMPLATE = "【补货提醒】\n<b>{name}</b>\n状态：有货\n库存：{stock}\n关键词：{keyword}\n链接：{url}\n时间：{checked_at}"
DEFAULT_SOLDOUT_TEMPLATE = "【售罄提醒】\n<b>{name}</b>\n状态：已售罄\n最后库存：{stock}\n关键词：{keyword}\n链接：{url}\n时间：{checked_at}"

FETCH_STRATEGY_BROWSER = "browser"
FETCH_STRATEGY_STATIC_HTTP = "static_http"
FETCH_STRATEGY_GENERIC_PRICING_TABLE = "generic_pricing_table"
FETCH_STRATEGY_WHMCS = "whmcs"
FETCH_STRATEGY_FIRECRAWL = "firecrawl"
FETCH_STRATEGY_FIRECRAWL_THEN_STATIC = "firecrawl_then_static"
FETCH_STRATEGY_STATIC_THEN_FIRECRAWL = "static_then_firecrawl"
FETCH_STRATEGY_FIRECRAWL_THEN_BROWSER = "firecrawl_then_browser"
FETCH_STRATEGY_ADAPTIVE = "adaptive"
FETCH_STRATEGY_CURL_CFFI = "curl_cffi"
FETCH_STRATEGY_MULTI_ENGINE = "multi_engine"
FETCH_STRATEGY_SCRAPLING_STANDARD = "scrapling_standard"
FETCH_STRATEGY_SCRAPLING_DYNAMIC = "scrapling_dynamic"
FETCH_STRATEGY_SCRAPLING_STEALTH = "scrapling_stealth"
FETCH_STRATEGY_SCRAPLING_ADAPTIVE = "scrapling_adaptive"
FETCH_STRATEGY_HEADED_SESSION = "headed_session"
FETCH_STRATEGY_MANUAL = "manual"
FETCH_STRATEGY_WEBHOOK = "webhook"
COLLECTOR_DIRECT = "direct"
COLLECTOR_CURL_CFFI = "curl_cffi"
COLLECTOR_EXTERNAL_SOLVER = "external_solver"
COLLECTOR_MANUAL = "manual"
COLLECTOR_WEBHOOK = "webhook"
DEFAULT_TASK_FETCH_STRATEGY = FETCH_STRATEGY_MULTI_ENGINE
SUPPORTED_FETCH_STRATEGIES = {
    FETCH_STRATEGY_BROWSER,
    FETCH_STRATEGY_STATIC_HTTP,
    FETCH_STRATEGY_GENERIC_PRICING_TABLE,
    FETCH_STRATEGY_WHMCS,
    FETCH_STRATEGY_FIRECRAWL,
    FETCH_STRATEGY_FIRECRAWL_THEN_STATIC,
    FETCH_STRATEGY_STATIC_THEN_FIRECRAWL,
    FETCH_STRATEGY_FIRECRAWL_THEN_BROWSER,
    FETCH_STRATEGY_ADAPTIVE,
    FETCH_STRATEGY_CURL_CFFI,
    FETCH_STRATEGY_MULTI_ENGINE,
    FETCH_STRATEGY_SCRAPLING_STANDARD,
    FETCH_STRATEGY_SCRAPLING_DYNAMIC,
    FETCH_STRATEGY_SCRAPLING_STEALTH,
    FETCH_STRATEGY_SCRAPLING_ADAPTIVE,
    FETCH_STRATEGY_HEADED_SESSION,
    FETCH_STRATEGY_MANUAL,
    FETCH_STRATEGY_WEBHOOK,
}
STATIC_HTTP_FETCH_STRATEGIES = {
    FETCH_STRATEGY_STATIC_HTTP,
    FETCH_STRATEGY_GENERIC_PRICING_TABLE,
    FETCH_STRATEGY_WHMCS,
}
LOCAL_HTTP_FINGERPRINT_FETCH_STRATEGIES = {
    FETCH_STRATEGY_STATIC_HTTP,
    FETCH_STRATEGY_CURL_CFFI,
}
FIRECRAWL_FETCH_STRATEGIES = {
    FETCH_STRATEGY_FIRECRAWL,
    FETCH_STRATEGY_FIRECRAWL_THEN_STATIC,
    FETCH_STRATEGY_STATIC_THEN_FIRECRAWL,
    FETCH_STRATEGY_FIRECRAWL_THEN_BROWSER,
}
FIRECRAWL_COST_ERROR_KINDS = {"firecrawl_credit_required", "firecrawl_rate_limited"}
FIRECRAWL_COST_COOLDOWN_MINUTES = 360
DOMAIN_SESSION_STATUS_READY = "ready"
DOMAIN_SESSION_STATUS_MISSING = "missing"
DOMAIN_SESSION_STATUS_FAILED = "failed"
SCRAPLING_FETCH_STRATEGIES = {
    FETCH_STRATEGY_SCRAPLING_STANDARD,
    FETCH_STRATEGY_SCRAPLING_DYNAMIC,
    FETCH_STRATEGY_SCRAPLING_STEALTH,
    FETCH_STRATEGY_SCRAPLING_ADAPTIVE,
}
HEADED_SESSION_FETCH_STRATEGIES = {FETCH_STRATEGY_HEADED_SESSION}
LEGACY_FETCH_STRATEGY_MIGRATIONS = {
    FETCH_STRATEGY_BROWSER: FETCH_STRATEGY_SCRAPLING_DYNAMIC,
    FETCH_STRATEGY_STATIC_HTTP: FETCH_STRATEGY_CURL_CFFI,
    FETCH_STRATEGY_GENERIC_PRICING_TABLE: FETCH_STRATEGY_MULTI_ENGINE,
    FETCH_STRATEGY_WHMCS: FETCH_STRATEGY_MULTI_ENGINE,
    FETCH_STRATEGY_ADAPTIVE: FETCH_STRATEGY_MULTI_ENGINE,
    FETCH_STRATEGY_FIRECRAWL: FETCH_STRATEGY_SCRAPLING_STEALTH,
    FETCH_STRATEGY_FIRECRAWL_THEN_STATIC: FETCH_STRATEGY_SCRAPLING_STEALTH,
    FETCH_STRATEGY_STATIC_THEN_FIRECRAWL: FETCH_STRATEGY_SCRAPLING_STANDARD,
    FETCH_STRATEGY_FIRECRAWL_THEN_BROWSER: FETCH_STRATEGY_SCRAPLING_STEALTH,
}
EXTERNAL_INPUT_FETCH_STRATEGIES = {FETCH_STRATEGY_MANUAL, FETCH_STRATEGY_WEBHOOK}
EXTERNAL_INPUT_PENDING_ERROR_KINDS = {"manual_pending", "webhook_pending"}
SUPPORTED_COLLECTOR_STRATEGIES = {
    COLLECTOR_DIRECT,
    COLLECTOR_CURL_CFFI,
    COLLECTOR_EXTERNAL_SOLVER,
    COLLECTOR_MANUAL,
    COLLECTOR_WEBHOOK,
}
CATALOG_DISCOVERY_LOCAL = "local"
CATALOG_DISCOVERY_FIRECRAWL_MAP = "firecrawl_map"
CATALOG_DISCOVERY_HYBRID = "hybrid"
CATALOG_DISCOVERY_STRATEGIES = {
    CATALOG_DISCOVERY_LOCAL,
    CATALOG_DISCOVERY_FIRECRAWL_MAP,
    CATALOG_DISCOVERY_HYBRID,
}
CATALOG_HIDDEN_PROBE_AUTO = "auto"
CATALOG_HIDDEN_PROBE_WHMCS = "whmcs"
CATALOG_HIDDEN_PROBE_HOSTBILL = "hostbill"
CATALOG_HIDDEN_PROBE_PLATFORMS = {
    CATALOG_HIDDEN_PROBE_AUTO,
    CATALOG_HIDDEN_PROBE_WHMCS,
    CATALOG_HIDDEN_PROBE_HOSTBILL,
}
CATALOG_SCRAPE_STATIC_HTTP = FETCH_STRATEGY_STATIC_HTTP
CATALOG_SCRAPE_BROWSER = FETCH_STRATEGY_BROWSER
CATALOG_SCRAPE_FIRECRAWL = FETCH_STRATEGY_FIRECRAWL
CATALOG_SCRAPE_ADAPTIVE = FETCH_STRATEGY_ADAPTIVE
CATALOG_SCRAPE_STRATEGIES = {
    CATALOG_SCRAPE_STATIC_HTTP,
    CATALOG_SCRAPE_BROWSER,
    CATALOG_SCRAPE_FIRECRAWL,
    CATALOG_SCRAPE_ADAPTIVE,
    FETCH_STRATEGY_CURL_CFFI,
    FETCH_STRATEGY_MULTI_ENGINE,
    FETCH_STRATEGY_SCRAPLING_STANDARD,
    FETCH_STRATEGY_SCRAPLING_DYNAMIC,
    FETCH_STRATEGY_SCRAPLING_STEALTH,
    FETCH_STRATEGY_SCRAPLING_ADAPTIVE,
}
CATALOG_EXTRACTOR_GENERIC = FETCH_STRATEGY_GENERIC_PRICING_TABLE
CATALOG_EXTRACTOR_WHMCS = FETCH_STRATEGY_WHMCS
CATALOG_EXTRACTOR_FIRECRAWL_PRODUCT_HINT = "firecrawl_product_hint"
CATALOG_EXTRACTOR_FALLBACK = "fallback_keyword_parser"
CATALOG_EXTRACTORS = {
    CATALOG_EXTRACTOR_GENERIC,
    CATALOG_EXTRACTOR_WHMCS,
    CATALOG_EXTRACTOR_FIRECRAWL_PRODUCT_HINT,
    CATALOG_EXTRACTOR_FALLBACK,
}
CATALOG_DEDUPE_POLICIES = {"by_url", "by_title_url", "by_pid"}
SCRAPLING_MODES = {"standard", "dynamic", "stealth"}
CATALOG_TARGET_KEYWORD_MODES = {"exact", "contains", "fuzzy"}
CATALOG_URL_KEEP_MARKERS = (
    "store",
    "cart",
    "product",
    "pricing",
    "vps",
    "cloud",
    "server",
    "hosting",
    "cart.php",
    "gid=",
    "pid=",
    "/configureproduct",
    "/dedicated",
)
CATALOG_URL_DROP_MARKERS = (
    "login",
    "register",
    "knowledgebase",
    "announcements",
    "terms",
    "privacy",
    "contact",
    "clientarea",
    "checkout",
    "viewcart",
    "submitticket",
    "affiliates",
)
FIRECRAWL_PROXY_MODES = {"basic", "enhanced", "auto"}
SENSITIVE_SETTINGS_KEYS = {"firecrawl_api_key"}
SCRAPLING_FETCH_STRATEGY_MIGRATION_KEY = "scrapling_fetch_strategy_migration_v1"
STATIC_HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/137.0 Safari/537.36"
)
PROTECTED_SOURCE_COOLDOWN_MINUTES = (1, 3, 10)
WEBHOOK_TOKEN_BYTES = 32
WEBHOOK_TOKEN_HINT_PREFIX = 6
WEBHOOK_TOKEN_HINT_SUFFIX = 4
SENSITIVE_SOURCE_CONFIG_KEYS = {
    "ingest_token",
    "webhook_token",
    "webhook_secret",
    "token",
    "secret",
    "hmac_secret",
    "cookie",
    "cookies",
    "headers",
    "authorization",
}
STOCK_RULE_TYPES = {
    "auto_card",
    "css_selector",
    "xpath",
    "regex",
    "text_near_keyword",
    "json_path",
}

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
        r"\b(?:order\s*now|configure|add\s*to\s*cart|buy\s*now|purchase|"
        r"pre[-\s]?order|back[-\s]?order|back\s*in\s*stock|available\s*now)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:立即(?:订购|訂購|购买|購買|下单|下單)|加入(?:购物车|購物車)|现在购买|現在購買|可下单|可下單|"
        r"可购买|可購買|选取此套餐|選取此套餐|提交订单|提交訂單|订购|訂購|预售|預售|预订|預訂|"
        r"预约|預約|现货|現貨|有货|有貨)",
    ),
    re.compile(r"(?:cart\.php\?a=(?:add|confproduct)|/cart/add|/order)", re.IGNORECASE),
]
WEAK_ORDERABLE_PATTERNS = [
    re.compile(r"\b(?:continue|proceed|next\s*step|checkout|select(?:ed)?|choose)\b", re.IGNORECASE),
    re.compile(r"(?:选择套餐|選擇套餐|已选|已選|继续|繼續|下一步|结账|結帳|前往付款)", re.IGNORECASE),
]
GENERIC_ORDERABLE_PATTERNS = [
    re.compile(r"\b(?:order\s*now|buy\s*now|configure|available|add\s*to\s*cart|purchase)\b", re.IGNORECASE),
    re.compile(r"(?:下单|下單|购买|購買|加入購物車|加入购物车|可下单|可下單|可购买|可購買)", re.IGNORECASE),
]
GENERIC_SOLD_OUT_PATTERNS = [
    re.compile(r"\b(?:out\s*of\s*stock|sold\s*out|unavailable)\b", re.IGNORECASE),
    re.compile(r"(?:缺货|缺貨|售罄|无货|無貨)", re.IGNORECASE),
]
WHMCS_ORDERABLE_PATTERNS = [
    re.compile(
        r"(?:cart\.php\?[^'\"<>]*(?:a=(?:add|confproduct)|pid=\d+)|configureproduct|"
        r"\b(?:order\s*now|configure|add\s*to\s*cart|purchase)\b)",
        re.IGNORECASE,
    ),
]
PRODUCT_CONTAINER_TAGS = (
    "tr",
    "plan-card",
    "product-card",
    "package-card",
    "pricing-card",
    "article",
    "section",
    "li",
    "form",
    "div",
    "table",
)


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


def normalize_task_subgroup(value: Any) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    parts = [part.strip() for part in re.split(r"\s*/\s*", raw) if part.strip()]
    subgroup_name = " / ".join(parts)
    return (subgroup_name or DEFAULT_TASK_SUBGROUP)[:120]


def split_task_subgroup_path(value: Any) -> list[str]:
    normalized = normalize_task_subgroup(value)
    if normalized == DEFAULT_TASK_SUBGROUP:
        return []
    return [part.strip() for part in normalized.split(" / ") if part.strip()]


def join_task_subgroup_path(parts: list[str]) -> str:
    cleaned = [normalize_task_subgroup(part) for part in parts if normalize_task_subgroup(part) != DEFAULT_TASK_SUBGROUP]
    return normalize_task_subgroup(" / ".join(cleaned))


def child_task_subgroup_path(parent_path: Any, child_name: Any) -> str:
    parent_parts = split_task_subgroup_path(parent_path)
    child_parts = split_task_subgroup_path(child_name)
    return join_task_subgroup_path(parent_parts + child_parts)


def mapping_value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, sqlite3.Row):
        return source[key] if key in source.keys() else default
    if isinstance(source, dict):
        return source.get(key, default)
    try:
        return source[key]
    except Exception:
        return default


def normalize_fetch_strategy(value: Any) -> str:
    strategy = str(value or "").strip().lower().replace("-", "_")
    if strategy in SUPPORTED_FETCH_STRATEGIES:
        return strategy
    return DEFAULT_TASK_FETCH_STRATEGY


def migrate_legacy_fetch_strategy(value: Any) -> str:
    strategy = normalize_fetch_strategy(value)
    return LEGACY_FETCH_STRATEGY_MIGRATIONS.get(strategy, strategy)


def is_supported_fetch_strategy(value: Any) -> bool:
    strategy = str(value or "").strip().lower().replace("-", "_")
    return not strategy or strategy in SUPPORTED_FETCH_STRATEGIES


def task_fetch_strategy(task: Any) -> str:
    return normalize_fetch_strategy(mapping_value(task, "fetch_strategy", DEFAULT_TASK_FETCH_STRATEGY))


def normalize_catalog_choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in allowed else default


def normalize_scrapling_mode(value: Any) -> str:
    mode = str(value or DEFAULT_SCRAPLING_DEFAULT_MODE).strip().lower().replace("-", "_")
    return mode if mode in SCRAPLING_MODES else "standard"


def bounded_setting_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_scrapling_settings(raw: dict[str, str]) -> dict[str, Any]:
    return {
        "scrapling_enabled": parse_setting_bool(raw.get("scrapling_enabled"), DEFAULT_SCRAPLING_ENABLED),
        "scrapling_default_mode": normalize_scrapling_mode(raw.get("scrapling_default_mode")),
        "scrapling_use_for_monitor": parse_setting_bool(raw.get("scrapling_use_for_monitor"), DEFAULT_SCRAPLING_USE_FOR_MONITOR),
        "scrapling_use_for_catalog": parse_setting_bool(raw.get("scrapling_use_for_catalog"), DEFAULT_SCRAPLING_USE_FOR_CATALOG),
        "scrapling_timeout_standard": bounded_setting_int(raw.get("scrapling_timeout_standard"), DEFAULT_SCRAPLING_TIMEOUT_STANDARD, 5, 180),
        "scrapling_timeout_dynamic": bounded_setting_int(raw.get("scrapling_timeout_dynamic"), DEFAULT_SCRAPLING_TIMEOUT_DYNAMIC, 10, 240),
        "scrapling_timeout_stealth": bounded_setting_int(raw.get("scrapling_timeout_stealth"), DEFAULT_SCRAPLING_TIMEOUT_STEALTH, 15, 300),
        "scrapling_domain_cooldown_standard": bounded_setting_int(raw.get("scrapling_domain_cooldown_standard"), DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STANDARD, 0, 3600),
        "scrapling_domain_cooldown_dynamic": bounded_setting_int(raw.get("scrapling_domain_cooldown_dynamic"), DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_DYNAMIC, 0, 7200),
        "scrapling_domain_cooldown_stealth": bounded_setting_int(raw.get("scrapling_domain_cooldown_stealth"), DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STEALTH, 0, 14400),
        "scrapling_max_concurrency_standard": bounded_setting_int(raw.get("scrapling_max_concurrency_standard"), DEFAULT_SCRAPLING_MAX_CONCURRENCY_STANDARD, 1, 10),
        "scrapling_max_concurrency_dynamic": bounded_setting_int(raw.get("scrapling_max_concurrency_dynamic"), DEFAULT_SCRAPLING_MAX_CONCURRENCY_DYNAMIC, 1, 5),
        "scrapling_max_concurrency_stealth": bounded_setting_int(raw.get("scrapling_max_concurrency_stealth"), DEFAULT_SCRAPLING_MAX_CONCURRENCY_STEALTH, 1, 3),
        "scrapling_session_reuse": parse_setting_bool(raw.get("scrapling_session_reuse"), DEFAULT_SCRAPLING_SESSION_REUSE),
        "scrapling_adaptive_selector": parse_setting_bool(raw.get("scrapling_adaptive_selector"), DEFAULT_SCRAPLING_ADAPTIVE_SELECTOR),
        "scrapling_headless": parse_setting_bool(raw.get("scrapling_headless"), DEFAULT_SCRAPLING_HEADLESS),
    }


def scrapling_runtime_status() -> dict[str, str | bool]:
    if importlib.util.find_spec("scrapling") is None:
        return {
            "available": False,
            "status": "unavailable",
            "detail": "Scrapling 未安装或当前运行环境无法导入；安装依赖后即可启用。",
        }
    missing: list[str] = []
    for module_name in ("scrapling.fetchers", "curl_cffi", "playwright", "patchright"):
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(module_name)
    if missing:
        return {
            "available": False,
            "status": "missing_fetchers",
            "detail": f"Scrapling 主包已安装，但 fetcher 依赖缺失：{', '.join(missing)}。请重新安装 requirements.txt。",
        }
    browser_binary = find_browser_binary()
    if not browser_binary:
        return {
            "available": False,
            "status": "missing_browser",
            "detail": "Scrapling 依赖已安装，但未找到可用 Chromium/Chrome。请重新执行安装或升级脚本安装浏览器依赖。",
        }
    headed_ready = bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
    xvfb_ready = shutil.which("Xvfb") is not None or shutil.which("xvfb-run") is not None
    return {
        "available": True,
        "status": "available",
        "detail": f"Scrapling 采集引擎可用，浏览器：{browser_binary}",
        "browser_binary": browser_binary,
        "headed_ready": headed_ready,
        "xvfb_ready": xvfb_ready,
        "headed_detail": "可直接启动有头浏览器。" if headed_ready else ("可通过 Xvfb 启动有头浏览器。" if xvfb_ready else "当前环境没有 DISPLAY/Xvfb，有头浏览器会启动失败。"),
    }


def cleanup_scrapling_xvfb() -> None:
    global _SCRAPLING_XVFB_PROCESS
    process = _SCRAPLING_XVFB_PROCESS
    if process is not None and process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    _SCRAPLING_XVFB_PROCESS = None


atexit.register(cleanup_scrapling_xvfb)


def ensure_scrapling_display_for_headed() -> str:
    global _SCRAPLING_XVFB_PROCESS, _SCRAPLING_XVFB_DISPLAY
    existing_display = os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")
    if existing_display:
        return existing_display
    xvfb_binary = shutil.which("Xvfb")
    if not xvfb_binary:
        return ""
    with _SCRAPLING_XVFB_LOCK:
        if _SCRAPLING_XVFB_PROCESS is not None and _SCRAPLING_XVFB_PROCESS.poll() is None and _SCRAPLING_XVFB_DISPLAY:
            os.environ["DISPLAY"] = _SCRAPLING_XVFB_DISPLAY
            return _SCRAPLING_XVFB_DISPLAY
        requested_display = os.getenv("SCRAPLING_XVFB_DISPLAY", ":99").strip() or ":99"
        candidate_displays = list(dict.fromkeys([requested_display, ":98", ":97", ":96"]))
        for display in candidate_displays:
            try:
                process = subprocess.Popen(
                    [xvfb_binary, display, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                continue
            time.sleep(0.3)
            if process.poll() is None:
                _SCRAPLING_XVFB_PROCESS = process
                _SCRAPLING_XVFB_DISPLAY = display
                os.environ["DISPLAY"] = display
                return display
        return ""


def catalog_option_int(value: Any, default: int, minimum: int = 1, maximum: int = 250) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def split_catalog_paths(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\n,]+", str(value or ""))
    return [str(item).strip().lower() for item in raw_items if str(item).strip()]


def normalize_catalog_options(
    payload: dict[str, Any] | None,
    settings_payload: dict[str, Any],
    group_name: str,
    auto_promote: bool,
) -> dict[str, Any]:
    payload = payload or {}
    return {
        "catalog_discovery_strategy": normalize_catalog_choice(
            payload.get("catalog_discovery_strategy") or payload.get("discovery_strategy") or settings_payload.get("catalog_discovery_strategy"),
            CATALOG_DISCOVERY_STRATEGIES,
            CATALOG_DISCOVERY_LOCAL,
        ),
        "catalog_scrape_strategy": normalize_catalog_choice(
            payload.get("catalog_scrape_strategy") or payload.get("scrape_strategy") or settings_payload.get("catalog_scrape_strategy"),
            CATALOG_SCRAPE_STRATEGIES,
            FETCH_STRATEGY_SCRAPLING_ADAPTIVE,
        ),
        "default_fetch_strategy": normalize_fetch_strategy(
            payload.get("default_fetch_strategy") or settings_payload.get("catalog_default_fetch_strategy") or DEFAULT_TASK_FETCH_STRATEGY
        ),
        "default_extractor": normalize_catalog_choice(
            payload.get("default_extractor") or settings_payload.get("catalog_default_extractor"),
            CATALOG_EXTRACTORS,
            CATALOG_EXTRACTOR_GENERIC,
        ),
        "default_group": normalize_task_group(group_name or payload.get("default_group") or settings_payload.get("catalog_default_group")),
        "target_keyword_mode": normalize_catalog_choice(payload.get("target_keyword_mode"), CATALOG_TARGET_KEYWORD_MODES, "contains"),
        "include_sold_out": parse_setting_bool(payload.get("include_sold_out"), bool(settings_payload.get("catalog_include_sold_out", True))),
        "auto_create_tasks": bool(auto_promote),
        "dedupe_policy": normalize_catalog_choice(
            payload.get("dedupe_policy") or settings_payload.get("catalog_dedupe_policy"),
            CATALOG_DEDUPE_POLICIES,
            "by_url",
        ),
        "max_discovered_urls": catalog_option_int(
            payload.get("max_discovered_urls") or settings_payload.get("catalog_max_discovered_urls"),
            int(settings_payload.get("catalog_max_discovered_urls") or 50),
            1,
            250,
        ),
        "max_import_items": catalog_option_int(
            payload.get("max_import_items") or settings_payload.get("catalog_max_import_items"),
            int(settings_payload.get("catalog_max_import_items") or 50),
            1,
            250,
        ),
        "timeout_seconds": catalog_option_int(
            payload.get("timeout_seconds") or settings_payload.get("catalog_timeout_seconds") or settings_payload.get("request_timeout_seconds"),
            int(settings_payload.get("request_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
            10,
            180,
        ),
        "search_keyword": str(payload.get("search_keyword") or payload.get("catalog_search_keyword") or "").strip(),
        "target_keyword": str(payload.get("target_keyword") or "").strip(),
        "include_paths": split_catalog_paths(payload.get("include_paths")),
        "exclude_paths": split_catalog_paths(payload.get("exclude_paths")),
        "allow_subdomains": parse_setting_bool(payload.get("allow_subdomains"), False),
        "ignore_query_parameters": parse_setting_bool(payload.get("ignore_query_parameters"), False),
        "enable_hidden_product_probe": parse_setting_bool(
            payload.get("enable_hidden_product_probe") or payload.get("hidden_product_probe"),
            False,
        ),
        "hidden_probe_platform": normalize_catalog_choice(
            payload.get("hidden_probe_platform") or payload.get("hidden_product_platform"),
            CATALOG_HIDDEN_PROBE_PLATFORMS,
            CATALOG_HIDDEN_PROBE_AUTO,
        ),
        "hidden_probe_start": catalog_option_int(payload.get("hidden_probe_start"), 1, 0, 5000),
        "hidden_probe_end": catalog_option_int(payload.get("hidden_probe_end"), 60, 0, 5000),
        "hidden_probe_limit": catalog_option_int(payload.get("hidden_probe_limit"), 40, 1, 250),
    }


def scrub_source_config(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if key_text.strip().lower() in SENSITIVE_SOURCE_CONFIG_KEYS:
            continue
        cleaned[key_text] = item
    return cleaned


def normalize_source_config_text(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(scrub_source_config(value), ensure_ascii=False, sort_keys=True)
    text = str(value or "").strip()
    if not text:
        return "{}"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return "{}"
    if not isinstance(parsed, dict):
        return "{}"
    return json.dumps(scrub_source_config(parsed), ensure_ascii=False, sort_keys=True)


def parse_source_config(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return scrub_source_config(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return scrub_source_config(parsed) if isinstance(parsed, dict) else {}


def raw_source_config(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def catalog_item_metadata(raw_payload: Any) -> dict[str, Any]:
    try:
        data = json.loads(str(raw_payload or "{}"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def task_blocked_count(task: Any) -> int:
    try:
        return max(0, int(mapping_value(task, "blocked_count", 0) or 0))
    except (TypeError, ValueError):
        return 0


def protected_source_cooldown_minutes(blocked_count: int) -> int:
    if blocked_count <= 1:
        return PROTECTED_SOURCE_COOLDOWN_MINUTES[0]
    if blocked_count == 2:
        return PROTECTED_SOURCE_COOLDOWN_MINUTES[1]
    return PROTECTED_SOURCE_COOLDOWN_MINUTES[2]


def protected_source_cooldown_until(blocked_count: int, now: datetime | None = None) -> str:
    now = now or now_utc()
    cooldown_at = now + timedelta(minutes=protected_source_cooldown_minutes(blocked_count))
    return cooldown_at.isoformat(timespec="seconds")


def task_cooldown_until(task: Any) -> datetime | None:
    return parse_iso_datetime(str(mapping_value(task, "cooldown_until", "") or ""))


def is_task_in_protected_cooldown(task: Any, now: datetime | None = None) -> bool:
    cooldown_at = task_cooldown_until(task)
    if cooldown_at is None:
        return False
    now = now or now_utc()
    return cooldown_at > now


def fetch_domain_for_url(url: Any) -> str:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return ""
    return (parsed.hostname or "").lower()


def normalize_domain_session_domain(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        return fetch_domain_for_url(raw)
    return raw.split("/", 1)[0].split(":", 1)[0].lower()


def safe_domain_profile_name(domain: str) -> str:
    safe = re.sub(r"[^a-z0-9.-]+", "-", domain.lower()).strip(".-")
    return safe or "unknown-domain"


def domain_session_profile_path(domain: str) -> Path:
    return DOMAIN_SESSION_PROFILE_ROOT / safe_domain_profile_name(domain)


def domain_session_warmup_url(url: Any) -> str:
    try:
        parsed = urlparse(str(url or ""))
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/"


def normalize_cookie_payload(cookies: Any) -> list[dict[str, Any]]:
    if not isinstance(cookies, list):
        return []
    normalized: list[dict[str, Any]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        if not name:
            continue
        normalized.append(
            {
                "name": name,
                "value": value,
                "domain": str(cookie.get("domain") or ""),
                "path": str(cookie.get("path") or "/") or "/",
                "expires": cookie.get("expires"),
                "httpOnly": bool(cookie.get("httpOnly", False)),
                "secure": bool(cookie.get("secure", False)),
                "sameSite": str(cookie.get("sameSite") or ""),
            }
        )
    return normalized


def parse_cookie_header(cookie_header: Any, domain: str = "") -> list[dict[str, Any]]:
    raw = str(cookie_header or "").strip()
    if not raw:
        return []
    parsed: list[dict[str, Any]] = []
    for part in raw.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        parsed.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "",
            }
        )
    return normalize_cookie_payload(parsed)


def parse_domain_session_cookies(value: Any) -> list[dict[str, Any]]:
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return normalize_cookie_payload(payload)


def domain_session_is_ready(session_payload: dict[str, Any] | None, now: datetime | None = None) -> bool:
    if not session_payload or session_payload.get("status") != DOMAIN_SESSION_STATUS_READY:
        return False
    if not session_payload.get("has_cookies"):
        return False
    expires_at = parse_iso_datetime(str(session_payload.get("expires_at") or ""))
    if not expires_at:
        return False
    return expires_at > (now or now_utc())


def safe_domain_session_payload(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "domain": "",
            "status": DOMAIN_SESSION_STATUS_MISSING,
            "has_cookies": False,
            "last_unlocked_at": "",
            "expires_at": "",
            "last_error": "",
            "failure_count": 0,
            "updated_at": "",
        }
    cookies = parse_domain_session_cookies(mapping_value(row, "cookies_json", "[]"))
    return {
        "domain": normalize_domain_session_domain(mapping_value(row, "domain", "")),
        "status": str(mapping_value(row, "status", DOMAIN_SESSION_STATUS_MISSING) or DOMAIN_SESSION_STATUS_MISSING),
        "has_cookies": bool(cookies),
        "source_url": str(mapping_value(row, "source_url", "") or ""),
        "last_unlocked_at": str(mapping_value(row, "last_unlocked_at", "") or ""),
        "expires_at": str(mapping_value(row, "expires_at", "") or ""),
        "last_error": sanitize_telegram_error(str(mapping_value(row, "last_error", "") or ""))[:400],
        "failure_count": int(mapping_value(row, "failure_count", 0) or 0),
        "updated_at": str(mapping_value(row, "updated_at", "") or ""),
    }


def missing_domain_session_payload(domain: str) -> dict[str, Any]:
    payload = safe_domain_session_payload(None)
    payload["domain"] = normalize_domain_session_domain(domain)
    return payload


def get_domain_session(domain_or_url: Any, safe: bool = False) -> dict[str, Any] | None:
    domain = normalize_domain_session_domain(domain_or_url)
    if not domain:
        return missing_domain_session_payload("") if safe else None
    try:
        with open_connection() as connection:
            row = connection.execute(
                "SELECT * FROM domain_sessions WHERE domain = ?",
                (domain,),
            ).fetchone()
    except sqlite3.OperationalError:
        row = None
    if safe:
        return safe_domain_session_payload(row) if row else missing_domain_session_payload(domain)
    return dict(row) if row else None


def get_ready_domain_session_for_url(url: Any) -> dict[str, Any] | None:
    session_payload = get_domain_session(fetch_domain_for_url(url), safe=False)
    safe_payload = safe_domain_session_payload(session_payload)
    if not domain_session_is_ready(safe_payload):
        return None
    return session_payload


def domain_session_cookie_dict(session_payload: dict[str, Any] | None) -> dict[str, str]:
    cookies = parse_domain_session_cookies(mapping_value(session_payload or {}, "cookies_json", "[]"))
    return {cookie["name"]: cookie["value"] for cookie in cookies if cookie.get("name")}


def build_candidate_domain_session_payload(
    domain: str,
    user_agent: str,
    cookies: list[dict[str, Any]],
    ttl_hours: int = DOMAIN_SESSION_TTL_HOURS,
) -> dict[str, Any]:
    return {
        "domain": normalize_domain_session_domain(domain),
        "status": DOMAIN_SESSION_STATUS_READY,
        "user_agent": str(user_agent or "").strip(),
        "cookies_json": json.dumps(normalize_cookie_payload(cookies), ensure_ascii=False),
        "expires_at": (now_utc() + timedelta(hours=max(1, int(ttl_hours or DOMAIN_SESSION_TTL_HOURS)))).isoformat(timespec="seconds"),
    }


def normalize_domain_session_import_payload(payload: dict[str, Any], fallback_domain: str = "") -> tuple[str, str, list[dict[str, Any]], int]:
    domain = normalize_domain_session_domain(payload.get("domain") or fallback_domain)
    if not domain:
        raise ValueError("无法识别要导入会话的域名。")

    user_agent = str(payload.get("user_agent") or payload.get("userAgent") or "").strip()
    if not user_agent:
        raise ValueError("请填写当前浏览器的 User-Agent。")

    cookies_payload: list[dict[str, Any]]
    if isinstance(payload.get("cookies"), list):
        cookies_payload = normalize_cookie_payload(payload.get("cookies"))
    elif isinstance(payload.get("cookies_json"), str):
        cookies_payload = parse_domain_session_cookies(payload.get("cookies_json"))
    else:
        cookies_payload = parse_cookie_header(payload.get("cookie_header") or payload.get("cookieHeader"), domain)

    if not cookies_payload:
        raise ValueError("请粘贴至少一个 Cookie。")

    ttl_hours = bounded_setting_int(payload.get("ttl_hours") or payload.get("ttlHours"), DOMAIN_SESSION_TTL_HOURS, 1, 24 * 30)
    return domain, user_agent, cookies_payload, ttl_hours


def upsert_domain_session(
    domain: str,
    *,
    status: str,
    user_agent: str = "",
    cookies: list[dict[str, Any]] | None = None,
    profile_path: str = "",
    source_url: str = "",
    last_error: str = "",
    ttl_hours: int = DOMAIN_SESSION_TTL_HOURS,
) -> dict[str, Any]:
    domain = normalize_domain_session_domain(domain)
    if not domain:
        raise ValueError("域名不能为空。")
    timestamp = now_iso()
    expires_at = ""
    last_unlocked_at = ""
    cookies_payload = normalize_cookie_payload(cookies or [])
    if status == DOMAIN_SESSION_STATUS_READY:
        last_unlocked_at = timestamp
        expires_at = (now_utc() + timedelta(hours=max(1, ttl_hours))).isoformat(timespec="seconds")
    with open_connection() as connection:
        current = connection.execute(
            "SELECT failure_count FROM domain_sessions WHERE domain = ?",
            (domain,),
        ).fetchone()
        failure_count = int(current["failure_count"] or 0) if current else 0
        if status == DOMAIN_SESSION_STATUS_READY:
            failure_count = 0
        elif status == DOMAIN_SESSION_STATUS_FAILED:
            failure_count += 1
        connection.execute(
            """
            INSERT INTO domain_sessions (
                domain, status, user_agent, cookies_json, profile_path, source_url,
                last_unlocked_at, expires_at, last_error, failure_count, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                status = excluded.status,
                user_agent = excluded.user_agent,
                cookies_json = excluded.cookies_json,
                profile_path = excluded.profile_path,
                source_url = excluded.source_url,
                last_unlocked_at = CASE WHEN excluded.last_unlocked_at != '' THEN excluded.last_unlocked_at ELSE domain_sessions.last_unlocked_at END,
                expires_at = excluded.expires_at,
                last_error = excluded.last_error,
                failure_count = excluded.failure_count,
                updated_at = excluded.updated_at
            """,
            (
                domain,
                status,
                user_agent,
                json.dumps(cookies_payload, ensure_ascii=False),
                profile_path,
                source_url,
                last_unlocked_at,
                expires_at,
                last_error[:1000],
                failure_count,
                timestamp,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM domain_sessions WHERE domain = ?", (domain,)).fetchone()
    return safe_domain_session_payload(row)


PRODUCT_CODE_CANDIDATE_RE = re.compile(r"\b[a-z0-9]{2,}(?:[._-][a-z0-9]{2,}){2,}\b", re.IGNORECASE)
PRODUCT_SIZE_TOKENS = {
    "nano",
    "micro",
    "tiny",
    "wee",
    "mini",
    "starter",
    "small",
    "medium",
    "large",
    "basic",
    "standard",
    "premium",
}


def product_query_slug_from_keyword(value: Any) -> str:
    text = str(value or "")
    for match in PRODUCT_CODE_CANDIDATE_RE.finditer(text):
        candidate = match.group(0).strip("._-").lower().replace("_", ".").replace("-", ".")
        parts = [part for part in candidate.split(".") if part]
        if len(parts) >= 3 and any(part in PRODUCT_SIZE_TOKENS for part in parts):
            return ".".join(parts)
    return ""


def whmcs_add_url_from_pid(url: str, pid: int) -> str:
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return url
    return parsed._replace(path="/cart.php", query=urlencode({"a": "add", "pid": int(pid)}), fragment="").geturl()


def hostbill_product_url_from_id(url: str, product_id: int) -> str:
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return url
    return parsed._replace(path="/cart/", query=urlencode({"action": "add", "id": int(product_id)}), fragment="").geturl()


def hostbill_category_url_from_id(url: str, category_id: int) -> str:
    parsed = urlparse(str(url or ""))
    if not parsed.scheme or not parsed.netloc:
        return url
    return parsed._replace(path=parsed.path or "/", query=urlencode({"cmd": "cart", "cat_id": int(category_id)}), fragment="").geturl()


def hidden_probe_ids(options: dict[str, Any]) -> list[int]:
    start = catalog_option_int(options.get("hidden_probe_start"), 1, 0, 5000)
    end = catalog_option_int(options.get("hidden_probe_end"), 60, 0, 5000)
    limit = catalog_option_int(options.get("hidden_probe_limit"), 40, 1, 250)
    if end < start:
        start, end = end, start
    return list(range(start, min(end, start + limit - 1) + 1))


def hidden_catalog_probe_candidates(source_url: str, options: dict[str, Any]) -> list[dict[str, str]]:
    if not parse_setting_bool(options.get("enable_hidden_product_probe"), False):
        return []
    platform = normalize_catalog_choice(
        options.get("hidden_probe_platform"),
        CATALOG_HIDDEN_PROBE_PLATFORMS,
        CATALOG_HIDDEN_PROBE_AUTO,
    )
    candidates: list[dict[str, str]] = []
    for probe_id in hidden_probe_ids(options):
        if probe_id <= 0:
            continue
        if platform in {CATALOG_HIDDEN_PROBE_AUTO, CATALOG_HIDDEN_PROBE_WHMCS}:
            candidates.append({"url": whmcs_add_url_from_pid(source_url, probe_id), "source": "whmcs_pid_probe"})
        if platform in {CATALOG_HIDDEN_PROBE_AUTO, CATALOG_HIDDEN_PROBE_HOSTBILL}:
            candidates.append({"url": hostbill_product_url_from_id(source_url, probe_id), "source": "hostbill_product_probe"})
            candidates.append({"url": hostbill_category_url_from_id(source_url, probe_id), "source": "hostbill_category_probe"})
    return candidates


def monitor_url_for_fetch(task: Any) -> str:
    url = str(mapping_value(task, "monitor_url", "") or "").strip()
    source_config = task_source_config(task)
    if parse_setting_bool(source_config.get("enable_whmcs_pid_probe"), False):
        pid = parse_int_value(source_config.get("pid") or source_config.get("product_id") or source_config.get("productId"))
        if pid is not None:
            return whmcs_add_url_from_pid(url, pid)
    if not parse_setting_bool(source_config.get("enable_product_query"), False):
        return url
    if parse_setting_bool(source_config.get("disable_product_query"), False) or parse_setting_bool(
        source_config.get("disable_auto_product_query"),
        False,
    ):
        return url
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if not parsed.scheme or not parsed.netloc:
        return url

    query = parse_qs(parsed.query, keep_blank_values=True)
    query_keys = {key.lower() for key in query}
    path = (parsed.path or "").lower()
    if (
        path.endswith("cart.php")
        and "product" not in query_keys
        and {"region", "network", "generation"}.issubset(query_keys)
    ):
        slug = product_query_slug_from_keyword(mapping_value(task, "target_keyword", ""))
        if slug:
            query["product"] = [slug]
            return parsed._replace(query=urlencode(query, doseq=True)).geturl()
    return url


def fetch_cache_key(task: Any) -> str:
    url = monitor_url_for_fetch(task)
    normalized_url, _ = urldefrag(url)
    return "|".join(
        [
            task_fetch_strategy(task),
            normalized_url.rstrip("/") or url,
        ]
    )


def shared_fetch_detail(result: "FetchPipelineResult") -> str:
    backend = result.backend_used or last_fetch_attempt_backend(result.attempts, result.error_kind)
    if result.error_kind:
        return f"同站点本轮已失败，跳过重复请求：{result.error_kind}（{backend or 'unknown'}）。"
    return f"复用同轮抓取结果（{backend or 'unknown'}）。"


def scrapling_domain_cooldown_seconds(backend: str, error_kind: str, settings_payload: dict[str, Any]) -> int:
    if error_kind in {"scrapling_challenge_upgrade_required", "scrapling_challenge_failed"}:
        return 0
    if error_kind == "cloudflare_challenge" or backend == FETCH_STRATEGY_SCRAPLING_STEALTH:
        return int(settings_payload.get("scrapling_domain_cooldown_stealth") or DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STEALTH)
    if backend == FETCH_STRATEGY_SCRAPLING_DYNAMIC:
        return int(settings_payload.get("scrapling_domain_cooldown_dynamic") or DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_DYNAMIC)
    if backend == FETCH_STRATEGY_SCRAPLING_STANDARD:
        return int(settings_payload.get("scrapling_domain_cooldown_standard") or DEFAULT_SCRAPLING_DOMAIN_COOLDOWN_STANDARD)
    return 0


def domain_cooldown_until(backend: str, error_kind: str, settings_payload: dict[str, Any], now: datetime | None = None) -> str:
    seconds = scrapling_domain_cooldown_seconds(backend, error_kind, settings_payload)
    if seconds <= 0:
        return ""
    now = now or now_utc()
    return (now + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def domain_cooldown_message(domain: str, cooldown_until: str, detail: str = "") -> str:
    base = f"{domain or '同站点'} 本轮已暂停重复请求，{cooldown_until} 后自动再试。"
    return f"{base}{detail}" if detail else base


def protected_source_cooldown_message(cooldown_until: str) -> str:
    return (
        f"受保护站点冷却中：目标页返回保护页，{cooldown_until} 后自动再试。"
        "如果持续失败，可改用 Webhook、手动录入或替代公开页面。"
    )


def firecrawl_cost_cooldown_until(now: datetime | None = None) -> str:
    now = now or now_utc()
    return (now + timedelta(minutes=FIRECRAWL_COST_COOLDOWN_MINUTES)).isoformat(timespec="seconds")


def firecrawl_cost_cooldown_message(cooldown_until: str) -> str:
    return (
        f"Firecrawl 额度不足或频率受限，已暂停外部抓取至 {cooldown_until}。"
        "Firecrawl 会消耗 credits，建议改用本地采集、手动检测或降低监控频率。"
    )


def last_error_looks_like_firecrawl_cost(task: Any) -> bool:
    text = normalize_signal_text(str(mapping_value(task, "last_error", "") or ""))
    return "firecrawlcreditrequired" in text or "firecrawlratelimited" in text or "额度不足" in text or "频率受限" in text


def last_firecrawl_cost_error_kind(task: Any) -> str:
    text = normalize_signal_text(str(mapping_value(task, "last_error", "") or ""))
    if "firecrawlratelimited" in text or "频率受限" in text:
        return "firecrawl_rate_limited"
    if "firecrawlcreditrequired" in text or "额度不足" in text:
        return "firecrawl_credit_required"
    return "firecrawl_credit_required"


def firecrawl_allowed_for_context(settings_payload: dict[str, Any] | None, context: str) -> bool:
    settings_payload = settings_payload or {}
    if not settings_payload.get("firecrawl_enabled"):
        return False
    if context == "catalog":
        return bool(settings_payload.get("firecrawl_use_for_catalog"))
    if context in {"test", "manual"}:
        return True
    return bool(settings_payload.get("firecrawl_use_for_monitor"))


def firecrawl_monitor_disabled_result(url: str) -> "FetchPipelineResult":
    attempt = FetchAttempt(
        backend=FETCH_STRATEGY_FIRECRAWL,
        started_at=now_iso(),
        ended_at=now_iso(),
        status="skipped",
        error_kind="firecrawl_monitor_disabled",
        detail="Firecrawl 定时监控未启用，已跳过外部抓取。",
        final_url=url,
    )
    return FetchPipelineResult(
        html="",
        final_url=url,
        status_code=0,
        backend_used="",
        attempts=[attempt],
        error_kind="firecrawl_monitor_disabled",
        detail=(
            "Firecrawl 会消耗 credits，当前未允许用于定时监控；"
            "已跳过本轮外部抓取。可手动立即检测，或改用本地采集策略。"
        ),
    )


def normalize_telegram_chat_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_values = [str(item).strip() for item in value]
    else:
        raw_text = str(value or "").replace("\r", "\n")
        raw_values = [part.strip() for part in re.split(r"[\n,;]+", raw_text)]
    chat_ids: list[str] = []
    for chat_id in raw_values:
        if chat_id and chat_id not in chat_ids:
            chat_ids.append(chat_id)
    return chat_ids


def serialize_telegram_chat_ids(chat_ids: list[str]) -> str:
    return "\n".join(normalize_telegram_chat_ids(chat_ids))


def parse_message_id_map(value: Any, fallback_chat_ids: list[str] | None = None, legacy_message_id: Any = None) -> dict[str, int]:
    message_ids: dict[str, int] = {}
    fallback_chat_ids = normalize_telegram_chat_ids(fallback_chat_ids or [])
    raw_text = str(value or "").strip()
    if raw_text:
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            for chat_id, message_id in parsed.items():
                try:
                    message_ids[str(chat_id).strip()] = int(message_id)
                except (TypeError, ValueError):
                    continue
        elif isinstance(parsed, list):
            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                chat_id = str(entry.get("chat_id", "")).strip()
                try:
                    message_id = int(entry.get("message_id"))
                except (TypeError, ValueError):
                    continue
                if chat_id:
                    message_ids[chat_id] = message_id
    if not message_ids and legacy_message_id not in (None, "") and fallback_chat_ids:
        try:
            message_ids[fallback_chat_ids[0]] = int(legacy_message_id)
        except (TypeError, ValueError):
            pass
    return message_ids


def serialize_message_id_map(message_ids: dict[str, int]) -> str:
    normalized: dict[str, int] = {}
    for chat_id, message_id in message_ids.items():
        chat_id_text = str(chat_id).strip()
        try:
            message_id_int = int(message_id)
        except (TypeError, ValueError):
            continue
        if chat_id_text:
            normalized[chat_id_text] = message_id_int
    return json.dumps(normalized, ensure_ascii=False) if normalized else ""


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


def is_public_webhook_request() -> bool:
    return request.endpoint == "webhook_ingest"


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def sanitize_sensitive_settings_value(key: str, value: Any) -> str:
    if str(key).strip().lower() in SENSITIVE_SETTINGS_KEYS:
        return ""
    return str(value if value is not None else "")


def webhook_endpoint_for_task(task_id: int) -> str:
    return f"/api/webhooks/restock/{int(task_id)}"


def generate_ingest_token() -> str:
    return secrets.token_urlsafe(WEBHOOK_TOKEN_BYTES)


def ingest_token_hint(token: str) -> str:
    text = str(token or "")
    if not text:
        return ""
    if len(text) <= WEBHOOK_TOKEN_HINT_PREFIX + WEBHOOK_TOKEN_HINT_SUFFIX:
        return "*" * len(text)
    return f"{text[:WEBHOOK_TOKEN_HINT_PREFIX]}...{text[-WEBHOOK_TOKEN_HINT_SUFFIX:]}"


def hash_ingest_token(token: str) -> str:
    token_text = str(token or "").strip()
    if not token_text:
        return ""
    secret = str(SECRET_KEY or "").encode("utf-8")
    return hmac.new(secret, token_text.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_ingest_token(task: Any, supplied_token: str) -> bool:
    expected_hash = str(mapping_value(task, "ingest_token_hash", "") or "")
    if not expected_hash:
        return False
    supplied_hash = hash_ingest_token(supplied_token)
    return bool(supplied_hash) and secrets.compare_digest(expected_hash, supplied_hash)


def extract_ingest_token_from_request(payload: dict[str, Any]) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(None, 1)[1].strip()
    for header_name in ("X-NOAFF-Token", "X-Webhook-Token", "X-Ingest-Token"):
        token = request.headers.get(header_name, "").strip()
        if token:
            return token
    for key in ("ingest_token", "webhook_token", "token"):
        token = str(payload.get(key, "") or "").strip()
        if token:
            return token
    return ""


def parse_external_checked_at(value: Any) -> datetime:
    if value in ("", None):
        return now_utc()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return now_utc()
    parsed = parse_iso_datetime(str(value))
    return parsed or now_utc()


def parse_external_stock_payload(payload: dict[str, Any]) -> tuple[int, str, datetime]:
    raw_stock = payload.get("stock")
    status = normalize_signal_text(payload.get("status", ""))
    if raw_stock not in ("", None):
        stock = parse_int_value(raw_stock)
        if stock is None:
            raise ValueError("stock 必须是非负整数。")
    elif status in {
        "instock",
        "available",
        "restocked",
        "ok",
        "true",
        "yes",
        "on",
        "有货",
        "有貨",
        "可购买",
        "可購買",
        "可下单",
        "可下單",
    }:
        stock = 1
    elif status in {
        "soldout",
        "outofstock",
        "unavailable",
        "false",
        "no",
        "off",
        "缺货",
        "缺貨",
        "售罄",
        "无货",
        "無貨",
    }:
        stock = 0
    else:
        raise ValueError("请提供 stock，或提供可识别的 status。")
    detail = re.sub(r"\s+", " ", str(payload.get("detail", "") or "")).strip()
    checked_at = parse_external_checked_at(payload.get("checked_at"))
    return stock, detail[:1000], checked_at


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


def is_root_process() -> bool:
    try:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    except Exception:
        return False


def panel_upgrade_can_start_systemd() -> bool:
    return PANEL_UPGRADE_ENABLED or is_root_process()


def systemd_upgrade_command(use_sudo: bool = False) -> str:
    prefix = "sudo " if use_sudo else ""
    return f"{prefix}systemctl start {UPGRADE_SERVICE_NAME}"


def docker_upgrade_command() -> str:
    return f"cd {INSTALL_APP_DIR} && bash install.sh --docker-upgrade"


def upgrade_start_error_message(raw_message: str) -> str:
    message = re.sub(r"\s+", " ", str(raw_message or "")).strip()
    if "interactive authentication required" in message.lower():
        return (
            "当前面板进程没有启动 systemd 升级服务的权限。"
            f"请在服务器终端执行：{systemd_upgrade_command(use_sudo=True)}"
        )
    return message or "升级命令执行失败。"


def upgrade_mode_payload() -> dict[str, str | bool]:
    if DEPLOY_MODE == "docker":
        return {
            "upgrade_mode": "manual",
            "upgrade_supported": False,
            "upgrade_state": "Docker 手动升级",
            "upgrade_hint": "Docker 隔离部署为了安全起见，不直接从面板接管宿主机 Docker。请复制命令到服务器执行。",
            "upgrade_command": docker_upgrade_command(),
        }
    if shutil.which("systemctl") and upgrade_service_exists():
        if not panel_upgrade_can_start_systemd():
            return {
                "upgrade_mode": "manual",
                "upgrade_supported": False,
                "upgrade_state": "需要手动升级",
                "upgrade_hint": "当前 Web 服务用户没有 systemd 启动权限。请复制命令到服务器终端执行。",
                "upgrade_command": systemd_upgrade_command(use_sudo=True),
            }
        return {
            "upgrade_mode": "panel",
            "upgrade_supported": True,
            "upgrade_state": "一键升级可用",
            "upgrade_hint": "将通过 systemd 在后台拉取最新代码并自动重启服务。",
            "upgrade_command": systemd_upgrade_command(),
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
    "task_groups",
    "task_group_nodes",
    "tasks",
    "activity_logs",
)
BACKUP_RESTORE_ORDER = (
    "admins",
    "settings",
    "merchant_sources",
    "merchant_items",
    "task_groups",
    "task_group_nodes",
    "tasks",
    "activity_logs",
)
BACKUP_AUTOINCREMENT_TABLES = (
    "admins",
    "merchant_sources",
    "merchant_items",
    "task_groups",
    "task_group_nodes",
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
                    "value": sanitize_sensitive_settings_value(key, effective_settings.get(key, "")),
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
            if table == "settings" and str(row.get("key", "")).strip().lower() in SENSITIVE_SETTINGS_KEYS:
                row = {**row, "value": ""}
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


class EnhancedCollectorManager:
    CANDIDATE_URLS = (
        "http://127.0.0.1:8191",
        "http://localhost:8191",
        "http://flaresolverr:8191",
    )

    def __init__(self, settings_payload: dict[str, Any], session: requests.Session | None = None) -> None:
        self.settings = settings_payload
        self.session = session or requests.Session()

    def configured_url(self) -> str:
        return str(self.settings.get("enhanced_collector_api_url") or "").strip().rstrip("/")

    def candidate_urls(self) -> list[str]:
        candidates: list[str] = []
        configured = self.configured_url()
        if configured:
            candidates.append(configured)
        for url in self.CANDIDATE_URLS:
            if url not in candidates:
                candidates.append(url)
        return candidates

    def health_check(self, probe_candidates: bool = True) -> dict[str, Any]:
        enabled = bool(self.settings.get("enhanced_collector_enabled"))
        configured = self.configured_url()
        if not enabled and not configured:
            return {
                "status": "disabled",
                "available": False,
                "api_url": "",
                "detail": "增强采集未启用。",
            }

        if not probe_candidates:
            if configured:
                return {
                    "status": "configured",
                    "available": False,
                    "api_url": configured,
                    "detail": "增强采集服务已配置，点击检测确认可用。",
                }
            return {
                "status": "not_configured",
                "available": False,
                "api_url": "",
                "detail": "未配置增强采集服务地址。",
            }

        urls = self.candidate_urls() if probe_candidates else ([configured] if configured else [])
        if not urls:
            return {
                "status": "not_configured",
                "available": False,
                "api_url": "",
                "detail": "未配置增强采集服务地址。",
            }

        timeout = max(3, min(30, int(self.settings.get("enhanced_collector_timeout_seconds") or DEFAULT_ENHANCED_COLLECTOR_TIMEOUT_SECONDS)))
        last_detail = ""
        for api_url in urls:
            if not validate_http_url(api_url):
                last_detail = f"增强采集地址无效：{api_url}"
                continue
            result = self._probe(api_url, timeout)
            if result["available"]:
                return result
            last_detail = result["detail"]

        return {
            "status": "unreachable",
            "available": False,
            "api_url": configured or urls[0],
            "detail": last_detail or "增强采集服务不可用。",
        }

    def _probe(self, api_url: str, timeout: int) -> dict[str, Any]:
        try:
            response = self.session.post(
                f"{api_url.rstrip('/')}/v1",
                json={"cmd": "sessions.list"},
                timeout=timeout,
            )
        except requests.Timeout:
            return {
                "status": "timeout",
                "available": False,
                "api_url": api_url,
                "detail": "增强采集服务连接超时。",
            }
        except requests.RequestException as exc:
            return {
                "status": "unreachable",
                "available": False,
                "api_url": api_url,
                "detail": f"增强采集服务无法访问：{str(exc)[:180]}",
            }

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            return {
                "status": "http_error",
                "available": False,
                "api_url": api_url,
                "status_code": status_code,
                "detail": f"增强采集服务 HTTP {status_code}。",
            }
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict) and payload.get("status") in {"ok", "success"}:
            return {
                "status": "ok",
                "available": True,
                "api_url": api_url,
                "status_code": status_code,
                "detail": "增强采集服务可用。",
            }
        text = str(getattr(response, "text", "") or "")
        if "flaresolverr" in text.lower() or "ready" in text.lower():
            return {
                "status": "ok",
                "available": True,
                "api_url": api_url,
                "status_code": status_code,
                "detail": "增强采集服务可用。",
            }
        return {
            "status": "bad_response",
            "available": False,
            "api_url": api_url,
            "status_code": status_code,
            "detail": "增强采集服务响应结构不正确。",
        }


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
    chat_ids = normalize_telegram_chat_ids(raw.get("telegram_chat_ids") or raw.get("telegram_chat_id"))
    legacy_chat_id = raw.get("telegram_chat_id", "").strip() or (chat_ids[0] if chat_ids else "")
    firecrawl_proxy_mode = str(raw.get("firecrawl_proxy_mode") or DEFAULT_FIRECRAWL_PROXY_MODE).strip().lower()
    if firecrawl_proxy_mode not in FIRECRAWL_PROXY_MODES:
        firecrawl_proxy_mode = "basic"
    firecrawl_allow_auto_proxy = parse_setting_bool(raw.get("firecrawl_allow_auto_proxy"), DEFAULT_FIRECRAWL_ALLOW_AUTO_PROXY)
    firecrawl_allow_enhanced_proxy = parse_setting_bool(
        raw.get("firecrawl_allow_enhanced_proxy"),
        DEFAULT_FIRECRAWL_ALLOW_ENHANCED_PROXY,
    )
    if firecrawl_proxy_mode == "auto" and not firecrawl_allow_auto_proxy:
        firecrawl_proxy_mode = "basic"
    if firecrawl_proxy_mode == "enhanced" and not firecrawl_allow_enhanced_proxy:
        firecrawl_proxy_mode = "basic"
    catalog_discovery_strategy = normalize_catalog_choice(
        raw.get("catalog_discovery_strategy"),
        CATALOG_DISCOVERY_STRATEGIES,
        DEFAULT_CATALOG_DISCOVERY_STRATEGY,
    )
    catalog_scrape_strategy = normalize_catalog_choice(
        raw.get("catalog_scrape_strategy"),
        CATALOG_SCRAPE_STRATEGIES,
        DEFAULT_CATALOG_SCRAPE_STRATEGY,
    )
    catalog_default_fetch_strategy = normalize_fetch_strategy(raw.get("catalog_default_fetch_strategy") or DEFAULT_CATALOG_FETCH_STRATEGY)
    catalog_default_extractor = normalize_catalog_choice(
        raw.get("catalog_default_extractor"),
        CATALOG_EXTRACTORS,
        DEFAULT_CATALOG_EXTRACTOR,
    )
    payload = {
        "telegram_bot_token": raw.get("telegram_bot_token", "").strip(),
        "telegram_chat_id": legacy_chat_id,
        "telegram_chat_ids": chat_ids,
        "telegram_chat_ids_text": serialize_telegram_chat_ids(chat_ids),
        "monitor_debug_port": monitor_port,
        "test_debug_port": test_port,
        "catalog_debug_port": catalog_port,
        "poll_interval_seconds": poll_interval,
        "request_timeout_seconds": timeout_seconds,
        "firecrawl_enabled": parse_setting_bool(raw.get("firecrawl_enabled"), DEFAULT_FIRECRAWL_ENABLED),
        "firecrawl_api_url": (raw.get("firecrawl_api_url") or DEFAULT_FIRECRAWL_API_URL).strip().rstrip("/") or DEFAULT_FIRECRAWL_API_URL,
        "firecrawl_api_key": raw.get("firecrawl_api_key", "").strip(),
        "firecrawl_timeout_seconds": max(
            10,
            min(180, int(raw.get("firecrawl_timeout_seconds") or DEFAULT_FIRECRAWL_TIMEOUT_SECONDS)),
        ),
        "firecrawl_max_age_ms": max(0, int(raw.get("firecrawl_max_age_ms") or DEFAULT_FIRECRAWL_MAX_AGE_MS)),
        "firecrawl_store_in_cache": parse_setting_bool(
            raw.get("firecrawl_store_in_cache"),
            DEFAULT_FIRECRAWL_STORE_IN_CACHE,
        ),
        "firecrawl_proxy_mode": firecrawl_proxy_mode,
        "firecrawl_allow_auto_proxy": firecrawl_allow_auto_proxy,
        "firecrawl_allow_enhanced_proxy": firecrawl_allow_enhanced_proxy,
        "firecrawl_zero_data_retention": parse_setting_bool(
            raw.get("firecrawl_zero_data_retention"),
            DEFAULT_FIRECRAWL_ZERO_DATA_RETENTION,
        ),
        "firecrawl_use_for_monitor": parse_setting_bool(
            raw.get("firecrawl_use_for_monitor"),
            DEFAULT_FIRECRAWL_USE_FOR_MONITOR,
        ),
        "firecrawl_use_for_catalog": parse_setting_bool(
            raw.get("firecrawl_use_for_catalog"),
            DEFAULT_FIRECRAWL_USE_FOR_CATALOG,
        ),
        "firecrawl_catalog_limit": max(1, min(250, int(raw.get("firecrawl_catalog_limit") or DEFAULT_FIRECRAWL_CATALOG_LIMIT))),
        "enhanced_collector_enabled": parse_setting_bool(
            raw.get("enhanced_collector_enabled"),
            DEFAULT_ENHANCED_COLLECTOR_ENABLED,
        ),
        "enhanced_collector_api_url": str(
            raw.get("enhanced_collector_api_url") or DEFAULT_ENHANCED_COLLECTOR_API_URL
        ).strip().rstrip("/"),
        "enhanced_collector_timeout_seconds": max(
            5,
            min(
                180,
                int(raw.get("enhanced_collector_timeout_seconds") or DEFAULT_ENHANCED_COLLECTOR_TIMEOUT_SECONDS),
            ),
        ),
        "enhanced_collector_max_retries": max(
            0,
            min(5, int(raw.get("enhanced_collector_max_retries") or DEFAULT_ENHANCED_COLLECTOR_MAX_RETRIES)),
        ),
        "enhanced_collector_use_for_monitor": parse_setting_bool(
            raw.get("enhanced_collector_use_for_monitor"),
            DEFAULT_ENHANCED_COLLECTOR_USE_FOR_MONITOR,
        ),
        "enhanced_collector_use_for_catalog": parse_setting_bool(
            raw.get("enhanced_collector_use_for_catalog"),
            DEFAULT_ENHANCED_COLLECTOR_USE_FOR_CATALOG,
        ),
        "catalog_discovery_strategy": catalog_discovery_strategy,
        "catalog_scrape_strategy": catalog_scrape_strategy,
        "catalog_default_fetch_strategy": catalog_default_fetch_strategy,
        "catalog_default_extractor": catalog_default_extractor,
        "catalog_default_group": normalize_task_group(raw.get("catalog_default_group") or DEFAULT_TASK_GROUP),
        "catalog_include_sold_out": parse_setting_bool(raw.get("catalog_include_sold_out"), True),
        "catalog_auto_create_tasks": parse_setting_bool(raw.get("catalog_auto_create_tasks"), True),
        "catalog_dedupe_policy": normalize_catalog_choice(raw.get("catalog_dedupe_policy"), CATALOG_DEDUPE_POLICIES, "by_url"),
        "catalog_max_discovered_urls": max(1, min(250, int(raw.get("catalog_max_discovered_urls") or 50))),
        "catalog_max_import_items": max(1, min(250, int(raw.get("catalog_max_import_items") or 50))),
        "catalog_timeout_seconds": max(10, min(180, int(raw.get("catalog_timeout_seconds") or timeout_seconds))),
    }
    payload.update(normalize_scrapling_settings(raw))
    return payload


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


def migrate_task_fetch_strategies_to_scrapling(connection: sqlite3.Connection) -> int:
    marker = connection.execute(
        "SELECT value FROM settings WHERE key = ?",
        (SCRAPLING_FETCH_STRATEGY_MIGRATION_KEY,),
    ).fetchone()
    if marker:
        return 0

    migrated_count = 0
    timestamp = now_iso()
    extractor_legacy_strategies = {
        FETCH_STRATEGY_GENERIC_PRICING_TABLE,
        FETCH_STRATEGY_WHMCS,
    }
    for legacy_strategy in extractor_legacy_strategies:
        target_strategy = LEGACY_FETCH_STRATEGY_MIGRATIONS[legacy_strategy]
        for row in connection.execute(
            """
            SELECT id, source_config
            FROM tasks
            WHERE fetch_strategy = ?
            """,
            (legacy_strategy,),
        ).fetchall():
            config = parse_source_config(row["source_config"])
            config.setdefault("extractor", legacy_strategy)
            config.setdefault("legacy_fetch_strategy", legacy_strategy)
            connection.execute(
                """
                UPDATE tasks
                SET fetch_strategy = ?, source_config = ?, updated_at = ?
                WHERE id = ?
                """,
                (target_strategy, normalize_source_config_text(config), timestamp, row["id"]),
            )
            migrated_count += 1
    for legacy_strategy, target_strategy in LEGACY_FETCH_STRATEGY_MIGRATIONS.items():
        if legacy_strategy in extractor_legacy_strategies:
            continue
        cursor = connection.execute(
            """
            UPDATE tasks
            SET fetch_strategy = ?, updated_at = ?
            WHERE fetch_strategy = ?
            """,
            (target_strategy, timestamp, legacy_strategy),
        )
        migrated_count += cursor.rowcount if cursor.rowcount is not None else 0
    cursor = connection.execute(
        """
        UPDATE tasks
        SET fetch_strategy = ?, updated_at = ?
        WHERE fetch_strategy IS NULL OR TRIM(fetch_strategy) = ''
        """,
        (DEFAULT_TASK_FETCH_STRATEGY, timestamp),
    )
    migrated_count += cursor.rowcount if cursor.rowcount is not None else 0
    connection.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (SCRAPLING_FETCH_STRATEGY_MIGRATION_KEY, timestamp, timestamp),
    )
    connection.commit()
    return migrated_count


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
                subgroup_name TEXT NOT NULL DEFAULT '默认子分组',
                sort_order INTEGER NOT NULL DEFAULT 0,
                monitor_url TEXT NOT NULL,
                target_keyword TEXT NOT NULL,
                fetch_strategy TEXT NOT NULL DEFAULT 'multi_engine',
                source_config TEXT NOT NULL DEFAULT '{}',
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
                message_ids TEXT DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_stock INTEGER,
                last_state TEXT NOT NULL DEFAULT 'unknown',
                message_id INTEGER,
                last_checked_at TEXT,
                last_error TEXT DEFAULT '',
                last_fetch_backend TEXT DEFAULT '',
                last_fetch_attempts TEXT DEFAULT '',
                last_fetch_domain TEXT DEFAULT '',
                domain_cooldown_until TEXT,
                last_shared_fetch_key TEXT DEFAULT '',
                last_shared_fetch_backend TEXT DEFAULT '',
                last_protected_source_backend TEXT DEFAULT '',
                blocked_count INTEGER NOT NULL DEFAULT 0,
                last_blocked_at TEXT,
                cooldown_until TEXT,
                ingest_token_hash TEXT DEFAULT '',
                ingest_token_hint TEXT DEFAULT '',
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
                group_name TEXT NOT NULL DEFAULT '默认分组',
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

            CREATE TABLE IF NOT EXISTS task_group_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                subgroup_name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(group_name, subgroup_name)
            );

            CREATE TABLE IF NOT EXISTS task_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS domain_sessions (
                domain TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'missing',
                user_agent TEXT DEFAULT '',
                cookies_json TEXT NOT NULL DEFAULT '[]',
                profile_path TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                last_unlocked_at TEXT,
                expires_at TEXT,
                last_error TEXT DEFAULT '',
                failure_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )
        ensure_column(connection, "tasks", "group_name", "TEXT NOT NULL DEFAULT '默认分组'")
        ensure_column(connection, "tasks", "subgroup_name", "TEXT NOT NULL DEFAULT '默认子分组'")
        ensure_column(connection, "tasks", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "tasks", "source_item_id", "INTEGER")
        ensure_column(connection, "tasks", "source_item_key", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_source_url", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_source_name", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_item_url", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_snapshot", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "source_last_sync_at", "TEXT")
        ensure_column(connection, "tasks", "message_ids", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "fetch_strategy", "TEXT NOT NULL DEFAULT 'multi_engine'")
        ensure_column(connection, "tasks", "source_config", "TEXT NOT NULL DEFAULT '{}'")
        ensure_column(connection, "tasks", "last_fetch_backend", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "last_fetch_attempts", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "last_fetch_domain", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "domain_cooldown_until", "TEXT")
        ensure_column(connection, "tasks", "last_shared_fetch_key", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "last_shared_fetch_backend", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "last_protected_source_backend", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "blocked_count", "INTEGER NOT NULL DEFAULT 0")
        ensure_column(connection, "tasks", "last_blocked_at", "TEXT")
        ensure_column(connection, "tasks", "cooldown_until", "TEXT")
        ensure_column(connection, "tasks", "ingest_token_hash", "TEXT DEFAULT ''")
        ensure_column(connection, "tasks", "ingest_token_hint", "TEXT DEFAULT ''")
        ensure_column(connection, "merchant_sources", "group_name", "TEXT NOT NULL DEFAULT '默认分组'")
        ensure_column(connection, "task_group_nodes", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        migrate_task_fetch_strategies_to_scrapling(connection)

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

        timestamp = now_iso()
        for row in connection.execute(
            """
            SELECT DISTINCT group_name FROM tasks
            UNION
            SELECT DISTINCT group_name FROM merchant_sources
            """
        ).fetchall():
            upsert_task_group(connection, row["group_name"], timestamp)
        for row in connection.execute(
            """
            SELECT DISTINCT group_name, subgroup_name
            FROM tasks
            WHERE subgroup_name IS NOT NULL AND subgroup_name != ?
            """,
            (DEFAULT_TASK_SUBGROUP,),
        ).fetchall():
            upsert_task_group_node(connection, row["group_name"], row["subgroup_name"], timestamp)
        connection.commit()


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
    last_error = sanitize_telegram_error(row["last_error"] or "")
    last_fetch_attempts = parse_fetch_attempts_text(row["last_fetch_attempts"] if "last_fetch_attempts" in keys else "")
    last_error_kind = task_error_kind_from_attempts(last_error, last_fetch_attempts)
    task_domain = fetch_domain_for_url(row["monitor_url"])
    normalized_fetch_strategy = normalize_fetch_strategy(row["fetch_strategy"] if "fetch_strategy" in keys else "")
    last_fetch_backend = (row["last_fetch_backend"] or "") if "last_fetch_backend" in keys else ""
    last_error_detail = summarize_task_error(last_error, last_error_kind)
    last_error_diagnostic = stock_check_diagnostic(
        last_error_kind,
        last_error_detail or last_error,
        last_fetch_attempts,
        last_fetch_backend,
        task_domain,
    ) if last_error or last_error_kind else {}
    return {
        "id": row["id"],
        "name": row["name"],
        "group_name": normalize_task_group(row["group_name"] if "group_name" in keys else ""),
        "subgroup_name": normalize_task_subgroup(row["subgroup_name"] if "subgroup_name" in keys else ""),
        "sort_order": int(row["sort_order"] or 0) if "sort_order" in keys else 0,
        "monitor_url": row["monitor_url"],
        "monitor_domain": task_domain,
        "domain_session": get_domain_session(task_domain, safe=True),
        "target_keyword": row["target_keyword"],
        "fetch_strategy": normalized_fetch_strategy,
        "collector_strategy": collector_strategy_for_task(row),
        "source_config": normalize_source_config_text(row["source_config"] if "source_config" in keys else "{}"),
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
        "message_ids": (row["message_ids"] or "") if "message_ids" in keys else "",
        "enabled": bool(row["enabled"]),
        "last_stock": row["last_stock"],
        "last_state": row["last_state"],
        "message_id": row["message_id"],
        "last_checked_at": row["last_checked_at"] or "",
        "last_error": last_error,
        "last_error_kind": last_error_kind,
        "last_error_detail": last_error_detail,
        "last_error_diagnostic": last_error_diagnostic,
        "last_fetch_backend": last_fetch_backend,
        "last_fetch_attempts": last_fetch_attempts,
        "last_fetch_domain": (row["last_fetch_domain"] or "") if "last_fetch_domain" in keys else "",
        "domain_cooldown_until": (row["domain_cooldown_until"] or "") if "domain_cooldown_until" in keys else "",
        "last_shared_fetch_key": (row["last_shared_fetch_key"] or "") if "last_shared_fetch_key" in keys else "",
        "last_shared_fetch_backend": (row["last_shared_fetch_backend"] or "") if "last_shared_fetch_backend" in keys else "",
        "last_protected_source_backend": (row["last_protected_source_backend"] or "") if "last_protected_source_backend" in keys else "",
        "blocked_count": int(row["blocked_count"] or 0) if "blocked_count" in keys else 0,
        "last_blocked_at": (row["last_blocked_at"] or "") if "last_blocked_at" in keys else "",
        "cooldown_until": (row["cooldown_until"] or "") if "cooldown_until" in keys else "",
        "ingest_token_hint": (row["ingest_token_hint"] or "") if "ingest_token_hint" in keys else "",
        "webhook_endpoint": webhook_endpoint_for_task(row["id"]) if normalized_fetch_strategy == FETCH_STRATEGY_WEBHOOK else "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def to_source_payload(row: sqlite3.Row, item_count: int = 0, linked_count: int = 0) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_url": row["source_url"],
        "source_name": row["source_name"] or "",
        "group_name": row["group_name"] if "group_name" in row.keys() else DEFAULT_TASK_GROUP,
        "active": bool(row["active"]),
        "discovered_count": row["discovered_count"],
        "item_count": item_count,
        "linked_count": linked_count,
        "last_sync_at": row["last_sync_at"] or "",
        "last_error": row["last_error"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def to_task_group_node_payload(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "group_name": normalize_task_group(row["group_name"]),
        "subgroup_name": normalize_task_subgroup(row["subgroup_name"]),
        "sort_order": int(row["sort_order"] or 0) if "sort_order" in keys else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def to_task_group_payload(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "group_name": normalize_task_group(row["group_name"]),
        "sort_order": int(row["sort_order"] or 0) if "sort_order" in keys else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def to_merchant_item_payload(
    row: sqlite3.Row,
    source_row: sqlite3.Row | None = None,
    task_row: sqlite3.Row | None = None,
) -> dict[str, Any]:
    raw_payload = row["raw_payload"] or ""
    raw_data = catalog_item_metadata(raw_payload)
    backend_used = str(raw_data.get("catalog_backend") or "")
    discovery_source = str(raw_data.get("catalog_discovery_source") or "")
    extractor = str(raw_data.get("extractor") or "")
    fetch_strategy = normalize_fetch_strategy(raw_data.get("fetch_strategy") or DEFAULT_TASK_FETCH_STRATEGY)
    signals = raw_data.get("signals") if isinstance(raw_data.get("signals"), list) else []
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
        "backend_used": backend_used,
        "discovery_source": discovery_source,
        "extractor": extractor,
        "fetch_strategy": fetch_strategy,
        "confidence": int(raw_data.get("confidence") or 0),
        "candidate_type": str(raw_data.get("candidate_type") or ""),
        "include_reason": str(raw_data.get("include_reason") or ""),
        "reject_reason": str(raw_data.get("reject_reason") or ""),
        "signals": signals[:12],
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
    if not is_supported_fetch_strategy(payload.get("fetch_strategy")):
        return False, "采集方式不受支持。"
    source_config = payload.get("source_config", {})
    if isinstance(source_config, str) and source_config.strip():
        try:
            parsed_config = json.loads(source_config)
        except json.JSONDecodeError:
            return False, "采集配置必须是 JSON 对象。"
        if not isinstance(parsed_config, dict):
            return False, "采集配置必须是 JSON 对象。"
    elif source_config not in ({}, "", None) and not isinstance(source_config, dict):
        return False, "采集配置必须是 JSON 对象。"
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
        normalize_task_subgroup(payload.get("subgroup_name")),
        int(payload.get("sort_order") or 0),
        str(payload["monitor_url"]).strip(),
        str(payload["target_keyword"]).strip(),
        normalize_fetch_strategy(payload.get("fetch_strategy") or DEFAULT_TASK_FETCH_STRATEGY),
        normalize_source_config_text(payload.get("source_config", {})),
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


def upsert_task_group_node(
    connection: sqlite3.Connection,
    group_name: Any,
    subgroup_name: Any,
    timestamp: str,
    sort_order: int | None = None,
) -> None:
    normalized_group = normalize_task_group(group_name)
    normalized_subgroup = normalize_task_subgroup(subgroup_name)
    if normalized_subgroup == DEFAULT_TASK_SUBGROUP:
        return
    existing = connection.execute(
        "SELECT id FROM task_group_nodes WHERE group_name = ? AND subgroup_name = ?",
        (normalized_group, normalized_subgroup),
    ).fetchone()
    if existing:
        if sort_order is not None:
            connection.execute(
                """
                UPDATE task_group_nodes
                SET sort_order = ?, updated_at = ?
                WHERE group_name = ? AND subgroup_name = ?
                """,
                (int(sort_order), timestamp, normalized_group, normalized_subgroup),
            )
        else:
            connection.execute(
                """
                UPDATE task_group_nodes
                SET updated_at = ?
                WHERE group_name = ? AND subgroup_name = ?
                """,
                (timestamp, normalized_group, normalized_subgroup),
            )
        return
    connection.execute(
        """
        INSERT INTO task_group_nodes (group_name, subgroup_name, sort_order, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            normalized_group,
            normalized_subgroup,
            int(sort_order) if sort_order is not None else next_sort_order(
                connection,
                "task_group_nodes",
                "group_name = ?",
                (normalized_group,),
            ),
            timestamp,
            timestamp,
        ),
    )


def next_sort_order(connection: sqlite3.Connection, table: str, where_clause: str = "", params: tuple[Any, ...] = ()) -> int:
    sql = f"SELECT COALESCE(MAX(sort_order), 0) + 100 FROM {sql_identifier(table)}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    return int(connection.execute(sql, params).fetchone()[0] or 100)


def upsert_task_group(connection: sqlite3.Connection, group_name: Any, timestamp: str, sort_order: int | None = None) -> None:
    normalized_group = normalize_task_group(group_name)
    existing = connection.execute("SELECT id FROM task_groups WHERE group_name = ?", (normalized_group,)).fetchone()
    if existing:
        if sort_order is not None:
            connection.execute(
                "UPDATE task_groups SET sort_order = ?, updated_at = ? WHERE group_name = ?",
                (int(sort_order), timestamp, normalized_group),
            )
        return
    connection.execute(
        """
        INSERT INTO task_groups (group_name, sort_order, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            normalized_group,
            int(sort_order) if sort_order is not None else next_sort_order(connection, "task_groups"),
            timestamp,
            timestamp,
        ),
    )


def normalize_ordered_values(raw_values: Any, normalizer: Callable[[Any], str], limit: int) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    ordered: list[str] = []
    for raw_value in raw_values:
        value = normalizer(raw_value)
        if value and value not in ordered:
            ordered.append(value)
        if len(ordered) > limit:
            break
    return ordered


def subgroup_descendant_like(subgroup_name: str) -> str:
    return f"{normalize_task_subgroup(subgroup_name)} / %"


def delete_task_subgroup_tree(connection: sqlite3.Connection, group_name: str, subgroup_name: str) -> int:
    normalized_group = normalize_task_group(group_name)
    normalized_subgroup = normalize_task_subgroup(subgroup_name)
    task_count = connection.execute(
        """
        SELECT COUNT(*) FROM tasks
        WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
        """,
        (normalized_group, normalized_subgroup, subgroup_descendant_like(normalized_subgroup)),
    ).fetchone()[0]
    connection.execute(
        """
        DELETE FROM tasks
        WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
        """,
        (normalized_group, normalized_subgroup, subgroup_descendant_like(normalized_subgroup)),
    )
    connection.execute(
        """
        DELETE FROM task_group_nodes
        WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
        """,
        (normalized_group, normalized_subgroup, subgroup_descendant_like(normalized_subgroup)),
    )
    return int(task_count)


def rename_task_subgroup_tree(
    connection: sqlite3.Connection,
    group_name: str,
    old_subgroup_name: str,
    new_leaf_name: str,
    timestamp: str,
) -> tuple[str, int, int]:
    normalized_group = normalize_task_group(group_name)
    old_path = normalize_task_subgroup(old_subgroup_name)
    old_parts = split_task_subgroup_path(old_path)
    if not old_parts:
        raise ValueError("默认子分组暂不支持重命名。")
    new_parts = split_task_subgroup_path(new_leaf_name)
    if not new_parts:
        raise ValueError("新的子分组名称不能为空。")
    new_path = join_task_subgroup_path(old_parts[:-1] + new_parts)
    if new_path == old_path:
        return new_path, 0, 0

    task_rows = connection.execute(
        """
        SELECT id, subgroup_name FROM tasks
        WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
        """,
        (normalized_group, old_path, subgroup_descendant_like(old_path)),
    ).fetchall()
    node_rows = connection.execute(
        """
        SELECT id, subgroup_name FROM task_group_nodes
        WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
        """,
        (normalized_group, old_path, subgroup_descendant_like(old_path)),
    ).fetchall()
    if not task_rows and not node_rows:
        raise LookupError("子分组不存在。")

    def next_path(current_path: str) -> str:
        if current_path == old_path:
            return new_path
        suffix = current_path[len(old_path) :].lstrip(" /")
        return normalize_task_subgroup(f"{new_path} / {suffix}")

    for row in task_rows:
        connection.execute(
            "UPDATE tasks SET subgroup_name = ?, updated_at = ? WHERE id = ?",
            (next_path(row["subgroup_name"]), timestamp, row["id"]),
        )
    for row in node_rows:
        connection.execute(
            "UPDATE OR IGNORE task_group_nodes SET subgroup_name = ?, updated_at = ? WHERE id = ?",
            (next_path(row["subgroup_name"]), timestamp, row["id"]),
        )
    connection.execute(
        """
        DELETE FROM task_group_nodes
        WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
        """,
        (normalized_group, old_path, subgroup_descendant_like(old_path)),
    )
    upsert_task_group_node(connection, normalized_group, new_path, timestamp)
    return new_path, len(task_rows), len(node_rows)


def insert_task_record(connection: sqlite3.Connection, payload: dict[str, Any], timestamp: str, fallback: sqlite3.Row | None = None) -> int:
    source_fields = normalize_task_source_fields(payload, fallback)
    normalized_group = normalize_task_group(payload.get("group_name"))
    normalized_subgroup = normalize_task_subgroup(payload.get("subgroup_name"))
    payload_with_order = dict(payload)
    if not payload_with_order.get("sort_order"):
        payload_with_order["sort_order"] = next_sort_order(
            connection,
            "tasks",
            "group_name = ? AND subgroup_name = ?",
            (normalized_group, normalized_subgroup),
        )
    cursor = connection.execute(
        """
        INSERT INTO tasks (
            name, group_name, subgroup_name, sort_order, monitor_url, target_keyword, fetch_strategy, source_config, restock_template, soldout_template,
            button_1_text, button_1_url, button_2_text, button_2_url,
            source_item_id, source_item_key, source_source_url, source_source_name, source_item_url,
            source_snapshot, source_last_sync_at, enabled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        build_task_insert_values(payload_with_order, source_fields, timestamp),
    )
    upsert_task_group(connection, normalized_group, timestamp)
    upsert_task_group_node(connection, normalized_group, normalized_subgroup, timestamp)
    connection.commit()
    return int(cursor.lastrowid)


def reset_task_ingest_token(connection: sqlite3.Connection, task_id: int, timestamp: str | None = None) -> tuple[str, str]:
    token = generate_ingest_token()
    hint = ingest_token_hint(token)
    connection.execute(
        """
        UPDATE tasks
        SET ingest_token_hash = ?, ingest_token_hint = ?, updated_at = ?
        WHERE id = ?
        """,
        (hash_ingest_token(token), hint, timestamp or now_iso(), task_id),
    )
    return token, hint


def create_task_from_catalog_item(
    connection: sqlite3.Connection,
    source_id: int,
    source_title: str,
    group_name: str,
    source_url: str,
    item_id: int,
    item: dict[str, Any],
) -> int:
    timestamp = now_iso()
    payload = {
        "name": item["title"],
        "group_name": group_name,
        "subgroup_name": item.get("subgroup_name") or DEFAULT_TASK_SUBGROUP,
        "monitor_url": item["monitor_url"],
        "target_keyword": item["keyword"],
        "restock_template": DEFAULT_RESTOCK_TEMPLATE,
        "soldout_template": DEFAULT_SOLDOUT_TEMPLATE,
        "fetch_strategy": item.get("fetch_strategy", DEFAULT_TASK_FETCH_STRATEGY),
        "source_config": item.get("source_config", {}),
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


def merchant_item_to_catalog_payload(item: sqlite3.Row) -> dict[str, Any]:
    metadata = catalog_item_metadata(item["raw_payload"] or "")
    source_config = metadata.get("source_config") if isinstance(metadata.get("source_config"), dict) else {}
    return {
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
        "fetch_strategy": normalize_fetch_strategy(metadata.get("fetch_strategy") or DEFAULT_TASK_FETCH_STRATEGY),
        "source_config": source_config,
    }


def promote_merchant_item_row(connection: sqlite3.Connection, item: sqlite3.Row) -> dict[str, Any]:
    item_id = int(item["id"])
    item_payload = merchant_item_to_catalog_payload(item)
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
            item_payload,
        )
        connection.commit()
        return {
            "item_id": item_id,
            "task_id": int(existing_task["id"]),
            "task_name": str(existing_task["name"]),
            "already_linked": True,
        }

    task_id = create_task_from_catalog_item(
        connection,
        source_id=int(item["source_id"]),
        source_title=str(item["source_name"] or item["source_url"]),
        group_name=str(item["group_name"] or DEFAULT_TASK_GROUP),
        source_url=str(item["source_url"]),
        item_id=item_id,
        item=item_payload,
    )
    connection.commit()
    return {
        "item_id": item_id,
        "task_id": task_id,
        "task_name": str(item["title"]),
        "already_linked": False,
    }


@dataclass
class FetchResult:
    html: str
    final_url: str
    status_code: int = 0
    error_kind: str = ""
    detail: str = ""


@dataclass
class FetchAttempt:
    backend: str
    started_at: str
    ended_at: str = ""
    status: str = "pending"
    error_kind: str = ""
    detail: str = ""
    final_url: str = ""


@dataclass
class FetchPipelineResult:
    html: str
    final_url: str
    status_code: int = 0
    backend_used: str = ""
    attempts: list[FetchAttempt] | None = None
    error_kind: str = ""
    detail: str = ""


@dataclass
class CollectorRequest:
    url: str
    strategy: str
    task_id: int | None = None
    target_keyword: str = ""
    source_config: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    headers: dict[str, str] = field(default_factory=dict)
    proxy: str = ""
    context: str = "monitor"


@dataclass
class CollectorResult:
    ok: bool
    html: str = ""
    final_url: str = ""
    status_code: int = 0
    backend: str = ""
    error_kind: str = ""
    detail: str = ""
    protected: bool = False
    attempts: list[FetchAttempt] = field(default_factory=list)


class BaseCollector:
    name = "base"

    def collect(self, request_payload: CollectorRequest, settings_payload: dict[str, Any]) -> CollectorResult:
        raise NotImplementedError


class FetcherCollectorAdapter(BaseCollector):
    def __init__(self, name: str, fetcher: Any) -> None:
        self.name = name
        self.fetcher = fetcher

    def collect(self, request_payload: CollectorRequest, settings_payload: dict[str, Any]) -> CollectorResult:
        try:
            result = self.fetcher.fetch(request_payload.url, request_payload.timeout_seconds)
        except ProtectedSourceError as exc:
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=exc.error_kind,
                detail=str(exc),
                protected=True,
            )
        except Exception as exc:
            detail = str(exc)
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=classify_browser_error(detail) or "request_error",
                detail=detail,
            )
        return CollectorResult(
            ok=not result.error_kind and bool(result.html),
            html=result.html,
            final_url=result.final_url,
            status_code=result.status_code,
            backend=self.name,
            error_kind=result.error_kind,
            detail=result.detail,
            protected=result.error_kind in {"cloudflare_challenge", "protected_source"},
        )


def sanitize_external_solver_detail(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    return text[:500]


def classify_external_solver_error(message: Any, status_code: int = 0) -> str:
    lowered = normalize_signal_text(message)
    if any(token in lowered for token in ("timeout", "timedout", "etimedout")):
        return "timeout"
    if any(token in lowered for token in ("unauthorized", "forbidden", "permission", "authentication")):
        return "external_solver_auth_error"
    if any(token in lowered for token in ("ratelimit", "toomanyrequests", "429")):
        return "external_solver_rate_limited"
    if any(token in lowered for token in ("cloudflare", "turnstile", "captcha", "challenge", "justamoment")):
        return "cloudflare_challenge"
    if status_code in {401, 403}:
        return "external_solver_auth_error"
    if status_code == 429:
        return "external_solver_rate_limited"
    if status_code >= 500:
        return "external_solver_upstream_error"
    if status_code >= 400:
        return "external_solver_http_error"
    return "external_solver_failed"


class ExternalSolverCollector(BaseCollector):
    name = COLLECTOR_EXTERNAL_SOLVER

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def collect(self, request_payload: CollectorRequest, settings_payload: dict[str, Any]) -> CollectorResult:
        attempt = FetchAttempt(backend=self.name, started_at=now_iso())
        api_url = str(settings_payload.get("enhanced_collector_api_url") or "").strip().rstrip("/")
        if not settings_payload.get("enhanced_collector_enabled") and not api_url:
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "external_solver_disabled"
            attempt.detail = "增强采集服务未启用。"
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )
        if request_payload.context == "monitor" and not settings_payload.get("enhanced_collector_use_for_monitor", False):
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "external_solver_monitor_disabled"
            attempt.detail = "增强采集默认不用于定时监控，请在设置中明确开启。"
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )
        if request_payload.context == "catalog" and not settings_payload.get("enhanced_collector_use_for_catalog", True):
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "external_solver_catalog_disabled"
            attempt.detail = "增强采集未启用于商品入库。"
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )
        if not api_url or not validate_http_url(api_url):
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "external_solver_not_configured"
            attempt.detail = "未配置可用的增强采集服务地址。"
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )

        payload: dict[str, Any] = {
            "cmd": "request.get",
            "url": request_payload.url,
            "maxTimeout": max(5000, int(request_payload.timeout_seconds or DEFAULT_TIMEOUT_SECONDS) * 1000),
        }
        if request_payload.headers:
            payload["headers"] = request_payload.headers
        proxy_url = request_payload.proxy or str(request_payload.source_config.get("proxy") or "")
        if proxy_url:
            payload["proxy"] = {"url": proxy_url}

        timeout_seconds = max(
            5,
            min(
                180,
                int(settings_payload.get("enhanced_collector_timeout_seconds") or request_payload.timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
            ),
        )
        try:
            response = self.session.post(f"{api_url}/v1", json=payload, timeout=timeout_seconds)
        except requests.Timeout:
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "timeout"
            attempt.detail = "增强采集服务请求超时。"
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )
        except requests.RequestException as exc:
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "external_solver_request_error"
            attempt.detail = sanitize_external_solver_detail(exc)
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )

        status_code = int(getattr(response, "status_code", 0) or 0)
        try:
            data = response.json()
        except ValueError:
            data = {}
        if status_code >= 400:
            detail = sanitize_external_solver_detail(data.get("message") if isinstance(data, dict) else getattr(response, "text", ""))
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = classify_external_solver_error(detail, status_code)
            attempt.detail = detail or f"增强采集服务 HTTP {status_code}。"
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                status_code=status_code,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                protected=attempt.error_kind == "cloudflare_challenge",
                attempts=[attempt],
            )

        if not isinstance(data, dict):
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "external_solver_bad_response"
            attempt.detail = "增强采集服务响应不是 JSON 对象。"
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                status_code=status_code,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )

        solver_status = str(data.get("status") or "").lower()
        if solver_status and solver_status not in {"ok", "success"}:
            detail = sanitize_external_solver_detail(data.get("message") or data.get("error") or "增强采集服务返回失败。")
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = classify_external_solver_error(detail, status_code)
            attempt.detail = detail
            return CollectorResult(
                ok=False,
                final_url=request_payload.url,
                status_code=status_code,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=detail,
                protected=attempt.error_kind == "cloudflare_challenge",
                attempts=[attempt],
            )

        solution = data.get("solution") if isinstance(data.get("solution"), dict) else {}
        html_text = str(solution.get("response") or data.get("html") or data.get("response") or "")
        final_url = str(solution.get("url") or data.get("url") or request_payload.url)
        target_status = int(solution.get("status") or data.get("statusCode") or 0) if str(solution.get("status") or data.get("statusCode") or "").isdigit() else 0
        if not html_text:
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "empty_response"
            attempt.detail = "增强采集服务返回了空页面。"
            return CollectorResult(
                ok=False,
                final_url=final_url,
                status_code=target_status or status_code,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                attempts=[attempt],
            )
        if looks_like_cloudflare_challenge(html_text, url=final_url):
            attempt.ended_at = now_iso()
            attempt.status = "failed"
            attempt.error_kind = "cloudflare_challenge"
            attempt.detail = "增强采集服务仍返回受保护页面。"
            attempt.final_url = final_url
            return CollectorResult(
                ok=False,
                html="",
                final_url=final_url,
                status_code=target_status or status_code,
                backend=self.name,
                error_kind=attempt.error_kind,
                detail=attempt.detail,
                protected=True,
                attempts=[attempt],
            )

        attempt.ended_at = now_iso()
        attempt.status = "success"
        attempt.final_url = final_url
        attempt.detail = "增强采集服务返回 HTML。"
        return CollectorResult(
            ok=True,
            html=html_text,
            final_url=final_url,
            status_code=target_status or status_code,
            backend=self.name,
            detail=attempt.detail,
            attempts=[attempt],
        )


def normalize_collector_strategy(value: Any, fallback: str = COLLECTOR_DIRECT) -> str:
    strategy = str(value or "").strip().lower()
    if strategy in SUPPORTED_COLLECTOR_STRATEGIES:
        return strategy
    return fallback


def collector_strategy_for_fetch_backend(backend: Any) -> str:
    strategy = str(backend or "").strip().lower()
    if strategy == COLLECTOR_EXTERNAL_SOLVER:
        return COLLECTOR_EXTERNAL_SOLVER
    if strategy == FETCH_STRATEGY_CURL_CFFI:
        return COLLECTOR_CURL_CFFI
    if strategy == FETCH_STRATEGY_MANUAL:
        return COLLECTOR_MANUAL
    if strategy == FETCH_STRATEGY_WEBHOOK:
        return COLLECTOR_WEBHOOK
    return COLLECTOR_DIRECT


def collector_strategy_for_task(task: Any) -> str:
    source_config = task_source_config(task)
    configured = normalize_collector_strategy(source_config.get("collector_strategy"), "")
    if configured:
        return configured
    return collector_strategy_for_fetch_backend(task_fetch_strategy(task))


def collector_result_from_fetch_pipeline(result: FetchPipelineResult) -> CollectorResult:
    backend = result.backend_used or last_fetch_attempt_backend(result.attempts, result.error_kind)
    return CollectorResult(
        ok=not result.error_kind and bool(result.html),
        html=result.html,
        final_url=result.final_url,
        status_code=result.status_code,
        backend=collector_strategy_for_fetch_backend(backend),
        error_kind=result.error_kind,
        detail=result.detail,
        protected=result.error_kind in {"cloudflare_challenge", "protected_source"},
        attempts=result.attempts or [],
    )


def collector_request_for_task(
    task: Any,
    settings_payload: dict[str, Any],
    context: str = "monitor",
) -> CollectorRequest:
    source_config = task_source_config(task)
    return CollectorRequest(
        url=monitor_url_for_fetch(task),
        strategy=collector_strategy_for_task(task),
        task_id=parse_int_value(mapping_value(task, "id", "")),
        target_keyword=str(mapping_value(task, "target_keyword", "") or ""),
        source_config=source_config,
        timeout_seconds=int(settings_payload.get("request_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        context=context,
    )


@dataclass
class DomainCooldown:
    until: str
    error_kind: str = "domain_cooldown"
    detail: str = ""
    backend: str = ""


@dataclass
class MonitorCycleContext:
    fetch_cache: dict[str, FetchPipelineResult] = field(default_factory=dict)
    domain_cooldowns: dict[str, DomainCooldown] = field(default_factory=dict)


def fetch_attempt_to_payload(attempt: FetchAttempt) -> dict[str, str]:
    return {
        "backend": attempt.backend,
        "started_at": attempt.started_at,
        "ended_at": attempt.ended_at,
        "status": attempt.status,
        "error_kind": attempt.error_kind,
        "detail": attempt.detail,
        "final_url": attempt.final_url,
    }


def serialize_fetch_attempts(attempts: list[FetchAttempt] | None) -> str:
    if not attempts:
        return "[]"
    return json.dumps([fetch_attempt_to_payload(attempt) for attempt in attempts], ensure_ascii=False)


def parse_fetch_attempts_text(value: Any) -> list[dict[str, str]]:
    try:
        payload = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    parsed: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        parsed.append(
            {
                "backend": str(item.get("backend") or ""),
                "started_at": str(item.get("started_at") or ""),
                "ended_at": str(item.get("ended_at") or ""),
                "status": str(item.get("status") or ""),
                "error_kind": str(item.get("error_kind") or ""),
                "detail": sanitize_firecrawl_detail(str(item.get("detail") or "")),
                "final_url": str(item.get("final_url") or ""),
            }
        )
    return parsed


def task_error_kind_from_attempts(last_error: str, attempts: list[dict[str, str]]) -> str:
    for attempt in reversed(attempts or []):
        error_kind = str(attempt.get("error_kind") or "").strip()
        if error_kind:
            return error_kind
    return classify_browser_error(last_error or "")


def fetch_attempts_summary(attempts: list[FetchAttempt] | None) -> str:
    if not attempts:
        return ""
    parts: list[str] = []
    for attempt in attempts:
        status = attempt.status or "failed"
        kind = f"/{attempt.error_kind}" if attempt.error_kind else ""
        parts.append(f"{attempt.backend}:{status}{kind}")
    return "；尝试后端：" + " -> ".join(parts)


def last_fetch_attempt_backend(attempts: list[FetchAttempt] | None, error_kind: str = "") -> str:
    if not attempts:
        return ""
    if error_kind:
        for attempt in reversed(attempts):
            if attempt.error_kind == error_kind:
                return attempt.backend
    return attempts[-1].backend


@dataclass
class ExtractorResult:
    stock: int | None
    fragment: str
    detail: str


@dataclass
class ScrapeResult:
    stock: int | None
    fragment: str
    detail: str
    used_test_browser: bool
    error_kind: str = ""
    cooldown_skip: bool = False
    backend_used: str = ""
    fetch_attempts: list[FetchAttempt] | None = None
    fetch_domain: str = ""
    shared_fetch_key: str = ""
    shared_fetch_backend: str = ""
    domain_cooldown_until: str = ""


class ProtectedSourceError(RuntimeError):
    error_kind = "cloudflare_challenge"


@dataclass
class DomainSessionUnlockResult:
    domain: str
    status: str
    detail: str
    final_url: str = ""
    user_agent: str = ""
    cookies: list[dict[str, Any]] = field(default_factory=list)
    profile_path: str = ""
    html: str = ""


class CatalogBrowserError(RuntimeError):
    error_kind = "catalog_browser_connection_failed"


class CatalogBrowserPortBusyError(CatalogBrowserError):
    error_kind = "catalog_browser_port_busy"


class CatalogBrowserConnectionError(CatalogBrowserError):
    error_kind = "catalog_browser_connection_failed"


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


@dataclass
class MerchantCatalogPreviewResult:
    source_url: str
    source_name: str
    group_name: str
    generated_at: str
    candidate_urls: list[dict[str, Any]]
    items: list[dict[str, Any]]
    rejected_items: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    options: dict[str, Any]


def merchant_catalog_preview_payload(result: MerchantCatalogPreviewResult) -> dict[str, Any]:
    return {
        "source_url": result.source_url,
        "source_name": result.source_name,
        "group_name": result.group_name,
        "generated_at": result.generated_at,
        "candidate_urls": result.candidate_urls,
        "items": result.items,
        "rejected_items": result.rejected_items,
        "failures": result.failures,
        "options": result.options,
        "counts": {
            "candidate_urls": len(result.candidate_urls),
            "items": len(result.items),
            "rejected_items": len(result.rejected_items),
            "failures": len(result.failures),
        },
    }


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


def summarize_task_error(message: str, kind: str = "") -> str:
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    if not text:
        return ""
    lowered = text.lower()
    if kind == "domain_cooldown" or "采集冷却" in text or "同域名保护等待" in text:
        return "同一站点刚刚失败，本轮不重复请求；下一轮会自动再试。"
    if kind == "domain_session_required":
        return "该站点需要先初始化采集会话，再执行库存检测。"
    if kind == "scrapling_browser_failed" or "launch_persistent_context" in lowered or "executable doesn't exist" in lowered:
        return "高兼容浏览器启动失败，请先在系统设置里检测 Scrapling，或切换为标准/增强模式。"
    if kind == "http_error" and ("http 403" in lowered or " 403" in lowered):
        return "目标站返回 403，当前出口没有拿到真实商品页。"
    if kind == "empty_response":
        return "采集后返回空页面，没有可解析内容。"
    if kind == "parse_unknown":
        return "页面已获取，但解析器没有找到明确的有货/售罄信号。"
    if kind == "cloudflare_challenge":
        if "冷却中" in text:
            return text
        stripped = re.sub(r"^.*?[:：]\s*", "", text).strip()
        if stripped:
            return stripped
    return text


def diagnostic_attempt_chain(attempts: list[dict[str, str]] | list[FetchAttempt] | None) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    for item in attempts or []:
        if isinstance(item, FetchAttempt):
            payload = fetch_attempt_to_payload(item)
        elif isinstance(item, dict):
            payload = {
                "backend": str(item.get("backend") or ""),
                "status": str(item.get("status") or ""),
                "error_kind": str(item.get("error_kind") or ""),
                "detail": sanitize_firecrawl_detail(str(item.get("detail") or "")),
                "final_url": str(item.get("final_url") or ""),
            }
        else:
            continue
        if not payload["backend"] and not payload["error_kind"]:
            continue
        chain.append(
            {
                "backend": payload["backend"],
                "status": payload["status"] or ("failed" if payload["error_kind"] else "success"),
                "error_kind": payload["error_kind"],
                "detail": summarize_task_error(payload["detail"], payload["error_kind"])[:240],
                "final_url": payload["final_url"],
            }
        )
    return chain[-8:]


def stock_check_diagnostic(
    error_kind: str,
    detail: str,
    attempts: list[dict[str, str]] | list[FetchAttempt] | None = None,
    backend_used: str = "",
    domain: str = "",
) -> dict[str, Any]:
    kind = str(error_kind or "").strip()
    clean_detail = summarize_task_error(detail, kind)
    attempt_chain = diagnostic_attempt_chain(attempts)
    labels = {
        "domain_session_required": ("需要采集会话", "先初始化或导入该站点会话，再重新检测。"),
        "cloudflare_challenge": ("页面被保护", "系统拿到的是保护页，不是商品页；可尝试外部 solver、会话导入或换公开页面。"),
        "scrapling_browser_failed": ("高兼容浏览器失败", "到系统设置检测 Scrapling；若缺浏览器依赖，先修复依赖或切换为标准/增强模式。"),
        "scrapling_challenge_failed": ("高兼容仍失败", "高兼容模式仍没有拿到真实商品内容；建议导入会话或配置外部 solver。"),
        "domain_cooldown": ("同站点已冷却", "本轮不会继续请求同一域名；冷却结束后会自动再试。"),
        "http_error": ("目标站返回错误", "检查状态码和出口网络；如果是 403，通常需要会话、代理出口或外部 solver。"),
        "timeout": ("请求超时", "稍后重试，或提高超时时间/降低并发。"),
        "empty_response": ("空页面", "页面已请求但没有可解析内容，建议切换增强模式或配置解析规则。"),
        "parse_unknown": ("无法判断库存", "页面已获取，但没有明确库存信号；请填写目标关键词或 CSS/XPath/正则规则。"),
        "firecrawl_credit_required": ("外部服务额度不足", "Firecrawl 额度不足，已停止继续消耗；建议改回本地采集或补充额度。"),
        "firecrawl_rate_limited": ("外部服务限流", "降低频率或稍后手动检测。"),
    }
    title, advice = labels.get(kind, ("采集失败", "查看尝试链路后调整采集模式、目标关键词或备用数据源。"))
    if not kind:
        title = "检测完成"
        advice = "未返回错误。"
    return {
        "title": title,
        "summary": clean_detail or title,
        "advice": advice,
        "error_kind": kind,
        "domain": domain,
        "backend_used": backend_used,
        "attempts": attempt_chain,
    }


def telegram_error_hint(description: str) -> str:
    normalized = description.lower()
    if "can't send messages to bots" in normalized or "cant send messages to bots" in normalized:
        return "Chat ID 指向了机器人账号，机器人不能给另一个机器人发消息；请填写用户、群组或频道的 Chat ID。"
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

    def profile_marker(self) -> str:
        return str(self.profile_dir).lower()

    def _process_owns_harness(self, process: psutil.Process) -> bool:
        try:
            info = getattr(process, "info", {}) or {}
            name = (info.get("name") or process.name() or "").lower()
            cmdline_parts = info.get("cmdline") or process.cmdline()
            cmdline = " ".join(cmdline_parts or []).lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
        if process.pid == os.getpid():
            return False
        if not any(token in name for token in ("chrome", "chromium", "edge")):
            return False
        owns_profile = self.profile_marker() in cmdline
        return owns_profile

    def _owned_browser_processes(self) -> list[psutil.Process]:
        victims: list[psutil.Process] = []
        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if self._process_owns_harness(process):
                    victims.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return victims

    def _listening_processes_on_port(self) -> list[psutil.Process]:
        listeners: list[psutil.Process] = []
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.AccessDenied, OSError):
            return listeners
        for connection in connections:
            local_address = connection.laddr
            if not local_address or getattr(local_address, "port", None) != self.port:
                continue
            status = getattr(connection, "status", "")
            if status and status != psutil.CONN_LISTEN:
                continue
            if not connection.pid or connection.pid == os.getpid():
                continue
            try:
                listeners.append(psutil.Process(connection.pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return listeners

    def _foreign_port_listeners(self) -> list[psutil.Process]:
        foreign: list[psutil.Process] = []
        for process in self._listening_processes_on_port():
            try:
                process_info = process.as_dict(attrs=["pid", "name", "cmdline"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if not self._process_info_owns_profile(process_info, process.pid):
                foreign.append(process)
        return foreign

    def _process_info_owns_profile(self, process_info: dict[str, Any], pid: int) -> bool:
        if pid == os.getpid():
            return False
        name = str(process_info.get("name") or "").lower()
        cmdline = " ".join(process_info.get("cmdline") or []).lower()
        if not any(token in name for token in ("chrome", "chromium", "edge")):
            return False
        return self.profile_marker() in cmdline

    def _assert_port_available_for_role(self) -> None:
        foreign = self._foreign_port_listeners()
        if not foreign:
            return
        first = foreign[0]
        try:
            process_name = first.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_name = "unknown"
        if self.role == "catalog":
            raise CatalogBrowserPortBusyError(
                f"商品入库浏览器端口 {self.port} 已被其他进程占用（PID {first.pid}, {process_name}）。"
                "请在系统设置中修改 CATALOG_DEBUG_PORT / 商品入库浏览器端口后重试。"
            )
        raise RuntimeError(f"{self.role} 浏览器调试端口 {self.port} 已被其他进程占用。")

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

        self._kill_zombies()
        self._clear_profile_locks()
        self._assert_port_available_for_role()

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
                log_activity(
                    "warning",
                    f"browser:{self.role}",
                    f"检测到 Cloudflare/Turnstile 受保护页面，停止本地浏览器重试：{url}",
                )
                raise ProtectedSourceError(f"{self.role} 浏览器被 Cloudflare 验证页拦截：{url}")
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
        victims = self._owned_browser_processes()
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


class BrowserFetcher:
    def __init__(self, harness: BrowserHarness) -> None:
        self.harness = harness

    def fetch(self, url: str, timeout_seconds: int) -> FetchResult:
        html_text = self.harness.fetch_html(url, timeout_seconds)
        return FetchResult(html=html_text, final_url=url, detail="ok")

    def rebuild(self, reason: str) -> None:
        self.harness.rebuild(reason)


class StaticHttpFetcher:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()

    def request_headers(self) -> dict[str, str]:
        return {
            "User-Agent": DEFAULT_BROWSER_USER_AGENT or STATIC_HTTP_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }

    def fetch(self, url: str, timeout_seconds: int) -> FetchResult:
        try:
            response: Response = self.session.get(
                url,
                headers=self.request_headers(),
                timeout=timeout_seconds,
                allow_redirects=True,
            )
        except requests.Timeout:
            return FetchResult(
                html="",
                final_url=url,
                error_kind="timeout",
                detail=f"static_http 请求超时：{url}",
            )
        except requests.RequestException as exc:
            message = str(exc)
            return FetchResult(
                html="",
                final_url=url,
                error_kind=classify_browser_error(message) or "request_error",
                detail=f"static_http 请求失败：{message}",
            )

        final_url = str(getattr(response, "url", "") or url)
        status_code = int(getattr(response, "status_code", 0) or 0)
        html_text = getattr(response, "text", "") or ""
        if looks_like_cloudflare_challenge(html_text, extract_page_title(html_text), final_url):
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="cloudflare_challenge",
                detail=f"static_http 被 Cloudflare 验证页拦截：{final_url}",
            )
        if status_code in {403, 429} or status_code >= 500:
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="http_error",
                detail=f"static_http HTTP {status_code}：{final_url}",
            )
        if not html_text:
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="empty_response",
                detail=f"static_http 返回了空 HTML：{final_url}",
            )
        return FetchResult(html=html_text, final_url=final_url, status_code=status_code, detail="ok")


class CurlCffiFetcher:
    def __init__(self, client: Any = None, session_provider: Callable[[str], dict[str, Any] | None] | None = None) -> None:
        self.client = client
        self.session_provider = session_provider or get_ready_domain_session_for_url

    def request_headers(self, session_payload: dict[str, Any] | None = None) -> dict[str, str]:
        user_agent = str(mapping_value(session_payload or {}, "user_agent", "") or "").strip()
        return {
            "User-Agent": user_agent or DEFAULT_BROWSER_USER_AGENT or STATIC_HTTP_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }

    def fetch(self, url: str, timeout_seconds: int) -> FetchResult:
        session_payload = self.session_provider(url) if self.session_provider else None
        try:
            response = self._request(url, timeout_seconds, session_payload)
        except ImportError as exc:
            return FetchResult(
                html="",
                final_url=url,
                error_kind="curl_cffi_unavailable",
                detail=f"curl_cffi 未安装或无法导入：{exc}",
            )
        except TimeoutError:
            return FetchResult(html="", final_url=url, error_kind="timeout", detail=f"curl_cffi 请求超时：{url}")
        except Exception as exc:
            message = str(exc)
            return FetchResult(
                html="",
                final_url=url,
                error_kind=classify_browser_error(message) or "request_error",
                detail=f"curl_cffi 请求失败：{message[:500]}",
            )

        final_url = str(getattr(response, "url", "") or url)
        status_code = int(getattr(response, "status_code", None) or getattr(response, "status", None) or 0)
        html_text = str(getattr(response, "text", "") or getattr(response, "content", "") or "")
        if looks_like_cloudflare_challenge(html_text, extract_page_title(html_text), final_url):
            if not session_payload:
                return FetchResult(
                    html="",
                    final_url=final_url,
                    status_code=status_code,
                    error_kind="domain_session_required",
                    detail=f"{fetch_domain_for_url(final_url) or '目标站'} 需要先初始化采集会话。",
                )
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="cloudflare_challenge",
                detail=f"curl_cffi 拿到的仍是 Cloudflare 验证页：{final_url}",
            )
        if status_code in {403, 429} or status_code >= 500:
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="http_error",
                detail=f"curl_cffi HTTP {status_code}：{final_url}",
            )
        if not html_text:
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="empty_response",
                detail=f"curl_cffi 返回了空 HTML：{final_url}",
            )
        detail = "curl_cffi ok"
        if session_payload:
            detail = "curl_cffi 复用域名会话成功"
        return FetchResult(html=html_text, final_url=final_url, status_code=status_code, detail=detail)

    def _request(self, url: str, timeout_seconds: int, session_payload: dict[str, Any] | None = None) -> Any:
        headers = self.request_headers(session_payload)
        cookies = domain_session_cookie_dict(session_payload)
        if self.client is not None:
            try:
                return self.client.get(url, timeout=timeout_seconds, headers=headers, cookies=cookies or None)
            except TypeError:
                return self.client.get(url, timeout=timeout_seconds, headers=headers)
        try:
            from curl_cffi import requests as curl_requests
        except Exception as exc:
            raise ImportError("curl_cffi.requests") from exc
        try:
            return curl_requests.get(
                url,
                headers=headers,
                cookies=cookies or None,
                timeout=timeout_seconds,
                impersonate="chrome",
                allow_redirects=True,
            )
        except TimeoutError:
            raise
        except Exception as exc:
            if any(token in str(exc).lower() for token in ("timeout", "timed out", "超时")):
                raise TimeoutError(str(exc)) from exc
            raise


class DomainSessionUnlocker:
    def unlock(
        self,
        url: str,
        target_keyword: str = "",
        timeout_seconds: int = DOMAIN_SESSION_UNLOCK_TIMEOUT_SECONDS,
    ) -> DomainSessionUnlockResult:
        if not validate_http_url(url):
            raise ValueError("解锁链接必须是有效的 http(s) 地址。")
        domain = fetch_domain_for_url(url)
        if not domain:
            raise ValueError("无法从链接中识别域名。")
        browser_binary = find_browser_binary()
        if not browser_binary:
            raise RuntimeError("未找到 Chromium/Chrome，无法初始化域名会话。")
        display = ensure_scrapling_display_for_headed()
        if not display and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
            raise RuntimeError("当前环境没有 DISPLAY/Xvfb，无法启动有头浏览器。")

        profile_path = domain_session_profile_path(domain)
        profile_path.mkdir(parents=True, exist_ok=True)
        timeout_seconds = max(15, min(300, int(timeout_seconds or DOMAIN_SESSION_UNLOCK_TIMEOUT_SECONDS)))
        deadline = time.monotonic() + timeout_seconds
        context = None
        try:
            sync_playwright = self._sync_playwright()
            with sync_playwright() as playwright:
                launch_kwargs: dict[str, Any] = {
                    "executable_path": browser_binary,
                    "headless": False,
                    "viewport": {"width": 1440, "height": 980},
                    "locale": "zh-CN",
                    "args": [
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                        "--window-size=1440,980",
                    ],
                }
                if DEFAULT_BROWSER_USER_AGENT:
                    launch_kwargs["user_agent"] = DEFAULT_BROWSER_USER_AGENT
                context = playwright.chromium.launch_persistent_context(
                    str(profile_path),
                    **launch_kwargs,
                )
                try:
                    context.add_init_script(
                        """
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en-US', 'en']});
                        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                        """
                    )
                except Exception:
                    pass
                page = context.pages[0] if context.pages else context.new_page()
                warmup_url = domain_session_warmup_url(url)
                if warmup_url and warmup_url.rstrip("/") != str(url).rstrip("/"):
                    try:
                        page.goto(warmup_url, wait_until="domcontentloaded", timeout=min(20000, timeout_seconds * 1000))
                        page.wait_for_timeout(1200)
                    except Exception:
                        pass
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                html_text = ""
                final_url = url
                challenge_seen = False
                keyword_seen = False
                while time.monotonic() < deadline:
                    try:
                        final_url = page.url or url
                        title = page.title()
                        html_text = page.content()
                    except Exception:
                        html_text = ""
                        title = ""
                    challenge_seen = looks_like_cloudflare_challenge(html_text, title, final_url)
                    keyword_seen = bool(target_keyword and re.search(re.escape(target_keyword), html_text, re.IGNORECASE))
                    if html_text and not challenge_seen and (not target_keyword or keyword_seen or len(html_text) > 6000):
                        break
                    page.wait_for_timeout(1500)
                user_agent = ""
                try:
                    user_agent = str(page.evaluate("navigator.userAgent") or "")
                except Exception:
                    user_agent = ""
                cookies = normalize_cookie_payload(context.cookies())
                if not html_text:
                    raise RuntimeError("浏览器没有返回可读取页面内容。")
                if looks_like_cloudflare_challenge(html_text, "", final_url):
                    detail = "仍停留在 Cloudflare/Turnstile 验证页；请保持窗口打开完成验证后再次点击解锁。"
                    return DomainSessionUnlockResult(
                        domain=domain,
                        status=DOMAIN_SESSION_STATUS_FAILED,
                        detail=detail,
                        final_url=final_url,
                        user_agent=user_agent,
                        cookies=cookies,
                        profile_path=str(profile_path),
                        html=html_text,
                    )
                if not cookies:
                    raise RuntimeError("浏览器已打开页面，但没有得到可复用 cookie。")
                detail = "域名会话已初始化，后续检测会优先复用 cookie。"
                if keyword_seen:
                    detail = "域名会话已初始化，并在页面中看到目标关键词。"
                return DomainSessionUnlockResult(
                    domain=domain,
                    status=DOMAIN_SESSION_STATUS_READY,
                    detail=detail,
                    final_url=final_url,
                    user_agent=user_agent,
                    cookies=cookies,
                    profile_path=str(profile_path),
                    html=html_text,
                )
        except Exception as exc:
            return DomainSessionUnlockResult(
                domain=domain,
                status=DOMAIN_SESSION_STATUS_FAILED,
                detail=str(exc)[:1000],
                final_url=url,
                profile_path=str(profile_path),
            )
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

    def _sync_playwright(self) -> Callable[..., Any]:
        try:
            from patchright.sync_api import sync_playwright

            return sync_playwright
        except Exception:
            try:
                from playwright.sync_api import sync_playwright

                return sync_playwright
            except Exception as exc:
                raise RuntimeError("Playwright/Patchright 不可用，请重新执行安装或升级脚本。") from exc


class ScraplingUnavailableError(RuntimeError):
    pass


@dataclass
class ScraplingResponseSnapshot:
    url: str
    status_code: int
    html_content: str


def scrapling_browser_fetch_worker(fetcher_name: str, url: str, kwargs: dict[str, Any], queue: multiprocessing.Queue) -> None:
    try:
        scrapling_module = importlib.import_module("scrapling")
        fetcher = getattr(scrapling_module, fetcher_name)
        response = fetcher.fetch(url, **kwargs)
        queue.put(
            {
                "ok": True,
                "url": str(getattr(response, "url", "") or url),
                "status_code": int(getattr(response, "status", None) or getattr(response, "status_code", None) or 0),
                "html": scrapling_response_html(response),
            }
        )
    except BaseException as exc:
        queue.put({"ok": False, "error": str(exc), "error_type": type(exc).__name__})


class ScraplingFetcher:
    def __init__(self, settings_payload: dict[str, Any], mode: str, client: Any = None) -> None:
        self.settings = settings_payload
        self.mode = normalize_scrapling_mode(mode)
        self.client = client

    def timeout_seconds(self, fallback: int) -> int:
        key = f"scrapling_timeout_{self.mode}"
        return int(self.settings.get(key) or fallback or DEFAULT_TIMEOUT_SECONDS)

    def source_config(self) -> dict[str, Any]:
        return raw_source_config(self.settings.get("source_config", {}))

    def configured_headers(self) -> dict[str, str]:
        config = self.source_config()
        raw_headers = config.get("headers")
        headers: dict[str, str] = {}
        if isinstance(raw_headers, dict):
            headers.update({str(key): str(value) for key, value in raw_headers.items() if str(key).strip() and str(value).strip()})
        elif isinstance(raw_headers, str) and raw_headers.strip():
            for line in raw_headers.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                if key and value:
                    headers[key] = value
        cookie = str(config.get("cookie") or "").strip()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def configured_cookies(self, url: str) -> list[dict[str, Any]]:
        config = self.source_config()
        cookies = config.get("cookies")
        if isinstance(cookies, list):
            return [cookie for cookie in cookies if isinstance(cookie, dict)]
        cookie_header = str(config.get("cookie") or "").strip()
        if not cookie_header:
            return []
        domain = urlparse(url).hostname or ""
        parsed_cookies: list[dict[str, Any]] = []
        for item in cookie_header.split(";"):
            if "=" not in item:
                continue
            name, value = item.split("=", 1)
            name = name.strip()
            value = value.strip()
            if name:
                parsed_cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})
        return parsed_cookies

    def configured_user_data_dir(self, url: str) -> str:
        config = self.source_config()
        explicit_dir = str(config.get("user_data_dir") or "").strip()
        if explicit_dir:
            return explicit_dir
        if parse_setting_bool(config.get("persistent_session"), False):
            domain = re.sub(r"[^a-zA-Z0-9._-]+", "_", urlparse(url).hostname or "site")
            profile_dir = DATA_DIR / "scrapling_profiles" / domain
            profile_dir.mkdir(parents=True, exist_ok=True)
            return str(profile_dir)
        return ""

    def browser_kwargs(self, timeout_seconds: int) -> dict[str, Any]:
        timeout_ms = max(5, int(timeout_seconds)) * 1000
        flags = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--start-maximized"]
        browser_binary = find_browser_binary()
        stealth_mode = self.mode == "stealth"
        headless = bool(self.settings.get("scrapling_headless", True))
        if not headless:
            ensure_scrapling_display_for_headed()
            flags.append("--window-size=1720,1120")
        kwargs: dict[str, Any] = {
            "headless": headless,
            "disable_resources": not stealth_mode,
            "block_ads": not stealth_mode,
            "load_dom": True,
            "network_idle": self.mode != "standard",
            "timeout": timeout_ms,
            "wait": 8000 if stealth_mode else 300,
            "extra_flags": flags,
            "extra_headers": {"Accept-Language": "en-US,en;q=0.9" if stealth_mode else "zh-CN,zh;q=0.9,en;q=0.8"},
        }
        if browser_binary:
            kwargs["executable_path"] = browser_binary
        if DEFAULT_BROWSER_USER_AGENT:
            kwargs["useragent"] = DEFAULT_BROWSER_USER_AGENT
        if self.mode == "stealth":
            kwargs.update(
                {
                    "real_chrome": True,
                    "locale": "en-US",
                    "hide_canvas": True,
                    "block_webrtc": True,
                    "allow_webgl": True,
                    "solve_cloudflare": True,
                }
            )
        return kwargs

    def apply_source_config_to_browser_kwargs(self, kwargs: dict[str, Any], url: str) -> dict[str, Any]:
        headers = self.configured_headers()
        if headers:
            kwargs["extra_headers"] = {**dict(kwargs.get("extra_headers") or {}), **headers}
        cookies = self.configured_cookies(url)
        if cookies:
            kwargs["cookies"] = cookies
        user_data_dir = self.configured_user_data_dir(url)
        if user_data_dir:
            kwargs["user_data_dir"] = user_data_dir
        config = self.source_config()
        wait_selector = str(config.get("wait_selector") or "").strip()
        if wait_selector:
            kwargs["wait_selector"] = wait_selector
        if "google_search" in config:
            kwargs["google_search"] = parse_setting_bool(config.get("google_search"), True)
        return kwargs

    def static_kwargs(self, timeout_seconds: int) -> dict[str, Any]:
        headers = {
            "User-Agent": DEFAULT_BROWSER_USER_AGENT or STATIC_HTTP_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }
        headers.update(self.configured_headers())
        return {
            "timeout": timeout_seconds,
            "follow_redirects": True,
            "retries": 1,
            "headers": headers,
        }

    def fetch(self, url: str, timeout_seconds: int) -> FetchResult:
        if not self.settings.get("scrapling_enabled", True):
            return FetchResult(html="", final_url=url, error_kind="scrapling_disabled", detail="Scrapling 采集引擎未启用。")
        timeout_seconds = self.timeout_seconds(timeout_seconds)
        try:
            response = self._fetch_response(url, timeout_seconds)
        except ImportError as exc:
            return FetchResult(
                html="",
                final_url=url,
                error_kind="scrapling_unavailable",
                detail=f"Scrapling fetcher 依赖未安装或无法导入：{exc}",
            )
        except TimeoutError:
            return FetchResult(html="", final_url=url, error_kind="timeout", detail=f"Scrapling {self.mode} 请求超时：{url}")
        except Exception as exc:
            message = str(exc)
            return FetchResult(
                html="",
                final_url=url,
                error_kind=self.classify_exception(message),
                detail=f"Scrapling {self.mode} 请求失败：{message[:500]}",
            )
        return self.response_to_fetch_result(response, url)

    def _fetch_response(self, url: str, timeout_seconds: int) -> Any:
        if self.client is not None:
            return self.client.fetch(self.mode, url, timeout_seconds)
        try:
            scrapling_module = importlib.import_module("scrapling")
        except ModuleNotFoundError as exc:
            raise ImportError("scrapling") from exc
        if self.mode == "standard":
            try:
                requests_fetcher_module = importlib.import_module("scrapling.fetchers.requests")
                fetcher_session = getattr(requests_fetcher_module, "FetcherSession")
            except (ModuleNotFoundError, AttributeError) as exc:
                raise ImportError("FetcherSession") from exc
            with fetcher_session(**self.static_kwargs(timeout_seconds)) as session:
                return session.get(url)
        fetcher_name = "StealthyFetcher" if self.mode == "stealth" else "DynamicFetcher"
        try:
            fetcher = getattr(scrapling_module, fetcher_name)
        except AttributeError as exc:
            raise ImportError(fetcher_name) from exc
        return self._fetch_browser_response_in_process(fetcher_name, url, timeout_seconds)

    def _fetch_browser_response_in_process(self, fetcher_name: str, url: str, timeout_seconds: int) -> ScraplingResponseSnapshot:
        kwargs = self.apply_source_config_to_browser_kwargs(self.browser_kwargs(timeout_seconds), url)
        queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=1)
        process = multiprocessing.Process(
            target=scrapling_browser_fetch_worker,
            args=(fetcher_name, url, kwargs, queue),
            daemon=True,
        )
        process.start()
        hard_timeout = max(10, int(timeout_seconds) + 5)
        process.join(hard_timeout)
        if process.is_alive():
            process.terminate()
            process.join(3)
            if process.is_alive():
                process.kill()
                process.join(2)
            raise TimeoutError(f"Scrapling {self.mode} 超过 {hard_timeout} 秒仍未返回。")
        if queue.empty():
            if process.exitcode:
                raise RuntimeError(f"Scrapling {self.mode} 子进程异常退出：exit {process.exitcode}")
            raise RuntimeError(f"Scrapling {self.mode} 子进程没有返回结果。")
        payload = queue.get()
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("error") or payload.get("error_type") or "Scrapling 子进程失败"))
        return ScraplingResponseSnapshot(
            url=str(payload.get("url") or url),
            status_code=int(payload.get("status_code") or 0),
            html_content=str(payload.get("html") or ""),
        )

    def response_to_fetch_result(self, response: Any, fallback_url: str) -> FetchResult:
        final_url = str(getattr(response, "url", "") or fallback_url)
        status_code = int(getattr(response, "status", None) or getattr(response, "status_code", None) or 0)
        html_text = scrapling_response_html(response)
        if looks_like_cloudflare_challenge(html_text, extract_page_title(html_text), final_url):
            if self.mode == "stealth":
                return FetchResult(
                    html="",
                    final_url=final_url,
                    status_code=status_code,
                    error_kind="cloudflare_challenge",
                    detail="Scrapling 高兼容已尝试处理 Cloudflare managed challenge，但本次仍未拿到商品页。",
                )
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="scrapling_challenge_upgrade_required",
                detail=f"Scrapling {self.mode} 需要升级到更高兼容模式。",
            )
        if status_code in {403, 429} or status_code >= 500:
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="http_error",
                detail=f"Scrapling {self.mode} HTTP {status_code}：{final_url}",
            )
        if not html_text:
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="empty_response",
                detail=f"Scrapling {self.mode} 返回了空 HTML：{final_url}",
            )
        return FetchResult(
            html=html_text,
            final_url=final_url,
            status_code=status_code,
            detail=f"Scrapling {self.mode} ok",
        )

    def classify_exception(self, message: str) -> str:
        lowered = message.lower()
        if any(token in lowered for token in ("timeout", "timed out", "超时")):
            return "timeout"
        if any(token in lowered for token in ("browser", "playwright", "patchright", "chromium", "chrome")):
            return "scrapling_browser_failed"
        return classify_browser_error(message) or "request_error"


class ScraplingSessionManager:
    def __init__(self, settings_payload: dict[str, Any], client: Any = None) -> None:
        self.settings = settings_payload
        self.client = client

    def fetcher(self, mode: str) -> ScraplingFetcher:
        return ScraplingFetcher(self.settings, mode, self.client)


class HeadedSessionFetcher:
    def __init__(self, settings_payload: dict[str, Any], unlocker: DomainSessionUnlocker | None = None) -> None:
        self.settings = settings_payload
        self.unlocker = unlocker or DomainSessionUnlocker()

    def fetch(self, url: str, timeout_seconds: int) -> FetchResult:
        timeout = int(
            self.settings.get("scrapling_timeout_stealth")
            or self.settings.get("domain_session_unlock_timeout_seconds")
            or timeout_seconds
            or DOMAIN_SESSION_UNLOCK_TIMEOUT_SECONDS
        )
        source_config = raw_source_config(self.settings.get("source_config", {}))
        target_keyword = str(source_config.get("target_keyword") or self.settings.get("target_keyword") or "").strip()
        result = self.unlocker.unlock(url, target_keyword=target_keyword, timeout_seconds=timeout)
        html_text = result.html or ""
        final_url = result.final_url or url
        if result.status == DOMAIN_SESSION_STATUS_READY and html_text:
            if looks_like_cloudflare_challenge(html_text, extract_page_title(html_text), final_url):
                return FetchResult(
                    html="",
                    final_url=final_url,
                    error_kind="cloudflare_challenge",
                    detail="有头会话仍停留在受保护页面，未拿到商品内容。",
                )
            return FetchResult(
                html=html_text,
                final_url=final_url,
                detail="headed_session ok",
            )
        if html_text and looks_like_cloudflare_challenge(html_text, extract_page_title(html_text), final_url):
            return FetchResult(
                html="",
                final_url=final_url,
                error_kind="cloudflare_challenge",
                detail=result.detail or "有头会话仍停留在受保护页面，未拿到商品内容。",
            )
        detail = result.detail or "有头会话没有拿到可解析商品页。"
        error_kind = classify_browser_error(detail) or "headed_session_failed"
        if any(token in detail.lower() for token in ("timeout", "timed out", "超时")):
            error_kind = "timeout"
        return FetchResult(html="", final_url=final_url, error_kind=error_kind, detail=detail)


def scrapling_response_html(response: Any) -> str:
    for attr in ("html_content", "text", "body", "content"):
        value = getattr(response, attr, "")
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
        if isinstance(value, bytes):
            return value.decode(getattr(response, "encoding", "utf-8") or "utf-8", errors="replace")
        if value:
            return str(value)
    return ""


def sanitize_firecrawl_detail(value: str, api_key: str = "") -> str:
    text = str(value or "")
    if api_key:
        text = text.replace(api_key, "<hidden-firecrawl-key>")
    return text[:500]


def firecrawl_response_error(response: Response, api_key: str = "") -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if value:
                return sanitize_firecrawl_detail(str(value), api_key)
    return sanitize_firecrawl_detail(getattr(response, "text", "") or "", api_key)


def firecrawl_http_error_result(response: Response, url: str, api_key: str, operation: str) -> FetchResult | None:
    status_code = int(getattr(response, "status_code", 0) or 0)
    error_text = firecrawl_response_error(response, api_key)
    error_lower = error_text.lower()
    if status_code == 401:
        return FetchResult(
            html="",
            final_url=url,
            status_code=status_code,
            error_kind="firecrawl_auth_error",
            detail="Firecrawl 认证失败，请检查 API Key。",
        )
    if status_code == 403:
        if "zero data retention" in error_lower or "zdr" in error_lower:
            return FetchResult(
                html="",
                final_url=url,
                status_code=status_code,
                error_kind="firecrawl_zdr_not_enabled",
                detail="当前 Firecrawl 账号未开通 zeroDataRetention。请在系统设置关闭 zeroDataRetention 后重试，或联系 Firecrawl 开通 ZDR。",
            )
        return FetchResult(
            html="",
            final_url=url,
            status_code=status_code,
            error_kind="firecrawl_permission_error",
            detail=f"Firecrawl 拒绝了 {operation} 请求：{error_text or '权限不足或当前账号不允许该操作。'}",
        )
    if status_code == 402:
        return FetchResult(html="", final_url=url, status_code=status_code, error_kind="firecrawl_credit_required", detail="Firecrawl 额度不足或需要付费额度。")
    if status_code == 429:
        return FetchResult(html="", final_url=url, status_code=status_code, error_kind="firecrawl_rate_limited", detail="Firecrawl 请求频率受限，请降低并发或稍后重试。")
    if status_code == 400:
        return FetchResult(
            html="",
            final_url=url,
            status_code=status_code,
            error_kind="firecrawl_bad_request",
            detail=f"Firecrawl {operation} 参数不被接受：{error_text or '请求参数错误。'}",
        )
    if status_code >= 500:
        return FetchResult(html="", final_url=url, status_code=status_code, error_kind="firecrawl_upstream_error", detail=f"Firecrawl 上游服务异常（HTTP {status_code}）。")
    return None


def firecrawl_diagnostic_advice(error_kind: str) -> str:
    if error_kind == "firecrawl_auth_error":
        return "检查 API Key 是否完整、是否属于当前 Firecrawl 账号，或者重新生成 Key 后再测试。"
    if error_kind == "firecrawl_zdr_not_enabled":
        return "当前账号没有开通 zeroDataRetention，请先关闭 zeroDataRetention 再测试。"
    if error_kind == "firecrawl_permission_error":
        return "检查账号权限、proxy 模式和 zeroDataRetention 配置。"
    if error_kind == "firecrawl_credit_required":
        return "Firecrawl 额度不足，需要充值或更换有额度的 Key。"
    if error_kind == "firecrawl_rate_limited":
        return "请求频率受限，稍后重试或降低商品入库并发。"
    if error_kind == "cloudflare_challenge":
        return "Firecrawl 仍返回受保护页面；可以改用 Webhook、手动录入或替代公开页面。"
    if error_kind == "timeout":
        return "请求超时，检查 API URL 网络连通性，或适当提高 Firecrawl 超时时间。"
    if error_kind == "firecrawl_bad_response":
        return "Firecrawl 返回结构异常，确认 API URL 是否指向 Firecrawl v2 服务。"
    if error_kind == "firecrawl_disabled":
        return "先勾选启用 Firecrawl 外部采集后端。"
    return "检查 Firecrawl API URL、API Key、proxy 模式和账号状态后重试。"


class FirecrawlClient:
    def __init__(self, settings_payload: dict[str, Any], session: requests.Session | None = None) -> None:
        self.settings = settings_payload
        self.session = session or requests.Session()
        self.api_url = str(settings_payload.get("firecrawl_api_url") or DEFAULT_FIRECRAWL_API_URL).rstrip("/")
        self.api_key = str(settings_payload.get("firecrawl_api_key") or "").strip()

    def headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def scrape_payload(self, url: str) -> dict[str, Any]:
        return {
            "url": url,
            "formats": ["rawHtml", "html", "markdown", "links"],
            "maxAge": int(self.settings.get("firecrawl_max_age_ms", 0) or 0),
            "storeInCache": bool(self.settings.get("firecrawl_store_in_cache", False)),
            "zeroDataRetention": bool(self.settings.get("firecrawl_zero_data_retention", False)),
            "proxy": str(self.settings.get("firecrawl_proxy_mode") or "basic"),
        }

    def map_payload(self, url: str, search: str = "", limit: int = 50) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": url,
            "limit": max(1, min(250, int(limit or DEFAULT_FIRECRAWL_CATALOG_LIMIT))),
            "sitemap": "include",
        }
        if search:
            payload["search"] = search
        return payload

    def map(self, url: str, search: str = "", limit: int = 50) -> FetchResult:
        if not self.settings.get("firecrawl_enabled"):
            return FetchResult(html="", final_url=url, error_kind="firecrawl_disabled", detail="Firecrawl 未启用。")
        if not self.api_key:
            return FetchResult(html="", final_url=url, error_kind="firecrawl_auth_error", detail="Firecrawl API key 未配置。")

        timeout_seconds = int(self.settings.get("firecrawl_timeout_seconds") or DEFAULT_FIRECRAWL_TIMEOUT_SECONDS)
        try:
            response: Response = self.session.post(
                f"{self.api_url}/v2/map",
                headers=self.headers(),
                json=self.map_payload(url, search, limit),
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            return FetchResult(html="", final_url=url, error_kind="timeout", detail="Firecrawl map 请求超时。")
        except requests.RequestException as exc:
            return FetchResult(
                html="",
                final_url=url,
                error_kind="firecrawl_request_error",
                detail=f"Firecrawl map 请求失败：{sanitize_firecrawl_detail(str(exc), self.api_key)}",
            )

        http_error = firecrawl_http_error_result(response, url, self.api_key, "map")
        if http_error:
            return http_error

        try:
            payload = response.json()
        except ValueError:
            return FetchResult(html="", final_url=url, status_code=response.status_code, error_kind="firecrawl_bad_response", detail="Firecrawl map 返回了非 JSON 响应。")
        if not isinstance(payload, dict):
            return FetchResult(html="", final_url=url, status_code=response.status_code, error_kind="firecrawl_bad_response", detail="Firecrawl map 响应结构不正确。")

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            return FetchResult(html="", final_url=url, status_code=response.status_code, error_kind="firecrawl_bad_response", detail="Firecrawl map 响应缺少 data 对象。")
        links_payload = data.get("links", [])
        links: list[str] = []
        if isinstance(links_payload, list):
            for item in links_payload:
                if isinstance(item, str):
                    links.append(item)
                elif isinstance(item, dict):
                    candidate = str(item.get("url") or item.get("href") or item.get("link") or "").strip()
                    if candidate:
                        links.append(candidate)
        if not links:
            return FetchResult(html="", final_url=url, status_code=response.status_code, error_kind="empty_response", detail="Firecrawl map 未发现候选链接。")
        return FetchResult(
            html=json.dumps({"links": links}, ensure_ascii=False),
            final_url=str(data.get("url") or url),
            status_code=response.status_code,
            detail=f"Firecrawl map 发现 {len(links)} 个链接。",
        )

    def scrape(self, url: str) -> FetchResult:
        if not self.settings.get("firecrawl_enabled"):
            return FetchResult(
                html="",
                final_url=url,
                error_kind="firecrawl_disabled",
                detail="Firecrawl 未启用。",
            )
        if not self.api_key:
            return FetchResult(
                html="",
                final_url=url,
                error_kind="firecrawl_auth_error",
                detail="Firecrawl API key 未配置。",
            )

        timeout_seconds = int(self.settings.get("firecrawl_timeout_seconds") or DEFAULT_FIRECRAWL_TIMEOUT_SECONDS)
        try:
            response: Response = self.session.post(
                f"{self.api_url}/v2/scrape",
                headers=self.headers(),
                json=self.scrape_payload(url),
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            return FetchResult(html="", final_url=url, error_kind="timeout", detail="Firecrawl scrape 请求超时。")
        except requests.RequestException as exc:
            return FetchResult(
                html="",
                final_url=url,
                error_kind="firecrawl_request_error",
                detail=f"Firecrawl scrape 请求失败：{sanitize_firecrawl_detail(str(exc), self.api_key)}",
            )

        http_error = firecrawl_http_error_result(response, url, self.api_key, "scrape")
        if http_error:
            return http_error

        try:
            payload = response.json()
        except ValueError:
            return FetchResult(html="", final_url=url, status_code=response.status_code, error_kind="firecrawl_bad_response", detail="Firecrawl 返回了非 JSON 响应。")
        if not isinstance(payload, dict):
            return FetchResult(html="", final_url=url, status_code=response.status_code, error_kind="firecrawl_bad_response", detail="Firecrawl 响应结构不正确。")

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            return FetchResult(html="", final_url=url, status_code=response.status_code, error_kind="firecrawl_bad_response", detail="Firecrawl 响应缺少 data 对象。")

        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        final_url = str(metadata.get("url") or metadata.get("sourceURL") or data.get("url") or url)
        status_code = int(metadata.get("statusCode") or response.status_code or 0)
        html_text = str(data.get("rawHtml") or data.get("html") or data.get("markdown") or "")
        if looks_like_cloudflare_challenge(html_text, extract_page_title(html_text), final_url):
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="cloudflare_challenge",
                detail="Firecrawl 返回的内容仍是 Cloudflare / Turnstile 验证页。",
            )
        if not html_text:
            return FetchResult(
                html="",
                final_url=final_url,
                status_code=status_code,
                error_kind="firecrawl_bad_response",
                detail="Firecrawl 响应未包含 rawHtml/html/markdown 内容。",
            )
        detail = "ok"
        if data.get("markdown"):
            detail = str(data.get("markdown"))[:300]
        return FetchResult(html=html_text, final_url=final_url, status_code=status_code, detail=detail)


class FirecrawlFetcher:
    def __init__(self, settings_payload: dict[str, Any], client: FirecrawlClient | None = None) -> None:
        self.client = client or FirecrawlClient(settings_payload)

    def fetch(self, url: str, timeout_seconds: int) -> FetchResult:
        return self.client.scrape(url)


class FirecrawlCatalogProvider:
    def __init__(self, settings_payload: dict[str, Any], client: FirecrawlClient | None = None) -> None:
        self.settings = settings_payload
        self.client = client or FirecrawlClient(settings_payload)

    def scrape(self, url: str) -> FetchResult:
        return self.client.scrape(url)

    def map(self, url: str, search: str = "", limit: int = 50) -> FetchResult:
        return self.client.map(url, search, limit)


class ExternalInputFetcher:
    def __init__(self, strategy: str) -> None:
        self.strategy = strategy

    def fetch(self, url: str, timeout_seconds: int) -> FetchResult:
        label = "手动录入" if self.strategy == FETCH_STRATEGY_MANUAL else "Webhook"
        return FetchResult(
            html="",
            final_url=url,
            error_kind=f"{self.strategy}_pending",
            detail=f"{label}采集方式等待外部库存写入，当前轮询不会请求目标页面。",
        )


def scrapling_mode_for_backend(backend: str) -> str:
    if backend == FETCH_STRATEGY_SCRAPLING_STEALTH:
        return "stealth"
    if backend == FETCH_STRATEGY_SCRAPLING_DYNAMIC:
        return "dynamic"
    return "standard"


class FetcherSelector:
    def __init__(
        self,
        static_http_fetcher: StaticHttpFetcher | None = None,
        curl_cffi_fetcher: CurlCffiFetcher | None = None,
        firecrawl_fetcher: FirecrawlFetcher | None = None,
        external_solver_collector: ExternalSolverCollector | None = None,
        scrapling_client: Any = None,
        headed_session_fetcher: HeadedSessionFetcher | None = None,
    ) -> None:
        self.static_http_fetcher = static_http_fetcher or StaticHttpFetcher()
        self.curl_cffi_fetcher = curl_cffi_fetcher or CurlCffiFetcher()
        self.firecrawl_fetcher = firecrawl_fetcher
        self.external_solver_collector = external_solver_collector or ExternalSolverCollector()
        self.scrapling_client = scrapling_client
        self.headed_session_fetcher = headed_session_fetcher

    def settings_for_task(self, settings_payload: dict[str, Any] | None, task: Any) -> dict[str, Any]:
        effective = dict(settings_payload or {})
        effective["source_config"] = raw_source_config(mapping_value(task, "source_config", "{}"))
        target_keyword = str(mapping_value(task, "target_keyword", "") or "").strip()
        if target_keyword and isinstance(effective["source_config"], dict):
            effective["source_config"].setdefault("target_keyword", target_keyword)
        return effective

    def select(
        self,
        task: Any,
        browser_harness: BrowserHarness,
        settings_payload: dict[str, Any] | None = None,
    ) -> BrowserFetcher | StaticHttpFetcher | CurlCffiFetcher | FirecrawlFetcher | ExternalInputFetcher | ScraplingFetcher | HeadedSessionFetcher:
        strategy = task_fetch_strategy(task)
        if strategy == FETCH_STRATEGY_CURL_CFFI:
            return self.curl_cffi_fetcher
        if strategy == FETCH_STRATEGY_FIRECRAWL:
            if self.firecrawl_fetcher is not None:
                return self.firecrawl_fetcher
            return FirecrawlFetcher(settings_payload or {})
        if strategy in SCRAPLING_FETCH_STRATEGIES:
            return ScraplingFetcher(settings_payload or {}, scrapling_mode_for_backend(strategy), self.scrapling_client)
        if strategy == FETCH_STRATEGY_HEADED_SESSION:
            return self.headed_session_fetcher or HeadedSessionFetcher(settings_payload or {})
        if strategy in STATIC_HTTP_FETCH_STRATEGIES:
            return self.static_http_fetcher
        if strategy in EXTERNAL_INPUT_FETCH_STRATEGIES:
            return ExternalInputFetcher(strategy)
        return BrowserFetcher(browser_harness)

    def fetcher_for_backend(
        self,
        backend: str,
        browser_harness: BrowserHarness,
        settings_payload: dict[str, Any] | None = None,
    ) -> BrowserFetcher | StaticHttpFetcher | CurlCffiFetcher | FirecrawlFetcher | ExternalInputFetcher | ScraplingFetcher | HeadedSessionFetcher:
        if backend == FETCH_STRATEGY_CURL_CFFI:
            return self.curl_cffi_fetcher
        if backend == FETCH_STRATEGY_FIRECRAWL:
            if self.firecrawl_fetcher is not None:
                return self.firecrawl_fetcher
            return FirecrawlFetcher(settings_payload or {})
        if backend in SCRAPLING_FETCH_STRATEGIES:
            return ScraplingFetcher(settings_payload or {}, scrapling_mode_for_backend(backend), self.scrapling_client)
        if backend == FETCH_STRATEGY_HEADED_SESSION:
            return self.headed_session_fetcher or HeadedSessionFetcher(settings_payload or {})
        if backend == FETCH_STRATEGY_STATIC_HTTP:
            return self.static_http_fetcher
        if backend in EXTERNAL_INPUT_FETCH_STRATEGIES:
            return ExternalInputFetcher(backend)
        return BrowserFetcher(browser_harness)

    def backends_for_strategy(
        self,
        task: Any,
        settings_payload: dict[str, Any] | None = None,
        context: str = "monitor",
    ) -> list[str]:
        strategy = task_fetch_strategy(task)
        settings_payload = settings_payload or {}
        firecrawl_allowed = firecrawl_allowed_for_context(settings_payload, context)
        if collector_strategy_for_task(task) == COLLECTOR_EXTERNAL_SOLVER:
            return [COLLECTOR_EXTERNAL_SOLVER]
        if strategy in EXTERNAL_INPUT_FETCH_STRATEGIES:
            return [strategy]
        if strategy in {
            FETCH_STRATEGY_SCRAPLING_STANDARD,
            FETCH_STRATEGY_SCRAPLING_DYNAMIC,
            FETCH_STRATEGY_SCRAPLING_STEALTH,
            FETCH_STRATEGY_CURL_CFFI,
            FETCH_STRATEGY_HEADED_SESSION,
        }:
            return [strategy]
        if strategy == FETCH_STRATEGY_MULTI_ENGINE:
            return [
                FETCH_STRATEGY_CURL_CFFI,
                FETCH_STRATEGY_SCRAPLING_STANDARD,
                FETCH_STRATEGY_SCRAPLING_DYNAMIC,
                FETCH_STRATEGY_SCRAPLING_STEALTH,
                FETCH_STRATEGY_HEADED_SESSION,
            ]
        if strategy == FETCH_STRATEGY_SCRAPLING_ADAPTIVE:
            return [
                FETCH_STRATEGY_SCRAPLING_STANDARD,
                FETCH_STRATEGY_SCRAPLING_DYNAMIC,
                FETCH_STRATEGY_SCRAPLING_STEALTH,
            ]
        if strategy == FETCH_STRATEGY_FIRECRAWL:
            if context == "monitor":
                return [FETCH_STRATEGY_SCRAPLING_STEALTH]
            return [FETCH_STRATEGY_FIRECRAWL]
        if strategy == FETCH_STRATEGY_FIRECRAWL_THEN_STATIC:
            if context == "monitor":
                return [FETCH_STRATEGY_SCRAPLING_STEALTH]
            return ([FETCH_STRATEGY_FIRECRAWL] if firecrawl_allowed else []) + [FETCH_STRATEGY_STATIC_HTTP]
        if strategy == FETCH_STRATEGY_STATIC_THEN_FIRECRAWL:
            if context == "monitor":
                return [FETCH_STRATEGY_SCRAPLING_STANDARD, FETCH_STRATEGY_SCRAPLING_STEALTH]
            return [FETCH_STRATEGY_STATIC_HTTP] + ([FETCH_STRATEGY_FIRECRAWL] if firecrawl_allowed else [])
        if strategy == FETCH_STRATEGY_FIRECRAWL_THEN_BROWSER:
            if context == "monitor":
                return [FETCH_STRATEGY_SCRAPLING_STEALTH]
            return ([FETCH_STRATEGY_FIRECRAWL] if firecrawl_allowed else []) + [FETCH_STRATEGY_BROWSER]
        if strategy == FETCH_STRATEGY_ADAPTIVE:
            if context == "monitor":
                return [
                    FETCH_STRATEGY_SCRAPLING_STANDARD,
                    FETCH_STRATEGY_SCRAPLING_DYNAMIC,
                    FETCH_STRATEGY_SCRAPLING_STEALTH,
                ]
            backends = [FETCH_STRATEGY_STATIC_HTTP, FETCH_STRATEGY_BROWSER]
            if context != "monitor" and firecrawl_allowed:
                backends.append(FETCH_STRATEGY_FIRECRAWL)
            return backends
        if strategy in STATIC_HTTP_FETCH_STRATEGIES:
            return [FETCH_STRATEGY_STATIC_HTTP]
        return [FETCH_STRATEGY_BROWSER]

    def should_try_next_backend(
        self,
        result: FetchResult,
        next_backend: str,
        settings_payload: dict[str, Any] | None = None,
    ) -> bool:
        settings_payload = settings_payload or {}
        if not result.error_kind:
            return False
        if next_backend == FETCH_STRATEGY_CURL_CFFI:
            return result.error_kind in {
                "timeout",
                "request_error",
                "empty_response",
                "http_error",
                "scrapling_browser_failed",
                "scrapling_unavailable",
                "scrapling_disabled",
            }
        if next_backend in SCRAPLING_FETCH_STRATEGIES and not settings_payload.get("scrapling_enabled", True):
            return False
        if result.error_kind == "domain_session_required":
            return next_backend in SCRAPLING_FETCH_STRATEGIES or next_backend == FETCH_STRATEGY_HEADED_SESSION
        if next_backend == FETCH_STRATEGY_SCRAPLING_STANDARD:
            return result.error_kind in {
                "cloudflare_challenge",
                "scrapling_challenge_upgrade_required",
                "timeout",
                "request_error",
                "empty_response",
                "http_error",
                "curl_cffi_unavailable",
                "scrapling_browser_failed",
                "scrapling_unavailable",
            }
        if next_backend in {FETCH_STRATEGY_SCRAPLING_DYNAMIC, FETCH_STRATEGY_SCRAPLING_STEALTH}:
            return result.error_kind in {
                "cloudflare_challenge",
                "scrapling_challenge_upgrade_required",
                "timeout",
                "request_error",
                "empty_response",
                "http_error",
                "curl_cffi_unavailable",
                "scrapling_browser_failed",
                "scrapling_unavailable",
            }
        if next_backend == FETCH_STRATEGY_HEADED_SESSION:
            return result.error_kind in {
                "cloudflare_challenge",
                "scrapling_challenge_upgrade_required",
                "timeout",
                "request_error",
                "empty_response",
                "http_error",
                "curl_cffi_unavailable",
                "scrapling_browser_failed",
                "scrapling_unavailable",
                "domain_session_required",
            }
        if next_backend == FETCH_STRATEGY_FIRECRAWL and not settings_payload.get("firecrawl_enabled"):
            return False
        if next_backend == COLLECTOR_EXTERNAL_SOLVER:
            return result.error_kind in {
                "cloudflare_challenge",
                "timeout",
                "request_error",
                "empty_response",
                "http_error",
                "scrapling_browser_failed",
                "scrapling_unavailable",
                "scrapling_disabled",
                "curl_cffi_unavailable",
            }
        return result.error_kind in {
            "timeout",
            "request_error",
            "empty_response",
            "http_error",
            "firecrawl_rate_limited",
            "firecrawl_upstream_error",
            "firecrawl_request_error",
            "firecrawl_bad_response",
            "firecrawl_disabled",
            "scrapling_browser_failed",
            "scrapling_unavailable",
            "scrapling_disabled",
            "curl_cffi_unavailable",
        }

    def fetch_pipeline(
        self,
        task: Any,
        browser_harness: BrowserHarness,
        settings_payload: dict[str, Any],
        context: str = "monitor",
    ) -> FetchPipelineResult:
        url = monitor_url_for_fetch(task)
        strategy = task_fetch_strategy(task)
        settings_payload = self.settings_for_task(settings_payload, task)
        timeout_seconds = int(settings_payload.get("request_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        backends = self.backends_for_strategy(task, settings_payload, context=context)
        attempts: list[FetchAttempt] = []
        last_result = FetchResult(html="", final_url=url, error_kind="request_error", detail="未执行抓取。")

        for index, backend in enumerate(backends):
            if backend == COLLECTOR_EXTERNAL_SOLVER:
                collector_result = self.external_solver_collector.collect(
                    collector_request_for_task(task, settings_payload, context=context),
                    settings_payload,
                )
                attempts.extend(collector_result.attempts)
                last_result = FetchResult(
                    html=collector_result.html,
                    final_url=collector_result.final_url or url,
                    status_code=collector_result.status_code,
                    error_kind=collector_result.error_kind,
                    detail=collector_result.detail,
                )
                if collector_result.ok and collector_result.html:
                    return FetchPipelineResult(
                        html=collector_result.html,
                        final_url=collector_result.final_url or url,
                        status_code=collector_result.status_code,
                        backend_used=COLLECTOR_EXTERNAL_SOLVER,
                        attempts=attempts,
                        detail=collector_result.detail,
                    )
                next_backend = backends[index + 1] if index + 1 < len(backends) else ""
                if not next_backend or not self.should_try_next_backend(last_result, next_backend, settings_payload):
                    break
                continue

            fetcher = self.fetcher_for_backend(backend, browser_harness, settings_payload)
            max_backend_attempts = 3 if backend == FETCH_STRATEGY_BROWSER and hasattr(fetcher, "rebuild") else 1
            for backend_attempt in range(max_backend_attempts):
                attempt = FetchAttempt(backend=backend, started_at=now_iso())
                attempts.append(attempt)
                try:
                    result = fetcher.fetch(url, timeout_seconds)
                except ProtectedSourceError as exc:
                    result = FetchResult(html="", final_url=url, error_kind=exc.error_kind, detail=str(exc))
                except Exception as exc:
                    detail = str(exc)
                    result = FetchResult(
                        html="",
                        final_url=url,
                        error_kind=classify_browser_error(detail) or "request_error",
                        detail=detail,
                    )
                    if should_auto_heal(exc) and backend_attempt < max_backend_attempts - 1 and hasattr(fetcher, "rebuild"):
                        attempt.ended_at = now_iso()
                        attempt.final_url = url
                        attempt.error_kind = result.error_kind
                        attempt.detail = detail[:300]
                        attempt.status = "retrying"
                        fetcher.rebuild(detail)
                        time.sleep(0.6)
                        last_result = result
                        continue

                attempt.ended_at = now_iso()
                attempt.final_url = result.final_url or url
                attempt.error_kind = result.error_kind
                attempt.detail = result.detail[:300] if result.detail else ""
                attempt.status = "success" if result.html and not result.error_kind else "failed"
                last_result = result

                if result.html and not result.error_kind:
                    return FetchPipelineResult(
                        html=result.html,
                        final_url=result.final_url,
                        status_code=result.status_code,
                        backend_used=backend,
                        attempts=attempts,
                        detail=result.detail,
                    )
                break

            remaining_backends = backends[index + 1 :]
            if (
                last_result.error_kind == "cloudflare_challenge"
                and FETCH_STRATEGY_FIRECRAWL in remaining_backends
                and firecrawl_allowed_for_context(settings_payload, context)
            ):
                backends[index + 1 :] = [FETCH_STRATEGY_FIRECRAWL] + [
                    backend_name for backend_name in remaining_backends if backend_name != FETCH_STRATEGY_FIRECRAWL
                ]
            next_backend = backends[index + 1] if index + 1 < len(backends) else ""
            if not next_backend or not self.should_try_next_backend(last_result, next_backend, settings_payload):
                break

        needs_domain_session = last_result.error_kind == "domain_session_required"
        if needs_domain_session:
            domain = fetch_domain_for_url(last_result.final_url or url) or fetch_domain_for_url(url)
            return FetchPipelineResult(
                html="",
                final_url=last_result.final_url or url,
                status_code=last_result.status_code,
                backend_used="",
                attempts=attempts,
                error_kind="domain_session_required",
                detail=f"{domain or '目标站'} 需要先初始化采集会话，再执行库存检测。",
            )

        return FetchPipelineResult(
            html="",
            final_url=last_result.final_url or url,
            status_code=last_result.status_code,
            backend_used="",
            attempts=attempts,
            error_kind=last_result.error_kind,
            detail=last_result.detail or "抓取失败",
        )


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
        self.fetcher_selector = FetcherSelector()
        self.domain_unlocker = DomainSessionUnlocker()
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
                    source["group_name"] if "group_name" in source.keys() else DEFAULT_TASK_GROUP,
                    settings_payload,
                    auto_promote=True,
                )
                synced_count += 1
            except Exception as exc:
                error_kind = catalog_browser_error_kind(exc)
                error_message = catalog_browser_error_message(exc, settings_payload["catalog_debug_port"])
                with open_connection() as connection:
                    connection.execute(
                        "UPDATE merchant_sources SET last_error = ?, updated_at = ? WHERE id = ?",
                        (error_message, now_iso(), source["id"]),
                    )
                    connection.commit()
                log_activity("warning", "catalog", f"同步商家来源 #{source['id']} 失败（{error_kind}）：{error_message}")

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
                cycle_context = MonitorCycleContext()
                for task in tasks:
                    if self.stop_event.is_set():
                        break
                    processed = self.process_task(task, settings_payload, use_test_browser=False, cycle_context=cycle_context)
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

    def scrape_task(
        self,
        task: sqlite3.Row | dict[str, Any],
        settings_payload: dict[str, Any],
        use_test_browser: bool,
        cycle_context: MonitorCycleContext | None = None,
    ) -> ScrapeResult:
        fetch_domain = fetch_domain_for_url(mapping_value(task, "monitor_url", ""))
        shared_key = fetch_cache_key(task)
        if not use_test_browser and is_task_in_protected_cooldown(task):
            cooldown_until = str(mapping_value(task, "cooldown_until", "") or "")
            if last_error_looks_like_firecrawl_cost(task):
                return ScrapeResult(
                    stock=None,
                    fragment="",
                    detail=firecrawl_cost_cooldown_message(cooldown_until),
                    used_test_browser=use_test_browser,
                    error_kind=last_firecrawl_cost_error_kind(task),
                    cooldown_skip=True,
                    fetch_domain=fetch_domain,
                    shared_fetch_key=shared_key,
                    domain_cooldown_until=cooldown_until,
                )
            return ScrapeResult(
                stock=None,
                fragment="",
                detail=protected_source_cooldown_message(cooldown_until),
                used_test_browser=use_test_browser,
                error_kind="cloudflare_challenge",
                cooldown_skip=True,
                fetch_domain=fetch_domain,
                shared_fetch_key=shared_key,
                domain_cooldown_until=cooldown_until,
            )

        if cycle_context and fetch_domain and not use_test_browser:
            domain_cooldown = cycle_context.domain_cooldowns.get(fetch_domain)
            cooldown_at = parse_iso_datetime(domain_cooldown.until) if domain_cooldown else None
            if domain_cooldown and cooldown_at and cooldown_at > now_utc():
                return ScrapeResult(
                    stock=None,
                    fragment="",
                    detail=domain_cooldown_message(fetch_domain, domain_cooldown.until, domain_cooldown.detail),
                    used_test_browser=use_test_browser,
                    error_kind=domain_cooldown.error_kind,
                    cooldown_skip=True,
                    backend_used=domain_cooldown.backend,
                    fetch_domain=fetch_domain,
                    shared_fetch_key=shared_key,
                    shared_fetch_backend=domain_cooldown.backend,
                    domain_cooldown_until=domain_cooldown.until,
                )

        browser = self.test_browser if use_test_browser else self.monitor_browser
        target_keyword = str(mapping_value(task, "target_keyword", "") or "")
        shared_backend = ""
        shared_detail_text = ""
        if cycle_context and not use_test_browser and shared_key in cycle_context.fetch_cache:
            pipeline_result = cycle_context.fetch_cache[shared_key]
            shared_backend = pipeline_result.backend_used or last_fetch_attempt_backend(pipeline_result.attempts, pipeline_result.error_kind)
            shared_detail_text = shared_fetch_detail(pipeline_result)
            if pipeline_result.detail:
                pipeline_result = FetchPipelineResult(
                    html=pipeline_result.html,
                    final_url=pipeline_result.final_url,
                    status_code=pipeline_result.status_code,
                    backend_used=pipeline_result.backend_used,
                    attempts=pipeline_result.attempts,
                    error_kind=pipeline_result.error_kind,
                    detail=f"{shared_detail_text}{pipeline_result.detail}",
                )
        else:
            pipeline_result = self.fetcher_selector.fetch_pipeline(
                task,
                browser,
                settings_payload,
                context="test" if use_test_browser else "monitor",
            )
            if cycle_context and not use_test_browser and shared_key:
                cycle_context.fetch_cache[shared_key] = pipeline_result
            backend_for_cooldown = pipeline_result.backend_used or last_fetch_attempt_backend(
                pipeline_result.attempts,
                pipeline_result.error_kind,
            )
            cooldown_until = domain_cooldown_until(backend_for_cooldown, pipeline_result.error_kind, settings_payload)
            if cycle_context and fetch_domain and cooldown_until and pipeline_result.error_kind:
                cycle_context.domain_cooldowns[fetch_domain] = DomainCooldown(
                    until=cooldown_until,
                    error_kind=pipeline_result.error_kind,
                    detail=fetch_attempts_summary(pipeline_result.attempts),
                    backend=backend_for_cooldown,
                )
        attempts_summary = fetch_attempts_summary(pipeline_result.attempts)
        backend_used = pipeline_result.backend_used or last_fetch_attempt_backend(pipeline_result.attempts, pipeline_result.error_kind)
        task_domain_cooldown = cycle_context.domain_cooldowns.get(fetch_domain) if cycle_context and fetch_domain else None
        task_domain_cooldown_until = task_domain_cooldown.until if task_domain_cooldown else ""
        if pipeline_result.error_kind:
            return ScrapeResult(
                stock=None,
                fragment="",
                detail=(pipeline_result.detail or "抓取失败") + attempts_summary,
                used_test_browser=use_test_browser,
                error_kind=pipeline_result.error_kind,
                backend_used=pipeline_result.backend_used,
                fetch_attempts=pipeline_result.attempts,
                fetch_domain=fetch_domain,
                shared_fetch_key=shared_key,
                shared_fetch_backend=shared_backend or backend_used,
                domain_cooldown_until=task_domain_cooldown_until,
            )
        if not pipeline_result.html:
            return ScrapeResult(
                stock=None,
                fragment="",
                detail=(pipeline_result.detail or "抓取返回了空 HTML") + attempts_summary,
                used_test_browser=use_test_browser,
                error_kind="empty_response",
                backend_used=pipeline_result.backend_used,
                fetch_attempts=pipeline_result.attempts,
                fetch_domain=fetch_domain,
                shared_fetch_key=shared_key,
                shared_fetch_backend=shared_backend or backend_used,
                domain_cooldown_until=task_domain_cooldown_until,
            )
        fetch_result = FetchResult(
            html=pipeline_result.html,
            final_url=pipeline_result.final_url,
            status_code=pipeline_result.status_code,
            detail=pipeline_result.detail,
        )
        if looks_like_cloudflare_challenge(pipeline_result.html, extract_page_title(pipeline_result.html), pipeline_result.final_url):
            return ScrapeResult(
                stock=None,
                fragment="",
                detail="目标页返回保护页，未进入库存解析。" + attempts_summary,
                used_test_browser=use_test_browser,
                error_kind="cloudflare_challenge",
                backend_used=pipeline_result.backend_used,
                fetch_attempts=pipeline_result.attempts,
                fetch_domain=fetch_domain,
                shared_fetch_key=shared_key,
                shared_fetch_backend=shared_backend or backend_used,
                domain_cooldown_until=task_domain_cooldown_until,
            )
        extracted = extract_stock_for_strategy(
            task_fetch_strategy(task),
            pipeline_result.html,
            target_keyword,
            task,
            fetch_result,
        )
        return ScrapeResult(
            stock=extracted.stock,
            fragment=extracted.fragment,
            detail=extracted.detail + (f"；{shared_detail_text}" if shared_detail_text else "") + attempts_summary,
            used_test_browser=use_test_browser,
            backend_used=pipeline_result.backend_used,
            fetch_attempts=pipeline_result.attempts,
            fetch_domain=fetch_domain,
            shared_fetch_key=shared_key,
            shared_fetch_backend=shared_backend or backend_used,
            domain_cooldown_until=task_domain_cooldown_until,
        )

    def fetch_catalog_entry_html(self, source_url: str, settings_payload: dict[str, Any], timeout_seconds: int) -> FetchResult:
        last_error = ""
        for attempt in range(2):
            try:
                html_text = self.catalog_browser.fetch_html(source_url, timeout_seconds)
                return FetchResult(html=html_text, final_url=source_url, detail="ok")
            except CatalogBrowserPortBusyError:
                raise
            except ProtectedSourceError:
                raise
            except Exception as exc:
                last_error = str(exc)
                if should_auto_heal(exc) and attempt < 1:
                    self.catalog_browser.rebuild(catalog_browser_error_message(exc, settings_payload["catalog_debug_port"]))
                    time.sleep(0.6)
                    continue
                raise CatalogBrowserConnectionError(
                    catalog_browser_error_message(exc, settings_payload["catalog_debug_port"])
                ) from exc
        raise CatalogBrowserConnectionError(last_error or "商家页面抓取失败。")

    def fetch_catalog_source_entry(self, source_url: str, settings_payload: dict[str, Any], options: dict[str, Any]) -> FetchResult:
        strategy = options.get("catalog_scrape_strategy") or DEFAULT_CATALOG_SCRAPE_STRATEGY
        if strategy == CATALOG_SCRAPE_FIRECRAWL:
            return FirecrawlCatalogProvider(settings_payload).scrape(source_url)
        if strategy in SCRAPLING_FETCH_STRATEGIES or strategy in {
            FETCH_STRATEGY_CURL_CFFI,
            FETCH_STRATEGY_MULTI_ENGINE,
            CATALOG_SCRAPE_STATIC_HTTP,
            CATALOG_SCRAPE_ADAPTIVE,
        }:
            return self.scrape_catalog_candidate(source_url, settings_payload, options)
        return self.fetch_catalog_entry_html(source_url, settings_payload, int(options.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))

    def scrape_catalog_candidate(self, candidate_url: str, settings_payload: dict[str, Any], options: dict[str, Any]) -> FetchResult:
        strategy = options.get("catalog_scrape_strategy") or DEFAULT_CATALOG_SCRAPE_STRATEGY
        timeout_seconds = int(options.get("timeout_seconds") or settings_payload.get("request_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
        if strategy == CATALOG_SCRAPE_STATIC_HTTP:
            return self.fetcher_selector.static_http_fetcher.fetch(candidate_url, timeout_seconds)
        if strategy == CATALOG_SCRAPE_FIRECRAWL:
            return FirecrawlCatalogProvider(settings_payload).scrape(candidate_url)
        if strategy in SCRAPLING_FETCH_STRATEGIES or strategy in {FETCH_STRATEGY_CURL_CFFI, FETCH_STRATEGY_MULTI_ENGINE}:
            pipeline_result = self.fetcher_selector.fetch_pipeline(
                {"monitor_url": candidate_url, "fetch_strategy": strategy},
                self.catalog_browser,
                settings_payload,
                context="catalog",
            )
            return FetchResult(
                html=pipeline_result.html,
                final_url=pipeline_result.final_url or candidate_url,
                status_code=pipeline_result.status_code,
                error_kind=pipeline_result.error_kind,
                detail=pipeline_result.detail or fetch_attempts_summary(pipeline_result.attempts),
            )
        if strategy == CATALOG_SCRAPE_ADAPTIVE:
            pipeline_result = self.fetcher_selector.fetch_pipeline(
                {"monitor_url": candidate_url, "fetch_strategy": FETCH_STRATEGY_ADAPTIVE},
                self.catalog_browser,
                settings_payload,
                context="catalog",
            )
            return FetchResult(
                html=pipeline_result.html,
                final_url=pipeline_result.final_url or candidate_url,
                status_code=pipeline_result.status_code,
                error_kind=pipeline_result.error_kind,
                detail=pipeline_result.detail or fetch_attempts_summary(pipeline_result.attempts),
            )
        return self.fetch_catalog_entry_html(candidate_url, settings_payload, timeout_seconds)

    def discover_catalog_candidate_urls(
        self,
        source_url: str,
        entry_html: str,
        settings_payload: dict[str, Any],
        options: dict[str, Any],
    ) -> list[dict[str, str]]:
        discovery_strategy = options.get("catalog_discovery_strategy") or CATALOG_DISCOVERY_LOCAL
        candidates: list[dict[str, str]] = []
        seen: set[str] = set()

        def add_candidate(candidate_url: str, source: str) -> None:
            normalized_url = normalize_candidate_url(source_url, candidate_url) or candidate_url
            if not is_catalog_candidate_url(source_url, normalized_url, options):
                return
            key = catalog_url_key(normalized_url, options.get("dedupe_policy", "by_url"), bool(options.get("ignore_query_parameters")))
            if key in seen:
                return
            seen.add(key)
            candidates.append({"url": normalized_url, "source": source})

        if discovery_strategy in {CATALOG_DISCOVERY_LOCAL, CATALOG_DISCOVERY_HYBRID}:
            for candidate in discover_candidate_urls_from_html(entry_html, source_url, options):
                add_candidate(candidate["url"], candidate["source"])

        if discovery_strategy in {CATALOG_DISCOVERY_FIRECRAWL_MAP, CATALOG_DISCOVERY_HYBRID}:
            provider = FirecrawlCatalogProvider(settings_payload)
            map_result = provider.map(
                source_url,
                str(options.get("search_keyword") or ""),
                min(int(options.get("max_discovered_urls") or 50), int(settings_payload.get("firecrawl_catalog_limit") or DEFAULT_FIRECRAWL_CATALOG_LIMIT)),
            )
            if map_result.error_kind:
                log_activity("warning", "catalog", f"Firecrawl map 发现 URL 失败（{map_result.error_kind}）：{map_result.detail}")
            for link in parse_firecrawl_map_links(map_result):
                add_candidate(link, "firecrawl_map")

        for candidate in hidden_catalog_probe_candidates(source_url, options):
            add_candidate(str(candidate.get("url") or ""), str(candidate.get("source") or "hidden_probe"))

        return candidates[: int(options.get("max_discovered_urls") or 50)]

    def catalog_source_title(self, source_url: str, source_name: str, html_text: str = "") -> str:
        source_title = normalize_candidate_title(source_name) or extract_page_title(html_text)
        if not source_title:
            source_title = urlparse(source_url).hostname or source_url
        return source_title

    def discover_merchant_catalog_urls(
        self,
        source_url: str,
        source_name: str,
        group_name: str,
        settings_payload: dict[str, Any],
        catalog_options: dict[str, Any] | None = None,
    ) -> MerchantCatalogPreviewResult:
        source_url = source_url.strip()
        if not source_url:
            raise RuntimeError("商家页面链接不能为空。")
        if not validate_http_url(source_url):
            raise RuntimeError("商家页面链接必须是有效的 http(s) 地址。")

        options = normalize_catalog_options(catalog_options, settings_payload, group_name, False)
        if options["catalog_discovery_strategy"] == CATALOG_DISCOVERY_FIRECRAWL_MAP:
            entry_result = FetchResult(html="", final_url=source_url, detail="firecrawl_map")
        else:
            entry_result = self.fetch_catalog_source_entry(source_url, settings_payload, options)
        html_text = entry_result.html
        if not html_text and options["catalog_discovery_strategy"] != CATALOG_DISCOVERY_FIRECRAWL_MAP:
            raise CatalogBrowserConnectionError(entry_result.detail or "商家页面抓取失败。")

        candidate_urls = self.discover_catalog_candidate_urls(source_url, html_text, settings_payload, options)
        if not candidate_urls and options["catalog_discovery_strategy"] != CATALOG_DISCOVERY_FIRECRAWL_MAP:
            candidate_urls = [{"url": source_url, "source": "entry"}]
        source_title = self.catalog_source_title(source_url, source_name, html_text)
        timestamp = now_iso()
        payload_urls: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidate_urls[: int(options["max_discovered_urls"])], start=1):
            candidate_url = normalize_candidate_url(source_url, str(candidate.get("url") or "")) or source_url
            payload_urls.append(
                {
                    "id": hashlib.sha1(f"{source_url}|{candidate_url}|{index}".encode("utf-8", errors="ignore")).hexdigest()[:16],
                    "url": candidate_url,
                    "source": str(candidate.get("source") or "page_links"),
                    "selected": True,
                    "status": "pending",
                }
            )
        return MerchantCatalogPreviewResult(
            source_url=source_url,
            source_name=source_title,
            group_name=normalize_task_group(options.get("default_group") or group_name),
            generated_at=timestamp,
            candidate_urls=payload_urls,
            items=[],
            rejected_items=[],
            failures=[],
            options=options,
        )

    def preview_merchant_source(
        self,
        source_url: str,
        source_name: str,
        group_name: str,
        settings_payload: dict[str, Any],
        catalog_options: dict[str, Any] | None = None,
        candidate_urls: list[Any] | None = None,
    ) -> MerchantCatalogPreviewResult:
        source_url = source_url.strip()
        if not source_url:
            raise RuntimeError("商家页面链接不能为空。")
        if not validate_http_url(source_url):
            raise RuntimeError("商家页面链接必须是有效的 http(s) 地址。")

        options = normalize_catalog_options(catalog_options, settings_payload, group_name, False)
        candidates: list[dict[str, Any]] = []
        source_title = self.catalog_source_title(source_url, source_name)
        entry_result_for_preview: FetchResult | None = None
        explicit_candidate_selection = bool(candidate_urls)

        def make_candidate_payload(candidate_url: str, candidate_source: str, index: int) -> dict[str, Any]:
            normalized_url = normalize_candidate_url(source_url, candidate_url) or source_url
            return {
                "id": hashlib.sha1(f"{source_url}|{normalized_url}|{index}".encode("utf-8", errors="ignore")).hexdigest()[:16],
                "url": normalized_url,
                "source": candidate_source or "page_links",
                "selected": True,
                "status": "pending",
            }

        if candidate_urls:
            selected_candidates: list[dict[str, Any]] = []
            seen_urls: set[str] = set()
            for index, raw_candidate in enumerate(candidate_urls[: int(options["max_discovered_urls"])], start=1):
                if isinstance(raw_candidate, dict):
                    raw_url = str(raw_candidate.get("url") or "")
                    raw_source = str(raw_candidate.get("source") or "selected")
                else:
                    raw_url = str(raw_candidate or "")
                    raw_source = "selected"
                normalized_url = normalize_candidate_url(source_url, raw_url)
                if not normalized_url or normalized_url in seen_urls:
                    continue
                if not is_catalog_candidate_url(source_url, normalized_url, options):
                    continue
                seen_urls.add(normalized_url)
                selected_candidates.append(make_candidate_payload(normalized_url, raw_source, index))
            candidates = selected_candidates
        else:
            if options["catalog_discovery_strategy"] == CATALOG_DISCOVERY_FIRECRAWL_MAP:
                entry_html = ""
            else:
                entry_result_for_preview = self.fetch_catalog_source_entry(source_url, settings_payload, options)
                entry_html = entry_result_for_preview.html
                if not entry_html:
                    raise CatalogBrowserConnectionError(entry_result_for_preview.detail or "商家页面抓取失败。")
                source_title = self.catalog_source_title(source_url, source_name, entry_html)
            discovered_urls = self.discover_catalog_candidate_urls(source_url, entry_html, settings_payload, options)
            if not discovered_urls and options["catalog_discovery_strategy"] != CATALOG_DISCOVERY_FIRECRAWL_MAP:
                discovered_urls = [{"url": source_url, "source": "entry"}]
            candidates = [
                make_candidate_payload(str(candidate.get("url") or ""), str(candidate.get("source") or "page_links"), index)
                for index, candidate in enumerate(discovered_urls[: int(options["max_discovered_urls"])], start=1)
            ]

        items: list[dict[str, Any]] = []
        rejected_items: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        seen_item_keys: set[str] = set()

        for candidate in candidates:
            if len(items) >= int(options["max_import_items"]):
                break
            candidate_url = str(candidate.get("url") or "")
            if not candidate_url:
                continue
            candidate_source = str(candidate.get("source") or "selected")
            candidate_status = dict(candidate)
            try:
                if (
                    entry_result_for_preview is not None
                    and candidate_url.rstrip("/") == source_url.rstrip("/")
                    and candidate_source == "entry"
                ):
                    fetch_result = entry_result_for_preview
                else:
                    fetch_result = self.scrape_catalog_candidate(candidate_url, settings_payload, options)
            except Exception as exc:
                error_kind = catalog_browser_error_kind(exc)
                detail = catalog_browser_error_message(exc, settings_payload["catalog_debug_port"])
                candidate_status.update({"status": "failed", "error_kind": error_kind, "detail": detail})
                failures.append({"url": candidate_url, "source": candidate_source, "error_kind": error_kind, "detail": detail})
                candidate.update(candidate_status)
                continue

            backend_used = options.get("catalog_scrape_strategy") or DEFAULT_CATALOG_SCRAPE_STRATEGY
            if fetch_result.error_kind:
                candidate_status.update(
                    {
                        "status": "failed",
                        "error_kind": fetch_result.error_kind,
                        "detail": fetch_result.detail,
                        "final_url": fetch_result.final_url or candidate_url,
                        "backend_used": backend_used,
                    }
                )
                failures.append(
                    {
                        "url": candidate_url,
                        "source": candidate_source,
                        "error_kind": fetch_result.error_kind,
                        "detail": fetch_result.detail,
                        "backend_used": backend_used,
                    }
                )
                candidate.update(candidate_status)
                continue

            if not source_title or source_title == (urlparse(source_url).hostname or source_url):
                source_title = self.catalog_source_title(source_url, source_name, fetch_result.html)

            all_candidates = discover_catalog_items(fetch_result.html, fetch_result.final_url or candidate_url, include_rejected=True)
            accepted_count = 0
            rejected_count = 0
            for raw_item in all_candidates:
                prepared = prepare_catalog_item(raw_item, source_url, fetch_result.final_url or candidate_url, candidate_source, backend_used, options)
                if raw_item.get("reject_reason"):
                    rejected_count += 1
                    if len(rejected_items) < 120:
                        rejected_items.append(catalog_item_response_payload(prepared, include_raw=False))
                    continue
                reject_reason = catalog_item_filter_reject_reason(prepared, options)
                if reject_reason:
                    rejected_count += 1
                    rejected = dict(prepared)
                    rejected["reject_reason"] = reject_reason
                    if len(rejected_items) < 120:
                        rejected_items.append(catalog_item_response_payload(rejected, include_raw=False))
                    continue
                if prepared["source_item_key"] in seen_item_keys:
                    continue
                seen_item_keys.add(prepared["source_item_key"])
                items.append(catalog_item_response_payload(prepared, include_raw=True))
                accepted_count += 1
                if len(items) >= int(options["max_import_items"]):
                    break

            candidate_status.update(
                {
                    "status": "scraped" if accepted_count or rejected_count else "no_items",
                    "final_url": fetch_result.final_url or candidate_url,
                    "backend_used": backend_used,
                    "accepted_count": accepted_count,
                    "rejected_count": rejected_count,
                    "detail": (
                        "已解析商品候选"
                        if accepted_count
                        else "仅发现低置信或被过滤候选，查看商品预览中的过滤原因。"
                        if rejected_count
                        else "未发现商品候选"
                    ),
                }
            )
            if not accepted_count and not rejected_count:
                failures.append(
                    {
                        "url": candidate_url,
                        "source": candidate_source,
                        "error_kind": "catalog_no_items",
                        "detail": "该 URL 未发现商品候选。",
                        "backend_used": backend_used,
                    }
                )
            candidate.update(candidate_status)
            if (
                not explicit_candidate_selection
                and options["catalog_discovery_strategy"] == CATALOG_DISCOVERY_LOCAL
                and candidate_source == "entry"
                and accepted_count > 0
            ):
                break

        return MerchantCatalogPreviewResult(
            source_url=source_url,
            source_name=source_title,
            group_name=normalize_task_group(options.get("default_group") or group_name),
            generated_at=now_iso(),
            candidate_urls=candidates,
            items=items,
            rejected_items=rejected_items,
            failures=failures,
            options=options,
        )

    def persist_merchant_catalog_items(
        self,
        source_url: str,
        source_title: str,
        group_name: str,
        discovered_items: list[dict[str, Any]],
        auto_promote: bool = True,
        archive_missing: bool = True,
    ) -> MerchantImportResult:
        source_url = source_url.strip()
        if not source_url:
            raise RuntimeError("商家页面链接不能为空。")
        if not validate_http_url(source_url):
            raise RuntimeError("商家页面链接必须是有效的 http(s) 地址。")

        normalized_items = [normalize_preview_catalog_item(item) for item in discovered_items[:250]]
        source_title = self.catalog_source_title(source_url, source_title)
        target_group_name = normalize_task_group(group_name)

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
                    SET source_name = ?, group_name = ?, active = 1, last_sync_at = ?, last_error = '', discovered_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (source_title, target_group_name, timestamp, len(normalized_items), timestamp, source_id),
                )
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO merchant_sources (
                        source_url, source_name, group_name, active, discovered_count, last_sync_at, last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?, '', ?, ?)
                    """,
                    (source_url, source_title, target_group_name, len(normalized_items), timestamp, timestamp, timestamp),
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

            for item in normalized_items:
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
                        group_name=target_group_name,
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
                        "confidence": item.get("confidence", 0),
                        "candidate_type": item.get("candidate_type", ""),
                        "include_reason": item.get("include_reason", ""),
                        "reject_reason": item.get("reject_reason", ""),
                        "signals": item.get("signals", []),
                        "item_state": item_state,
                        "task_id": task_id,
                    }
                )

            if archive_missing and seen_keys:
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
            scanned_count=len(normalized_items),
            upserted_count=upserted_count,
            promoted_count=promoted_count,
            archived_count=archived_count,
            last_sync_at=timestamp,
            items=persisted_items,
        )

    def import_merchant_source(
        self,
        source_url: str,
        source_name: str,
        group_name: str,
        settings_payload: dict[str, Any],
        auto_promote: bool = True,
        catalog_options: dict[str, Any] | None = None,
    ) -> MerchantImportResult:
        preview = self.preview_merchant_source(
            source_url,
            source_name,
            group_name,
            settings_payload,
            catalog_options=catalog_options,
        )
        return self.persist_merchant_catalog_items(
            preview.source_url,
            preview.source_name,
            preview.group_name,
            preview.items,
            auto_promote=auto_promote,
            archive_missing=True,
        )

    def resolve_chat_ids(self, settings_payload: dict[str, Any]) -> list[str]:
        return normalize_telegram_chat_ids(settings_payload.get("telegram_chat_ids") or settings_payload.get("telegram_chat_id"))

    def send_messages_to_chats(
        self,
        token: str,
        chat_ids: list[str],
        text: str,
        buttons: list[dict[str, str]] | None = None,
    ) -> tuple[dict[str, int], list[str]]:
        sent: dict[str, int] = {}
        errors: list[str] = []
        for chat_id in chat_ids:
            try:
                sent[chat_id] = self.telegram.send_message(token, chat_id, text, buttons)
            except Exception as exc:
                errors.append(f"{chat_id}: {sanitize_telegram_error(str(exc), token)}")
        return sent, errors

    def edit_messages_to_chats(
        self,
        token: str,
        chat_ids: list[str],
        message_id_map: dict[str, int],
        text: str,
        buttons: list[dict[str, str]] | None = None,
    ) -> tuple[dict[str, int], list[str]]:
        edited: dict[str, int] = {}
        errors: list[str] = []
        for chat_id in chat_ids:
            message_id = message_id_map.get(chat_id)
            if message_id is None:
                continue
            try:
                self.telegram.edit_message(token, chat_id, int(message_id), text, buttons)
                edited[chat_id] = int(message_id)
            except Exception as exc:
                errors.append(f"{chat_id}: {sanitize_telegram_error(str(exc), token)}")
        return edited, errors

    def apply_task_result(
        self,
        task: sqlite3.Row,
        settings_payload: dict[str, Any],
        result: ScrapeResult,
        checked_at: datetime | None = None,
        send_notifications: bool = True,
    ) -> bool:
        with open_connection() as connection:
            checked_at = checked_at or now_utc()
            timestamp = checked_at.isoformat(timespec="seconds")
            if result.stock is None:
                fetch_backend = result.backend_used or last_fetch_attempt_backend(result.fetch_attempts, result.error_kind)
                fetch_attempts_text = serialize_fetch_attempts(result.fetch_attempts)
                fetch_domain = result.fetch_domain or fetch_domain_for_url(task["monitor_url"])
                shared_fetch_key = result.shared_fetch_key or fetch_cache_key(task)
                shared_fetch_backend = result.shared_fetch_backend or fetch_backend
                if result.error_kind in EXTERNAL_INPUT_PENDING_ERROR_KINDS:
                    connection.execute(
                        """
                        UPDATE tasks
                        SET last_checked_at = ?,
                            last_error = '',
                            last_fetch_backend = ?,
                            last_fetch_attempts = ?,
                            last_fetch_domain = ?,
                            domain_cooldown_until = ?,
                            last_shared_fetch_key = ?,
                            last_shared_fetch_backend = ?,
                            last_protected_source_backend = '',
                            cooldown_until = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            timestamp,
                            fetch_backend,
                            fetch_attempts_text,
                            fetch_domain,
                            result.domain_cooldown_until or None,
                            shared_fetch_key,
                            shared_fetch_backend,
                            timestamp,
                            task["id"],
                        ),
                    )
                elif result.error_kind == "cloudflare_challenge" and not result.cooldown_skip:
                    blocked_count = task_blocked_count(task) + 1
                    cooldown_until = protected_source_cooldown_until(blocked_count, checked_at)
                    domain_until = result.domain_cooldown_until or cooldown_until
                    protected_backend = result.backend_used or last_fetch_attempt_backend(result.fetch_attempts, "cloudflare_challenge")
                    connection.execute(
                        """
                        UPDATE tasks
                        SET last_checked_at = ?,
                            last_error = ?,
                            last_fetch_backend = ?,
                            last_fetch_attempts = ?,
                            last_fetch_domain = ?,
                            domain_cooldown_until = ?,
                            last_shared_fetch_key = ?,
                            last_shared_fetch_backend = ?,
                            last_protected_source_backend = ?,
                            blocked_count = ?,
                            last_blocked_at = ?,
                            cooldown_until = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            timestamp,
                            result.detail[:1000],
                            fetch_backend,
                            fetch_attempts_text,
                            fetch_domain,
                            domain_until,
                            shared_fetch_key,
                            shared_fetch_backend,
                            protected_backend,
                            blocked_count,
                            timestamp,
                            cooldown_until,
                            timestamp,
                            task["id"],
                        ),
                    )
                elif result.error_kind in FIRECRAWL_COST_ERROR_KINDS and not result.cooldown_skip:
                    cooldown_until = firecrawl_cost_cooldown_until(checked_at)
                    connection.execute(
                        """
                        UPDATE tasks
                        SET last_checked_at = ?,
                            last_error = ?,
                            last_fetch_backend = ?,
                            last_fetch_attempts = ?,
                            last_fetch_domain = ?,
                            domain_cooldown_until = ?,
                            last_shared_fetch_key = ?,
                            last_shared_fetch_backend = ?,
                            last_protected_source_backend = '',
                            last_blocked_at = ?,
                            cooldown_until = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            timestamp,
                            result.detail[:1000],
                            fetch_backend,
                            fetch_attempts_text,
                            fetch_domain,
                            result.domain_cooldown_until or cooldown_until,
                            shared_fetch_key,
                            shared_fetch_backend,
                            timestamp,
                            cooldown_until,
                            timestamp,
                            task["id"],
                        ),
                    )
                elif result.cooldown_skip:
                    connection.execute(
                        """
                        UPDATE tasks
                        SET last_checked_at = ?,
                            last_error = ?,
                            last_fetch_backend = ?,
                            last_fetch_attempts = ?,
                            last_fetch_domain = ?,
                            domain_cooldown_until = ?,
                            last_shared_fetch_key = ?,
                            last_shared_fetch_backend = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            timestamp,
                            result.detail[:1000],
                            fetch_backend,
                            fetch_attempts_text,
                            fetch_domain,
                            result.domain_cooldown_until or None,
                            shared_fetch_key,
                            shared_fetch_backend,
                            timestamp,
                            task["id"],
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE tasks
                        SET last_checked_at = ?,
                            last_error = ?,
                            last_fetch_backend = ?,
                            last_fetch_attempts = ?,
                            last_fetch_domain = ?,
                            domain_cooldown_until = ?,
                            last_shared_fetch_key = ?,
                            last_shared_fetch_backend = ?,
                            last_protected_source_backend = '',
                            cooldown_until = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            timestamp,
                            result.detail[:1000],
                            fetch_backend,
                            fetch_attempts_text,
                            fetch_domain,
                            result.domain_cooldown_until or None,
                            shared_fetch_key,
                            shared_fetch_backend,
                            timestamp,
                            task["id"],
                        ),
                    )
                connection.commit()
                return False

            last_stock = task["last_stock"]
            new_state = "in_stock" if result.stock > 0 else "sold_out"
            last_error = ""
            message_id = task["message_id"] if "message_id" in task.keys() else None
            message_ids_text = task["message_ids"] if "message_ids" in task.keys() else ""
            message_id_map = parse_message_id_map(
                message_ids_text,
                self.resolve_chat_ids(settings_payload),
                message_id,
            )

            if send_notifications:
                chat_ids = self.resolve_chat_ids(settings_payload)
                if not settings_payload.get("telegram_bot_token") or not chat_ids:
                    raise RuntimeError("请先配置 Telegram Bot Token 和至少一个 Chat ID。")

                buttons = build_buttons(task)
                message_values = message_template_values(task, result.stock)
                message_id_map = parse_message_id_map(
                    task["message_ids"] if "message_ids" in task.keys() else "",
                    chat_ids,
                    task["message_id"] if "message_id" in task.keys() else None,
                )
                message_id_map = {chat_id: message_id for chat_id, message_id in message_id_map.items() if chat_id in chat_ids}
                operation_errors: list[str] = []
                existing_message_ids = dict(message_id_map)

                try:
                    missing_chat_ids = [chat_id for chat_id in chat_ids if chat_id not in message_id_map]
                    if result.stock > 0 and missing_chat_ids:
                        text = safe_format(task["restock_template"], message_values)
                        sent_map, send_errors = self.send_messages_to_chats(
                            settings_payload["telegram_bot_token"],
                            missing_chat_ids,
                            text,
                            buttons,
                        )
                        if sent_map:
                            message_id_map.update(sent_map)
                            log_activity(
                                "info",
                                f"task:{task['id']}",
                                f"{task['name']} 刚补货，已向 {len(sent_map)} 个群发送新消息。",
                            )
                        operation_errors.extend(send_errors)
                    if result.stock > 0 and existing_message_ids and last_stock != result.stock:
                        text = safe_format(task["restock_template"], message_values)
                        edited_map, edit_errors = self.edit_messages_to_chats(
                            settings_payload["telegram_bot_token"],
                            chat_ids,
                            existing_message_ids,
                            text,
                            buttons,
                        )
                        if edited_map:
                            log_activity(
                                "info",
                                f"task:{task['id']}",
                                f"{task['name']} 库存变化为 {result.stock}，已静默编辑 {len(edited_map)} 条消息。",
                            )
                        operation_errors.extend(edit_errors)
                    elif result.stock <= 0 and message_id_map:
                        text = safe_format(task["soldout_template"], message_values | {"status": telegram_html_value("sold_out")})
                        edited_map, edit_errors = self.edit_messages_to_chats(
                            settings_payload["telegram_bot_token"],
                            chat_ids,
                            message_id_map,
                            text,
                            buttons,
                        )
                        if edited_map:
                            log_activity(
                                "warning",
                                f"task:{task['id']}",
                                f"{task['name']} 已售罄，已覆盖原消息并清空会话记录。",
                            )
                        message_id_map = {}
                        operation_errors.extend(edit_errors)
                except Exception as exc:
                    last_error = sanitize_telegram_error(str(exc), settings_payload["telegram_bot_token"])
                    log_activity("error", f"task:{task['id']}", f"{task['name']} Telegram 推送失败：{last_error}")

                if operation_errors and not last_error:
                    last_error = "; ".join(operation_errors)[:1000]

                first_chat_id = chat_ids[0] if chat_ids else ""
                message_id = message_id_map.get(first_chat_id) if first_chat_id else None
                message_ids_text = serialize_message_id_map(message_id_map)

            connection.execute(
                """
                UPDATE tasks
                SET last_stock = ?,
                    last_state = ?,
                    message_id = ?,
                    message_ids = ?,
                    last_checked_at = ?,
                    last_error = ?,
                    last_fetch_backend = ?,
                    last_fetch_attempts = ?,
                    last_fetch_domain = ?,
                    domain_cooldown_until = ?,
                    last_shared_fetch_key = ?,
                    last_shared_fetch_backend = ?,
                    last_protected_source_backend = '',
                    blocked_count = 0,
                    last_blocked_at = NULL,
                    cooldown_until = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    result.stock,
                    new_state,
                    message_id,
                    message_ids_text,
                    timestamp,
                    last_error[:1000],
                    result.backend_used or last_fetch_attempt_backend(result.fetch_attempts),
                    serialize_fetch_attempts(result.fetch_attempts),
                    result.fetch_domain or fetch_domain_for_url(task["monitor_url"]),
                    result.domain_cooldown_until or None,
                    result.shared_fetch_key or fetch_cache_key(task),
                    result.shared_fetch_backend or result.backend_used or last_fetch_attempt_backend(result.fetch_attempts),
                    timestamp,
                    task["id"],
                ),
            )
            connection.commit()
        return True

    def process_task(
        self,
        task: sqlite3.Row,
        settings_payload: dict[str, Any],
        use_test_browser: bool,
        cycle_context: MonitorCycleContext | None = None,
    ) -> bool:
        if cycle_context is None:
            result = self.scrape_task(task, settings_payload, use_test_browser)
        else:
            result = self.scrape_task(task, settings_payload, use_test_browser, cycle_context=cycle_context)
        if use_test_browser:
            raise RuntimeError("测试推送应走 run_test_push 流程，不进入常规状态机。")
        return self.apply_task_result(task, settings_payload, result)

    def run_stock_check(self, task_id: int) -> dict[str, Any]:
        settings_payload = self.get_runtime_settings()
        self.configure_browsers(settings_payload)
        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise RuntimeError("任务不存在。")

        result = self.scrape_task(task, settings_payload, use_test_browser=True)
        self.apply_task_result(task, settings_payload, result, send_notifications=False)
        log_activity("info", f"task:{task_id}", f"{task['name']} 已完成一次库存检测，结果：{result.stock if result.stock is not None else '未知'}。")
        result_state = "failed" if result.stock is None and result.error_kind else "unknown"
        if result.stock is not None:
            result_state = "in_stock" if result.stock > 0 else "sold_out"
        backend_used = result.backend_used or last_fetch_attempt_backend(result.fetch_attempts, result.error_kind)
        attempts_payload = [fetch_attempt_to_payload(attempt) for attempt in result.fetch_attempts or []]
        diagnostic = stock_check_diagnostic(
            result.error_kind,
            result.detail,
            result.fetch_attempts,
            backend_used,
            result.fetch_domain or fetch_domain_for_url(task["monitor_url"]),
        )
        return {
            "stock": result.stock,
            "state": result_state,
            "detail": result.detail,
            "error_kind": result.error_kind,
            "backend_used": backend_used,
            "attempts": attempts_payload,
            "diagnostic": diagnostic,
            "checked_at": now_iso(),
        }

    def validate_imported_domain_session(
        self,
        task: sqlite3.Row,
        domain: str,
        user_agent: str,
        cookies: list[dict[str, Any]],
        ttl_hours: int,
    ) -> tuple[FetchResult, ExtractorResult]:
        url = monitor_url_for_fetch(task)
        candidate_session = build_candidate_domain_session_payload(domain, user_agent, cookies, ttl_hours)
        fetcher = CurlCffiFetcher(session_provider=lambda _url: candidate_session)
        result = fetcher.fetch(url, int(self.get_runtime_settings().get("request_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS))
        if result.error_kind:
            raise RuntimeError(f"导入的会话仍无法获取真实商品页：{result.detail}")
        if not result.html:
            raise RuntimeError("导入的会话返回空页面，未保存。")
        extracted = extract_stock_for_strategy(
            task_fetch_strategy(task),
            result.html,
            str(task["target_keyword"] or ""),
            task,
            result,
        )
        if extracted.stock is None:
            raise RuntimeError(f"导入的会话能打开页面，但仍未识别库存：{extracted.detail}")
        return result, extracted

    def unlock_task_domain_session(self, task_id: int, timeout_seconds: int | None = None) -> dict[str, Any]:
        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise RuntimeError("任务不存在。")

        url = monitor_url_for_fetch(task)
        target_keyword = str(task["target_keyword"] or "")
        result = self.domain_unlocker.unlock(
            url,
            target_keyword=target_keyword,
            timeout_seconds=timeout_seconds or DOMAIN_SESSION_UNLOCK_TIMEOUT_SECONDS,
        )
        session_payload = upsert_domain_session(
            result.domain,
            status=result.status,
            user_agent=result.user_agent,
            cookies=result.cookies,
            profile_path=result.profile_path,
            source_url=result.final_url or url,
            last_error="" if result.status == DOMAIN_SESSION_STATUS_READY else result.detail,
        )
        level = "info" if result.status == DOMAIN_SESSION_STATUS_READY else "warning"
        log_activity(level, f"domain:{result.domain}", result.detail)
        return {
            "task_id": task_id,
            "domain": result.domain,
            "status": result.status,
            "detail": result.detail,
            "final_url": result.final_url,
            "session": session_payload,
        }

    def import_task_domain_session(self, task_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise RuntimeError("任务不存在。")

        url = monitor_url_for_fetch(task)
        fallback_domain = fetch_domain_for_url(url)
        domain, user_agent, cookies, ttl_hours = normalize_domain_session_import_payload(payload, fallback_domain)
        fetch_result, extracted = self.validate_imported_domain_session(task, domain, user_agent, cookies, ttl_hours)
        session_payload = upsert_domain_session(
            domain,
            status=DOMAIN_SESSION_STATUS_READY,
            user_agent=user_agent,
            cookies=cookies,
            source_url=url,
            last_error="",
            ttl_hours=ttl_hours,
        )
        state = "有货" if extracted.stock and extracted.stock > 0 else "售罄"
        log_activity("info", f"domain:{domain}", f"{domain} 已导入并验证浏览器会话，当前库存：{state}。")
        return {
            "task_id": task_id,
            "domain": domain,
            "status": DOMAIN_SESSION_STATUS_READY,
            "detail": f"浏览器会话已导入并验证，当前库存：{state}。",
            "stock": extracted.stock,
            "state": "in_stock" if extracted.stock and extracted.stock > 0 else "sold_out",
            "backend_used": FETCH_STRATEGY_CURL_CFFI,
            "final_url": fetch_result.final_url,
            "session": session_payload,
        }

    def run_test_push(self, task_id: int) -> dict[str, Any]:
        settings_payload = self.get_runtime_settings()
        self.configure_browsers(settings_payload)
        chat_ids = self.resolve_chat_ids(settings_payload)
        if not settings_payload["telegram_bot_token"] or not chat_ids:
            raise RuntimeError("请先配置 Telegram Bot Token 和至少一个 Chat ID。")

        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise RuntimeError("任务不存在。")

        result = self.scrape_task(task, settings_payload, use_test_browser=True)
        stock_text = "未知" if result.stock is None else str(result.stock)
        preview_values = message_template_values(task, result.stock)
        preview_values["status"] = "test"
        preview_text = (
            f"【测试推送】{task['name']}\n"
            f"隔离测试端口：{settings_payload['test_debug_port']}\n"
            f"识别库存：{stock_text}\n\n"
            f"{safe_format(task['restock_template'], preview_values)}"
        )
        sent_map, send_errors = self.send_messages_to_chats(
            settings_payload["telegram_bot_token"],
            chat_ids,
            preview_text,
            build_buttons(task),
        )
        if send_errors and not sent_map:
            raise RuntimeError("; ".join(send_errors)[:1000])
        if send_errors and sent_map:
            log_activity("warning", f"task:{task_id}", "; ".join(send_errors)[:1000])
        first_chat_id = chat_ids[0]
        message_id = sent_map.get(first_chat_id)
        log_activity("info", f"task:{task_id}", f"{task['name']} 已通过测试浏览器发送测试消息（message_id={message_id}）。")
        return {
            "message_id": message_id,
            "message_ids": sent_map,
            "stock": result.stock,
            "detail": result.detail,
            "test_port": settings_payload["test_debug_port"],
        }

    def run_template_test_push(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings_payload = self.get_runtime_settings()
        chat_ids = normalize_telegram_chat_ids(
            payload.get("test_chat_ids") or payload.get("telegram_chat_ids") or payload.get("telegram_chat_id") or ""
        ) or self.resolve_chat_ids(settings_payload)
        if not settings_payload["telegram_bot_token"] or not chat_ids:
            raise RuntimeError("请先配置 Telegram Bot Token 和至少一个 Chat ID。")

        template_kind = str(payload.get("template_kind") or "restock").strip().lower()
        if template_kind not in {"restock", "soldout"}:
            template_kind = "restock"
        sample_stock = 0 if template_kind == "soldout" else 3
        try:
            if payload.get("stock") not in (None, ""):
                sample_stock = max(0, int(payload.get("stock")))
        except (TypeError, ValueError):
            sample_stock = 0 if template_kind == "soldout" else 3

        task_payload = {
            "name": str(payload.get("name") or "NOAFF 模板测试商品").strip()[:160],
            "monitor_url": str(payload.get("monitor_url") or "https://example.com/product").strip(),
            "target_keyword": str(payload.get("target_keyword") or "NOAFF").strip(),
            "source_source_name": str(payload.get("source_source_name") or "").strip(),
            "source_source_url": str(payload.get("source_source_url") or "").strip(),
            "button_1_text": str(payload.get("button_1_text") or "").strip(),
            "button_1_url": str(payload.get("button_1_url") or "").strip(),
            "button_2_text": str(payload.get("button_2_text") or "").strip(),
            "button_2_url": str(payload.get("button_2_url") or "").strip(),
        }
        template = str(
            payload.get("soldout_template") if template_kind == "soldout" else payload.get("restock_template")
        ).strip()
        if not template:
            template = DEFAULT_SOLDOUT_TEMPLATE if template_kind == "soldout" else DEFAULT_RESTOCK_TEMPLATE

        values = message_template_values(task_payload, sample_stock)
        values["status"] = telegram_html_value("sold_out" if template_kind == "soldout" else "in_stock")
        message_text = f"【模板测试】\n{safe_format(template, values)}"
        sent_map, send_errors = self.send_messages_to_chats(
            settings_payload["telegram_bot_token"],
            chat_ids,
            message_text,
            build_buttons(task_payload),
        )
        if send_errors and not sent_map:
            raise RuntimeError("; ".join(send_errors)[:1000])
        if send_errors and sent_map:
            log_activity("warning", "telegram:template-test", "; ".join(send_errors)[:1000])
        first_chat_id = chat_ids[0]
        message_id = sent_map.get(first_chat_id)
        log_activity("info", "telegram:template-test", f"已发送 TG 模板测试消息（message_id={message_id}）。")
        return {
            "message_id": message_id,
            "message_ids": sent_map,
            "template_kind": template_kind,
            "stock": sample_stock,
            "chat_count": len(sent_map),
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
    if isinstance(exc, (ProtectedSourceError, CatalogBrowserPortBusyError)):
        return False
    message = str(exc).lower()
    if classify_browser_error(message) == "cloudflare_challenge":
        return False
    return any(token.lower() in message for token in BROWSER_RECOVERY_MARKERS)


def catalog_browser_error_kind(exc: Exception) -> str:
    if isinstance(exc, ProtectedSourceError):
        return exc.error_kind
    if isinstance(exc, CatalogBrowserError):
        return exc.error_kind
    classified = classify_browser_error(str(exc))
    if classified == "cloudflare_challenge":
        return classified
    if classified == "timeout":
        return classified
    if classified == "browser_connection" or should_auto_heal(exc):
        return "catalog_browser_connection_failed"
    return classified or "catalog_import_failed"


def catalog_browser_error_message(exc: Exception, port: int) -> str:
    kind = catalog_browser_error_kind(exc)
    if kind == "catalog_browser_port_busy":
        return str(exc)
    if kind == "cloudflare_challenge":
        return "商家页面受到 Cloudflare / Turnstile 验证保护，已按受保护来源处理。建议改用 webhook/manual 或替代公开页面。"
    if kind == "timeout":
        return f"商品入库浏览器打开页面超时。请稍后重试，或在系统设置中提高请求超时时间。"
    if kind == "catalog_browser_connection_failed":
        return (
            f"商品入库浏览器连接失败（端口 {port}）。系统已尝试清理本角色浏览器残留并重建一次；"
            "如果仍失败，请修改 CATALOG_DEBUG_PORT / 商品入库浏览器端口，或重启服务后重试。"
        )
    raw = str(exc).strip()
    return raw[:300] if raw else "商家页面导入失败。"


def looks_like_cloudflare_challenge(html_text: str, title: str = "", url: str = "") -> bool:
    html_head = html_text[:20000]
    haystack = " ".join(part for part in (html_head, title, url) if part).lower()
    normalized_title = normalize_signal_text(title or extract_page_title(html_text))

    strong_markers = (
        "cf-turnstile",
        "cf_chl_",
        "cf-chl-",
        "cf_chl_opt",
        "cf_chl_prog",
        "challenge-platform",
        "/cdn-cgi/challenge-platform/",
        "challenges.cloudflare.com",
        "__cf_chl_tk",
        "turnstile.render",
        "verify you are human",
        "checking your browser",
        "checking if the site connection is secure",
        "review the security of your connection",
        "enable javascript and cookies to continue",
        "please wait while we verify",
        "attention required",
    )
    if any(marker in haystack for marker in strong_markers):
        return True

    title_markers = {
        "justamoment",
        "attentionrequired",
        "checkingyourbrowser",
        "verifyyouarehuman",
        "onemoremoment",
    }
    if normalized_title in title_markers or normalized_title.startswith("justamoment"):
        return True

    cloudflare_context_markers = (
        "ray id",
        "rayid",
        "performance & security by cloudflare",
        "cloudflare ray",
        "managed challenge",
        "cloudflare challenge",
        "cloudflare turnstile",
    )
    return "cloudflare" in haystack and any(marker in haystack for marker in cloudflare_context_markers)


def slice_fragment(html_text: str, keyword: str) -> str:
    if not html_text:
        return ""
    if not keyword:
        return ""
    keyword_candidates = html_keyword_candidates(keyword)
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


def html_keyword_candidates(keyword: Any) -> list[str]:
    raw = str(keyword or "").strip()
    if not raw:
        return []
    candidates = [
        raw,
        html_module.escape(raw, quote=False),
        html_module.escape(raw, quote=True),
    ]
    for match in PRODUCT_CODE_CANDIDATE_RE.finditer(raw):
        code = match.group(0).strip()
        if code:
            candidates.extend(
                [
                    code,
                    html_module.escape(code, quote=False),
                    html_module.escape(code, quote=True),
                ]
            )
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def normalize_signal_text(value: Any) -> str:
    return re.sub(r"[\s_\-]+", "", html_module.unescape(str(value)).strip().lower())


def classify_browser_error(message: str) -> str:
    lowered = normalize_signal_text(message)
    if not lowered:
        return ""
    if "受保护站点冷却中" in message or "目标页返回保护页" in message:
        return "cloudflare_challenge"
    if any(token in lowered for token in ("telegram", "sendmessage", "editmessage", "botcantsendmessagestobot")):
        return "telegram_error"
    for kind, markers in BROWSER_ERROR_KINDS.items():
        if any(marker in lowered for marker in markers):
            return kind
    if any(token in lowered for token in ("firecrawlzdrnotenabled", "zerodataretention", "zdrisnotenabled")):
        return "firecrawl_zdr_not_enabled"
    if "firecrawlpermissionerror" in lowered:
        return "firecrawl_permission_error"
    if "firecrawlbadrequest" in lowered:
        return "firecrawl_bad_request"
    if "firecrawlautherror" in lowered or "firecrawl认证失败" in lowered:
        return "firecrawl_auth_error"
    if "firecrawlcreditrequired" in lowered or "firecrawl额度不足" in lowered:
        return "firecrawl_credit_required"
    if "firecrawlratelimited" in lowered or "firecrawl频率受限" in lowered:
        return "firecrawl_rate_limited"
    if "firecrawlmonitordisabled" in lowered or "firecrawl定时监控未启用" in lowered:
        return "firecrawl_monitor_disabled"
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
        if not is_date_like_context(snippet) and not has_sold_out_marker(snippet):
            return int(text_match.group(1)), append_restock_hint("通过文本降噪提取到库存数字。", restock_hint)

    reverse_text_match = re.search(
        rf"(\d{{1,6}})[^0-9]{{0,80}}{STOCK_LABEL}",
        cleaned,
        re.IGNORECASE,
    )
    if reverse_text_match:
        snippet = cleaned[max(0, reverse_text_match.start() - 40) : min(len(cleaned), reverse_text_match.end() + 40)]
        if not is_date_like_context(snippet) and not has_sold_out_marker(snippet):
            return int(reverse_text_match.group(1)), append_restock_hint("通过文本倒序提取到库存数字。", restock_hint)

    if has_sold_out_marker(cleaned):
        return 0, append_restock_hint("命中售罄标记。", restock_hint)

    if has_orderable_marker(fragment, cleaned):
        return 1, append_restock_hint("未显示库存数字，但命中可下单/购买入口，按有货处理。", restock_hint)

    if restock_hint:
        return 0, f"检测到补货信息：{restock_hint}，但未发现明确库存数字。"

    return None, "未找到库存数字或售罄标记。"


StockExtractor = Callable[[str, str, Any, FetchResult], ExtractorResult]


def task_source_config(task: Any) -> dict[str, Any]:
    value = mapping_value(task, "source_config", {})
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def config_text_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = re.split(r"[\n,|]+", str(value or ""))
    return [str(item).strip() for item in raw_items if str(item).strip()]


def explicit_stock_rule_enabled(source_config: dict[str, Any]) -> bool:
    rule_type = str(source_config.get("stock_rule_type") or "").strip().lower().replace("-", "_")
    if rule_type and rule_type != "auto_card":
        return True
    return any(
        str(source_config.get(key) or "").strip()
        for key in (
            "stock_selector",
            "soldout_selector",
            "button_selector",
            "disabled_selector",
            "target_scope_selector",
            "json_path",
            "regex_pattern",
        )
    ) or bool(source_config.get("in_stock_keywords") or source_config.get("soldout_keywords"))


def parse_html_document(html_text: str) -> Any:
    if lxml_html is None or not html_text:
        return None
    try:
        return lxml_html.fromstring(html_text)
    except Exception:
        return None


def element_html(element: Any) -> str:
    try:
        return lxml_html.tostring(element, encoding="unicode", with_tail=False) if lxml_html is not None else ""
    except Exception:
        return ""


def element_text(element: Any) -> str:
    try:
        return re.sub(r"\s+", " ", element.text_content()).strip()
    except Exception:
        return clean_fragment_text(element_html(element))


def select_fragments_by_css(html_text: str, selector: str) -> list[str]:
    selector = str(selector or "").strip()
    if not selector:
        return []
    document = parse_html_document(html_text)
    if document is None:
        return []
    try:
        return [element_html(element) for element in document.cssselect(selector)[:30] if element_html(element)]
    except Exception:
        return []


def select_fragments_by_xpath(html_text: str, expression: str) -> list[str]:
    expression = str(expression or "").strip()
    if not expression:
        return []
    document = parse_html_document(html_text)
    if document is None:
        return []
    try:
        values = document.xpath(expression)
    except Exception:
        return []
    fragments: list[str] = []
    for value in values[:30]:
        if isinstance(value, str):
            if value.strip():
                fragments.append(value.strip())
            continue
        fragment = element_html(value)
        if fragment:
            fragments.append(fragment)
    return fragments


def json_path_values(payload: Any, path: str) -> list[Any]:
    path = str(path or "").strip()
    if not path:
        return []
    normalized = path[2:] if path.startswith("$.") else path[1:] if path.startswith("$") else path
    parts = [part for part in re.split(r"\.", normalized) if part]
    values = [payload]
    for part in parts:
        next_values: list[Any] = []
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+|\*)\])?", part)
        key = match.group(1) if match else part
        index = match.group(2) if match else None
        for value in values:
            if isinstance(value, dict) and key in value:
                child = value[key]
            else:
                continue
            if index == "*":
                if isinstance(child, list):
                    next_values.extend(child)
            elif index is not None:
                if isinstance(child, list):
                    try:
                        next_values.append(child[int(index)])
                    except (IndexError, ValueError):
                        pass
            else:
                next_values.append(child)
        values = next_values
        if not values:
            break
    return values


def json_payloads_from_html(html_text: str) -> list[Any]:
    payloads: list[Any] = []
    for match in JSON_SCRIPT_PATTERN.finditer(html_text or ""):
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
            payloads.append(json.loads(body))
        except json.JSONDecodeError:
            continue
    return payloads


def stock_from_rule_value(value: Any, detail_prefix: str) -> tuple[int | None, str] | None:
    if isinstance(value, (dict, list)):
        matched = scan_json_stock_signal(value)
        if matched is not None:
            stock, detail = matched
            return stock, f"{detail_prefix}：{detail}"
    parsed_int = parse_int_value(value)
    if parsed_int is not None:
        return parsed_int, f"{detail_prefix}：匹配到库存数字。"
    parsed_bool = parse_bool_value(value)
    if parsed_bool is not None:
        return (1 if parsed_bool else 0), f"{detail_prefix}：匹配到布尔可用状态。"
    text = str(value or "").strip()
    if text:
        stock, detail = parse_stock(text)
        if stock is not None:
            return stock, f"{detail_prefix}：{detail}"
        normalized = normalize_signal_text(text)
        if any(token in normalized for token in JSON_IN_STOCK_TOKENS):
            return 1, f"{detail_prefix}：命中可购买文本。"
        if any(token in normalized for token in JSON_OUT_OF_STOCK_TOKENS):
            return 0, f"{detail_prefix}：命中售罄文本。"
    return None


def extract_stock_by_json_path(html_text: str, json_path: str) -> ExtractorResult | None:
    for payload in json_payloads_from_html(html_text):
        for value in json_path_values(payload, json_path):
            matched = stock_from_rule_value(value, "json_path")
            if matched is not None:
                stock, detail = matched
                return ExtractorResult(stock=stock, fragment=json.dumps(value, ensure_ascii=False)[:1200], detail=detail)
    return None


def extract_stock_by_regex(html_text: str, pattern_text: str) -> ExtractorResult | None:
    pattern_text = str(pattern_text or "").strip()
    if not pattern_text:
        return None
    try:
        pattern = re.compile(pattern_text, re.IGNORECASE | re.DOTALL)
    except re.error:
        return ExtractorResult(stock=None, fragment="", detail="regex：规则格式错误，无法编译。")
    match = pattern.search(html_text or "")
    if not match:
        return ExtractorResult(stock=None, fragment="", detail="regex：未匹配到内容。")
    value = match.groupdict().get("stock") or match.group(1) if match.groups() else match.group(0)
    matched = stock_from_rule_value(value, "regex")
    fragment = html_text[max(0, match.start() - 120) : min(len(html_text), match.end() + 120)]
    if matched is None:
        return ExtractorResult(stock=None, fragment=fragment, detail="regex：已匹配内容，但无法转换为库存状态。")
    stock, detail = matched
    return ExtractorResult(stock=stock, fragment=fragment, detail=detail)


def evaluate_rule_fragments(fragments: list[str], detail_prefix: str) -> ExtractorResult | None:
    for fragment in fragments:
        stock, detail = parse_stock(fragment)
        if stock is not None:
            return ExtractorResult(stock=stock, fragment=fragment, detail=f"{detail_prefix}：{detail}")
        cleaned = clean_fragment_text(fragment)
        if has_generic_sold_out_marker(fragment, cleaned):
            return ExtractorResult(stock=0, fragment=fragment, detail=f"{detail_prefix}：命中售罄标记。")
        if has_generic_orderable_marker(fragment, cleaned):
            return ExtractorResult(stock=1, fragment=fragment, detail=f"{detail_prefix}：命中可下单/购买入口，按有货处理。")
    return None


def extract_stock_by_keyword_lists(fragment: str, source_config: dict[str, Any], detail_prefix: str) -> ExtractorResult | None:
    cleaned = clean_fragment_text(fragment)
    haystack = normalize_signal_text(f"{fragment}\n{cleaned}")
    for keyword in config_text_list(source_config.get("soldout_keywords")):
        if normalize_signal_text(keyword) in haystack:
            return ExtractorResult(stock=0, fragment=fragment, detail=f"{detail_prefix}：命中自定义售罄关键词「{keyword}」。")
    for keyword in config_text_list(source_config.get("in_stock_keywords")):
        if normalize_signal_text(keyword) in haystack:
            return ExtractorResult(stock=1, fragment=fragment, detail=f"{detail_prefix}：命中自定义有货关键词「{keyword}」。")
    return None


def extract_stock_by_rule(
    html_text: str,
    target_keyword: str,
    task: Any,
    fetch_result: FetchResult,
) -> ExtractorResult | None:
    source_config = task_source_config(task)
    if not explicit_stock_rule_enabled(source_config):
        return None
    rule_type = str(source_config.get("stock_rule_type") or "auto_card").strip().lower().replace("-", "_")
    if rule_type not in STOCK_RULE_TYPES:
        rule_type = "auto_card"

    scope_fragments = select_fragments_by_css(html_text, str(source_config.get("target_scope_selector") or ""))
    base_html = "\n".join(scope_fragments) if scope_fragments else html_text
    if rule_type == "text_near_keyword":
        base_html = locate_product_fragment(html_text, target_keyword, lambda fragment: bool(clean_fragment_text(fragment)))

    keyword_result = extract_stock_by_keyword_lists(base_html, source_config, "custom_rule")
    if keyword_result is not None:
        return keyword_result

    soldout_selector = str(source_config.get("soldout_selector") or "").strip()
    if soldout_selector and select_fragments_by_css(base_html, soldout_selector):
        return ExtractorResult(stock=0, fragment="\n".join(select_fragments_by_css(base_html, soldout_selector)), detail="css_selector：命中自定义售罄选择器。")

    disabled_selector = str(source_config.get("disabled_selector") or "").strip()
    if disabled_selector and select_fragments_by_css(base_html, disabled_selector):
        return ExtractorResult(stock=0, fragment="\n".join(select_fragments_by_css(base_html, disabled_selector)), detail="css_selector：命中自定义禁用按钮选择器。")

    button_selector = str(source_config.get("button_selector") or "").strip()
    if button_selector and select_fragments_by_css(base_html, button_selector):
        fragments = select_fragments_by_css(base_html, button_selector)
        return ExtractorResult(stock=1, fragment="\n".join(fragments), detail="css_selector：命中自定义购买按钮选择器，按有货处理。")

    if rule_type == "json_path" or source_config.get("json_path"):
        result = extract_stock_by_json_path(base_html, str(source_config.get("json_path") or ""))
        if result is not None:
            return result

    if rule_type == "regex" or source_config.get("regex_pattern"):
        result = extract_stock_by_regex(base_html, str(source_config.get("regex_pattern") or ""))
        if result is not None:
            return result

    if rule_type == "xpath":
        fragments = select_fragments_by_xpath(base_html, str(source_config.get("stock_selector") or ""))
        result = evaluate_rule_fragments(fragments, "xpath")
        if result is not None:
            return result

    if rule_type == "css_selector" or source_config.get("stock_selector"):
        fragments = select_fragments_by_css(base_html, str(source_config.get("stock_selector") or ""))
        result = evaluate_rule_fragments(fragments, "css_selector")
        if result is not None:
            return result

    if rule_type == "text_near_keyword":
        result = evaluate_rule_fragments([base_html], "text_near_keyword")
        if result is not None:
            return result

    return ExtractorResult(
        stock=None,
        fragment=base_html[:1800],
        detail=f"{rule_type}：自定义规则未能判断库存，请检查 selector / keyword / regex / json_path。",
    )


def find_html_text_position(html_text: str, keyword: str) -> int:
    if not html_text or not keyword:
        return -1
    for candidate in html_keyword_candidates(keyword):
        match = re.search(re.escape(candidate), html_text, re.IGNORECASE)
        if match:
            return match.start()
    return -1


def bounded_html_slice(html_text: str, position: int, before: int = 80, after: int = 1400) -> str:
    if not html_text:
        return ""
    if position < 0:
        return html_text[: after + before]
    start = max(0, position - before)
    end = min(len(html_text), position + after)
    return html_text[start:end]


def iter_enclosing_html_blocks(html_text: str, position: int) -> list[tuple[str, int, int]]:
    if position < 0:
        return []
    blocks: list[tuple[str, int, int]] = []
    for tag_name in PRODUCT_CONTAINER_TAGS:
        token_pattern = re.compile(rf"(?is)<\s*(/?)\s*{tag_name}\b[^>]*>")
        stack: list[int] = []
        for match in token_pattern.finditer(html_text):
            closing = bool(match.group(1))
            token = match.group(0)
            if closing:
                if not stack:
                    continue
                start = stack.pop()
                end = match.end()
                if start <= position < end:
                    blocks.append((tag_name, start, end))
                continue
            if token.rstrip().endswith("/>"):
                continue
            stack.append(match.start())
    return blocks


def score_product_fragment_candidate(fragment: str, keyword_position: int, start: int, end: int) -> int:
    cleaned = clean_fragment_text(fragment)
    stock, _ = parse_stock(fragment)
    sold_out = has_sold_out_marker(cleaned)
    orderable = has_orderable_marker(fragment, cleaned)
    score = 0
    if stock is not None:
        score += 100
    if sold_out:
        score += 40
    if orderable:
        score += 40
    if sold_out and orderable:
        score -= 70
    if start <= keyword_position < end:
        score += 30
        distance_to_keyword = keyword_position - start
        score += max(0, 18 - min(distance_to_keyword, 1800) // 100)
    fragment_length = end - start
    if fragment_length <= 5000:
        score += max(0, 18 - fragment_length // 500)
    else:
        score -= min(30, fragment_length // 2000)
    return score


def has_pattern_signal(fragment: str, cleaned_text: str, patterns: list[re.Pattern[str]]) -> bool:
    haystack = f"{fragment}\n{cleaned_text}"
    return any(pattern.search(haystack) for pattern in patterns)


def has_generic_orderable_marker(fragment: str, cleaned_text: str) -> bool:
    return has_orderable_marker(fragment, cleaned_text) or has_pattern_signal(
        fragment,
        cleaned_text,
        GENERIC_ORDERABLE_PATTERNS,
    )


def has_weak_orderable_marker(fragment: str, cleaned_text: str) -> bool:
    return has_pattern_signal(fragment, cleaned_text, WEAK_ORDERABLE_PATTERNS)


def has_generic_sold_out_marker(fragment: str, cleaned_text: str) -> bool:
    lowered = cleaned_text.lower()
    return has_sold_out_marker(cleaned_text) or any(pattern.search(lowered) for pattern in GENERIC_SOLD_OUT_PATTERNS)


def normalized_product_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def product_token_aliases(value: Any) -> set[str]:
    token = normalized_product_token(value)
    if not token:
        return set()
    aliases = {token}
    compact = token
    for removable in ("pro", "premium", "tier1", "t1"):
        compact = compact.replace(removable, "")
    if compact:
        aliases.add(compact)
    aliases.add(token.replace("tier1", "t1"))
    aliases.add(token.replace("t1", "tier1"))
    return {alias for alias in aliases if alias}


def product_query_values(task: Any, fetch_result: FetchResult) -> list[str]:
    values: list[str] = []
    urls = [
        mapping_value(task, "monitor_url", ""),
        getattr(fetch_result, "final_url", ""),
    ]
    for raw_url in urls:
        try:
            parsed = urlparse(html_module.unescape(str(raw_url or "")))
        except Exception:
            continue
        query = parse_qs(parsed.query)
        for key in ("product", "pid", "plan", "sku", "package", "service"):
            for value in query.get(key, []):
                if str(value or "").strip():
                    values.append(str(value).strip())
    return list(dict.fromkeys(values))


def product_tokens_match(left: Any, right: Any) -> bool:
    left_tokens = product_token_aliases(left)
    right_tokens = product_token_aliases(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens & right_tokens:
        return True
    return any(
        left_token.endswith(right_token) or right_token.endswith(left_token)
        for left_token in left_tokens
        for right_token in right_tokens
    )


def target_selected_by_url(task: Any, fetch_result: FetchResult, target_keyword: str) -> bool:
    if not product_token_aliases(target_keyword):
        return False
    for value in product_query_values(task, fetch_result):
        if product_tokens_match(target_keyword, value):
            return True
    return False


def find_product_query_position(html_text: str, task: Any, fetch_result: FetchResult) -> int:
    for value in product_query_values(task, fetch_result):
        parts = re.findall(r"[A-Za-z0-9]+", str(value or ""))
        if not parts:
            continue
        flexible = r"[\s._-]*".join(re.escape(part) for part in parts)
        match = re.search(flexible, html_text or "", re.IGNORECASE)
        if match:
            return match.start()
    return -1


def page_has_enabled_orderable_control(html_text: str, *, allow_weak: bool = False) -> bool:
    control_pattern = re.compile(r"(?is)<(?P<tag>a|button)\b(?P<attrs>[^>]*)>(?P<body>.{0,240}?)</(?P=tag)>")
    for match in control_pattern.finditer(html_text or ""):
        attrs = html_module.unescape(match.group("attrs") or "")
        body = clean_fragment_text(match.group("body") or "")
        control_text = f"{attrs}\n{body}"
        lowered_attrs = attrs.lower()
        if (
            "disabled" in lowered_attrs
            or "aria-disabled=\"true\"" in lowered_attrs
            or "aria-disabled='true'" in lowered_attrs
            or re.search(r"\bdisabled\b", lowered_attrs)
        ):
            continue
        if has_orderable_marker(control_text, body):
            return True
        if allow_weak and has_weak_orderable_marker(control_text, body):
            return True
    return False


def fragment_has_selected_state(fragment: str) -> bool:
    if not fragment:
        return False
    return bool(
        re.search(
            r"(?is)\b(?:class|data-state|aria-selected)\s*=\s*['\"][^'\"]*(?:selected|active|current|chosen|true)[^'\"]*['\"]",
            fragment,
        )
    )


def page_level_orderable_for_target(
    html_text: str,
    target_keyword: str,
    task: Any,
    fetch_result: FetchResult,
    fragment: str,
) -> bool:
    target_in_fragment = find_html_text_position(fragment, target_keyword) >= 0
    target_in_page = find_html_text_position(html_text, target_keyword) >= 0
    selected_by_url = target_selected_by_url(task, fetch_result, target_keyword)
    selected_by_fragment = fragment_has_selected_state(fragment)
    if not target_in_fragment and not target_in_page and not selected_by_url:
        return False
    if has_generic_sold_out_marker(fragment, clean_fragment_text(fragment)):
        return False
    if has_idc_sellable_card_signal(fragment) and (
        selected_by_url or selected_by_fragment or page_has_idc_product_selector_context(html_text)
    ):
        return True
    page_cleaned = clean_fragment_text(html_text)
    if has_generic_sold_out_marker(html_text, page_cleaned) and not selected_by_url:
        return False
    if page_has_enabled_orderable_control(html_text):
        return selected_by_url or selected_by_fragment or has_generic_orderable_marker(html_text, page_cleaned)
    if selected_by_url or selected_by_fragment:
        return page_has_enabled_orderable_control(html_text, allow_weak=True)
    return False


def has_generic_pricing_signal(fragment: str) -> bool:
    stock, _ = parse_stock(fragment)
    if stock is not None:
        return True
    cleaned = clean_fragment_text(fragment)
    return has_generic_sold_out_marker(fragment, cleaned) or has_generic_orderable_marker(fragment, cleaned)


def page_has_idc_product_selector_context(html_text: str) -> bool:
    if not html_text:
        return False
    card_like_matches = re.findall(
        r"(?is)<(?:article|div|plan-card|product-card|package-card|pricing-card)\b[^>]*(?:product-card|plan-card|pricing-card|package-card|selected|active)[^>]*>",
        html_text,
    )
    if len(card_like_matches) >= 2:
        return True
    product_heading_matches = re.findall(
        r"(?is)<h[1-6]\b[^>]*>\s*[^<]*[A-Z]{2,6}\.[A-Z0-9]+(?:\.[A-Z0-9]+){1,5}[^<]*</h[1-6]>",
        html_text,
    )
    return len(product_heading_matches) >= 2


def has_idc_product_card_signal(fragment: str) -> bool:
    if has_generic_pricing_signal(fragment):
        return True
    cleaned = clean_fragment_text(fragment)
    return bool(extract_price_hint(fragment) or has_resource_spec_signal(cleaned))


def has_whmcs_orderable_marker(fragment: str, cleaned_text: str) -> bool:
    return has_generic_orderable_marker(fragment, cleaned_text) or has_pattern_signal(
        fragment,
        cleaned_text,
        WHMCS_ORDERABLE_PATTERNS,
    )


def has_whmcs_signal(fragment: str) -> bool:
    stock, _ = parse_stock(fragment)
    if stock is not None:
        return True
    cleaned = clean_fragment_text(fragment)
    return has_generic_sold_out_marker(fragment, cleaned) or has_whmcs_orderable_marker(fragment, cleaned)


def locate_html_fragment_around_position(
    html_text: str,
    position: int,
    signal_checker: Callable[[str], bool],
) -> str:
    candidates: list[tuple[int, int, int, int, str]] = []

    def add_candidate(fragment: str, start: int, end: int, priority: int) -> None:
        if not fragment or not signal_checker(fragment):
            return
        score = score_product_fragment_candidate(fragment, position, start, end)
        if priority < 10:
            score += 80
        candidates.append((-score, priority, end - start, start, fragment))

    for tag_name, start, end in iter_enclosing_html_blocks(html_text, position):
        fragment = html_text[start:end]
        tag_priority = PRODUCT_CONTAINER_TAGS.index(tag_name)
        add_candidate(fragment, start, end, tag_priority)

    for priority, (before, after) in enumerate(((80, 1400), (180, 2400), (320, 4200)), start=10):
        start = max(0, position - before)
        end = min(len(html_text), position + after)
        add_candidate(html_text[start:end], start, end, priority)

    if candidates:
        candidates.sort()
        return candidates[0][4]
    return bounded_html_slice(html_text, position)


def locate_product_fragment(
    html_text: str,
    target_keyword: str,
    signal_checker: Callable[[str], bool],
) -> str:
    for candidate in html_keyword_candidates(target_keyword):
        position = find_html_text_position(html_text, candidate)
        if position >= 0:
            return locate_html_fragment_around_position(html_text, position, signal_checker)
    if target_keyword:
        return slice_fragment(html_text, target_keyword)
    return html_text


def extractor_detail(prefix: str, detail: str) -> str:
    detail = str(detail or "").strip()
    if not detail:
        return prefix
    return f"{prefix}：{detail}"


def extractor_unknown_detail(prefix: str, html_text: str, target_keyword: str, fragment: str) -> str:
    cleaned_page = clean_fragment_text(html_text)
    cleaned_fragment = clean_fragment_text(fragment)
    if not cleaned_page:
        return f"{prefix}：页面内容为空，可能抓到了 JS 空壳或上游返回空内容。"
    if target_keyword and find_html_text_position(html_text, target_keyword) < 0:
        return f"{prefix}：未找到目标商品标题「{target_keyword}」。"
    if len(cleaned_page) < 80 and not fragment:
        return f"{prefix}：页面文本过短，可能需要浏览器渲染或 Firecrawl。"
    if target_keyword and cleaned_fragment:
        if extract_price_hint(fragment) or has_resource_spec_signal(cleaned_fragment):
            return f"{prefix}：找到了目标商品，但缺少明确购买入口或售罄标记。"
        return f"{prefix}：找到了目标商品，但片段中缺少价格、规格、购买入口或售罄标记。"
    return f"{prefix}：未找到可用于判断库存的商品片段。"


def default_stock_extractor(
    html_text: str,
    target_keyword: str,
    task: Any,
    fetch_result: FetchResult,
) -> ExtractorResult:
    fragment = locate_product_fragment(html_text, target_keyword, has_generic_pricing_signal)
    stock, detail = parse_stock(fragment)
    return ExtractorResult(stock=stock, fragment=fragment, detail=detail)


def generic_pricing_table_extractor(
    html_text: str,
    target_keyword: str,
    task: Any,
    fetch_result: FetchResult,
) -> ExtractorResult:
    fragment = locate_product_fragment(html_text, target_keyword, has_generic_pricing_signal)
    if not fragment and target_selected_by_url(task, fetch_result, target_keyword):
        query_position = find_product_query_position(html_text, task, fetch_result)
        if query_position >= 0:
            fragment = locate_html_fragment_around_position(html_text, query_position, has_idc_product_card_signal)
    stock, detail = parse_stock(fragment)
    if stock is not None:
        return ExtractorResult(stock=stock, fragment=fragment, detail=extractor_detail("generic_pricing_table", detail))
    cleaned = clean_fragment_text(fragment)
    if has_generic_sold_out_marker(fragment, cleaned):
        return ExtractorResult(stock=0, fragment=fragment, detail="generic_pricing_table：命中售罄标记。")
    if has_generic_orderable_marker(fragment, cleaned):
        return ExtractorResult(
            stock=1,
            fragment=fragment,
            detail="generic_pricing_table：未显示库存数字，但命中可下单/购买入口，按有货处理。",
        )
    if page_level_orderable_for_target(html_text, target_keyword, task, fetch_result, fragment):
        return ExtractorResult(
            stock=1,
            fragment=fragment,
            detail="generic_pricing_table：目标产品已出现在可继续下单页面，按有货处理。",
        )
    return ExtractorResult(stock=None, fragment=fragment, detail=extractor_unknown_detail("generic_pricing_table", html_text, target_keyword, fragment))


def extract_query_int(url: str, key: str) -> int | None:
    parsed = urlparse(html_module.unescape(str(url or "")))
    values = parse_qs(parsed.query).get(key, [])
    for value in values:
        parsed_value = parse_int_value(value)
        if parsed_value is not None:
            return parsed_value
    return None


def whmcs_task_pid(task: Any, fetch_result: FetchResult) -> int | None:
    source_config = task_source_config(task)
    for key in ("pid", "product_id", "productId"):
        parsed_value = parse_int_value(source_config.get(key))
        if parsed_value is not None:
            return parsed_value
    urls = [
        mapping_value(task, "monitor_url", ""),
        getattr(fetch_result, "final_url", ""),
    ]
    for url in urls:
        parsed_value = extract_query_int(str(url or ""), "pid")
        if parsed_value is not None:
            return parsed_value
    return None


def find_whmcs_pid_position(html_text: str, pid: int) -> int:
    pid_text = re.escape(str(pid))
    patterns = [
        re.compile(rf"(?:\?|&amp;|&)pid={pid_text}\b", re.IGNORECASE),
        re.compile(
            rf"name\s*=\s*['\"]pid['\"][^>]*value\s*=\s*['\"]{pid_text}['\"]",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            rf"value\s*=\s*['\"]{pid_text}['\"][^>]*name\s*=\s*['\"]pid['\"]",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(rf"\bpid\s*[:=]\s*['\"]?{pid_text}\b", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(html_text)
        if match:
            return match.start()
    return -1


def whmcs_product_fragment(
    html_text: str,
    target_keyword: str,
    task: Any,
    fetch_result: FetchResult,
) -> str:
    pid = whmcs_task_pid(task, fetch_result)
    if pid is not None:
        position = find_whmcs_pid_position(html_text, pid)
        if position >= 0:
            return locate_html_fragment_around_position(html_text, position, has_whmcs_signal)
    return locate_product_fragment(html_text, target_keyword, has_whmcs_signal)


def whmcs_extractor(
    html_text: str,
    target_keyword: str,
    task: Any,
    fetch_result: FetchResult,
) -> ExtractorResult:
    fragment = whmcs_product_fragment(html_text, target_keyword, task, fetch_result)
    stock, detail = parse_stock(fragment)
    if stock is not None:
        return ExtractorResult(stock=stock, fragment=fragment, detail=extractor_detail("WHMCS", detail))
    cleaned = clean_fragment_text(fragment)
    if has_generic_sold_out_marker(fragment, cleaned):
        return ExtractorResult(stock=0, fragment=fragment, detail="WHMCS：命中售罄标记。")
    if has_whmcs_orderable_marker(fragment, cleaned):
        return ExtractorResult(
            stock=1,
            fragment=fragment,
            detail="WHMCS：未显示库存数字，但命中 WHMCS 下单入口，按有货处理。",
        )
    return ExtractorResult(stock=None, fragment=fragment, detail=extractor_unknown_detail("WHMCS", html_text, target_keyword, fragment))


EXTRACTOR_REGISTRY: dict[str, StockExtractor] = {
    FETCH_STRATEGY_GENERIC_PRICING_TABLE: generic_pricing_table_extractor,
    FETCH_STRATEGY_WHMCS: whmcs_extractor,
}


def extract_stock_for_strategy(
    strategy: str,
    html_text: str,
    target_keyword: str,
    task: Any,
    fetch_result: FetchResult,
) -> ExtractorResult:
    if looks_like_cloudflare_challenge(html_text, extract_page_title(html_text), fetch_result.final_url):
        return ExtractorResult(
            stock=None,
            fragment="",
            detail="目标页返回保护页，未进入库存解析。",
        )
    rule_result = extract_stock_by_rule(html_text, target_keyword, task, fetch_result)
    if rule_result is not None:
        return rule_result
    source_config = parse_source_config(mapping_value(task, "source_config", "{}"))
    configured_extractor = normalize_fetch_strategy(source_config.get("extractor"))
    extractor_key = configured_extractor if configured_extractor in EXTRACTOR_REGISTRY else normalize_fetch_strategy(strategy)
    extractor = EXTRACTOR_REGISTRY.get(extractor_key, default_stock_extractor)
    return extractor(html_text, target_keyword, task, fetch_result)


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
    "main",
    "my",
    "join",
    "channel",
    "join channel",
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
    "english",
    "中文",
    "简体中文",
    "簡體中文",
    "繁體中文",
    "繁体中文",
    "日本語",
    "한국어",
}
DISCOVERY_LOCALE_TEXTS = {
    "中文",
    "简体中文",
    "簡體中文",
    "繁體中文",
    "繁体中文",
    "english",
    "en",
    "日本語",
    "日本语",
    "한국어",
}
DISCOVERY_SECTION_ONLY_TEXTS = {
    "选择地区",
    "選擇地區",
    "选择区域",
    "選擇區域",
    "选择网络",
    "選擇網絡",
    "选择网络类型",
    "選擇網絡類型",
    "选择套餐",
    "選擇套餐",
    "选择套餐类型",
    "選擇套餐類型",
    "选择世代",
    "選擇世代",
    "选择实例类型",
    "選擇實例類型",
    "region",
    "network",
    "generation",
    "products",
    "plans",
    "pricing",
}
DISCOVERY_RESOURCE_PATTERNS = [
    re.compile(
        r"\b(?:v?cpu|cores?|ram|memory|nvme|ssd|hdd|disk|storage|bandwidth|traffic|transfer|ipv4|ipv6|ddos|gbps|mbps|tb|gb)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:虚拟核心|虛擬核心|核心|内存|記憶體|內存|硬碟|硬盘|流量|带宽|頻寬|網絡路由|网络路由|防禦|防御)"),
]
DISCOVERY_PRODUCT_TITLE_PATTERN = re.compile(
    r"(?:\b(?:vps|cloud|server|dedicated|premium|starter|tiny|mini|micro|pro|standard|basic|plan|package|nvme)\b|[A-Z0-9]{2,}(?:[._-][A-Z0-9]{2,}){1,})",
    re.IGNORECASE,
)
DISCOVERY_WHMSC_URL_PATTERN = re.compile(
    r"(?:cart\.php\?[^#]*(?:gid=|pid=|a=(?:add|confproduct))|/store/|configureproduct)",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(r"<h[1-6]\b(?P<attrs>[^>]*)>(?P<body>.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
ANCHOR_PATTERN = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>", re.IGNORECASE | re.DOTALL)
TITLE_ATTR_PATTERN = re.compile(r"\b(?P<key>[a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)\2", re.DOTALL)
CONTEXT_ATTR_PATTERN = re.compile(
    r"\b(?:class|id|role|aria-label|data-section|data-testid|data-role)\s*=\s*(?P<quote>['\"])(?P<value>.*?)\1",
    re.IGNORECASE | re.DOTALL,
)
DISCOVERY_CONTEXT_POSITIVE_MARKERS = (
    "product",
    "package",
    "plan",
    "pricing",
    "price",
    "offer",
    "item",
    "card",
    "listing",
    "catalog",
    "service",
    "sku",
    "inventory",
    "shop",
)
DISCOVERY_CONTEXT_NEGATIVE_MARKERS = (
    "nav",
    "navbar",
    "breadcrumb",
    "menu",
    "sidebar",
    "footer",
    "header",
    "topbar",
    "toolbar",
    "mobile",
    "drawer",
    "pagination",
    "pager",
    "filter",
    "sort",
    "login",
    "logout",
    "account",
    "cart",
    "checkout",
    "search",
)
PRICE_PATTERN = re.compile(
    r"(?:￥|¥|CNY|RMB|HK\$|USD|\$|€|£)\s*\d[\d,]*(?:\.\d{1,2})?",
    re.IGNORECASE,
)
DISCOVERY_GENERIC_TEXTS_NORMALIZED = {normalize_signal_text(text) for text in DISCOVERY_GENERIC_TEXTS}
DISCOVERY_ACTION_TEXTS_NORMALIZED = {normalize_signal_text(text) for text in DISCOVERY_ACTION_TEXTS}


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


def collect_context_blob(fragment: str) -> str:
    values: list[str] = []
    for match in CONTEXT_ATTR_PATTERN.finditer(fragment or ""):
        value = normalize_signal_text(match.group("value"))
        if value:
            values.append(value)
    return " ".join(values)


def catalog_signal(signal_type: str, weight: int, text: str) -> dict[str, Any]:
    return {
        "type": signal_type,
        "weight": int(weight),
        "text": normalize_candidate_title(text)[:160],
    }


def has_resource_spec_signal(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in DISCOVERY_RESOURCE_PATTERNS)


def has_idc_sellable_card_signal(fragment: str) -> bool:
    """Return true when a target IDC product card has enough local buyability evidence.

    This intentionally ignores page-level footer buttons such as Continue/Checkout.
    A product card with a price and server resources is selectable on many IDC cart
    pages; a sold-out marker inside that same card is handled before this helper.
    """

    if not fragment:
        return False
    cleaned = clean_fragment_text(fragment)
    if has_generic_sold_out_marker(fragment, cleaned):
        return False
    if has_generic_orderable_marker(fragment, cleaned):
        return True
    return bool(extract_price_hint(fragment) and has_resource_spec_signal(cleaned))


def normalized_title_token(value: Any) -> str:
    return normalize_signal_text(normalize_candidate_title(value))


def is_locale_or_navigation_title(title: str) -> bool:
    normalized = normalized_title_token(title)
    if not normalized:
        return True
    if normalized in DISCOVERY_GENERIC_TEXTS_NORMALIZED or normalized in DISCOVERY_ACTION_TEXTS_NORMALIZED:
        return True
    locale_tokens = {normalize_signal_text(text) for text in DISCOVERY_LOCALE_TEXTS}
    if normalized in locale_tokens:
        return True
    return bool(re.fullmatch(r"(?:en|zh|zhcn|zhtw|cn|tw|hk|jp|ja|kr|ko)", normalized))


def is_section_only_title(title: str) -> bool:
    normalized = normalized_title_token(title)
    section_tokens = {normalize_signal_text(text) for text in DISCOVERY_SECTION_ONLY_TEXTS}
    return normalized in section_tokens


def catalog_candidate_evaluation(
    title: str,
    fragment: str,
    cleaned_fragment: str,
    stock_value: int | None,
    price_hint: str,
    restock_hint: str,
    monitor_url: str = "",
    item_url: str = "",
    structured: bool = False,
) -> dict[str, Any]:
    normalized_title = normalize_candidate_title(title)
    signals: list[dict[str, Any]] = []
    reject_reasons: list[str] = []

    if not is_likely_product_title(normalized_title):
        reject_reasons.append("标题不像商品名称")
    if is_locale_or_navigation_title(normalized_title):
        reject_reasons.append("语言切换或导航文本")
    if is_section_only_title(normalized_title):
        reject_reasons.append("分类/步骤标题，不是商品")

    context_blob = normalize_signal_text(f"{cleaned_fragment} {collect_context_blob(fragment)}")
    has_positive_context = any(marker in context_blob for marker in DISCOVERY_CONTEXT_POSITIVE_MARKERS)
    has_negative_context = any(marker in context_blob for marker in DISCOVERY_CONTEXT_NEGATIVE_MARKERS)
    has_orderable = has_orderable_marker(fragment, cleaned_fragment)
    has_sold_out = has_sold_out_marker(cleaned_fragment)
    has_resource_specs = has_resource_spec_signal(cleaned_fragment)
    url_text = f"{monitor_url} {item_url}"
    has_whmcs_url = bool(DISCOVERY_WHMSC_URL_PATTERN.search(url_text))
    has_product_url = any(marker in url_text.lower() for marker in ("/store/", "product=", "pid=", "gid=", "package=", "sku=", "cart.php"))

    if structured:
        signals.append(catalog_signal("structured_data", 24, "结构化商品数据"))
    if has_positive_context:
        signals.append(catalog_signal("product_context", 18, collect_context_blob(fragment) or "product/pricing/card"))
    if price_hint:
        signals.append(catalog_signal("price", 30, price_hint))
    if stock_value is not None and not has_negative_context:
        signals.append(catalog_signal("stock", 24, str(stock_value)))
    if has_orderable:
        signals.append(catalog_signal("order_button", 34, "命中购买/继续下单入口"))
    if has_sold_out:
        signals.append(catalog_signal("sold_out", 24, "命中售罄标记"))
    if restock_hint:
        signals.append(catalog_signal("restock_hint", 16, restock_hint))
    if has_resource_specs:
        signals.append(catalog_signal("specs", 20, "命中 CPU/RAM/SSD/流量等资源规格"))
    if has_whmcs_url:
        signals.append(catalog_signal("whmcs_url", 30, url_text))
    elif has_product_url:
        signals.append(catalog_signal("product_url", 16, url_text))
    if DISCOVERY_PRODUCT_TITLE_PATTERN.search(normalized_title):
        signals.append(catalog_signal("product_title", 20, normalized_title))

    score = sum(signal["weight"] for signal in signals)
    if has_negative_context:
        penalty = 22 if has_positive_context else 70
        signals.append(catalog_signal("negative_nav", -penalty, collect_context_blob(fragment) or "nav/footer/header"))
        score -= penalty
    if len(cleaned_fragment) > 3600 and not has_positive_context:
        signals.append(catalog_signal("wide_fragment", -12, "片段过大且缺少商品上下文"))
        score -= 12
    if is_section_only_title(normalized_title):
        signals.append(catalog_signal("negative_section_title", -80, normalized_title))
        score -= 80
    if is_locale_or_navigation_title(normalized_title):
        signals.append(catalog_signal("negative_locale_nav", -100, normalized_title))
        score -= 100

    has_core_signal = bool(price_hint or has_orderable or has_sold_out or stock_value is not None or has_resource_specs or has_whmcs_url)
    if not has_core_signal:
        reject_reasons.append("缺少价格、库存、规格或购买入口")
    if has_negative_context and not has_positive_context:
        reject_reasons.append("位于导航/页脚/菜单区域")
    if score < 45:
        reject_reasons.append("置信度过低")

    included = not reject_reasons and score >= 45
    reason_source = [signal for signal in signals if signal["weight"] > 0]
    include_reason = "、".join(signal["type"] for signal in reason_source[:4]) if included else ""
    return {
        "included": included,
        "confidence": max(0, min(100, score)),
        "signals": signals,
        "include_reason": include_reason,
        "reject_reason": "；".join(dict.fromkeys(reject_reasons)),
        "candidate_type": "structured" if structured else ("whmcs" if has_whmcs_url else "html"),
    }


def is_discovery_candidate(title: str, fragment: str, cleaned_fragment: str, stock_value: int | None, price_hint: str, restock_hint: str) -> bool:
    return bool(
        catalog_candidate_evaluation(
            title,
            fragment,
            cleaned_fragment,
            stock_value,
            price_hint,
            restock_hint,
        )["included"]
    )


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


def catalog_url_host_allowed(source_url: str, candidate_url: str, allow_subdomains: bool = False) -> bool:
    source_host = (urlparse(source_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()
    if not source_host or not candidate_host:
        return False
    if candidate_host == source_host:
        return True
    return allow_subdomains and candidate_host.endswith(f".{source_host}")


def catalog_url_key(candidate_url: str, dedupe_policy: str = "by_url", ignore_query_parameters: bool = False) -> str:
    parsed = urlparse(candidate_url)
    query = parsed.query
    query_values = parse_qs(query, keep_blank_values=True)
    if dedupe_policy == "by_pid" and (query_values.get("pid") or query_values.get("gid")):
        marker = query_values.get("pid", query_values.get("gid", [""]))[0]
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{('pid' if query_values.get('pid') else 'gid')}={marker}".lower()
    if dedupe_policy == "by_pid" and (query_values.get("id") or query_values.get("cat_id")):
        marker_key = "id" if query_values.get("id") else "cat_id"
        marker = query_values.get(marker_key, [""])[0]
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{marker_key}={marker}".lower()
    if ignore_query_parameters:
        query = ""
    return parsed._replace(fragment="", query=query).geturl().rstrip("/").lower()


def is_hidden_catalog_probe_url(candidate_url: str) -> bool:
    parsed = urlparse(candidate_url)
    path = (parsed.path or "").lower()
    query = parse_qs(parsed.query, keep_blank_values=True)
    action = first_non_empty(*(query.get("a") or query.get("action") or [])).lower()
    command = first_non_empty(*(query.get("cmd") or [])).lower()
    if path.endswith("cart.php") and action == "add" and query.get("pid"):
        return True
    if path.rstrip("/").endswith("/cart") and action == "add" and query.get("id"):
        return True
    return bool(command == "cart" and query.get("cat_id"))


def is_catalog_candidate_url(source_url: str, candidate_url: str, options: dict[str, Any]) -> bool:
    if not candidate_url or not validate_http_url(candidate_url):
        return False
    if not catalog_url_host_allowed(source_url, candidate_url, bool(options.get("allow_subdomains"))):
        return False
    parsed = urlparse(candidate_url)
    haystack = f"{parsed.path}?{parsed.query}".lower()
    include_paths = options.get("include_paths") or []
    exclude_paths = options.get("exclude_paths") or []
    if include_paths and not any(part in haystack for part in include_paths):
        return False
    if exclude_paths and any(part in haystack for part in exclude_paths):
        return False
    if is_hidden_catalog_probe_url(candidate_url):
        return True
    if any(marker in haystack for marker in CATALOG_URL_DROP_MARKERS):
        return False
    if any(marker in haystack for marker in CATALOG_URL_KEEP_MARKERS):
        return True
    return candidate_url.rstrip("/") == source_url.rstrip("/")


def discover_candidate_urls_from_html(html_text: str, source_url: str, options: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = [{"url": source_url, "source": "entry"}]
    seen = {catalog_url_key(source_url, options.get("dedupe_policy", "by_url"), bool(options.get("ignore_query_parameters")))}
    for anchor in ANCHOR_PATTERN.finditer(html_text or ""):
        attrs = parse_tag_attributes(anchor.group("attrs") or "")
        href = (attrs.get("href") or "").strip()
        if not href:
            continue
        candidate_url = normalize_candidate_url(source_url, href)
        if not is_catalog_candidate_url(source_url, candidate_url, options):
            continue
        key = catalog_url_key(candidate_url, options.get("dedupe_policy", "by_url"), bool(options.get("ignore_query_parameters")))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"url": candidate_url, "source": "page_links"})
        if len(candidates) >= int(options.get("max_discovered_urls") or 50):
            break
    return candidates


def parse_firecrawl_map_links(result: FetchResult) -> list[str]:
    if result.error_kind or not result.html:
        return []
    try:
        payload = json.loads(result.html)
    except json.JSONDecodeError:
        return []
    links = payload.get("links") if isinstance(payload, dict) else []
    if not isinstance(links, list):
        return []
    return [str(link).strip() for link in links if str(link).strip()]


def catalog_item_matches_target_keyword(item: dict[str, Any], options: dict[str, Any]) -> bool:
    target_keyword = str(options.get("target_keyword") or "").strip()
    if not target_keyword:
        return True
    mode = str(options.get("target_keyword_mode") or "contains").strip().lower()
    title = str(item.get("title") or item.get("keyword") or "")
    searchable_text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "keyword", "price_hint", "stock_hint")
    )
    normalized_target = normalize_signal_text(target_keyword)
    normalized_title = normalize_signal_text(title)
    normalized_searchable = normalize_signal_text(searchable_text)
    if mode == "exact":
        return normalized_title == normalized_target or product_tokens_match(title, target_keyword)
    if mode == "fuzzy":
        target_parts = [part for part in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", target_keyword.lower()) if len(part) >= 2]
        if target_parts and all(normalize_signal_text(part) in normalized_searchable for part in target_parts):
            return True
        return product_tokens_match(title, target_keyword)
    return normalized_target in normalized_searchable or product_tokens_match(title, target_keyword)


def catalog_item_filter_reject_reason(item: dict[str, Any], options: dict[str, Any]) -> str:
    target_keyword = str(options.get("target_keyword") or "").strip()
    if target_keyword and not catalog_item_matches_target_keyword(item, options):
        return f"目标关键词不匹配：{target_keyword}"
    if options.get("include_sold_out", True):
        return ""
    stock_hint = normalize_signal_text(item.get("stock_hint", ""))
    text = normalize_signal_text(f"{item.get('raw_snippet', '')} {item.get('raw_payload', '')}")
    if stock_hint in {"0", "outofstock", "soldout", "unavailable"}:
        return "已按设置排除售罄商品"
    if any(normalize_signal_text(marker) in text for marker in SOLD_OUT_MARKERS):
        return "已按设置排除售罄商品"
    return ""


def should_keep_catalog_item(item: dict[str, Any], options: dict[str, Any]) -> bool:
    return not catalog_item_filter_reject_reason(item, options)


def prepare_catalog_item(item: dict[str, Any], source_url: str, page_url: str, discovery_source: str, backend_used: str, options: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(item)
    prepared["monitor_url"] = normalize_candidate_url(page_url, prepared.get("monitor_url", "")) or page_url
    prepared["item_url"] = normalize_candidate_url(page_url, prepared.get("item_url", "")) or prepared["monitor_url"]
    prepared["fetch_strategy"] = options.get("default_fetch_strategy") or DEFAULT_TASK_FETCH_STRATEGY
    configured_extractor = options.get("default_extractor") or CATALOG_EXTRACTOR_GENERIC
    prepared["source_config"] = {
        "extractor": configured_extractor,
        "catalog_backend": backend_used,
        "catalog_discovery_source": discovery_source,
        "catalog_source_url": source_url,
    }
    probe_urls = [prepared["monitor_url"], prepared["item_url"], page_url]
    pid = next((value for value in (extract_query_int(url, "pid") for url in probe_urls) if value is not None), None)
    gid = next((value for value in (extract_query_int(url, "gid") for url in probe_urls) if value is not None), None)
    hostbill_id = next((value for value in (extract_query_int(url, "id") for url in probe_urls) if value is not None), None)
    hostbill_cat_id = next((value for value in (extract_query_int(url, "cat_id") for url in probe_urls) if value is not None), None)
    if pid is not None:
        prepared["source_config"]["pid"] = pid
        prepared["source_config"]["enable_whmcs_pid_probe"] = True
        if configured_extractor == CATALOG_EXTRACTOR_GENERIC:
            prepared["source_config"]["extractor"] = CATALOG_EXTRACTOR_WHMCS
    if gid is not None:
        prepared["source_config"]["gid"] = gid
        if configured_extractor == CATALOG_EXTRACTOR_GENERIC:
            prepared["source_config"]["extractor"] = CATALOG_EXTRACTOR_WHMCS
    if hostbill_id is not None and ("hostbill" in discovery_source or is_hidden_catalog_probe_url(prepared["monitor_url"])):
        prepared["source_config"]["hostbill_id"] = hostbill_id
    if hostbill_cat_id is not None:
        prepared["source_config"]["hostbill_cat_id"] = hostbill_cat_id
    payload = {
        "catalog_backend": backend_used,
        "catalog_discovery_source": discovery_source,
        "catalog_page_url": page_url,
        "fetch_strategy": prepared["fetch_strategy"],
        "extractor": prepared["source_config"]["extractor"],
        "source_config": prepared["source_config"],
        "confidence": prepared.get("confidence", 0),
        "candidate_type": prepared.get("candidate_type", ""),
        "include_reason": prepared.get("include_reason", ""),
        "reject_reason": prepared.get("reject_reason", ""),
        "signals": prepared.get("signals", []),
        "raw_payload": prepared.get("raw_payload", ""),
    }
    prepared["raw_payload"] = json.dumps(payload, ensure_ascii=False)[:4000]
    return prepared


def catalog_item_response_payload(item: dict[str, Any], include_raw: bool = True) -> dict[str, Any]:
    source_config = item.get("source_config") if isinstance(item.get("source_config"), dict) else {}
    payload = {
        "source_item_key": str(item.get("source_item_key") or item.get("item_key") or ""),
        "title": str(item.get("title") or ""),
        "keyword": str(item.get("keyword") or item.get("title") or ""),
        "monitor_url": str(item.get("monitor_url") or ""),
        "item_url": str(item.get("item_url") or item.get("monitor_url") or ""),
        "price_hint": str(item.get("price_hint") or ""),
        "stock_hint": str(item.get("stock_hint") or ""),
        "restock_hint": str(item.get("restock_hint") or ""),
        "fetch_strategy": normalize_fetch_strategy(item.get("fetch_strategy") or DEFAULT_TASK_FETCH_STRATEGY),
        "source_config": source_config,
        "backend_used": str(source_config.get("catalog_backend") or item.get("backend_used") or ""),
        "discovery_source": str(source_config.get("catalog_discovery_source") or item.get("discovery_source") or ""),
        "extractor": str(source_config.get("extractor") or item.get("extractor") or ""),
        "confidence": int(item.get("confidence") or 0),
        "candidate_type": str(item.get("candidate_type") or ""),
        "include_reason": str(item.get("include_reason") or ""),
        "reject_reason": str(item.get("reject_reason") or ""),
        "signals": item.get("signals") if isinstance(item.get("signals"), list) else [],
    }
    if include_raw:
        payload["raw_snippet"] = str(item.get("raw_snippet") or "")[:4000]
        payload["raw_payload"] = str(item.get("raw_payload") or "")[:4000]
    return payload


def normalize_preview_catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = catalog_item_response_payload(item, include_raw=True)
    if not normalized["source_item_key"]:
        normalized["source_item_key"] = infer_source_item_key(
            "",
            normalized["title"],
            normalized["monitor_url"],
            normalized["item_url"],
        )
    if not normalized["title"]:
        raise ValueError("预览商品缺少标题。")
    if not validate_http_url(normalized["monitor_url"]):
        raise ValueError(f"预览商品链接无效：{normalized['monitor_url']}")
    if normalized["item_url"] and not validate_http_url(normalized["item_url"]):
        normalized["item_url"] = normalized["monitor_url"]
    return normalized


def is_action_url(url: str) -> bool:
    lowered = url.lower()
    return any(part in lowered for part in ("cart.php?a=add", "/cart/add", "/checkout", "/order", "add-to-cart", "addtocart"))


def is_likely_product_title(title: str) -> bool:
    candidate = normalize_candidate_title(title)
    if len(candidate) < 2:
        return False
    lowered = normalize_signal_text(candidate)
    if lowered in DISCOVERY_GENERIC_TEXTS_NORMALIZED or lowered in DISCOVERY_ACTION_TEXTS_NORMALIZED:
        return False
    if is_section_only_title(candidate) or is_locale_or_navigation_title(candidate):
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


def discover_catalog_items(html_text: str, source_url: str, include_rejected: bool = False) -> list[dict[str, Any]]:
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
        stock_value: int | None = None,
        stock_hint: str = "",
        restock_hint: str = "",
        structured: bool = False,
    ) -> None:
        normalized_title = normalize_candidate_title(title)
        cleaned_snippet = clean_fragment_text(snippet)
        normalized_monitor = normalize_candidate_url(source_url, monitor_url) if monitor_url else source_url
        normalized_item = normalize_candidate_url(source_url, item_url) if item_url else normalized_monitor
        effective_price_hint = price_hint
        parsed_stock_value = stock_value if isinstance(stock_value, int) else None
        evaluation = catalog_candidate_evaluation(
            normalized_title,
            snippet,
            cleaned_snippet,
            parsed_stock_value,
            effective_price_hint,
            restock_hint,
            normalized_monitor,
            normalized_item,
            structured,
        )
        if not evaluation["included"] and not include_rejected:
            return
        key = infer_source_item_key(source_url, normalized_title, normalized_monitor, normalized_item)
        if key in candidates:
            existing = candidates[key]
            if len(snippet) > len(existing.get("raw_snippet", "")):
                existing["raw_snippet"] = snippet[:4000]
            if effective_price_hint and not existing.get("price_hint"):
                existing["price_hint"] = effective_price_hint[:120]
            if stock_hint and not existing.get("stock_hint"):
                existing["stock_hint"] = stock_hint[:80]
            if restock_hint and not existing.get("restock_hint"):
                existing["restock_hint"] = restock_hint[:120]
            if int(evaluation.get("confidence") or 0) > int(existing.get("confidence") or 0):
                existing["confidence"] = int(evaluation.get("confidence") or 0)
                existing["candidate_type"] = str(evaluation.get("candidate_type") or "")
                existing["include_reason"] = str(evaluation.get("include_reason") or "")
                existing["reject_reason"] = str(evaluation.get("reject_reason") or "")
                existing["signals"] = evaluation.get("signals", [])
            return
        raw_payload = {
            "candidate": raw_payload,
            "confidence": evaluation["confidence"],
            "candidate_type": evaluation["candidate_type"],
            "include_reason": evaluation["include_reason"],
            "reject_reason": evaluation["reject_reason"],
            "signals": evaluation["signals"],
        }
        candidates[key] = {
            "source_item_key": key,
            "title": normalized_title,
            "keyword": normalized_title,
            "monitor_url": normalized_monitor or source_url,
            "item_url": normalized_item or normalized_monitor or source_url,
            "price_hint": effective_price_hint[:120],
            "stock_hint": stock_hint[:80],
            "restock_hint": restock_hint[:120],
            "raw_snippet": snippet[:4000],
            "raw_payload": json.dumps(raw_payload, ensure_ascii=False)[:4000],
            "confidence": int(evaluation["confidence"]),
            "candidate_type": str(evaluation["candidate_type"]),
            "include_reason": str(evaluation["include_reason"]),
            "reject_reason": str(evaluation["reject_reason"]),
            "signals": evaluation["signals"],
        }

    def extract_best_links(fragment: str, start_offset: int = 0, max_gap: int = 420) -> tuple[str, str]:
        fallback_url = source_url
        for anchor in ANCHOR_PATTERN.finditer(fragment):
            if anchor.start() < start_offset:
                continue
            if anchor.start() > start_offset + max_gap:
                break
            attrs = parse_tag_attributes(anchor.group("attrs") or "")
            href = (attrs.get("href") or "").strip()
            if not href:
                continue
            candidate_url = normalize_candidate_url(source_url, href)
            if is_action_url(href):
                return source_url, candidate_url
            if fallback_url == source_url:
                fallback_url = candidate_url
        return fallback_url, fallback_url

    for json_candidate in extract_jsonld_catalog_candidates(html_text, source_url):
        register_candidate(
            json_candidate["title"],
            json_candidate["monitor_url"],
            json_candidate["item_url"],
            json_candidate.get("raw_payload", ""),
            json_candidate,
            json_candidate.get("price_hint", ""),
            None,
            json_candidate.get("stock_hint", ""),
            json_candidate.get("restock_hint", ""),
            True,
        )

    for heading in HEADING_PATTERN.finditer(html_text):
        attrs = parse_tag_attributes(heading.group("attrs") or "")
        title = first_non_empty(
            attrs.get("data-title"),
            attrs.get("aria-label"),
            attrs.get("title"),
            heading.group("body"),
        )
        if not title:
            continue
        snippet_start = max(0, heading.start() - 180)
        snippet_end = min(len(html_text), heading.end() + 600)
        snippet = html_text[snippet_start:snippet_end]
        cleaned_snippet = clean_fragment_text(snippet)
        stock_value, stock_detail = parse_stock(snippet)
        stock_hint = "" if stock_value is None else str(stock_value)
        restock_hint = ""
        if "补货" in stock_detail or "restock" in stock_detail.lower() or "到货" in stock_detail:
            restock_hint = stock_detail
        price_hint = extract_price_hint(snippet)
        monitor_url, item_url = extract_best_links(snippet, max(0, heading.end() - snippet_start), 320)
        register_candidate(
            title,
            monitor_url,
            item_url,
            snippet,
            {
                "source": "heading",
                "title": title,
                "heading": cleaned_snippet,
            },
            price_hint,
            stock_value,
            stock_hint,
            restock_hint,
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
        snippet_start = max(0, anchor.start() - 160)
        snippet_end = min(len(html_text), anchor.end() + 450)
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
            stock_value,
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
            True,
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
        if is_public_webhook_request():
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
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self' data:; "
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
            tasks = connection.execute("SELECT * FROM tasks ORDER BY sort_order ASC, id DESC").fetchall()
            task_groups = connection.execute("SELECT * FROM task_groups ORDER BY sort_order ASC, group_name ASC").fetchall()
            task_group_nodes = connection.execute(
                "SELECT * FROM task_group_nodes ORDER BY group_name ASC, sort_order ASC, subgroup_name ASC"
            ).fetchall()
            domain_session_rows = connection.execute(
                "SELECT * FROM domain_sessions ORDER BY updated_at DESC, domain ASC"
            ).fetchall()
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
                "task_groups": [to_task_group_payload(row) for row in task_groups],
                "task_group_nodes": [to_task_group_node_payload(row) for row in task_group_nodes],
                "domain_sessions": [safe_domain_session_payload(row) for row in domain_session_rows],
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
                    "telegram_chat_ids": settings_payload["telegram_chat_ids"],
                    "telegram_chat_ids_text": settings_payload["telegram_chat_ids_text"],
                    "monitor_debug_port": settings_payload["monitor_debug_port"],
                    "test_debug_port": settings_payload["test_debug_port"],
                    "catalog_debug_port": settings_payload["catalog_debug_port"],
                    "poll_interval_seconds": settings_payload["poll_interval_seconds"],
                    "request_timeout_seconds": settings_payload["request_timeout_seconds"],
                    "firecrawl_enabled": settings_payload["firecrawl_enabled"],
                    "firecrawl_api_url": settings_payload["firecrawl_api_url"],
                    "firecrawl_api_key_masked": mask_secret(settings_payload["firecrawl_api_key"]),
                    "firecrawl_timeout_seconds": settings_payload["firecrawl_timeout_seconds"],
                    "firecrawl_max_age_ms": settings_payload["firecrawl_max_age_ms"],
                    "firecrawl_store_in_cache": settings_payload["firecrawl_store_in_cache"],
                    "firecrawl_proxy_mode": settings_payload["firecrawl_proxy_mode"],
                    "firecrawl_allow_auto_proxy": settings_payload["firecrawl_allow_auto_proxy"],
                    "firecrawl_allow_enhanced_proxy": settings_payload["firecrawl_allow_enhanced_proxy"],
                    "firecrawl_zero_data_retention": settings_payload["firecrawl_zero_data_retention"],
                    "firecrawl_use_for_monitor": settings_payload["firecrawl_use_for_monitor"],
                    "firecrawl_use_for_catalog": settings_payload["firecrawl_use_for_catalog"],
                    "firecrawl_catalog_limit": settings_payload["firecrawl_catalog_limit"],
                    "enhanced_collector_status": EnhancedCollectorManager(settings_payload).health_check(
                        probe_candidates=False
                    ),
                    "enhanced_collector_enabled": settings_payload["enhanced_collector_enabled"],
                    "enhanced_collector_api_url": settings_payload["enhanced_collector_api_url"],
                    "enhanced_collector_timeout_seconds": settings_payload["enhanced_collector_timeout_seconds"],
                    "enhanced_collector_max_retries": settings_payload["enhanced_collector_max_retries"],
                    "enhanced_collector_use_for_monitor": settings_payload["enhanced_collector_use_for_monitor"],
                    "enhanced_collector_use_for_catalog": settings_payload["enhanced_collector_use_for_catalog"],
                    "scrapling_status": scrapling_runtime_status(),
                    "scrapling_enabled": settings_payload["scrapling_enabled"],
                    "scrapling_default_mode": settings_payload["scrapling_default_mode"],
                    "scrapling_use_for_monitor": settings_payload["scrapling_use_for_monitor"],
                    "scrapling_use_for_catalog": settings_payload["scrapling_use_for_catalog"],
                    "scrapling_timeout_standard": settings_payload["scrapling_timeout_standard"],
                    "scrapling_timeout_dynamic": settings_payload["scrapling_timeout_dynamic"],
                    "scrapling_timeout_stealth": settings_payload["scrapling_timeout_stealth"],
                    "scrapling_domain_cooldown_standard": settings_payload["scrapling_domain_cooldown_standard"],
                    "scrapling_domain_cooldown_dynamic": settings_payload["scrapling_domain_cooldown_dynamic"],
                    "scrapling_domain_cooldown_stealth": settings_payload["scrapling_domain_cooldown_stealth"],
                    "scrapling_max_concurrency_standard": settings_payload["scrapling_max_concurrency_standard"],
                    "scrapling_max_concurrency_dynamic": settings_payload["scrapling_max_concurrency_dynamic"],
                    "scrapling_max_concurrency_stealth": settings_payload["scrapling_max_concurrency_stealth"],
                    "scrapling_session_reuse": settings_payload["scrapling_session_reuse"],
                    "scrapling_adaptive_selector": settings_payload["scrapling_adaptive_selector"],
                    "scrapling_headless": settings_payload["scrapling_headless"],
                    "catalog_discovery_strategy": settings_payload["catalog_discovery_strategy"],
                    "catalog_scrape_strategy": settings_payload["catalog_scrape_strategy"],
                    "catalog_default_fetch_strategy": settings_payload["catalog_default_fetch_strategy"],
                    "catalog_default_extractor": settings_payload["catalog_default_extractor"],
                    "catalog_default_group": settings_payload["catalog_default_group"],
                    "catalog_include_sold_out": settings_payload["catalog_include_sold_out"],
                    "catalog_auto_create_tasks": settings_payload["catalog_auto_create_tasks"],
                    "catalog_dedupe_policy": settings_payload["catalog_dedupe_policy"],
                    "catalog_max_discovered_urls": settings_payload["catalog_max_discovered_urls"],
                    "catalog_max_import_items": settings_payload["catalog_max_import_items"],
                    "catalog_timeout_seconds": settings_payload["catalog_timeout_seconds"],
                    "telegram_ready": bool(
                        settings_payload["telegram_bot_token"] and settings_payload["telegram_chat_ids"]
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
                SET name = ?, group_name = ?, subgroup_name = ?, monitor_url = ?, target_keyword = ?, fetch_strategy = ?,
                    source_config = ?, restock_template = ?, soldout_template = ?, button_1_text = ?, button_1_url = ?,
                    button_2_text = ?, button_2_url = ?, source_item_id = ?, source_item_key = ?,
                    source_source_url = ?, source_source_name = ?, source_item_url = ?, source_snapshot = ?,
                    source_last_sync_at = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(payload["name"]).strip(),
                    normalize_task_group(payload.get("group_name")),
                    normalize_task_subgroup(payload.get("subgroup_name")),
                    str(payload["monitor_url"]).strip(),
                    str(payload["target_keyword"]).strip(),
                    normalize_fetch_strategy(payload.get("fetch_strategy") or DEFAULT_TASK_FETCH_STRATEGY),
                    normalize_source_config_text(payload.get("source_config", {})),
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
            upsert_task_group(connection, payload.get("group_name"), timestamp)
            upsert_task_group_node(connection, payload.get("group_name"), payload.get("subgroup_name"), timestamp)
            connection.commit()
        log_activity("info", "tasks", f"已更新任务 #{task_id}。")
        return jsonify({"ok": True, "message": "任务已更新。", "task_id": task_id})

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

    @app.route("/api/tasks/bulk-delete", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def bulk_delete_tasks():
        payload = read_json()
        raw_ids = payload.get("task_ids")
        if not isinstance(raw_ids, list):
            return jsonify({"ok": False, "message": "请选择要删除的任务。"}), 400
        task_ids: list[int] = []
        for raw_id in raw_ids:
            try:
                task_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if task_id > 0 and task_id not in task_ids:
                task_ids.append(task_id)
        if not task_ids:
            return jsonify({"ok": False, "message": "请选择要删除的任务。"}), 400
        if len(task_ids) > 200:
            return jsonify({"ok": False, "message": "单次最多删除 200 个任务。"}), 400

        placeholders = ",".join("?" for _ in task_ids)
        with open_connection() as connection:
            existing = connection.execute(
                f"SELECT id, name FROM tasks WHERE id IN ({placeholders})",
                task_ids,
            ).fetchall()
            if not existing:
                return jsonify({"ok": False, "message": "选中的任务不存在。"}), 404
            connection.execute(f"DELETE FROM tasks WHERE id IN ({placeholders})", task_ids)
            connection.commit()

        deleted_count = len(existing)
        log_activity("warning", "tasks", f"已批量删除 {deleted_count} 个任务。")
        return jsonify({"ok": True, "message": f"已删除 {deleted_count} 个任务。", "result": {"deleted_count": deleted_count}})

    @app.route("/api/tasks/move", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def move_tasks():
        payload = read_json()
        raw_ids = payload.get("task_ids")
        if not isinstance(raw_ids, list):
            return jsonify({"ok": False, "message": "请选择要移动的任务。"}), 400

        task_ids: list[int] = []
        for raw_id in raw_ids:
            try:
                task_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if task_id > 0 and task_id not in task_ids:
                task_ids.append(task_id)
        if not task_ids:
            return jsonify({"ok": False, "message": "请选择要移动的任务。"}), 400
        if len(task_ids) > 200:
            return jsonify({"ok": False, "message": "单次最多移动 200 个任务。"}), 400

        target_group = normalize_task_group(payload.get("target_group_name") or payload.get("group_name"))
        target_subgroup = normalize_task_subgroup(payload.get("target_subgroup_name") or payload.get("subgroup_name"))
        if not target_group:
            return jsonify({"ok": False, "message": "目标主分组不能为空。"}), 400
        if not target_subgroup:
            return jsonify({"ok": False, "message": "目标子分组不能为空。"}), 400

        timestamp = now_iso()
        placeholders = ",".join("?" for _ in task_ids)
        with open_connection() as connection:
            rows = connection.execute(
                f"SELECT id, name FROM tasks WHERE id IN ({placeholders})",
                task_ids,
            ).fetchall()
            row_by_id = {int(row["id"]): row for row in rows}
            ordered_rows = [row_by_id[task_id] for task_id in task_ids if task_id in row_by_id]
            if not ordered_rows:
                return jsonify({"ok": False, "message": "选中的任务不存在。"}), 404

            upsert_task_group(connection, target_group, timestamp)
            upsert_task_group_node(connection, target_group, target_subgroup, timestamp)
            next_order = next_sort_order(
                connection,
                "tasks",
                "group_name = ? AND subgroup_name = ?",
                (target_group, target_subgroup),
            )
            for index, row in enumerate(ordered_rows):
                connection.execute(
                    """
                    UPDATE tasks
                    SET group_name = ?, subgroup_name = ?, sort_order = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        target_group,
                        target_subgroup,
                        next_order + (index * 100),
                        timestamp,
                        int(row["id"]),
                    ),
                )
            connection.commit()

        moved_count = len(ordered_rows)
        destination = target_group if target_subgroup == DEFAULT_TASK_SUBGROUP else f"{target_group} / {target_subgroup}"
        log_activity("info", "tasks", f"已移动 {moved_count} 个任务到「{destination}」。")
        return jsonify(
            {
                "ok": True,
                "message": f"已移动 {moved_count} 个任务到「{destination}」。",
                "result": {
                    "moved_count": moved_count,
                    "target_group_name": target_group,
                    "target_subgroup_name": target_subgroup,
                    "task_ids": [int(row["id"]) for row in ordered_rows],
                },
            }
        )

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

    @app.route("/api/task-groups/rename", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def rename_task_group():
        payload = read_json()
        old_name = normalize_task_group(payload.get("old_name"))
        new_name = normalize_task_group(payload.get("new_name"))
        if not new_name:
            return jsonify({"ok": False, "message": "新的分组名称不能为空。"}), 400
        if old_name == new_name:
            return jsonify({"ok": True, "message": "分组名称未变化。", "result": {"old_name": old_name, "new_name": new_name}})
        if old_name == DEFAULT_TASK_GROUP:
            return jsonify({"ok": False, "message": "默认分组暂不支持重命名。"}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            task_count = connection.execute("SELECT COUNT(*) FROM tasks WHERE group_name = ?", (old_name,)).fetchone()[0]
            source_count = connection.execute("SELECT COUNT(*) FROM merchant_sources WHERE group_name = ?", (old_name,)).fetchone()[0]
            if not task_count and not source_count:
                return jsonify({"ok": False, "message": "分组不存在。"}), 404
            connection.execute(
                "UPDATE tasks SET group_name = ?, updated_at = ? WHERE group_name = ?",
                (new_name, timestamp, old_name),
            )
            connection.execute(
                "UPDATE merchant_sources SET group_name = ?, updated_at = ? WHERE group_name = ?",
                (new_name, timestamp, old_name),
            )
            connection.execute(
                "UPDATE task_group_nodes SET group_name = ?, updated_at = ? WHERE group_name = ?",
                (new_name, timestamp, old_name),
            )
            old_group_sort = connection.execute(
                "SELECT sort_order FROM task_groups WHERE group_name = ?",
                (old_name,),
            ).fetchone()
            connection.execute("DELETE FROM task_groups WHERE group_name = ?", (old_name,))
            upsert_task_group(
                connection,
                new_name,
                timestamp,
                int(old_group_sort["sort_order"]) if old_group_sort else None,
            )
            connection.commit()

        log_activity("info", "tasks", f'分组「{old_name}」已重命名为「{new_name}」。')
        return jsonify(
            {
                "ok": True,
                "message": "分组已重命名。",
                "result": {
                    "old_name": old_name,
                    "new_name": new_name,
                    "task_count": int(task_count),
                    "source_count": int(source_count),
                },
            }
        )

    @app.route("/api/task-groups/delete", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def delete_task_group():
        payload = read_json()
        group_name = normalize_task_group(payload.get("group_name"))
        if not group_name:
            return jsonify({"ok": False, "message": "分组名称不能为空。"}), 400
        if group_name == DEFAULT_TASK_GROUP:
            return jsonify({"ok": False, "message": "默认分组暂不支持整体删除。"}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            task_count = connection.execute("SELECT COUNT(*) FROM tasks WHERE group_name = ?", (group_name,)).fetchone()[0]
            source_count = connection.execute("SELECT COUNT(*) FROM merchant_sources WHERE group_name = ?", (group_name,)).fetchone()[0]
            if not task_count and not source_count:
                return jsonify({"ok": False, "message": "分组不存在。"}), 404
            connection.execute("DELETE FROM tasks WHERE group_name = ?", (group_name,))
            connection.execute(
                "UPDATE merchant_sources SET group_name = ?, updated_at = ? WHERE group_name = ?",
                (DEFAULT_TASK_GROUP, timestamp, group_name),
            )
            connection.execute("DELETE FROM task_group_nodes WHERE group_name = ?", (group_name,))
            connection.execute("DELETE FROM task_groups WHERE group_name = ?", (group_name,))
            connection.commit()

        log_activity("warning", "tasks", f"分组「{group_name}」已删除，移除了 {int(task_count)} 个任务。")
        return jsonify(
            {
                "ok": True,
                "message": f"分组已删除，移除了 {int(task_count)} 个任务。",
                "result": {"group_name": group_name, "task_count": int(task_count), "source_count": int(source_count)},
            }
        )

    @app.route("/api/task-subgroups/delete", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def delete_task_subgroup():
        payload = read_json()
        group_name = normalize_task_group(payload.get("group_name"))
        subgroup_name = normalize_task_subgroup(payload.get("subgroup_name"))
        if not group_name or not subgroup_name:
            return jsonify({"ok": False, "message": "分组和子分组不能为空。"}), 400
        if subgroup_name == DEFAULT_TASK_SUBGROUP:
            return jsonify({"ok": False, "message": "默认子分组暂不支持整体删除。"}), 400

        with open_connection() as connection:
            exists = connection.execute(
                """
                SELECT 1 FROM tasks
                WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
                UNION
                SELECT 1 FROM task_group_nodes
                WHERE group_name = ? AND (subgroup_name = ? OR subgroup_name LIKE ?)
                LIMIT 1
                """,
                (
                    group_name,
                    subgroup_name,
                    subgroup_descendant_like(subgroup_name),
                    group_name,
                    subgroup_name,
                    subgroup_descendant_like(subgroup_name),
                ),
            ).fetchone()
            if not exists:
                return jsonify({"ok": False, "message": "子分组不存在或没有任务。"}), 404
            task_count = delete_task_subgroup_tree(connection, group_name, subgroup_name)
            connection.commit()

        log_activity("warning", "tasks", f"子分组「{group_name} / {subgroup_name}」已删除，移除了 {int(task_count)} 个任务。")
        return jsonify(
            {
                "ok": True,
                "message": f"子分组已删除，移除了 {int(task_count)} 个任务。",
                "result": {"group_name": group_name, "subgroup_name": subgroup_name, "task_count": int(task_count)},
            }
        )

    @app.route("/api/task-subgroups", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def create_task_subgroup():
        payload = read_json()
        group_name = normalize_task_group(payload.get("group_name"))
        parent_path = normalize_task_subgroup(payload.get("parent_subgroup_name"))
        subgroup_name = child_task_subgroup_path(parent_path, payload.get("name") or payload.get("subgroup_name"))
        if not group_name:
            return jsonify({"ok": False, "message": "主分组不能为空。"}), 400
        if subgroup_name == DEFAULT_TASK_SUBGROUP:
            return jsonify({"ok": False, "message": "子分组名称不能为空。"}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            upsert_task_group_node(connection, group_name, subgroup_name, timestamp)
            connection.commit()
        log_activity("info", "tasks", f"已创建子分组「{group_name} / {subgroup_name}」。")
        return jsonify(
            {
                "ok": True,
                "message": "子分组已创建。",
                "result": {"group_name": group_name, "subgroup_name": subgroup_name},
            }
        )

    @app.route("/api/task-subgroups/rename", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def rename_task_subgroup():
        payload = read_json()
        group_name = normalize_task_group(payload.get("group_name"))
        old_path = normalize_task_subgroup(payload.get("old_subgroup_name") or payload.get("subgroup_name"))
        new_name = normalize_task_subgroup(payload.get("new_name") or payload.get("new_subgroup_name"))
        if not group_name or not old_path or not new_name:
            return jsonify({"ok": False, "message": "分组和新的子分组名称不能为空。"}), 400
        if old_path == DEFAULT_TASK_SUBGROUP:
            return jsonify({"ok": False, "message": "默认子分组暂不支持重命名。"}), 400

        timestamp = now_iso()
        try:
            with open_connection() as connection:
                new_path, task_count, node_count = rename_task_subgroup_tree(connection, group_name, old_path, new_name, timestamp)
                connection.commit()
        except LookupError:
            return jsonify({"ok": False, "message": "子分组不存在。"}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400

        log_activity("info", "tasks", f"子分组「{group_name} / {old_path}」已重命名为「{new_path}」。")
        return jsonify(
            {
                "ok": True,
                "message": "子分组已重命名。",
                "result": {
                    "group_name": group_name,
                    "old_subgroup_name": old_path,
                    "new_subgroup_name": new_path,
                    "task_count": task_count,
                    "node_count": node_count,
                },
            }
        )

    @app.route("/api/task-subgroups/bulk-delete", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def bulk_delete_task_subgroups():
        payload = read_json()
        group_name = normalize_task_group(payload.get("group_name"))
        raw_subgroups = payload.get("subgroup_names")
        if not group_name or not isinstance(raw_subgroups, list):
            return jsonify({"ok": False, "message": "请选择要删除的子分组。"}), 400
        subgroup_names = []
        for item in raw_subgroups:
            subgroup_name = normalize_task_subgroup(item)
            if subgroup_name != DEFAULT_TASK_SUBGROUP and subgroup_name not in subgroup_names:
                subgroup_names.append(subgroup_name)
        if not subgroup_names:
            return jsonify({"ok": False, "message": "请选择要删除的子分组。"}), 400
        if len(subgroup_names) > 100:
            return jsonify({"ok": False, "message": "单次最多删除 100 个子分组。"}), 400

        deleted_tasks = 0
        with open_connection() as connection:
            for subgroup_name in subgroup_names:
                deleted_tasks += delete_task_subgroup_tree(connection, group_name, subgroup_name)
            connection.commit()

        log_activity("warning", "tasks", f"已批量删除 {len(subgroup_names)} 个子分组，移除了 {deleted_tasks} 个任务。")
        return jsonify(
            {
                "ok": True,
                "message": f"已删除 {len(subgroup_names)} 个子分组，移除了 {deleted_tasks} 个任务。",
                "result": {"group_name": group_name, "subgroup_count": len(subgroup_names), "task_count": deleted_tasks},
            }
        )

    @app.route("/api/task-groups/reorder", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def reorder_task_groups():
        payload = read_json()
        group_names = normalize_ordered_values(payload.get("group_names"), normalize_task_group, 200)
        if not group_names:
            return jsonify({"ok": False, "message": "请选择要排序的分组。"}), 400
        if len(group_names) > 200:
            return jsonify({"ok": False, "message": "单次最多排序 200 个分组。"}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            for index, group_name in enumerate(group_names):
                upsert_task_group(connection, group_name, timestamp, (index + 1) * 100)
            connection.commit()

        return jsonify(
            {
                "ok": True,
                "message": "分组排序已保存。",
                "result": {"group_count": len(group_names)},
            }
        )

    @app.route("/api/task-subgroups/reorder", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def reorder_task_subgroups():
        payload = read_json()
        group_name = normalize_task_group(payload.get("group_name"))
        subgroup_names = [
            subgroup_name
            for subgroup_name in normalize_ordered_values(payload.get("subgroup_names"), normalize_task_subgroup, 300)
            if subgroup_name != DEFAULT_TASK_SUBGROUP
        ]
        if not group_name or not subgroup_names:
            return jsonify({"ok": False, "message": "请选择要排序的子分组。"}), 400
        if len(subgroup_names) > 300:
            return jsonify({"ok": False, "message": "单次最多排序 300 个子分组。"}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            upsert_task_group(connection, group_name, timestamp)
            for index, subgroup_name in enumerate(subgroup_names):
                upsert_task_group_node(connection, group_name, subgroup_name, timestamp, (index + 1) * 100)
            connection.commit()

        return jsonify(
            {
                "ok": True,
                "message": "子分组排序已保存。",
                "result": {"group_name": group_name, "subgroup_count": len(subgroup_names)},
            }
        )

    @app.route("/api/tasks/reorder", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def reorder_tasks():
        payload = read_json()
        raw_ids = payload.get("task_ids")
        if not isinstance(raw_ids, list):
            return jsonify({"ok": False, "message": "请选择要排序的任务。"}), 400
        task_ids: list[int] = []
        for raw_id in raw_ids:
            try:
                task_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if task_id > 0 and task_id not in task_ids:
                task_ids.append(task_id)
            if len(task_ids) > 500:
                break
        if not task_ids:
            return jsonify({"ok": False, "message": "请选择要排序的任务。"}), 400
        if len(task_ids) > 500:
            return jsonify({"ok": False, "message": "单次最多排序 500 个任务。"}), 400

        timestamp = now_iso()
        with open_connection() as connection:
            for index, task_id in enumerate(task_ids):
                connection.execute(
                    "UPDATE tasks SET sort_order = ?, updated_at = ? WHERE id = ?",
                    ((index + 1) * 100, timestamp, task_id),
                )
            updated_count = connection.total_changes
            connection.commit()

        return jsonify(
            {
                "ok": True,
                "message": "任务排序已保存。",
                "result": {"task_count": min(updated_count, len(task_ids))},
            }
        )

    @app.route("/api/test-push/<int:task_id>", methods=["POST"])
    @login_required
    @limiter.limit("8 per minute")
    def test_push(task_id: int):
        try:
            result = app.extensions["monitor_engine"].run_test_push(task_id)
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        return jsonify({"ok": True, "message": "测试消息已发送。", "result": result})

    @app.route("/api/tasks/<int:task_id>/check", methods=["POST"])
    @login_required
    @limiter.limit("12 per minute")
    def check_task_stock(task_id: int):
        try:
            result = app.extensions["monitor_engine"].run_stock_check(task_id)
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        return jsonify({"ok": True, "message": "库存检测已完成。", "result": result})

    @app.route("/api/tasks/<int:task_id>/unlock-session", methods=["POST"])
    @login_required
    @limiter.limit("4 per minute")
    def unlock_task_domain_session(task_id: int):
        payload = request.get_json(silent=True) or {}
        timeout_seconds = bounded_setting_int(
            payload.get("timeout_seconds"),
            DOMAIN_SESSION_UNLOCK_TIMEOUT_SECONDS,
            15,
            300,
        )
        try:
            result = app.extensions["monitor_engine"].unlock_task_domain_session(task_id, timeout_seconds)
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        ok = result.get("status") == DOMAIN_SESSION_STATUS_READY
        status_code = 200 if ok else 400
        return jsonify(
            {
                "ok": ok,
                "message": "域名会话已初始化。" if ok else result.get("detail") or "域名会话初始化失败。",
                "result": result,
            }
        ), status_code

    @app.route("/api/tasks/<int:task_id>/domain-session/import", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def import_task_domain_session(task_id: int):
        payload = read_json()
        try:
            result = app.extensions["monitor_engine"].import_task_domain_session(task_id, payload)
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        return jsonify({"ok": True, "message": "浏览器会话已导入。", "result": result})

    @app.route("/api/template-test-push", methods=["POST"])
    @login_required
    @limiter.limit("8 per minute")
    def template_test_push():
        payload = read_json()
        try:
            result = app.extensions["monitor_engine"].run_template_test_push(payload)
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        return jsonify({"ok": True, "message": "模板测试消息已发送。", "result": result})

    @app.route("/api/tasks/<int:task_id>/manual-stock", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def manual_stock_update(task_id: int):
        payload = read_json()
        try:
            stock, detail, checked_at = parse_external_stock_payload(payload)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400

        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return jsonify({"ok": False, "message": "任务不存在。"}), 404
        if task_fetch_strategy(task) != FETCH_STRATEGY_MANUAL:
            return jsonify({"ok": False, "message": "只有手动录入任务可以使用该接口。"}), 400

        result = ScrapeResult(
            stock=stock,
            fragment="",
            detail=detail or "手动录入库存状态。",
            used_test_browser=False,
        )
        try:
            processed = app.extensions["monitor_engine"].apply_task_result(
                task,
                app.extensions["monitor_engine"].get_runtime_settings(),
                result,
                checked_at,
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        log_activity("info", f"task:{task_id}", f"{task['name']} 已手动录入库存：{stock}。")
        return jsonify(
            {
                "ok": True,
                "message": "手动库存状态已写入。",
                "result": {
                    "task_id": task_id,
                    "stock": stock,
                    "processed": processed,
                    "checked_at": checked_at.isoformat(timespec="seconds"),
                },
            }
        )

    @app.route("/api/tasks/<int:task_id>/webhook-token", methods=["POST"])
    @login_required
    @limiter.limit("8 per minute")
    def reset_webhook_token(task_id: int):
        read_json()
        timestamp = now_iso()
        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                return jsonify({"ok": False, "message": "任务不存在。"}), 404
            if task_fetch_strategy(task) != FETCH_STRATEGY_WEBHOOK:
                return jsonify({"ok": False, "message": "只有 Webhook 任务可以生成 ingest token。"}), 400
            token, hint = reset_task_ingest_token(connection, task_id, timestamp)
            connection.commit()
        log_activity("info", f"task:{task_id}", f"{task['name']} Webhook ingest token 已重置。")
        return jsonify(
            {
                "ok": True,
                "message": "Webhook token 已重置，请只在外部推送端保存一次性明文。",
                "result": {
                    "task_id": task_id,
                    "ingest_token": token,
                    "ingest_token_hint": hint,
                    "webhook_endpoint": webhook_endpoint_for_task(task_id),
                },
            }
        )

    @app.route("/api/webhooks/restock/<int:task_id>", methods=["POST"])
    @limiter.limit("120 per minute")
    def webhook_ingest(task_id: int):
        payload = read_json()
        supplied_token = extract_ingest_token_from_request(payload)
        with open_connection() as connection:
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task or task_fetch_strategy(task) != FETCH_STRATEGY_WEBHOOK:
            return jsonify({"ok": False, "message": "Webhook 任务不存在。"}), 404
        if not verify_ingest_token(task, supplied_token):
            log_activity("warning", f"task:{task_id}", "Webhook ingest token 校验失败。")
            return jsonify({"ok": False, "message": "Webhook token 无效。"}), 401

        try:
            stock, detail, checked_at = parse_external_stock_payload(payload)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400

        result = ScrapeResult(
            stock=stock,
            fragment="",
            detail=detail or "Webhook 外部库存写入。",
            used_test_browser=False,
        )
        try:
            processed = app.extensions["monitor_engine"].apply_task_result(
                task,
                app.extensions["monitor_engine"].get_runtime_settings(),
                result,
                checked_at,
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        log_activity("info", f"task:{task_id}", f"{task['name']} 已接收 Webhook 库存：{stock}。")
        return jsonify(
            {
                "ok": True,
                "message": "Webhook 库存状态已写入。",
                "result": {
                    "task_id": task_id,
                    "stock": stock,
                    "processed": processed,
                    "checked_at": checked_at.isoformat(timespec="seconds"),
                },
            }
        )

    @app.route("/api/merchant/discover", methods=["POST"])
    @login_required
    @limiter.limit("6 per minute")
    def discover_merchant_source_urls():
        payload = read_json()
        source_url = str(payload.get("source_url", "")).strip()
        source_name = str(payload.get("source_name", "")).strip()
        if not source_url:
            return jsonify({"ok": False, "message": "商家页面链接不能为空。"}), 400
        if not validate_http_url(source_url):
            return jsonify({"ok": False, "message": "商家页面链接必须是有效的 http(s) 地址。"}), 400

        try:
            result = app.extensions["monitor_engine"].discover_merchant_catalog_urls(
                source_url,
                source_name,
                str(payload.get("group_name", "")).strip(),
                app.extensions["monitor_engine"].get_runtime_settings(),
                catalog_options=payload,
            )
        except Exception as exc:
            error_kind = catalog_browser_error_kind(exc)
            message = catalog_browser_error_message(exc, app.extensions["monitor_engine"].get_runtime_settings()["catalog_debug_port"])
            log_activity("warning", "catalog", f"发现商家 URL 失败（{error_kind}）：{message}")
            return jsonify({"ok": False, "message": message, "error_kind": error_kind}), 400

        log_activity("info", "catalog", f"已发现商家来源 {result.source_name} 的 {len(result.candidate_urls)} 个候选 URL。")
        return jsonify({"ok": True, "message": "候选 URL 已发现。", "result": merchant_catalog_preview_payload(result)})

    @app.route("/api/merchant/preview", methods=["POST"])
    @login_required
    @limiter.limit("6 per minute")
    def preview_merchant_source_items():
        payload = read_json()
        source_url = str(payload.get("source_url", "")).strip()
        source_name = str(payload.get("source_name", "")).strip()
        candidate_urls = payload.get("candidate_urls", [])
        if candidate_urls is not None and not isinstance(candidate_urls, list):
            return jsonify({"ok": False, "message": "candidate_urls 必须是数组。"}), 400
        if not source_url:
            return jsonify({"ok": False, "message": "商家页面链接不能为空。"}), 400
        if not validate_http_url(source_url):
            return jsonify({"ok": False, "message": "商家页面链接必须是有效的 http(s) 地址。"}), 400

        try:
            result = app.extensions["monitor_engine"].preview_merchant_source(
                source_url,
                source_name,
                str(payload.get("group_name", "")).strip(),
                app.extensions["monitor_engine"].get_runtime_settings(),
                catalog_options=payload,
                candidate_urls=candidate_urls,
            )
        except Exception as exc:
            error_kind = catalog_browser_error_kind(exc)
            message = catalog_browser_error_message(exc, app.extensions["monitor_engine"].get_runtime_settings()["catalog_debug_port"])
            log_activity("warning", "catalog", f"预览商家商品失败（{error_kind}）：{message}")
            return jsonify({"ok": False, "message": message, "error_kind": error_kind}), 400

        log_activity(
            "info",
            "catalog",
            f"已预览商家来源 {result.source_name}，可入库 {len(result.items)} 个商品，过滤 {len(result.rejected_items)} 个候选。",
        )
        return jsonify({"ok": True, "message": "商品预览已生成。", "result": merchant_catalog_preview_payload(result)})

    @app.route("/api/merchant/commit", methods=["POST"])
    @login_required
    @limiter.limit("6 per minute")
    def commit_merchant_preview_items():
        payload = read_json()
        source_url = str(payload.get("source_url", "")).strip()
        source_name = str(payload.get("source_name", "")).strip()
        group_name = str(payload.get("group_name", "")).strip()
        auto_promote = bool(payload.get("auto_promote", False))
        raw_items = payload.get("items", [])
        if not isinstance(raw_items, list):
            return jsonify({"ok": False, "message": "items 必须是数组。"}), 400
        if not raw_items:
            return jsonify({"ok": False, "message": "请选择要写入的预览商品。"}), 400
        if not source_url:
            return jsonify({"ok": False, "message": "商家页面链接不能为空。"}), 400
        if not validate_http_url(source_url):
            return jsonify({"ok": False, "message": "商家页面链接必须是有效的 http(s) 地址。"}), 400

        try:
            result = app.extensions["monitor_engine"].persist_merchant_catalog_items(
                source_url,
                source_name,
                group_name,
                raw_items,
                auto_promote=auto_promote,
                archive_missing=False,
            )
        except Exception as exc:
            message = str(exc)[:300] or "预览商品写入失败。"
            log_activity("warning", "catalog", f"写入预览商品失败：{message}")
            return jsonify({"ok": False, "message": message, "error_kind": "catalog_commit_failed"}), 400

        log_activity(
            "info",
            "catalog",
            f"已写入商家来源 {result.source_name}，保存 {result.upserted_count} 个商品，自动生成 {result.promoted_count} 个任务。",
        )
        return jsonify(
            {
                "ok": True,
                "message": "预览商品已写入。",
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
                str(payload.get("group_name", "")).strip(),
                app.extensions["monitor_engine"].get_runtime_settings(),
                auto_promote=auto_promote,
                catalog_options=payload,
            )
        except Exception as exc:
            error_kind = catalog_browser_error_kind(exc)
            message = catalog_browser_error_message(exc, app.extensions["monitor_engine"].get_runtime_settings()["catalog_debug_port"])
            log_activity("warning", "catalog", f"导入商家来源失败（{error_kind}）：{message}")
            return jsonify({"ok": False, "message": message, "error_kind": error_kind}), 400

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
                source["group_name"] if "group_name" in source.keys() else DEFAULT_TASK_GROUP,
                app.extensions["monitor_engine"].get_runtime_settings(),
                auto_promote=auto_promote,
                catalog_options=payload,
            )
        except Exception as exc:
            error_kind = catalog_browser_error_kind(exc)
            message = catalog_browser_error_message(exc, app.extensions["monitor_engine"].get_runtime_settings()["catalog_debug_port"])
            with open_connection() as connection:
                connection.execute(
                    "UPDATE merchant_sources SET last_error = ?, updated_at = ? WHERE id = ?",
                    (message[:1000], now_iso(), source_id),
                )
                connection.commit()
            log_activity("warning", "catalog", f"同步商家来源 #{source_id} 失败（{error_kind}）：{message}")
            return jsonify({"ok": False, "message": message, "error_kind": error_kind}), 400

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
                SELECT mi.*, ms.source_url, ms.source_name, ms.group_name
                FROM merchant_items mi
                JOIN merchant_sources ms ON ms.id = mi.source_id
                WHERE mi.id = ?
                """,
                (item_id,),
            ).fetchone()
            if not item:
                return jsonify({"ok": False, "message": "商家商品不存在。"}), 404
            result = promote_merchant_item_row(connection, item)

        log_activity("info", "catalog", f"已将商家商品 #{item_id} 生成/关联为任务 #{result['task_id']}。")
        return jsonify(
            {
                "ok": True,
                "message": "商家商品已生成任务。",
                "result": result,
            }
        )

    @app.route("/api/merchant/items/bulk-promote", methods=["POST"])
    @login_required
    @limiter.limit(GENERAL_MUTATION_LIMIT)
    def bulk_promote_merchant_items():
        payload = read_json()
        raw_item_ids = payload.get("item_ids", [])
        if not isinstance(raw_item_ids, list):
            return jsonify({"ok": False, "message": "item_ids 必须是数组。"}), 400
        item_ids: list[int] = []
        for raw_id in raw_item_ids[:250]:
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if item_id > 0 and item_id not in item_ids:
                item_ids.append(item_id)
        if not item_ids:
            return jsonify({"ok": False, "message": "请选择要创建任务的商品。"}), 400

        placeholders = ",".join("?" for _ in item_ids)
        with open_connection() as connection:
            rows = connection.execute(
                f"""
                SELECT mi.*, ms.source_url, ms.source_name, ms.group_name
                FROM merchant_items mi
                JOIN merchant_sources ms ON ms.id = mi.source_id
                WHERE mi.id IN ({placeholders})
                """,
                tuple(item_ids),
            ).fetchall()
            rows_by_id = {int(row["id"]): row for row in rows}
            results: list[dict[str, Any]] = []
            for item_id in item_ids:
                item = rows_by_id.get(item_id)
                if item is None:
                    continue
                results.append(promote_merchant_item_row(connection, item))

        if not results:
            return jsonify({"ok": False, "message": "没有找到可创建任务的商品。"}), 404
        created_count = sum(1 for item in results if not item["already_linked"])
        linked_count = len(results) - created_count
        log_activity("info", "catalog", f"批量创建商家商品任务：新增 {created_count} 个，同步 {linked_count} 个。")
        return jsonify(
            {
                "ok": True,
                "message": f"批量创建完成：新增 {created_count} 个任务，同步 {linked_count} 个已关联任务。",
                "result": {
                    "created_count": created_count,
                    "linked_count": linked_count,
                    "items": results,
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

        chat_ids_value = payload.get("telegram_chat_ids", payload.get("telegram_chat_id", ""))
        chat_ids = normalize_telegram_chat_ids(chat_ids_value)
        updates["telegram_chat_ids"] = serialize_telegram_chat_ids(chat_ids)
        updates["telegram_chat_id"] = chat_ids[0] if chat_ids else ""

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
            ("firecrawl_timeout_seconds", 10, 180),
            ("firecrawl_max_age_ms", 0, 604800000),
            ("firecrawl_catalog_limit", 1, 250),
            ("scrapling_timeout_standard", 5, 180),
            ("scrapling_timeout_dynamic", 10, 240),
            ("scrapling_timeout_stealth", 15, 300),
            ("scrapling_domain_cooldown_standard", 0, 3600),
            ("scrapling_domain_cooldown_dynamic", 0, 7200),
            ("scrapling_domain_cooldown_stealth", 0, 14400),
            ("scrapling_max_concurrency_standard", 1, 10),
            ("scrapling_max_concurrency_dynamic", 1, 5),
            ("scrapling_max_concurrency_stealth", 1, 3),
            ("enhanced_collector_timeout_seconds", 5, 180),
            ("enhanced_collector_max_retries", 0, 5),
        ):
            if key in payload:
                try:
                    value = int(payload[key])
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "message": "配置项必须是整数。"}), 400
                if value < minimum or value > maximum:
                    return jsonify({"ok": False, "message": f"{key} 超出允许范围。"}), 400
                updates[key] = str(value)

        for key in (
            "firecrawl_enabled",
            "firecrawl_store_in_cache",
            "firecrawl_allow_auto_proxy",
            "firecrawl_allow_enhanced_proxy",
            "firecrawl_zero_data_retention",
            "firecrawl_use_for_monitor",
            "firecrawl_use_for_catalog",
            "scrapling_enabled",
            "scrapling_use_for_monitor",
            "scrapling_use_for_catalog",
            "scrapling_session_reuse",
            "scrapling_adaptive_selector",
            "scrapling_headless",
            "enhanced_collector_enabled",
            "enhanced_collector_use_for_monitor",
            "enhanced_collector_use_for_catalog",
        ):
            if key in payload:
                updates[key] = settings_bool_text(parse_setting_bool(payload.get(key)))

        if "scrapling_default_mode" in payload:
            mode = normalize_scrapling_mode(payload.get("scrapling_default_mode"))
            updates["scrapling_default_mode"] = mode

        if "firecrawl_api_url" in payload:
            api_url = str(payload.get("firecrawl_api_url", "")).strip().rstrip("/")
            if not api_url or not validate_http_url(api_url):
                return jsonify({"ok": False, "message": "Firecrawl API URL 必须是有效的 http(s) 地址。"}), 400
            updates["firecrawl_api_url"] = api_url

        if "firecrawl_api_key" in payload:
            updates["firecrawl_api_key"] = str(payload.get("firecrawl_api_key", "")).strip()

        if "enhanced_collector_api_url" in payload:
            api_url = str(payload.get("enhanced_collector_api_url") or "").strip().rstrip("/")
            if api_url and not validate_http_url(api_url):
                return jsonify({"ok": False, "message": "增强采集服务地址必须是有效的 http(s) 地址。"}), 400
            updates["enhanced_collector_api_url"] = api_url

        if "firecrawl_proxy_mode" in payload:
            proxy_mode = str(payload.get("firecrawl_proxy_mode") or "").strip().lower()
            if proxy_mode not in FIRECRAWL_PROXY_MODES:
                return jsonify({"ok": False, "message": "Firecrawl proxy 模式必须是 basic / enhanced / auto。"}), 400
            allow_auto = parse_setting_bool(
                updates.get("firecrawl_allow_auto_proxy"),
                bool(current_settings["firecrawl_allow_auto_proxy"]),
            )
            allow_enhanced = parse_setting_bool(
                updates.get("firecrawl_allow_enhanced_proxy"),
                bool(current_settings["firecrawl_allow_enhanced_proxy"]),
            )
            if proxy_mode == "auto" and not allow_auto:
                return jsonify({"ok": False, "message": "使用 Firecrawl auto proxy 前必须显式开启允许 auto proxy。"}), 400
            if proxy_mode == "enhanced" and not allow_enhanced:
                return jsonify({"ok": False, "message": "使用 Firecrawl enhanced proxy 前必须显式开启允许 enhanced proxy。"}), 400
            updates["firecrawl_proxy_mode"] = proxy_mode

        if not updates:
            return jsonify({"ok": False, "message": "没有可更新的设置。"}), 400

        with open_connection() as connection:
            save_settings(connection, updates)

        app.extensions["monitor_engine"].configure_browsers(app.extensions["monitor_engine"].get_runtime_settings())
        log_activity("info", "settings", "Telegram / 引擎配置已更新。")
        return jsonify({"ok": True, "message": "设置已保存。"})

    @app.route("/api/settings/firecrawl-test", methods=["POST"])
    @login_required
    @limiter.limit("10 per minute")
    def test_firecrawl_settings():
        payload = read_json()
        current_settings = dict(app.extensions["monitor_engine"].get_runtime_settings())
        settings_payload = dict(current_settings)

        api_url = str(payload.get("firecrawl_api_url") or current_settings.get("firecrawl_api_url") or DEFAULT_FIRECRAWL_API_URL).strip().rstrip("/")
        if not api_url or not validate_http_url(api_url):
            return jsonify({"ok": False, "message": "Firecrawl API URL 必须是有效的 http(s) 地址。"}), 400
        settings_payload["firecrawl_api_url"] = api_url

        if "firecrawl_api_key" in payload and str(payload.get("firecrawl_api_key") or "").strip():
            settings_payload["firecrawl_api_key"] = str(payload.get("firecrawl_api_key") or "").strip()

        for key, default_value, minimum, maximum in (
            ("firecrawl_timeout_seconds", DEFAULT_FIRECRAWL_TIMEOUT_SECONDS, 10, 180),
            ("firecrawl_max_age_ms", 0, 0, 604800000),
        ):
            if key in payload:
                try:
                    value = int(payload[key])
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "message": "Firecrawl 诊断配置必须是整数。"}), 400
                if value < minimum or value > maximum:
                    return jsonify({"ok": False, "message": f"{key} 超出允许范围。"}), 400
                settings_payload[key] = value
            else:
                settings_payload[key] = int(settings_payload.get(key) or default_value)

        for key in (
            "firecrawl_enabled",
            "firecrawl_store_in_cache",
            "firecrawl_zero_data_retention",
            "firecrawl_allow_auto_proxy",
            "firecrawl_allow_enhanced_proxy",
        ):
            if key in payload:
                settings_payload[key] = parse_setting_bool(payload.get(key))

        proxy_mode = str(payload.get("firecrawl_proxy_mode") or settings_payload.get("firecrawl_proxy_mode") or "basic").strip().lower()
        if proxy_mode not in FIRECRAWL_PROXY_MODES:
            return jsonify({"ok": False, "message": "Firecrawl proxy 模式必须是 basic / enhanced / auto。"}), 400
        if proxy_mode == "auto" and not parse_setting_bool(settings_payload.get("firecrawl_allow_auto_proxy")):
            return jsonify({"ok": False, "message": "使用 Firecrawl auto proxy 前必须显式开启允许 auto proxy。"}), 400
        if proxy_mode == "enhanced" and not parse_setting_bool(settings_payload.get("firecrawl_allow_enhanced_proxy")):
            return jsonify({"ok": False, "message": "使用 Firecrawl enhanced proxy 前必须显式开启允许 enhanced proxy。"}), 400
        settings_payload["firecrawl_proxy_mode"] = proxy_mode

        result = FirecrawlClient(settings_payload).scrape("https://example.com/")
        if result.error_kind:
            detail = sanitize_firecrawl_detail(result.detail, str(settings_payload.get("firecrawl_api_key") or ""))
            return jsonify(
                {
                    "ok": True,
                    "message": f"Firecrawl 连接测试失败：{detail}",
                    "result": {
                        "status": "failed",
                        "error_kind": result.error_kind,
                        "detail": detail,
                        "advice": firecrawl_diagnostic_advice(result.error_kind),
                        "status_code": result.status_code,
                    },
                }
            ), 200

        return jsonify(
            {
                "ok": True,
                "message": "Firecrawl 连接测试成功。",
                "result": {
                    "status": "ok",
                    "status_code": result.status_code,
                    "backend": "firecrawl",
                    "detail": "Firecrawl API 可用，返回内容结构正常。",
                    "final_url": result.final_url,
                },
            }
        )

    @app.route("/api/settings/scrapling-test", methods=["POST"])
    @login_required
    @limiter.limit("20 per minute")
    def test_scrapling_settings():
        result = scrapling_runtime_status()
        return jsonify(
            {
                "ok": True,
                "message": "Scrapling 检测完成。",
                "result": result,
            }
        )

    @app.route("/api/settings/enhanced-collector-test", methods=["POST"])
    @login_required
    @limiter.limit("20 per minute")
    def test_enhanced_collector_settings():
        payload = read_json()
        current_settings = dict(app.extensions["monitor_engine"].get_runtime_settings())
        settings_payload = dict(current_settings)

        api_url = str(
            payload.get("enhanced_collector_api_url")
            or current_settings.get("enhanced_collector_api_url")
            or ""
        ).strip().rstrip("/")
        if api_url and not validate_http_url(api_url):
            return jsonify({"ok": False, "message": "增强采集服务地址必须是有效的 http(s) 地址。"}), 400
        settings_payload["enhanced_collector_api_url"] = api_url

        for key in (
            "enhanced_collector_enabled",
            "enhanced_collector_use_for_monitor",
            "enhanced_collector_use_for_catalog",
        ):
            if key in payload:
                settings_payload[key] = parse_setting_bool(payload.get(key))

        for key, default_value, minimum, maximum in (
            ("enhanced_collector_timeout_seconds", DEFAULT_ENHANCED_COLLECTOR_TIMEOUT_SECONDS, 5, 180),
            ("enhanced_collector_max_retries", DEFAULT_ENHANCED_COLLECTOR_MAX_RETRIES, 0, 5),
        ):
            if key in payload:
                try:
                    value = int(payload[key])
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "message": "增强采集诊断配置必须是整数。"}), 400
                if value < minimum or value > maximum:
                    return jsonify({"ok": False, "message": f"{key} 超出允许范围。"}), 400
                settings_payload[key] = value
            else:
                settings_payload[key] = int(settings_payload.get(key) or default_value)

        result = EnhancedCollectorManager(settings_payload).health_check(probe_candidates=True)
        return jsonify(
            {
                "ok": True,
                "message": "增强采集服务检测完成。",
                "result": result,
            }
        )

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
                    "message": system.get("upgrade_hint") or "请复制下方升级命令后在服务器上执行。",
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
            message = upgrade_start_error_message(completed.stderr or completed.stdout)
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
