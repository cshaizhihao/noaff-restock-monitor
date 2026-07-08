import io
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

import app as app_module


BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0 Safari/537.36"
BASE_URL = "http://localhost"


class PortalAppTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.data_dir = self.base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.originals = {
            "DATA_DIR": app_module.DATA_DIR,
            "DB_PATH": app_module.DB_PATH,
            "BOOTSTRAP_CREDENTIALS_PATH": app_module.BOOTSTRAP_CREDENTIALS_PATH,
            "SECRET_KEY_PATH": app_module.SECRET_KEY_PATH,
            "SECRET_KEY": app_module.SECRET_KEY,
            "PORTAL_PATH": app_module.PORTAL_PATH,
            "LOGIN_RATE_LIMIT": app_module.LOGIN_RATE_LIMIT,
            "GENERAL_MUTATION_LIMIT": app_module.GENERAL_MUTATION_LIMIT,
            "LIMITER_STORAGE_URI": app_module.LIMITER_STORAGE_URI,
            "ENABLE_PROXY_FIX": app_module.ENABLE_PROXY_FIX,
            "DEFAULT_APP_PORT": app_module.DEFAULT_APP_PORT,
            "DEPLOY_MODE": app_module.DEPLOY_MODE,
            "INSTALL_APP_DIR": app_module.INSTALL_APP_DIR,
            "REPO_REF": app_module.REPO_REF,
            "APP_VERSION_OVERRIDE": app_module.APP_VERSION_OVERRIDE,
            "APP_BRANCH_OVERRIDE": app_module.APP_BRANCH_OVERRIDE,
            "UPGRADE_SERVICE_NAME": app_module.UPGRADE_SERVICE_NAME,
            "PANEL_UPGRADE_ENABLED": app_module.PANEL_UPGRADE_ENABLED,
        }

        app_module.DATA_DIR = self.data_dir
        app_module.DB_PATH = self.data_dir / "monitor.db"
        app_module.BOOTSTRAP_CREDENTIALS_PATH = self.data_dir / "bootstrap_admin.txt"
        app_module.SECRET_KEY_PATH = self.data_dir / ".secret_key"
        app_module.SECRET_KEY = "test-secret-key"
        app_module.PORTAL_PATH = ""
        app_module.LOGIN_RATE_LIMIT = "5 per minute"
        app_module.GENERAL_MUTATION_LIMIT = "100 per minute"
        app_module.LIMITER_STORAGE_URI = "memory://"
        app_module.ENABLE_PROXY_FIX = False
        app_module.DEFAULT_APP_PORT = 7777
        app_module.DEPLOY_MODE = "native"
        app_module.INSTALL_APP_DIR = "/opt/noaff-monitor"
        app_module.REPO_REF = "master"
        app_module.APP_VERSION_OVERRIDE = ""
        app_module.APP_BRANCH_OVERRIDE = ""
        app_module.PANEL_UPGRADE_ENABLED = False

        app_module.initialize_database()
        self.app = app_module.make_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.app.extensions["monitor_engine"].stop()
        for key, value in self.originals.items():
            setattr(app_module, key, value)
        self.temp_dir.cleanup()

    def browser_headers(self) -> dict[str, str]:
        return {"User-Agent": BROWSER_UA, "Accept": "application/json"}

    def read_bootstrap_credentials(self) -> dict[str, str]:
        text = app_module.BOOTSTRAP_CREDENTIALS_PATH.read_text(encoding="utf-8")
        return dict(line.split("=", 1) for line in text.strip().splitlines())

    def test_bootstrap_credentials_file_is_minimal(self) -> None:
        text = app_module.BOOTSTRAP_CREDENTIALS_PATH.read_text(encoding="utf-8")
        self.assertIn("username=", text)
        self.assertIn("password=", text)
        self.assertNotIn("panel_path=", text)

    def test_initialize_database_migrates_task_fetch_strategy_columns(self) -> None:
        original_db_path = app_module.DB_PATH
        legacy_db_path = self.data_dir / "legacy-monitor.db"
        try:
            app_module.DB_PATH = legacy_db_path
            connection = sqlite3.connect(legacy_db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE tasks (
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
                        message_ids TEXT DEFAULT '',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        last_stock INTEGER,
                        last_state TEXT NOT NULL DEFAULT 'unknown',
                        message_id INTEGER,
                        last_checked_at TEXT,
                        last_error TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            app_module.initialize_database()
            connection = sqlite3.connect(legacy_db_path)
            try:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()}
                node_columns = {row[1] for row in connection.execute("PRAGMA table_info(task_group_nodes)").fetchall()}
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
                row = connection.execute(
                    """
                    SELECT dflt_value
                    FROM pragma_table_info('tasks')
                    WHERE name = 'fetch_strategy'
                    """
                ).fetchone()
            finally:
                connection.close()

            self.assertIn("fetch_strategy", columns)
            self.assertIn("subgroup_name", columns)
            self.assertIn("sort_order", columns)
            self.assertIn("sort_order", node_columns)
            self.assertIn("task_groups", tables)
            self.assertIn("task_group_nodes", tables)
            self.assertIn("source_config", columns)
            self.assertIn("blocked_count", columns)
            self.assertIn("last_blocked_at", columns)
            self.assertIn("cooldown_until", columns)
            self.assertIn("ingest_token_hash", columns)
            self.assertIn("ingest_token_hint", columns)
            self.assertEqual(row[0], "'scrapling_adaptive'")
        finally:
            app_module.DB_PATH = original_db_path

    def test_initialize_database_migrates_legacy_fetch_strategies_to_scrapling(self) -> None:
        original_db_path = app_module.DB_PATH
        legacy_db_path = self.data_dir / "legacy-strategy-monitor.db"
        timestamp = app_module.now_iso()
        try:
            app_module.DB_PATH = legacy_db_path
            connection = sqlite3.connect(legacy_db_path)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute(
                    """
                    CREATE TABLE settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        monitor_url TEXT NOT NULL,
                        target_keyword TEXT NOT NULL,
                        fetch_strategy TEXT NOT NULL DEFAULT 'browser',
                        source_config TEXT NOT NULL DEFAULT '{}',
                        restock_template TEXT NOT NULL,
                        soldout_template TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                rows = [
                    ("browser task", "browser", {}),
                    ("static task", "static_http", {}),
                    ("generic task", "generic_pricing_table", {}),
                    ("whmcs task", "whmcs", {}),
                    ("firecrawl task", "firecrawl", {}),
                    ("manual task", "manual", {}),
                    ("webhook task", "webhook", {}),
                ]
                for name, strategy, source_config in rows:
                    connection.execute(
                        """
                        INSERT INTO tasks (
                            name, monitor_url, target_keyword, fetch_strategy, source_config,
                            restock_template, soldout_template, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            name,
                            "https://example.com/item",
                            name,
                            strategy,
                            json.dumps(source_config),
                            app_module.DEFAULT_RESTOCK_TEMPLATE,
                            app_module.DEFAULT_SOLDOUT_TEMPLATE,
                            timestamp,
                            timestamp,
                        ),
                    )
                connection.commit()
            finally:
                connection.close()

            app_module.initialize_database()
            with app_module.open_connection() as connection:
                tasks = {
                    row["name"]: row
                    for row in connection.execute(
                        "SELECT name, fetch_strategy, source_config FROM tasks"
                    ).fetchall()
                }
                marker = connection.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (app_module.SCRAPLING_FETCH_STRATEGY_MIGRATION_KEY,),
                ).fetchone()

            self.assertIsNotNone(marker)
            self.assertEqual(tasks["browser task"]["fetch_strategy"], "scrapling_dynamic")
            self.assertEqual(tasks["static task"]["fetch_strategy"], "scrapling_standard")
            self.assertEqual(tasks["generic task"]["fetch_strategy"], "scrapling_adaptive")
            self.assertEqual(tasks["whmcs task"]["fetch_strategy"], "scrapling_adaptive")
            self.assertEqual(tasks["firecrawl task"]["fetch_strategy"], "scrapling_stealth")
            self.assertEqual(tasks["manual task"]["fetch_strategy"], "manual")
            self.assertEqual(tasks["webhook task"]["fetch_strategy"], "webhook")
            generic_config = json.loads(tasks["generic task"]["source_config"])
            whmcs_config = json.loads(tasks["whmcs task"]["source_config"])
            self.assertEqual(generic_config["extractor"], "generic_pricing_table")
            self.assertEqual(generic_config["legacy_fetch_strategy"], "generic_pricing_table")
            self.assertEqual(whmcs_config["extractor"], "whmcs")
            self.assertEqual(whmcs_config["legacy_fetch_strategy"], "whmcs")

            with app_module.open_connection() as connection:
                connection.execute(
                    "UPDATE tasks SET fetch_strategy = ? WHERE name = ?",
                    ("browser", "manual task"),
                )
                connection.commit()
            app_module.initialize_database()
            with app_module.open_connection() as connection:
                strategy = connection.execute(
                    "SELECT fetch_strategy FROM tasks WHERE name = ?",
                    ("manual task",),
                ).fetchone()["fetch_strategy"]
            self.assertEqual(strategy, "browser")
        finally:
            app_module.DB_PATH = original_db_path

    def test_protected_source_cooldown_schedule_is_short_and_progressive(self) -> None:
        base = app_module.datetime(2026, 7, 7, 0, 0, tzinfo=app_module.UTC)

        first = app_module.parse_iso_datetime(app_module.protected_source_cooldown_until(1, base))
        second = app_module.parse_iso_datetime(app_module.protected_source_cooldown_until(2, base))
        third = app_module.parse_iso_datetime(app_module.protected_source_cooldown_until(3, base))
        later = app_module.parse_iso_datetime(app_module.protected_source_cooldown_until(8, base))

        self.assertEqual((first - base).total_seconds(), 60)
        self.assertEqual((second - base).total_seconds(), 180)
        self.assertEqual((third - base).total_seconds(), 600)
        self.assertEqual((later - base).total_seconds(), 600)

    def test_asset_route_serves_logo_for_browser_requests(self) -> None:
        response = self.client.get("/assets/noaff-logo.svg", headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn("image/svg+xml", response.headers["Content-Type"])
            self.assertIn("<svg", response.get_data(as_text=True))
        finally:
            response.close()

    def get_portal_csrf(self) -> str:
        response = self.client.get("/", headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        self.assertEqual(response.status_code, 200)
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def ajax_headers(self, csrf_token: str) -> dict[str, str]:
        headers = self.browser_headers()
        headers.update(
            {
                "Origin": BASE_URL,
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": csrf_token,
            }
        )
        return headers

    def login(self) -> tuple[dict[str, str], dict[str, str]]:
        bootstrap = self.read_bootstrap_credentials()
        csrf_token = self.get_portal_csrf()
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/gate",
            headers=self.ajax_headers(csrf_token),
            base_url=BASE_URL,
            json={"username": bootstrap["username"], "password": bootstrap["password"]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        headers = self.ajax_headers(payload["csrf_token"])
        return bootstrap, headers

    def insert_admin(self, username: str, password: str) -> None:
        with app_module.open_connection() as connection:
            connection.execute(
                """
                INSERT INTO admins (username, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    username,
                    app_module.generate_password_hash(password),
                    app_module.now_iso(),
                    app_module.now_iso(),
                ),
            )
            connection.commit()

    def test_root_panel_and_browser_header_gate(self) -> None:
        root_response = self.client.get("/", headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        self.assertEqual(root_response.status_code, 200)

        health_response = self.client.get("/healthz", headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.get_json()["ok"], True)

        blocked_health_response = self.client.get("/healthz", base_url=BASE_URL)
        self.assertEqual(blocked_health_response.status_code, 404)

        blocked_response = self.client.get("/", base_url=BASE_URL)
        self.assertEqual(blocked_response.status_code, 404)

        old_portal_response = self.client.get("/portal_test", headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        self.assertEqual(old_portal_response.status_code, 404)

        allowed_response = self.client.get("/", headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        self.assertEqual(allowed_response.status_code, 200)
        html = allowed_response.get_data(as_text=True)
        self.assertIn('id="dashboard-shell" class="hidden flex h-screen flex-col overflow-hidden md:flex-row"', html)
        self.assertIn('id="mobile-nav-merchant"', html)
        self.assertIn('id="mobile-nav-settings"', html)
        self.assertIn('id="mobile-logout-button"', html)

    def test_login_requires_ajax_and_csrf_headers(self) -> None:
        bootstrap = self.read_bootstrap_credentials()
        csrf_token = self.get_portal_csrf()

        missing_ajax = self.client.post(
            f"{app_module.PORTAL_PATH}/gate",
            headers={
                "User-Agent": BROWSER_UA,
                "Origin": BASE_URL,
                "X-CSRF-Token": csrf_token,
                "Accept": "application/json",
            },
            base_url=BASE_URL,
            json={"username": bootstrap["username"], "password": bootstrap["password"]},
        )
        self.assertEqual(missing_ajax.status_code, 404)

        missing_csrf = self.client.post(
            f"{app_module.PORTAL_PATH}/gate",
            headers={
                "User-Agent": BROWSER_UA,
                "Origin": BASE_URL,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            },
            base_url=BASE_URL,
            json={"username": bootstrap["username"], "password": bootstrap["password"]},
        )
        self.assertEqual(missing_csrf.status_code, 404)

    def test_login_accepts_forwarded_https_origin(self) -> None:
        bootstrap = self.read_bootstrap_credentials()
        root_response = self.client.get(
            "/",
            headers={"User-Agent": BROWSER_UA, "Host": "monitor.example.com"},
            base_url="http://monitor.example.com",
        )
        self.assertEqual(root_response.status_code, 200)
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', root_response.get_data(as_text=True))
        self.assertIsNotNone(match)
        csrf_token = match.group(1)
        headers = self.ajax_headers(csrf_token)
        headers.update(
            {
                "Origin": "https://monitor.example.com",
                "Host": "monitor.example.com",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "monitor.example.com",
                "X-Forwarded-Port": "443",
            }
        )
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/gate",
            headers=headers,
            base_url="http://monitor.example.com",
            json={"username": bootstrap["username"], "password": bootstrap["password"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_login_accepts_https_origin_with_loopback_upstream_host(self) -> None:
        bootstrap = self.read_bootstrap_credentials()
        root_response = self.client.get(
            "/",
            headers={"User-Agent": BROWSER_UA},
            base_url="http://127.0.0.1:7788",
        )
        self.assertEqual(root_response.status_code, 200)
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', root_response.get_data(as_text=True))
        self.assertIsNotNone(match)
        csrf_token = match.group(1)
        headers = self.ajax_headers(csrf_token)
        headers.update(
            {
                "Origin": "https://monitor.example.com",
                "Host": "127.0.0.1:7788",
            }
        )
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/gate",
            headers=headers,
            base_url="http://127.0.0.1:7788",
            json={"username": bootstrap["username"], "password": bootstrap["password"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_login_rejects_external_origin_when_public_host_is_known(self) -> None:
        bootstrap = self.read_bootstrap_credentials()
        root_response = self.client.get(
            "/",
            headers={"User-Agent": BROWSER_UA, "Host": "monitor.example.com"},
            base_url="http://monitor.example.com",
        )
        self.assertEqual(root_response.status_code, 200)
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', root_response.get_data(as_text=True))
        self.assertIsNotNone(match)
        csrf_token = match.group(1)
        headers = self.ajax_headers(csrf_token)
        headers.update(
            {
                "Origin": "https://evil.example.net",
                "Host": "monitor.example.com",
            }
        )
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/gate",
            headers=headers,
            base_url="http://monitor.example.com",
            json={"username": bootstrap["username"], "password": bootstrap["password"]},
        )
        self.assertEqual(response.status_code, 404)

    def test_stale_session_is_rejected_after_admin_removed(self) -> None:
        _, headers = self.login()

        with app_module.open_connection() as connection:
            connection.execute("DELETE FROM admins")
            connection.commit()

        response = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["message"], "未登录或会话已过期。")

    def test_login_rate_limit_blocks_sixth_failed_attempt(self) -> None:
        bootstrap = self.read_bootstrap_credentials()
        csrf_token = self.get_portal_csrf()
        headers = self.ajax_headers(csrf_token)

        for _ in range(5):
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/gate",
                headers=headers,
                base_url=BASE_URL,
                json={"username": bootstrap["username"], "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 401)

        limited = self.client.post(
            f"{app_module.PORTAL_PATH}/gate",
            headers=headers,
            base_url=BASE_URL,
            json={"username": bootstrap["username"], "password": "wrong-password"},
        )
        self.assertEqual(limited.status_code, 429)

    def test_snapshot_and_task_creation_after_login(self) -> None:
        _, headers = self.login()

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        self.assertEqual(snapshot.status_code, 200)
        self.assertTrue(snapshot.get_json()["ok"])

        create = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "HK VM",
                "group_name": "Geelinx JP",
                "subgroup_name": "Tokyo / Premium",
                "monitor_url": "https://example.com/cart.php?gid=1",
                "target_keyword": "HK-CMI",
                "fetch_strategy": "static_http",
                "source_config": {"mode": "public"},
                "restock_template": "<b>{name}</b> {stock}",
                "soldout_template": "<b>{name}</b> sold out",
                "button_1_text": "Open",
                "button_1_url": "https://example.com/order",
                "button_2_text": "",
                "button_2_url": "",
                "enabled": True,
            },
        )
        self.assertEqual(create.status_code, 200)
        self.assertTrue(create.get_json()["ok"])

        refreshed = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        payload = refreshed.get_json()
        self.assertEqual(payload["metrics"]["total"], 1)
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertEqual(payload["tasks"][0]["group_name"], "Geelinx JP")
        self.assertEqual(payload["tasks"][0]["subgroup_name"], "Tokyo / Premium")
        self.assertEqual(payload["tasks"][0]["fetch_strategy"], "static_http")
        self.assertEqual(json.loads(payload["tasks"][0]["source_config"]), {"mode": "public"})
        self.assertEqual(payload["tasks"][0]["blocked_count"], 0)
        self.assertEqual(payload["tasks"][0]["last_blocked_at"], "")
        self.assertEqual(payload["tasks"][0]["cooldown_until"], "")
        self.assertIn("system", payload)
        self.assertIn("version", payload["system"])

        update = self.client.put(
            f"{app_module.PORTAL_PATH}/api/tasks/{create.get_json()['task_id']}",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "HK VM",
                "group_name": "Geelinx JP",
                "subgroup_name": "Osaka / Budget",
                "monitor_url": "https://example.com/cart.php?gid=1",
                "target_keyword": "HK-CMI",
                "fetch_strategy": "whmcs",
                "source_config": {},
                "restock_template": "<b>{name}</b> {stock}",
                "soldout_template": "<b>{name}</b> sold out",
                "button_1_text": "Open",
                "button_1_url": "https://example.com/order",
                "button_2_text": "",
                "button_2_url": "",
                "enabled": True,
            },
        )
        self.assertEqual(update.status_code, 200)

        updated = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        self.assertEqual(updated.get_json()["tasks"][0]["fetch_strategy"], "whmcs")
        self.assertEqual(updated.get_json()["tasks"][0]["subgroup_name"], "Osaka / Budget")

        invalid_strategy = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "Invalid",
                "group_name": "Default",
                "monitor_url": "https://example.com/cart.php?gid=1",
                "target_keyword": "Invalid",
                "fetch_strategy": "unknown",
                "restock_template": "{name}",
                "soldout_template": "{name}",
                "enabled": True,
            },
        )
        self.assertEqual(invalid_strategy.status_code, 400)
        self.assertIn("采集方式", invalid_strategy.get_json()["message"])

    def test_task_creation_without_fetch_strategy_defaults_to_scrapling_adaptive(self) -> None:
        _, headers = self.login()

        create = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "Default Strategy VM",
                "group_name": "Default",
                "monitor_url": "https://example.com/cart.php?gid=8",
                "target_keyword": "Default Strategy VM",
                "restock_template": "<b>{name}</b> {stock}",
                "soldout_template": "<b>{name}</b> sold out",
                "enabled": True,
            },
        )
        self.assertEqual(create.status_code, 200)
        self.assertTrue(create.get_json()["ok"])

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        payload = snapshot.get_json()
        self.assertEqual(payload["tasks"][0]["fetch_strategy"], "scrapling_adaptive")

    def test_merchant_import_discovers_products_and_promotes_tasks(self) -> None:
        _, headers = self.login()
        engine = self.app.extensions["monitor_engine"]

        class FakeCatalogBrowser:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                self.calls.append((url, timeout_seconds))
                return """
                <html>
                  <head><title>Geelinx | London BGP</title></head>
                  <body>
                    <nav class="topbar">
                      <a href="/join">Join Channel</a>
                      <a href="/">Main</a>
                      <a href="/cart">Cart</a>
                      <a href="/account">My</a>
                    </nav>
                    <aside class="sidebar">
                      <a href="/cart?fid=1&gid=9" class="active">GB | London BGP 1#</a>
                    </aside>
                    <main class="catalog">
                      <article class="product-card">
                        <h3 class="product-title">GB.LON.BGP.Darwin</h3>
                        <p>库存 9</p>
                        <a href="cart.php?a=add&pid=21">Order Now</a>
                      </article>
                      <article class="product-card">
                        <h3 class="product-title">GB.LON.BGP.Newton</h3>
                        <p>Only 2 left</p>
                        <a href="/cart.php?a=add&pid=22">Order Now</a>
                      </article>
                    </main>
                  </body>
                </html>
                """

            def rebuild(self, reason: str) -> None:
                raise AssertionError(reason)

        original_browser = engine.catalog_browser
        fake_browser = FakeCatalogBrowser()
        engine.catalog_browser = fake_browser
        try:
            result = engine.import_merchant_source(
                "https://merchant.example.com/products",
                "",
                "London BGP",
                engine.get_runtime_settings(),
                auto_promote=True,
                catalog_options={
                    "catalog_scrape_strategy": "browser",
                    "default_fetch_strategy": "generic_pricing_table",
                },
            )
        finally:
            engine.catalog_browser = original_browser

        self.assertEqual(result.scanned_count, 2)
        self.assertEqual(result.promoted_count, 2)
        self.assertEqual(result.source_name, "Geelinx | London BGP")
        self.assertEqual(sorted(item["title"] for item in result.items), ["GB.LON.BGP.Darwin", "GB.LON.BGP.Newton"])
        self.assertEqual(len(result.items), 2)
        self.assertTrue(all(item["confidence"] >= 45 for item in result.items))
        self.assertTrue(all(item["include_reason"] for item in result.items))
        self.assertEqual(len(fake_browser.calls), 1)

        with app_module.open_connection() as connection:
            source_count = connection.execute("SELECT COUNT(*) FROM merchant_sources").fetchone()[0]
            item_count = connection.execute("SELECT COUNT(*) FROM merchant_items").fetchone()[0]
            task_count = connection.execute("SELECT COUNT(*) FROM tasks WHERE source_item_id IS NOT NULL").fetchone()[0]
            source_group = connection.execute("SELECT group_name FROM merchant_sources LIMIT 1").fetchone()[0]

        self.assertEqual(source_count, 1)
        self.assertEqual(item_count, 2)
        self.assertEqual(task_count, 2)
        self.assertEqual(source_group, "London BGP")

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=headers,
            base_url=BASE_URL,
        )
        payload = snapshot.get_json()
        self.assertEqual(payload["merchant"]["metrics"]["total_sources"], 1)
        self.assertEqual(payload["merchant"]["metrics"]["total_items"], 2)
        self.assertEqual(payload["merchant"]["metrics"]["linked_tasks"], 2)
        self.assertTrue(all(item["confidence"] >= 45 for item in payload["merchant"]["items"]))

    def test_catalog_defaults_are_scrapling_first(self) -> None:
        engine = self.app.extensions["monitor_engine"]
        options = app_module.normalize_catalog_options({}, engine.get_runtime_settings(), "Default", True)

        self.assertEqual(options["catalog_scrape_strategy"], "scrapling_adaptive")
        self.assertEqual(options["default_fetch_strategy"], "scrapling_adaptive")

    def test_scrape_catalog_candidate_uses_scrapling_strategy(self) -> None:
        class FakeScraplingResponse:
            url = "https://merchant.example.com/products"
            status = 200
            html_content = """
            <html>
              <body>
                <article class="product-card">
                  <h3>Tokyo VPS</h3>
                  <p>库存 6</p>
                  <a>Order Now</a>
                </article>
              </body>
            </html>
            """

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, int]] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append((mode, url, timeout_seconds))
                return FakeScraplingResponse()

        class NoBrowser:
            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                raise AssertionError("catalog browser should not be used for scrapling catalog scrape")

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        original_browser = engine.catalog_browser
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            engine.catalog_browser = NoBrowser()
            result = engine.scrape_catalog_candidate(
                "https://merchant.example.com/products",
                {**engine.get_runtime_settings(), **self.scrapling_settings()},
                {"catalog_scrape_strategy": "scrapling_adaptive", "timeout_seconds": 25},
            )
        finally:
            engine.fetcher_selector = original_selector
            engine.catalog_browser = original_browser

        self.assertEqual(result.error_kind, "")
        self.assertIn("Tokyo VPS", result.html)
        self.assertEqual(client.calls, [("standard", "https://merchant.example.com/products", 25)])

    def test_preview_merchant_source_defaults_to_scrapling_discovery(self) -> None:
        class FakeScraplingResponse:
            status = 200

            def __init__(self, url: str) -> None:
                self.url = url
                self.html_content = """
                <html>
                  <head><title>Example IDC Store</title></head>
                  <body>
                    <nav>
                      <a href="/en">English</a>
                      <a href="/privacy">Privacy</a>
                    </nav>
                    <main>
                      <a href="/cart.php?gid=9">Hong Kong VPS</a>
                      <article class="product-card">
                        <h3>HKG Premium VPS</h3>
                        <p>$ 9.90 USD / month</p>
                        <p>2 vCores</p>
                        <p>2GB RAM</p>
                        <a href="/cart.php?a=add&pid=88">Order Now</a>
                      </article>
                    </main>
                  </body>
                </html>
                """

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, int]] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append((mode, url, timeout_seconds))
                return FakeScraplingResponse(url)

        class NoBrowser:
            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                raise AssertionError("catalog browser should not be used for default Scrapling product intake")

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        original_browser = engine.catalog_browser
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            engine.catalog_browser = NoBrowser()
            result = engine.preview_merchant_source(
                "https://merchant.example.com/products",
                "",
                "Example",
                {**engine.get_runtime_settings(), **self.scrapling_settings()},
                catalog_options={
                    "catalog_discovery_strategy": "local",
                    "catalog_scrape_strategy": "scrapling_adaptive",
                    "default_fetch_strategy": "scrapling_adaptive",
                    "target_keyword": "HKG Premium",
                    "max_discovered_urls": 5,
                    "max_import_items": 5,
                    "timeout_seconds": 25,
                },
            )
        finally:
            engine.fetcher_selector = original_selector
            engine.catalog_browser = original_browser

        self.assertGreaterEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0], ("standard", "https://merchant.example.com/products", 25))
        self.assertEqual(result.source_name, "Example IDC Store")
        self.assertTrue(result.candidate_urls)
        self.assertEqual([item["title"] for item in result.items], ["HKG Premium VPS"])
        self.assertEqual(result.items[0]["fetch_strategy"], "scrapling_adaptive")
        self.assertEqual(result.items[0]["backend_used"], "scrapling_adaptive")

    def test_catalog_discovery_scores_products_and_filters_locale_navigation_noise(self) -> None:
        html_text = """
        <html>
          <body>
            <header class="navbar">
              <a href="/en">English</a>
              <a href="/zh">中文</a>
              <a href="/clientarea.php">Client Area</a>
            </header>
            <main class="pricing">
              <h2>选择地区</h2>
              <div class="region-picker">
                <button>Hong Kong</button>
                <button>Los Angeles</button>
              </div>
              <h2>選擇實例類型</h2>
              <article class="product-card">
                <h3>HKG.AS3.T1.WEE</h3>
                <p>$ 36.90 USD / 年繳</p>
                <ul>
                  <li>1 vCores</li>
                  <li>1.0GB RAM</li>
                  <li>20GB SSD</li>
                  <li>1000GB Transfer</li>
                </ul>
                <a href="/cart.php?a=add&pid=101">Order Now</a>
              </article>
            </main>
            <footer>
              <a href="/terms">Terms</a>
              <a href="/privacy">Privacy</a>
            </footer>
          </body>
        </html>
        """

        accepted = app_module.discover_catalog_items(html_text, "https://example.com/cart.php?gid=1")
        self.assertEqual([item["title"] for item in accepted], ["HKG.AS3.T1.WEE"])
        self.assertGreaterEqual(accepted[0]["confidence"], 70)
        self.assertIn("price", accepted[0]["include_reason"])
        self.assertTrue(any(signal["type"] == "specs" for signal in accepted[0]["signals"]))

        all_candidates = app_module.discover_catalog_items(
            html_text,
            "https://example.com/cart.php?gid=1",
            include_rejected=True,
        )
        rejected = {item["title"]: item["reject_reason"] for item in all_candidates if item["reject_reason"]}
        self.assertIn("English", rejected)
        self.assertIn("選擇實例類型", rejected)
        self.assertIn("语言切换或导航文本", rejected["English"])
        self.assertIn("分类/步骤标题", rejected["選擇實例類型"])

    def test_catalog_discovery_does_not_promote_noise_with_global_price(self) -> None:
        html_text = """
        <html>
          <body>
            <div class="hero">
              <strong>Starting from $ 6.90 USD</strong>
              <a href="/en">English</a>
              <a href="/zh">中文</a>
              <a href="/cart.php">Cart</a>
            </div>
            <section class="steps">
              <h2>选择网络类型</h2>
              <button>Premium</button>
              <button>Tier 1</button>
            </section>
            <section class="pricing-products">
              <article class="product-card">
                <h3>HKG.AS3.T1.TINY</h3>
                <p>$ 6.90 USD / 月繳</p>
                <p>1 vCores</p>
                <p>1.0GB RAM</p>
                <p>2000GB @ 4Gbps</p>
              </article>
            </section>
          </body>
        </html>
        """

        accepted = app_module.discover_catalog_items(
            html_text,
            "https://example.com/cart.php?region=hong-kong&network=tier-1&generation=as3",
        )
        self.assertEqual([item["title"] for item in accepted], ["HKG.AS3.T1.TINY"])

        all_candidates = app_module.discover_catalog_items(
            html_text,
            "https://example.com/cart.php?region=hong-kong&network=tier-1&generation=as3",
            include_rejected=True,
        )
        rejected_titles = {item["title"] for item in all_candidates if item["reject_reason"]}
        self.assertIn("English", rejected_titles)
        self.assertIn("中文", rejected_titles)
        self.assertIn("选择网络类型", rejected_titles)

    def test_catalog_discovery_accepts_idc_plan_cards_with_specs_without_per_card_button(self) -> None:
        html_text = """
        <main class="cart-page">
          <section>
            <h2>選擇網絡類型</h2>
            <button>Premium</button>
            <button>Tier 1</button>
          </section>
          <section class="pricing-products">
            <h2>選擇實例類型</h2>
            <article class="product-card selected">
              <h3>HKG.AS3.T1.WEE</h3>
              <p>$ 36.90 USD / 年繳</p>
              <p>1 vCores</p>
              <p>1.0GB RAM</p>
              <p>20GB SSD</p>
              <p>1000GB @ 4Gbps</p>
            </article>
            <article class="product-card">
              <h3>HKG.AS3.T1.TINY</h3>
              <p>$ 6.90 USD / 月繳</p>
              <p>1 vCores</p>
              <p>1.0GB RAM</p>
              <p>2000GB @ 4Gbps</p>
            </article>
          </section>
          <footer><button>繼續</button></footer>
        </main>
        """

        items = app_module.discover_catalog_items(
            html_text,
            "https://example.com/cart.php?region=hong-kong&network=tier-1&generation=as3&product=hkg.as3.t1.wee",
        )
        self.assertEqual(
            [item["title"] for item in items],
            ["HKG.AS3.T1.WEE", "HKG.AS3.T1.TINY"],
        )
        self.assertTrue(all(item["confidence"] >= 60 for item in items))
        self.assertTrue(all(any(signal["type"] == "specs" for signal in item["signals"]) for item in items))

    def test_merchant_import_port_busy_returns_user_readable_error_kind(self) -> None:
        _, headers = self.login()
        engine = self.app.extensions["monitor_engine"]

        class FakeCatalogBrowser:
            def __init__(self) -> None:
                self.rebuild_calls: list[str] = []

            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                raise app_module.CatalogBrowserPortBusyError(
                    "商品入库浏览器端口 9445 已被其他进程占用（PID 4242, python）。"
                    "请在系统设置中修改 CATALOG_DEBUG_PORT / 商品入库浏览器端口后重试。"
                )

            def rebuild(self, reason: str) -> None:
                self.rebuild_calls.append(reason)
                raise AssertionError("端口占用不应触发浏览器重建")

        original_browser = engine.catalog_browser
        fake_browser = FakeCatalogBrowser()
        engine.catalog_browser = fake_browser
        try:
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/api/merchant/import",
                headers=headers,
                base_url=BASE_URL,
                json={"source_url": "https://merchant.example.com/products", "catalog_scrape_strategy": "browser"},
            )
        finally:
            engine.catalog_browser = original_browser

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error_kind"], "catalog_browser_port_busy")
        self.assertIn("CATALOG_DEBUG_PORT", payload["message"])
        self.assertEqual(fake_browser.rebuild_calls, [])

    def test_merchant_preview_pipeline_discovers_scrapes_then_commits_selected_items(self) -> None:
        _, headers = self.login()
        engine = self.app.extensions["monitor_engine"]

        class FakeCatalogBrowser:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                self.calls.append(url)
                if url.endswith("/store/hk-vps"):
                    return """
                    <html><body>
                      <nav><a href="/en">English</a></nav>
                      <h2>选择地区</h2>
                      <section class="product-card">
                        <h3>HK Preview VPS</h3>
                        <p>$9.90 USD / month</p>
                        <p>1 vCPU 1GB RAM 20GB SSD</p>
                        <a href="/cart.php?a=add&pid=99">Order Now</a>
                      </section>
                      <section class="product-card">
                        <h3>Tokyo Preview VPS</h3>
                        <p>$8.90 USD / month</p>
                        <p>1 vCPU 1GB RAM 20GB SSD</p>
                        <a href="/cart.php?a=add&pid=100">Order Now</a>
                      </section>
                    </body></html>
                    """
                return """
                <html>
                  <head><title>Preview Merchant</title></head>
                  <body>
                    <a href="/store/hk-vps">HK VPS</a>
                    <a href="/login">Login</a>
                  </body>
                </html>
                """

            def rebuild(self, reason: str) -> None:
                raise AssertionError(reason)

        original_browser = engine.catalog_browser
        fake_browser = FakeCatalogBrowser()
        engine.catalog_browser = fake_browser
        try:
            discover = self.client.post(
                f"{app_module.PORTAL_PATH}/api/merchant/discover",
                headers=headers,
                base_url=BASE_URL,
                json={
                    "source_url": "https://merchant.example.com/products",
                    "group_name": "Preview IDC",
                    "catalog_discovery_strategy": "local",
                    "catalog_scrape_strategy": "browser",
                    "default_fetch_strategy": "generic_pricing_table",
                    "default_extractor": "generic_pricing_table",
                },
            )
            self.assertEqual(discover.status_code, 200)
            discover_payload = discover.get_json()["result"]
            urls = discover_payload["candidate_urls"]
            self.assertTrue(any(item["url"].endswith("/store/hk-vps") for item in urls))

            with app_module.open_connection() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM merchant_sources").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM merchant_items").fetchone()[0], 0)

            preview = self.client.post(
                f"{app_module.PORTAL_PATH}/api/merchant/preview",
                headers=headers,
                base_url=BASE_URL,
                json={
                    "source_url": "https://merchant.example.com/products",
                    "source_name": discover_payload["source_name"],
                    "group_name": "Preview IDC",
                    "catalog_discovery_strategy": "local",
                    "catalog_scrape_strategy": "browser",
                    "default_fetch_strategy": "generic_pricing_table",
                    "default_extractor": "generic_pricing_table",
                    "target_keyword": "HK",
                    "target_keyword_mode": "contains",
                    "candidate_urls": [item for item in urls if item["url"].endswith("/store/hk-vps")],
                },
            )
            self.assertEqual(preview.status_code, 200)
            preview_payload = preview.get_json()["result"]
            self.assertEqual([item["title"] for item in preview_payload["items"]], ["HK Preview VPS"])
            self.assertTrue(any(item["reject_reason"] for item in preview_payload["rejected_items"]))
            rejected_reasons = {item["title"]: item["reject_reason"] for item in preview_payload["rejected_items"]}
            self.assertIn("Tokyo Preview VPS", rejected_reasons)
            self.assertIn("目标关键词不匹配", rejected_reasons["Tokyo Preview VPS"])

            with app_module.open_connection() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM merchant_sources").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM merchant_items").fetchone()[0], 0)

            commit = self.client.post(
                f"{app_module.PORTAL_PATH}/api/merchant/commit",
                headers=headers,
                base_url=BASE_URL,
                json={
                    "source_url": preview_payload["source_url"],
                    "source_name": preview_payload["source_name"],
                    "group_name": preview_payload["group_name"],
                    "auto_promote": False,
                    "items": preview_payload["items"],
                },
            )
            self.assertEqual(commit.status_code, 200)
            commit_payload = commit.get_json()["result"]
            self.assertEqual(commit_payload["upserted_count"], 1)
            self.assertEqual(commit_payload["promoted_count"], 0)
        finally:
            engine.catalog_browser = original_browser

        with app_module.open_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM merchant_sources").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM merchant_items").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)

    def test_merchant_import_cloudflare_keeps_catalog_browser_stable(self) -> None:
        _, headers = self.login()
        engine = self.app.extensions["monitor_engine"]

        class FakeCatalogBrowser:
            def __init__(self) -> None:
                self.rebuild_calls: list[str] = []

            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                raise app_module.ProtectedSourceError("catalog 浏览器被 Cloudflare 验证页拦截：https://merchant.example.com/products")

            def rebuild(self, reason: str) -> None:
                self.rebuild_calls.append(reason)
                raise AssertionError("Cloudflare challenge 不应触发浏览器重建")

        original_browser = engine.catalog_browser
        fake_browser = FakeCatalogBrowser()
        engine.catalog_browser = fake_browser
        try:
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/api/merchant/import",
                headers=headers,
                base_url=BASE_URL,
                json={"source_url": "https://merchant.example.com/products", "catalog_scrape_strategy": "browser"},
            )
        finally:
            engine.catalog_browser = original_browser

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["error_kind"], "cloudflare_challenge")
        self.assertIn("受保护来源", payload["message"])
        self.assertEqual(fake_browser.rebuild_calls, [])

    def test_merchant_import_connection_failure_rebuilds_once_and_sanitizes_message(self) -> None:
        engine = self.app.extensions["monitor_engine"]
        raw_error = (
            "The browser connection fails. Address: 127.0.0.1:9445\n"
            "Tip: 1, the user folder does not conflict with the open browser 2, "
            "if no interface system, please add '--headless=new' startup parameter 3, "
            "if the system is Linux, try adding '--no-sandbox' boot parameter "
            "The port and user folder paths can be set using ChromiumOptions. Version: 4.1.1.4"
        )

        class FakeCatalogBrowser:
            def __init__(self) -> None:
                self.fetch_calls = 0
                self.rebuild_calls: list[str] = []

            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                self.fetch_calls += 1
                raise RuntimeError(raw_error)

            def rebuild(self, reason: str) -> None:
                self.rebuild_calls.append(reason)

        original_browser = engine.catalog_browser
        fake_browser = FakeCatalogBrowser()
        engine.catalog_browser = fake_browser
        try:
            with self.assertRaises(app_module.CatalogBrowserConnectionError) as ctx:
                engine.import_merchant_source(
                    "https://merchant.example.com/products",
                    "",
                    "默认分组",
                    engine.get_runtime_settings(),
                    auto_promote=False,
                    catalog_options={"catalog_scrape_strategy": "browser"},
                )
        finally:
            engine.catalog_browser = original_browser

        self.assertEqual(fake_browser.fetch_calls, 2)
        self.assertEqual(len(fake_browser.rebuild_calls), 1)
        self.assertIn("商品入库浏览器连接失败（端口 9445）", str(ctx.exception))
        self.assertNotIn("ChromiumOptions", str(ctx.exception))
        self.assertNotIn("The browser connection fails", str(ctx.exception))
        self.assertNotIn("ChromiumOptions", fake_browser.rebuild_calls[0])
        self.assertNotIn("The browser connection fails", fake_browser.rebuild_calls[0])

    def test_task_group_rename_updates_tasks_and_merchant_sources(self) -> None:
        _, headers = self.login()
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    name, group_name, monitor_url, target_keyword, restock_template, soldout_template,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    "Rename SKU",
                    "原分组",
                    "https://example.com/products/rename",
                    "Rename SKU",
                    "<b>{name}</b> {stock}",
                    "<b>{name}</b> sold out",
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO merchant_sources (
                    source_url, source_name, group_name, active, discovered_count, last_sync_at, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, 1, 0, ?, '', ?, ?)
                """,
                (
                    "https://merchant.example.com/rename",
                    "Rename Merchant",
                    "原分组",
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-groups/rename",
            headers=headers,
            base_url=BASE_URL,
            json={"old_name": "原分组", "new_name": "新分组"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["task_count"], 1)
        self.assertEqual(payload["result"]["source_count"], 1)

        with app_module.open_connection() as connection:
            task_group = connection.execute("SELECT group_name FROM tasks LIMIT 1").fetchone()[0]
            source_group = connection.execute("SELECT group_name FROM merchant_sources LIMIT 1").fetchone()[0]

        self.assertEqual(task_group, "新分组")
        self.assertEqual(source_group, "新分组")

    def test_task_group_subgroup_and_bulk_delete_endpoints(self) -> None:
        _, headers = self.login()
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            task_ids = []
            for name, group_name, subgroup_name in (
                ("HK Starter", "IDC-A", "香港"),
                ("US Starter", "IDC-A", "洛杉矶"),
                ("JP Starter", "IDC-B", "东京"),
                ("SG Starter", "IDC-B", "新加坡"),
            ):
                cursor = connection.execute(
                    """
                    INSERT INTO tasks (
                        name, group_name, subgroup_name, monitor_url, target_keyword,
                        restock_template, soldout_template, enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        name,
                        group_name,
                        subgroup_name,
                        f"https://example.com/{name.lower().replace(' ', '-')}",
                        name,
                        "{name} restock",
                        "{name} soldout",
                        timestamp,
                        timestamp,
                    ),
                )
                task_ids.append(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO merchant_sources (
                    source_url, source_name, group_name, active, discovered_count, last_sync_at, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, 1, 0, ?, '', ?, ?)
                """,
                ("https://merchant.example.com/idc-a", "IDC-A", "IDC-A", timestamp, timestamp, timestamp),
            )
            connection.commit()

        bulk = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks/bulk-delete",
            headers=headers,
            base_url=BASE_URL,
            json={"task_ids": [task_ids[2], task_ids[3], task_ids[3], "bad"]},
        )
        self.assertEqual(bulk.status_code, 200)
        self.assertEqual(bulk.get_json()["result"]["deleted_count"], 2)

        delete_subgroup = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-subgroups/delete",
            headers=headers,
            base_url=BASE_URL,
            json={"group_name": "IDC-A", "subgroup_name": "香港"},
        )
        self.assertEqual(delete_subgroup.status_code, 200)
        self.assertEqual(delete_subgroup.get_json()["result"]["task_count"], 1)

        delete_default = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-groups/delete",
            headers=headers,
            base_url=BASE_URL,
            json={"group_name": app_module.DEFAULT_TASK_GROUP},
        )
        self.assertEqual(delete_default.status_code, 400)

        delete_group = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-groups/delete",
            headers=headers,
            base_url=BASE_URL,
            json={"group_name": "IDC-A"},
        )
        self.assertEqual(delete_group.status_code, 200)
        self.assertEqual(delete_group.get_json()["result"]["task_count"], 1)
        self.assertEqual(delete_group.get_json()["result"]["source_count"], 1)

        with app_module.open_connection() as connection:
            remaining_tasks = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            source_group = connection.execute("SELECT group_name FROM merchant_sources WHERE source_name = ?", ("IDC-A",)).fetchone()[0]

        self.assertEqual(remaining_tasks, 0)
        self.assertEqual(source_group, app_module.DEFAULT_TASK_GROUP)

    def test_task_subgroup_nodes_can_be_created_renamed_and_bulk_deleted(self) -> None:
        _, headers = self.login()
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    name, group_name, subgroup_name, monitor_url, target_keyword,
                    restock_template, soldout_template, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    "HK WEE",
                    "DMIT",
                    "香港 / Tier 1 / AS3",
                    "https://example.com/hk-wee",
                    "HKG.AS3.T1.WEE",
                    "{name} restock",
                    "{name} soldout",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()

        create = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-subgroups",
            headers=headers,
            base_url=BASE_URL,
            json={"group_name": "DMIT", "parent_subgroup_name": "香港 / Tier 1", "name": "AS4"},
        )
        self.assertEqual(create.status_code, 200)
        self.assertEqual(create.get_json()["result"]["subgroup_name"], "香港 / Tier 1 / AS4")

        rename = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-subgroups/rename",
            headers=headers,
            base_url=BASE_URL,
            json={"group_name": "DMIT", "old_subgroup_name": "香港 / Tier 1", "new_name": "HK Tier 1"},
        )
        self.assertEqual(rename.status_code, 200)
        self.assertEqual(rename.get_json()["result"]["new_subgroup_name"], "香港 / HK Tier 1")

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        ).get_json()
        self.assertEqual(snapshot["tasks"][0]["subgroup_name"], "香港 / HK Tier 1 / AS3")
        self.assertIn(
            "香港 / HK Tier 1 / AS4",
            {node["subgroup_name"] for node in snapshot["task_group_nodes"]},
        )

        bulk_delete = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-subgroups/bulk-delete",
            headers=headers,
            base_url=BASE_URL,
            json={"group_name": "DMIT", "subgroup_names": ["香港 / HK Tier 1"]},
        )
        self.assertEqual(bulk_delete.status_code, 200)
        self.assertEqual(bulk_delete.get_json()["result"]["task_count"], 1)

        with app_module.open_connection() as connection:
            remaining_tasks = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            remaining_nodes = connection.execute("SELECT COUNT(*) FROM task_group_nodes").fetchone()[0]
        self.assertEqual(remaining_tasks, 0)
        self.assertEqual(remaining_nodes, 0)

    def test_task_browser_reorder_endpoints_persist_sort_order(self) -> None:
        _, headers = self.login()
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            task_ids = []
            for name, group_name, subgroup_name in (
                ("HK WEE", "IDC-A", "香港"),
                ("HK TINY", "IDC-A", "洛杉矶"),
                ("SG MINI", "IDC-B", "新加坡"),
            ):
                cursor = connection.execute(
                    """
                    INSERT INTO tasks (
                        name, group_name, subgroup_name, monitor_url, target_keyword,
                        restock_template, soldout_template, enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        name,
                        group_name,
                        subgroup_name,
                        f"https://example.com/{name.lower().replace(' ', '-')}",
                        name,
                        "{name} restock",
                        "{name} soldout",
                        timestamp,
                        timestamp,
                    ),
                )
                task_ids.append(cursor.lastrowid)
            connection.commit()

        group_reorder = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-groups/reorder",
            headers=headers,
            base_url=BASE_URL,
            json={"group_names": ["IDC-B", "IDC-A"]},
        )
        self.assertEqual(group_reorder.status_code, 200)
        self.assertEqual(group_reorder.get_json()["result"]["group_count"], 2)

        subgroup_reorder = self.client.post(
            f"{app_module.PORTAL_PATH}/api/task-subgroups/reorder",
            headers=headers,
            base_url=BASE_URL,
            json={"group_name": "IDC-A", "subgroup_names": ["洛杉矶", "香港"]},
        )
        self.assertEqual(subgroup_reorder.status_code, 200)
        self.assertEqual(subgroup_reorder.get_json()["result"]["subgroup_count"], 2)

        task_reorder = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks/reorder",
            headers=headers,
            base_url=BASE_URL,
            json={"task_ids": [task_ids[1], task_ids[0]]},
        )
        self.assertEqual(task_reorder.status_code, 200)
        self.assertEqual(task_reorder.get_json()["result"]["task_count"], 2)

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        ).get_json()
        group_orders = {group["group_name"]: group["sort_order"] for group in snapshot["task_groups"]}
        node_orders = {
            node["subgroup_name"]: node["sort_order"]
            for node in snapshot["task_group_nodes"]
            if node["group_name"] == "IDC-A"
        }
        task_orders = {task["id"]: task["sort_order"] for task in snapshot["tasks"]}

        self.assertEqual(group_orders["IDC-B"], 100)
        self.assertEqual(group_orders["IDC-A"], 200)
        self.assertEqual(node_orders["洛杉矶"], 100)
        self.assertEqual(node_orders["香港"], 200)
        self.assertEqual(task_orders[task_ids[1]], 100)
        self.assertEqual(task_orders[task_ids[0]], 200)

    def test_task_move_rehomes_single_task_and_preserves_state(self) -> None:
        _, headers = self.login()
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, group_name, subgroup_name, monitor_url, target_keyword,
                    restock_template, soldout_template, fetch_strategy, source_config,
                    source_source_name, source_item_url, last_stock, last_state, message_id,
                    message_ids, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    "HK WEE",
                    "DMIT",
                    "香港 / Tier 1",
                    "https://example.com/hk-wee",
                    "HKG.AS3.T1.WEE",
                    "{name} restock",
                    "{name} soldout",
                    "scrapling_adaptive",
                    json.dumps({"stock_rule_type": "auto_card", "target_scope_selector": ".plan"}),
                    "DMIT catalog",
                    "https://example.com/source",
                    3,
                    "in_stock",
                    901,
                    json.dumps({"chat-a": 901}),
                    timestamp,
                    timestamp,
                ),
            )
            task_id = cursor.lastrowid
            connection.commit()

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks/move",
            headers=headers,
            base_url=BASE_URL,
            json={
                "task_ids": [task_id],
                "target_group_name": "New IDC",
                "target_subgroup_name": "美国 / Premium",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["result"]["moved_count"], 1)

        with app_module.open_connection() as connection:
            row = connection.execute(
                """
                SELECT group_name, subgroup_name, sort_order, source_config, source_source_name,
                       source_item_url, last_stock, last_state, message_id, message_ids
                FROM tasks WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
            target_group = connection.execute(
                "SELECT 1 FROM task_groups WHERE group_name = ?",
                ("New IDC",),
            ).fetchone()
            target_node = connection.execute(
                "SELECT 1 FROM task_group_nodes WHERE group_name = ? AND subgroup_name = ?",
                ("New IDC", "美国 / Premium"),
            ).fetchone()

        self.assertEqual(row["group_name"], "New IDC")
        self.assertEqual(row["subgroup_name"], "美国 / Premium")
        self.assertGreaterEqual(row["sort_order"], 100)
        self.assertEqual(json.loads(row["source_config"])["stock_rule_type"], "auto_card")
        self.assertEqual(row["source_source_name"], "DMIT catalog")
        self.assertEqual(row["source_item_url"], "https://example.com/source")
        self.assertEqual(row["last_stock"], 3)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["message_id"], 901)
        self.assertEqual(json.loads(row["message_ids"]), {"chat-a": 901})
        self.assertIsNotNone(target_group)
        self.assertIsNotNone(target_node)

    def test_task_move_batches_tasks_and_creates_target_nodes(self) -> None:
        _, headers = self.login()
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            task_ids = []
            for name, subgroup_name, state, message_id in (
                ("US TRI", "美国 / TRI", "unknown", None),
                ("KR INTL", "韩国 / INTL", "sold_out", 777),
            ):
                cursor = connection.execute(
                    """
                    INSERT INTO tasks (
                        name, group_name, subgroup_name, monitor_url, target_keyword,
                        restock_template, soldout_template, enabled, last_state, message_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        "Source IDC",
                        subgroup_name,
                        f"https://example.com/{name.lower().replace(' ', '-')}",
                        name,
                        "{name} restock",
                        "{name} soldout",
                        state,
                        message_id,
                        timestamp,
                        timestamp,
                    ),
                )
                task_ids.append(cursor.lastrowid)
            connection.commit()

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks/move",
            headers=headers,
            base_url=BASE_URL,
            json={
                "task_ids": [task_ids[0], task_ids[1], task_ids[1], "bad"],
                "target_group_name": "Target IDC",
                "target_subgroup_name": "北美 / Premium / AS3",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["result"]
        self.assertEqual(payload["moved_count"], 2)
        self.assertEqual(payload["task_ids"], task_ids)

        with app_module.open_connection() as connection:
            rows = connection.execute(
                "SELECT id, group_name, subgroup_name, sort_order, last_state, message_id FROM tasks ORDER BY sort_order"
            ).fetchall()
            target_group = connection.execute(
                "SELECT 1 FROM task_groups WHERE group_name = ?",
                ("Target IDC",),
            ).fetchone()
            target_node = connection.execute(
                "SELECT 1 FROM task_group_nodes WHERE group_name = ? AND subgroup_name = ?",
                ("Target IDC", "北美 / Premium / AS3"),
            ).fetchone()

        self.assertEqual([row["id"] for row in rows], task_ids)
        self.assertEqual({row["group_name"] for row in rows}, {"Target IDC"})
        self.assertEqual({row["subgroup_name"] for row in rows}, {"北美 / Premium / AS3"})
        self.assertEqual([row["sort_order"] for row in rows], [100, 200])
        self.assertEqual(rows[0]["last_state"], "unknown")
        self.assertEqual(rows[1]["last_state"], "sold_out")
        self.assertEqual(rows[1]["message_id"], 777)
        self.assertIsNotNone(target_group)
        self.assertIsNotNone(target_node)

    def test_merchant_item_promote_creates_linked_task(self) -> None:
        _, headers = self.login()
        engine = self.app.extensions["monitor_engine"]

        class FakeCatalogBrowser:
            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                return """
                <html>
                  <head><title>Acme Hosting</title></head>
                  <body>
                    <div class="package">
                      <h3>HK-CMI Unlimited</h3>
                      <p>库存 9</p>
                      <a href="cart.php?a=add&pid=21">Order Now</a>
                    </div>
                  </body>
                </html>
                """

            def rebuild(self, reason: str) -> None:
                raise AssertionError(reason)

        original_browser = engine.catalog_browser
        fake_browser = FakeCatalogBrowser()
        engine.catalog_browser = fake_browser
        try:
            result = engine.import_merchant_source(
                "https://merchant.example.com/products",
                "",
                "网络节点",
                engine.get_runtime_settings(),
                auto_promote=False,
                catalog_options={"catalog_scrape_strategy": "browser"},
            )
        finally:
            engine.catalog_browser = original_browser

        self.assertEqual(result.scanned_count, 1)
        self.assertEqual(result.promoted_count, 0)

        with app_module.open_connection() as connection:
            item_id = connection.execute("SELECT id FROM merchant_items LIMIT 1").fetchone()[0]
            task_count_before = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

        self.assertEqual(task_count_before, 0)

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/merchant/items/{item_id}/promote",
            headers=headers,
            base_url=BASE_URL,
            json={},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["item_id"], item_id)
        self.assertIsInstance(payload["result"]["task_id"], int)

        with app_module.open_connection() as connection:
            task_row = connection.execute(
                "SELECT source_item_id, source_source_url, source_source_name, group_name FROM tasks LIMIT 1"
            ).fetchone()
            task_count_after = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

        self.assertEqual(task_count_after, 1)
        self.assertEqual(task_row["source_item_id"], item_id)
        self.assertEqual(task_row["source_source_url"], "https://merchant.example.com/products")
        self.assertEqual(task_row["source_source_name"], "Acme Hosting")
        self.assertEqual(task_row["group_name"], "网络节点")

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        payload = snapshot.get_json()
        self.assertEqual(payload["merchant"]["metrics"]["linked_tasks"], 1)

    def test_merchant_bulk_promote_deduplicates_items_and_preserves_catalog_strategy(self) -> None:
        _, headers = self.login()
        engine = self.app.extensions["monitor_engine"]

        class FakeCatalogBrowser:
            def fetch_html(self, url: str, timeout_seconds: int) -> str:
                return """
                <html>
                  <head><title>Acme Catalog</title></head>
                  <body>
                    <section class="product-card">
                      <h3>HK-CMI Starter</h3>
                      <p>库存 3</p>
                      <a href="cart.php?a=add&pid=31">Order Now</a>
                    </section>
                    <section class="product-card">
                      <h3>HK-CMI Pro</h3>
                      <p>库存 8</p>
                      <a href="cart.php?a=add&pid=32">Order Now</a>
                    </section>
                  </body>
                </html>
                """

            def rebuild(self, reason: str) -> None:
                raise AssertionError(reason)

        original_browser = engine.catalog_browser
        engine.catalog_browser = FakeCatalogBrowser()
        try:
            result = engine.import_merchant_source(
                "https://merchant.example.com/products",
                "",
                "香港节点",
                engine.get_runtime_settings(),
                auto_promote=False,
                catalog_options={
                    "catalog_scrape_strategy": "browser",
                    "default_fetch_strategy": "generic_pricing_table",
                    "default_extractor": "whmcs",
                    "target_keyword": "HK-CMI",
                    "target_keyword_mode": "contains",
                    "dedupe_policy": "by_pid",
                },
            )
        finally:
            engine.catalog_browser = original_browser

        self.assertEqual(result.scanned_count, 2)
        self.assertEqual(result.promoted_count, 0)

        with app_module.open_connection() as connection:
            item_ids = [
                row["id"]
                for row in connection.execute("SELECT id FROM merchant_items ORDER BY title").fetchall()
            ]
        self.assertEqual(len(item_ids), 2)

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/merchant/items/bulk-promote",
            headers=headers,
            base_url=BASE_URL,
            json={"item_ids": [item_ids[0], item_ids[0], item_ids[1]]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["created_count"], 2)
        self.assertEqual(payload["result"]["linked_count"], 0)

        repeat_response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/merchant/items/bulk-promote",
            headers=headers,
            base_url=BASE_URL,
            json={"item_ids": item_ids},
        )
        self.assertEqual(repeat_response.status_code, 200)
        repeat_payload = repeat_response.get_json()
        self.assertEqual(repeat_payload["result"]["created_count"], 0)
        self.assertEqual(repeat_payload["result"]["linked_count"], 2)

        with app_module.open_connection() as connection:
            task_rows = connection.execute(
                "SELECT fetch_strategy, source_config FROM tasks ORDER BY name"
            ).fetchall()
            task_count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

        self.assertEqual(task_count, 2)
        self.assertEqual([row["fetch_strategy"] for row in task_rows], ["generic_pricing_table", "generic_pricing_table"])
        configs = [json.loads(row["source_config"]) for row in task_rows]
        self.assertEqual([config["extractor"] for config in configs], ["whmcs", "whmcs"])
        self.assertEqual([config["catalog_backend"] for config in configs], ["browser", "browser"])

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=headers,
            base_url=BASE_URL,
        )
        merchant_items = snapshot.get_json()["merchant"]["items"]
        self.assertEqual({item["backend_used"] for item in merchant_items}, {"browser"})
        self.assertEqual({item["extractor"] for item in merchant_items}, {"whmcs"})
        self.assertEqual({item["fetch_strategy"] for item in merchant_items}, {"generic_pricing_table"})

    def test_merchant_source_toggle_updates_activity_and_snapshot(self) -> None:
        _, headers = self.login()
        with app_module.open_connection() as connection:
            connection.execute(
                """
                INSERT INTO merchant_sources (
                    source_url, source_name, active, discovered_count, last_sync_at, last_error, created_at, updated_at
                ) VALUES (?, ?, 1, 0, ?, '', ?, ?)
                """,
                (
                    "https://merchant.example.com/products",
                    "Merchant One",
                    app_module.now_iso(),
                    app_module.now_iso(),
                    app_module.now_iso(),
                ),
            )
            connection.commit()
            source_id = connection.execute("SELECT id FROM merchant_sources LIMIT 1").fetchone()[0]

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/merchant/sources/{source_id}/toggle",
            headers=headers,
            base_url=BASE_URL,
            json={"active": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["result"]["active"])

        refreshed = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        merchant_sources = refreshed.get_json()["merchant"]["sources"]
        self.assertFalse(merchant_sources[0]["active"])

    def test_system_upgrade_endpoint_reports_unsupported_local_environment(self) -> None:
        app_module.UPGRADE_SERVICE_NAME = "noaff-monitor-missing-test-upgrade.service"
        _, headers = self.login()
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/system/upgrade",
            headers=headers,
            base_url=BASE_URL,
            json={},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["system"]["upgrade_mode"], "unsupported")
        self.assertFalse(payload["system"]["upgrade_supported"])

    def test_system_payload_reports_docker_manual_upgrade_mode(self) -> None:
        app_module.DEPLOY_MODE = "docker"
        app_module.INSTALL_APP_DIR = "/srv/noaff"
        app_module.REPO_REF = "master"
        app_module.APP_VERSION_OVERRIDE = "v1.2.3"
        app_module.APP_BRANCH_OVERRIDE = "main"
        original_run_short_command = app_module.run_short_command
        app_module.run_short_command = lambda args, timeout=4: ""
        payload = app_module.system_payload()
        app_module.run_short_command = original_run_short_command
        self.assertEqual(payload["upgrade_mode"], "manual")
        self.assertFalse(payload["upgrade_supported"])
        self.assertEqual(payload["version"], "v1.2.3")
        self.assertEqual(payload["branch"], "main")
        self.assertIn("bash install.sh --docker-upgrade", payload["upgrade_command"])

    def test_system_payload_reports_manual_upgrade_without_systemd_permission(self) -> None:
        app_module.DEPLOY_MODE = "native"
        app_module.PANEL_UPGRADE_ENABLED = False
        original_upgrade_service_exists = app_module.upgrade_service_exists
        original_is_root_process = app_module.is_root_process
        original_which = app_module.shutil.which
        try:
            app_module.upgrade_service_exists = lambda: True
            app_module.is_root_process = lambda: False
            app_module.shutil.which = lambda name: "/usr/bin/systemctl" if name == "systemctl" else original_which(name)
            payload = app_module.system_payload()
        finally:
            app_module.upgrade_service_exists = original_upgrade_service_exists
            app_module.is_root_process = original_is_root_process
            app_module.shutil.which = original_which

        self.assertEqual(payload["upgrade_mode"], "manual")
        self.assertFalse(payload["upgrade_supported"])
        self.assertEqual(payload["upgrade_state"], "需要手动升级")
        self.assertIn("sudo systemctl start noaff-monitor-upgrade.service", payload["upgrade_command"])

    def test_system_payload_allows_panel_upgrade_when_explicitly_enabled(self) -> None:
        app_module.DEPLOY_MODE = "native"
        app_module.PANEL_UPGRADE_ENABLED = True
        original_upgrade_service_exists = app_module.upgrade_service_exists
        original_is_root_process = app_module.is_root_process
        original_which = app_module.shutil.which
        try:
            app_module.upgrade_service_exists = lambda: True
            app_module.is_root_process = lambda: False
            app_module.shutil.which = lambda name: "/usr/bin/systemctl" if name == "systemctl" else original_which(name)
            payload = app_module.system_payload()
        finally:
            app_module.upgrade_service_exists = original_upgrade_service_exists
            app_module.is_root_process = original_is_root_process
            app_module.shutil.which = original_which

        self.assertEqual(payload["upgrade_mode"], "panel")
        self.assertTrue(payload["upgrade_supported"])
        self.assertEqual(payload["upgrade_command"], "systemctl start noaff-monitor-upgrade.service")

    def test_upgrade_start_error_explains_interactive_auth(self) -> None:
        message = app_module.upgrade_start_error_message(
            "Failed to start noaff-monitor-upgrade.service: Interactive authentication required."
        )

        self.assertIn("没有启动 systemd 升级服务的权限", message)
        self.assertIn("sudo systemctl start noaff-monitor-upgrade.service", message)

    def test_system_upgrade_endpoint_reports_docker_manual_command(self) -> None:
        app_module.DEPLOY_MODE = "docker"
        _, headers = self.login()
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/system/upgrade",
            headers=headers,
            base_url=BASE_URL,
            json={},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertIn("Docker", payload["message"])
        self.assertEqual(payload["system"]["upgrade_mode"], "manual")
        self.assertIn("bash install.sh --docker-upgrade", payload["system"]["upgrade_command"])

    def test_system_backup_export_and_restore_round_trip(self) -> None:
        _, headers = self.login()
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    name, group_name, monitor_url, target_keyword, restock_template, soldout_template,
                    fetch_strategy, source_config, blocked_count, last_blocked_at, cooldown_until,
                    ingest_token_hash, ingest_token_hint, enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    "Backup SKU",
                    "Backup Group",
                    "https://example.com/products/backup",
                    "Backup SKU",
                    "<b>{name}</b> {stock}",
                    "<b>{name}</b> sold out",
                    "static_http",
                    "{\"mode\":\"backup\"}",
                    2,
                    "2026-07-07T00:00:00+00:00",
                    "2026-07-07T00:10:00+00:00",
                    "hash-from-backup",
                    "hint-1234",
                    timestamp,
                    timestamp,
                ),
            )
            app_module.save_settings(
                connection,
                {
                    "telegram_chat_id": "backup-chat-id",
                    "poll_interval_seconds": "60",
                    "firecrawl_api_key": "fc-secret-backup-key",
                },
            )
            connection.commit()

        export_response = self.client.get(
            f"{app_module.PORTAL_PATH}/api/system/backup",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        self.assertEqual(export_response.status_code, 200)
        self.assertIn("attachment; filename=\"noaff-backup-", export_response.headers["Content-Disposition"])
        backup_payload = json.loads(export_response.get_data(as_text=True))
        self.assertEqual(backup_payload["schema_version"], 1)
        self.assertGreaterEqual(len(backup_payload["tables"]["tasks"]), 1)
        self.assertEqual(backup_payload["tables"]["tasks"][0]["fetch_strategy"], "static_http")
        self.assertEqual(backup_payload["tables"]["tasks"][0]["blocked_count"], 2)
        self.assertEqual(backup_payload["tables"]["tasks"][0]["ingest_token_hash"], "hash-from-backup")
        self.assertEqual(backup_payload["tables"]["tasks"][0]["ingest_token_hint"], "hint-1234")
        self.assertIn("admins", backup_payload["tables"])
        backup_text = json.dumps(backup_payload, ensure_ascii=False)
        self.assertNotIn("fc-secret-backup-key", backup_text)
        settings_rows = {row["key"]: row["value"] for row in backup_payload["tables"]["settings"]}
        self.assertEqual(settings_rows["firecrawl_api_key"], "")

        with app_module.open_connection() as connection:
            connection.execute("DELETE FROM tasks")
            app_module.save_settings(
                connection,
                {
                    "telegram_chat_id": "mutated-chat-id",
                    "poll_interval_seconds": "120",
                },
            )
            connection.commit()

        restore_response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/system/backup",
            headers=headers,
            base_url=BASE_URL,
            data={
                "backup_file": (io.BytesIO(json.dumps(backup_payload).encode("utf-8")), "backup.json"),
            },
        )
        self.assertEqual(restore_response.status_code, 200)
        self.assertTrue(restore_response.get_json()["ok"])

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        payload = snapshot.get_json()
        self.assertEqual(payload["settings"]["telegram_chat_id"], "backup-chat-id")
        self.assertNotIn("firecrawl_api_key", payload["settings"])
        self.assertEqual(payload["metrics"]["total"], 1)
        self.assertEqual(payload["tasks"][0]["fetch_strategy"], "static_http")
        self.assertEqual(payload["tasks"][0]["blocked_count"], 2)
        self.assertEqual(payload["tasks"][0]["cooldown_until"], "2026-07-07T00:10:00+00:00")
        self.assertEqual(payload["tasks"][0]["ingest_token_hint"], "hint-1234")

    def test_system_backup_restore_rejects_invalid_payload(self) -> None:
        _, headers = self.login()
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/system/backup",
            headers=headers,
            base_url=BASE_URL,
            data={"backup_file": (io.BytesIO(b"{\"schema_version\":1,\"tables\":{}}"), "bad.json")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("缺少管理员或设置数据", response.get_json()["message"])

    def test_telegram_state_machine_sends_edits_and_clears_message_id(self) -> None:
        _, headers = self.login()
        create = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "HK VM",
                "monitor_url": "https://example.com/cart.php?gid=1",
                "target_keyword": "HK-CMI",
                "restock_template": "<b>{name}</b> stock={stock}",
                "soldout_template": "<b>{name}</b> sold out",
                "button_1_text": "Open",
                "button_1_url": "https://example.com/order",
                "button_2_text": "",
                "button_2_url": "",
                "enabled": True,
            },
        )
        self.assertEqual(create.status_code, 200)
        task_id = create.get_json()["task_id"]

        class FakeTelegram:
            def __init__(self) -> None:
                self.sent: list[dict[str, object]] = []
                self.edited: list[dict[str, object]] = []

            def send_message(self, token, chat_id, text, buttons=None) -> int:
                message_id = 900 + len(self.sent) + 1
                self.sent.append({"token": token, "chat_id": chat_id, "text": text, "buttons": buttons, "message_id": message_id})
                return message_id

            def edit_message(self, token, chat_id, message_id, text, buttons=None) -> None:
                self.edited.append(
                    {"token": token, "chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons}
                )

        engine = self.app.extensions["monitor_engine"]
        original_telegram = engine.telegram
        original_scrape_task = engine.scrape_task
        fake_telegram = FakeTelegram()
        stock_box = {"value": 5}
        settings_payload = {
            "telegram_bot_token": "token",
            "telegram_chat_id": "chat-a",
            "telegram_chat_ids": "chat-a\nchat-b",
            "monitor_debug_port": 9223,
            "test_debug_port": 9334,
            "poll_interval_seconds": 45,
            "request_timeout_seconds": 25,
        }

        def fetch_task() -> sqlite3.Row:
            with app_module.open_connection() as connection:
                return connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

        def fake_scrape_task(task, settings, use_test_browser):
            return app_module.ScrapeResult(
                stock=stock_box["value"],
                fragment="<html></html>",
                detail="ok",
                used_test_browser=use_test_browser,
            )

        try:
            engine.telegram = fake_telegram
            engine.scrape_task = fake_scrape_task

            self.assertTrue(engine.process_task(fetch_task(), settings_payload, use_test_browser=False))
            with app_module.open_connection() as connection:
                row = connection.execute(
                    "SELECT last_stock, last_state, message_id, message_ids FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            self.assertEqual(row["last_stock"], 5)
            self.assertEqual(row["last_state"], "in_stock")
            self.assertEqual(row["message_id"], 901)
            self.assertEqual(json.loads(row["message_ids"]), {"chat-a": 901, "chat-b": 902})
            self.assertEqual(len(fake_telegram.sent), 2)
            self.assertEqual(len(fake_telegram.edited), 0)
            self.assertEqual({msg["chat_id"] for msg in fake_telegram.sent}, {"chat-a", "chat-b"})

            stock_box["value"] = 7
            self.assertTrue(engine.process_task(fetch_task(), settings_payload, use_test_browser=False))
            with app_module.open_connection() as connection:
                row = connection.execute(
                    "SELECT last_stock, last_state, message_id, message_ids FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            self.assertEqual(row["last_stock"], 7)
            self.assertEqual(row["last_state"], "in_stock")
            self.assertEqual(row["message_id"], 901)
            self.assertEqual(json.loads(row["message_ids"]), {"chat-a": 901, "chat-b": 902})
            self.assertEqual(len(fake_telegram.sent), 2)
            self.assertEqual(len(fake_telegram.edited), 2)
            self.assertEqual([entry["message_id"] for entry in fake_telegram.edited], [901, 902])
            self.assertIn("stock=7", fake_telegram.edited[-1]["text"])

            stock_box["value"] = 0
            self.assertTrue(engine.process_task(fetch_task(), settings_payload, use_test_browser=False))
            with app_module.open_connection() as connection:
                row = connection.execute(
                    "SELECT last_stock, last_state, message_id, message_ids FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            self.assertEqual(row["last_stock"], 0)
            self.assertEqual(row["last_state"], "sold_out")
            self.assertIsNone(row["message_id"])
            self.assertEqual(row["message_ids"], "")
            self.assertEqual(len(fake_telegram.sent), 2)
            self.assertEqual(len(fake_telegram.edited), 4)
            self.assertIn("sold out", fake_telegram.edited[-1]["text"])
        finally:
            engine.telegram = original_telegram
            engine.scrape_task = original_scrape_task

    def test_manual_stock_update_reuses_telegram_state_machine(self) -> None:
        _, headers = self.login()
        create = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "Manual VM",
                "monitor_url": "https://example.com/manual",
                "target_keyword": "Manual VM",
                "fetch_strategy": "manual",
                "source_config": {},
                "restock_template": "<b>{name}</b> stock={stock}",
                "soldout_template": "<b>{name}</b> sold out",
                "button_1_text": "",
                "button_1_url": "",
                "button_2_text": "",
                "button_2_url": "",
                "enabled": True,
            },
        )
        self.assertEqual(create.status_code, 200)
        task_id = create.get_json()["task_id"]
        with app_module.open_connection() as connection:
            app_module.save_settings(
                connection,
                {
                    "telegram_bot_token": "bot-token",
                    "telegram_chat_ids": "manual-chat",
                },
            )

        class FakeTelegram:
            def __init__(self) -> None:
                self.sent: list[dict[str, object]] = []
                self.edited: list[dict[str, object]] = []

            def send_message(self, token, chat_id, text, buttons=None) -> int:
                message_id = 1000 + len(self.sent)
                self.sent.append({"token": token, "chat_id": chat_id, "text": text, "buttons": buttons})
                return message_id

            def edit_message(self, token, chat_id, message_id, text, buttons=None) -> None:
                self.edited.append(
                    {"token": token, "chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons}
                )

        engine = self.app.extensions["monitor_engine"]
        original_telegram = engine.telegram
        fake_telegram = FakeTelegram()
        try:
            engine.telegram = fake_telegram
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/api/tasks/{task_id}/manual-stock",
                headers=headers,
                base_url=BASE_URL,
                json={
                    "stock": 3,
                    "detail": "operator confirmed",
                    "checked_at": "2026-07-07T01:02:03+00:00",
                },
            )
        finally:
            engine.telegram = original_telegram

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(len(fake_telegram.sent), 1)
        self.assertEqual(fake_telegram.sent[0]["chat_id"], "manual-chat")
        self.assertIn("stock=3", fake_telegram.sent[0]["text"])
        self.assertEqual(fake_telegram.edited, [])
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 3)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["last_checked_at"], "2026-07-07T01:02:03+00:00")

    def test_webhook_ingest_token_and_telegram_state_machine(self) -> None:
        _, headers = self.login()
        create = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "Webhook VM",
                "monitor_url": "https://example.com/webhook",
                "target_keyword": "Webhook VM",
                "fetch_strategy": "webhook",
                "source_config": {"token": "must-not-persist", "mode": "push"},
                "restock_template": "<b>{name}</b> stock={stock}",
                "soldout_template": "<b>{name}</b> sold out",
                "button_1_text": "",
                "button_1_url": "",
                "button_2_text": "",
                "button_2_url": "",
                "enabled": True,
            },
        )
        self.assertEqual(create.status_code, 200)
        task_id = create.get_json()["task_id"]
        with app_module.open_connection() as connection:
            app_module.save_settings(
                connection,
                {
                    "telegram_bot_token": "bot-token",
                    "telegram_chat_ids": "chat-a\nchat-b",
                },
            )

        reset = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks/{task_id}/webhook-token",
            headers=headers,
            base_url=BASE_URL,
            json={},
        )
        self.assertEqual(reset.status_code, 200)
        reset_payload = reset.get_json()["result"]
        ingest_token = reset_payload["ingest_token"]
        self.assertTrue(ingest_token)
        self.assertEqual(reset_payload["webhook_endpoint"], f"/api/webhooks/restock/{task_id}")

        class FakeTelegram:
            def __init__(self) -> None:
                self.sent: list[dict[str, object]] = []
                self.edited: list[dict[str, object]] = []

            def send_message(self, token, chat_id, text, buttons=None) -> int:
                message_id = 2000 + len(self.sent) + 1
                self.sent.append({"token": token, "chat_id": chat_id, "text": text, "buttons": buttons, "message_id": message_id})
                return message_id

            def edit_message(self, token, chat_id, message_id, text, buttons=None) -> None:
                self.edited.append(
                    {"token": token, "chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons}
                )

        engine = self.app.extensions["monitor_engine"]
        original_telegram = engine.telegram
        fake_telegram = FakeTelegram()
        try:
            engine.telegram = fake_telegram
            invalid = self.client.post(
                f"{app_module.PORTAL_PATH}/api/webhooks/restock/{task_id}",
                headers={"X-NOAFF-Token": "invalid-webhook-token"},
                base_url=BASE_URL,
                json={"stock": 9},
            )
            self.assertEqual(invalid.status_code, 401)
            self.assertEqual(fake_telegram.sent, [])

            first = self.client.post(
                f"{app_module.PORTAL_PATH}/api/webhooks/restock/{task_id}",
                headers={"X-NOAFF-Token": ingest_token},
                base_url=BASE_URL,
                json={"stock": 5, "detail": "provider push", "checked_at": "2026-07-07T02:00:00+00:00"},
            )
            self.assertEqual(first.status_code, 200)
            self.assertEqual(len(fake_telegram.sent), 2)
            self.assertEqual({entry["chat_id"] for entry in fake_telegram.sent}, {"chat-a", "chat-b"})

            changed = self.client.post(
                f"{app_module.PORTAL_PATH}/api/webhooks/restock/{task_id}",
                headers={"Authorization": f"Bearer {ingest_token}"},
                base_url=BASE_URL,
                json={"stock": 7, "detail": "provider count changed"},
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(len(fake_telegram.edited), 2)
            self.assertIn("stock=7", fake_telegram.edited[-1]["text"])

            sold_out = self.client.post(
                f"{app_module.PORTAL_PATH}/api/webhooks/restock/{task_id}",
                headers={"X-NOAFF-Token": ingest_token},
                base_url=BASE_URL,
                json={"status": "sold_out"},
            )
            self.assertEqual(sold_out.status_code, 200)
            self.assertEqual(len(fake_telegram.edited), 4)
            self.assertIn("sold out", fake_telegram.edited[-1]["text"])
        finally:
            engine.telegram = original_telegram

        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 0)
        self.assertEqual(row["last_state"], "sold_out")
        self.assertEqual(row["message_ids"], "")
        self.assertNotEqual(row["ingest_token_hash"], ingest_token)
        self.assertEqual(row["ingest_token_hint"], reset_payload["ingest_token_hint"])

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        snapshot_text = json.dumps(snapshot.get_json(), ensure_ascii=False)
        self.assertNotIn(ingest_token, snapshot_text)
        self.assertNotIn("must-not-persist", snapshot_text)
        self.assertNotIn("invalid-webhook-token", snapshot_text)
        self.assertIn(reset_payload["ingest_token_hint"], snapshot_text)
        self.assertIn(f"/api/webhooks/restock/{task_id}", snapshot_text)

    def test_external_input_polling_waits_without_recording_error(self) -> None:
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, fetch_strategy, restock_template, soldout_template,
                    enabled, last_stock, last_state, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    "Manual Pending VM",
                    "https://example.com/manual",
                    "Manual Pending VM",
                    "manual",
                    "{name} {stock}",
                    "{name} sold out",
                    2,
                    "in_stock",
                    "old transient error",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        class FakeTelegram:
            def send_message(self, token, chat_id, text, buttons=None) -> int:
                raise AssertionError("pending manual task must not send Telegram")

            def edit_message(self, token, chat_id, message_id, text, buttons=None) -> None:
                raise AssertionError("pending manual task must not edit Telegram")

        engine = self.app.extensions["monitor_engine"]
        original_telegram = engine.telegram
        try:
            engine.telegram = FakeTelegram()
            processed = engine.process_task(
                task,
                {
                    "telegram_bot_token": "",
                    "telegram_chat_id": "",
                    "telegram_chat_ids": "",
                    "monitor_debug_port": 9223,
                    "test_debug_port": 9334,
                    "poll_interval_seconds": 45,
                    "request_timeout_seconds": 25,
                },
                use_test_browser=False,
            )
        finally:
            engine.telegram = original_telegram

        self.assertFalse(processed)
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task["id"],)).fetchone()
        self.assertEqual(row["last_stock"], 2)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["last_error"], "")
        self.assertTrue(row["last_checked_at"])

    def test_process_task_records_scrape_error_without_telegram_or_state_change(self) -> None:
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, restock_template, soldout_template,
                    enabled, last_stock, last_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Protected VM",
                    "https://example.com/products",
                    "Protected VM",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    3,
                    "in_stock",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task_id = cursor.lastrowid

        class FakeTelegram:
            def __init__(self) -> None:
                self.sent: list[dict[str, object]] = []
                self.edited: list[dict[str, object]] = []

            def send_message(self, token, chat_id, text, buttons=None) -> int:
                self.sent.append({"token": token, "chat_id": chat_id, "text": text, "buttons": buttons})
                return 1

            def edit_message(self, token, chat_id, message_id, text, buttons=None) -> None:
                self.edited.append(
                    {"token": token, "chat_id": chat_id, "message_id": message_id, "text": text, "buttons": buttons}
                )

        engine = self.app.extensions["monitor_engine"]
        original_telegram = engine.telegram
        original_scrape_task = engine.scrape_task
        fake_telegram = FakeTelegram()

        def fetch_task() -> sqlite3.Row:
            with app_module.open_connection() as connection:
                return connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

        def fake_scrape_task(task, settings, use_test_browser):
            return app_module.ScrapeResult(
                stock=None,
                fragment="",
                detail="monitor 浏览器被 Cloudflare 验证页拦截：https://example.com/products",
                used_test_browser=use_test_browser,
                error_kind="cloudflare_challenge",
            )

        try:
            engine.telegram = fake_telegram
            engine.scrape_task = fake_scrape_task
            processed = engine.process_task(
                fetch_task(),
                {
                    "telegram_bot_token": "",
                    "telegram_chat_id": "",
                    "telegram_chat_ids": "",
                    "monitor_debug_port": 9223,
                    "test_debug_port": 9334,
                    "poll_interval_seconds": 45,
                    "request_timeout_seconds": 25,
                },
                use_test_browser=False,
            )
        finally:
            engine.telegram = original_telegram
            engine.scrape_task = original_scrape_task

        self.assertFalse(processed)
        self.assertEqual(fake_telegram.sent, [])
        self.assertEqual(fake_telegram.edited, [])
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 3)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertIn("Cloudflare 验证页拦截", row["last_error"])
        self.assertEqual(row["blocked_count"], 1)
        self.assertTrue(row["last_blocked_at"])
        self.assertTrue(row["cooldown_until"])
        blocked_at = app_module.parse_iso_datetime(row["last_blocked_at"])
        cooldown_until = app_module.parse_iso_datetime(row["cooldown_until"])
        self.assertIsNotNone(blocked_at)
        self.assertIsNotNone(cooldown_until)
        self.assertAlmostEqual((cooldown_until - blocked_at).total_seconds(), 60, delta=2)

    def test_process_task_skips_protected_source_during_cooldown(self) -> None:
        timestamp = app_module.now_iso()
        cooldown_until = (app_module.now_utc() + app_module.timedelta(minutes=3)).isoformat(timespec="seconds")
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, restock_template, soldout_template,
                    enabled, last_stock, last_state, blocked_count, last_blocked_at, cooldown_until,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Cooling VM",
                    "https://example.com/products",
                    "Cooling VM",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    4,
                    "in_stock",
                    1,
                    timestamp,
                    cooldown_until,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task_id = cursor.lastrowid

        class ExplodingBrowser:
            def __init__(self) -> None:
                self.calls = 0
                self.rebuilds = 0

            def fetch_html(self, url, timeout_seconds):
                self.calls += 1
                raise AssertionError("cooldown task must not fetch target pages")

            def rebuild(self, reason):
                self.rebuilds += 1
                raise AssertionError("cooldown task must not rebuild browsers")

        engine = self.app.extensions["monitor_engine"]
        original_browser = engine.monitor_browser
        exploding_browser = ExplodingBrowser()
        try:
            engine.monitor_browser = exploding_browser
            with app_module.open_connection() as connection:
                task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            processed = engine.process_task(
                task,
                {
                    "telegram_bot_token": "",
                    "telegram_chat_id": "",
                    "telegram_chat_ids": "",
                    "monitor_debug_port": 9223,
                    "test_debug_port": 9334,
                    "poll_interval_seconds": 45,
                    "request_timeout_seconds": 25,
                },
                use_test_browser=False,
            )
        finally:
            engine.monitor_browser = original_browser

        self.assertFalse(processed)
        self.assertEqual(exploding_browser.calls, 0)
        self.assertEqual(exploding_browser.rebuilds, 0)
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 4)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["blocked_count"], 1)
        self.assertEqual(row["cooldown_until"], cooldown_until)
        self.assertIn("受保护站点冷却中", row["last_error"])

    def test_cooldown_skips_firecrawl_fetcher(self) -> None:
        timestamp = app_module.now_iso()
        cooldown_until = (app_module.now_utc() + app_module.timedelta(minutes=3)).isoformat(timespec="seconds")
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, fetch_strategy, restock_template, soldout_template,
                    enabled, last_stock, last_state, blocked_count, last_blocked_at, cooldown_until,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Firecrawl Cooling VM",
                    "https://example.com/products",
                    "Firecrawl Cooling VM",
                    "firecrawl",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    2,
                    "in_stock",
                    2,
                    timestamp,
                    cooldown_until,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task_id = cursor.lastrowid

        class ExplodingFirecrawlFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                raise AssertionError("cooldown task must not call Firecrawl")

        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                firecrawl_fetcher=ExplodingFirecrawlFetcher(),
            )
            with app_module.open_connection() as connection:
                task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            processed = engine.process_task(
                task,
                {
                    "telegram_bot_token": "",
                    "telegram_chat_ids": "",
                    "request_timeout_seconds": 25,
                    **self.firecrawl_settings(),
                },
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertFalse(processed)
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 2)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["blocked_count"], 2)
        self.assertEqual(row["cooldown_until"], cooldown_until)
        self.assertIn("受保护站点冷却中", row["last_error"])

    def test_telegram_error_masks_bot_token_and_explains_bad_request(self) -> None:
        class FakeResponse:
            status_code = 400
            text = ""
            reason = "Bad Request"

            def json(self):
                return {"ok": False, "description": "Bad Request: chat not found"}

        class FakeSession:
            def post(self, url, json, timeout):
                self.url = url
                return FakeResponse()

        token = "8839205541:AAFCQmQOEQaVerySecretToken"
        client = app_module.TelegramClient()
        fake_session = FakeSession()
        client.session = fake_session

        with self.assertRaises(RuntimeError) as raised:
            client.send_message(token, "bad-chat", "hello")

        message = str(raised.exception)
        self.assertNotIn(token, message)
        self.assertNotIn("api.telegram.org", message)
        self.assertIn("Chat ID", message)
        self.assertIn("chat not found", message)
        self.assertIn(token, fake_session.url)

        self.assertIn(
            "机器人不能给另一个机器人发消息",
            app_module.telegram_error_hint("Forbidden: the bot can't send messages to bots"),
        )

    def test_template_test_push_uses_edited_template_and_target_chat(self) -> None:
        _, headers = self.login()
        with app_module.open_connection() as connection:
            app_module.save_settings(
                connection,
                {
                    "telegram_bot_token": "bot-token",
                    "telegram_chat_ids": "default-chat",
                },
            )

        class FakeTelegram:
            def __init__(self) -> None:
                self.sent: list[dict[str, object]] = []

            def send_message(self, token, chat_id, text, buttons=None) -> int:
                self.sent.append({"token": token, "chat_id": chat_id, "text": text, "buttons": buttons})
                return 8123

            def edit_message(self, token, chat_id, message_id, text, buttons=None) -> None:
                raise AssertionError("template test push must send a standalone message")

        engine = self.app.extensions["monitor_engine"]
        original_telegram = engine.telegram
        fake_telegram = FakeTelegram()
        try:
            engine.telegram = fake_telegram
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/api/template-test-push",
                headers=headers,
                base_url=BASE_URL,
                json={
                    "name": "HK & JP <VM>",
                    "monitor_url": "https://example.com/cart?gid=1&pid=9",
                    "target_keyword": "HK & JP",
                    "template_kind": "soldout",
                    "test_chat_ids": "custom-chat",
                    "restock_template": "restock {name}",
                    "soldout_template": "售罄 {name} {status} stock={stock} {keyword} {url}",
                    "button_1_text": "Open",
                    "button_1_url": "https://example.com/order",
                },
            )
        finally:
            engine.telegram = original_telegram

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["template_kind"], "soldout")
        self.assertEqual(payload["result"]["chat_count"], 1)
        self.assertEqual(fake_telegram.sent[0]["token"], "bot-token")
        self.assertEqual(fake_telegram.sent[0]["chat_id"], "custom-chat")
        self.assertIn("【模板测试】", fake_telegram.sent[0]["text"])
        self.assertIn("HK &amp; JP &lt;VM&gt;", fake_telegram.sent[0]["text"])
        self.assertIn("sold_out", fake_telegram.sent[0]["text"])
        self.assertIn("stock=0", fake_telegram.sent[0]["text"])
        self.assertEqual(fake_telegram.sent[0]["buttons"], [{"text": "Open", "url": "https://example.com/order"}])

    def test_message_template_values_escape_dynamic_html_for_telegram(self) -> None:
        values = app_module.message_template_values(
            {
                "name": "Geelinx & Sonic <JP>",
                "monitor_url": "https://www.geelinx.com/cart?fid=6&gid=12",
                "target_keyword": "Sonic & Kawasaki",
            },
            28,
        )

        self.assertEqual(values["name"], "Geelinx &amp; Sonic &lt;JP&gt;")
        self.assertEqual(values["url"], "https://www.geelinx.com/cart?fid=6&amp;gid=12")
        self.assertEqual(values["keyword"], "Sonic &amp; Kawasaki")
        self.assertEqual(values["stock"], "28")

    def test_task_payload_masks_stored_telegram_token_errors(self) -> None:
        token = "8839205541:AAFCQmQOEQaVerySecretToken"
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, restock_template, soldout_template,
                    enabled, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Sonic",
                    "https://example.com/cart?fid=6&gid=12",
                    "Sonic",
                    "{name}",
                    "{name} sold out",
                    1,
                    f"400 Client Error for url: https://api.telegram.org/bot{token}/sendMessage",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        payload = app_module.to_task_payload(row)
        self.assertNotIn(token, payload["last_error"])
        self.assertNotIn("api.telegram.org/bot883", payload["last_error"])
        self.assertNotIn("bot<hidden-token>", payload["last_error"])
        self.assertIn("Telegram sendMessage 失败", payload["last_error"])
        self.assertIn("Chat ID", payload["last_error"])

        self.assertEqual(payload["last_error_kind"], "telegram_error")

    def test_task_payload_classifies_cloudflare_errors(self) -> None:
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, restock_template, soldout_template,
                    enabled, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "HK-CMI",
                    "https://example.com/products",
                    "HK-CMI",
                    "{name}",
                    "{name} sold out",
                    1,
                    "catalog 浏览器被 Cloudflare 验证页拦截：https://example.com/products",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        payload = app_module.to_task_payload(row)
        self.assertEqual(payload["last_error_kind"], "cloudflare_challenge")
        self.assertIn("Cloudflare 验证页拦截", payload["last_error"])
        self.assertEqual(payload["last_error_detail"], "https://example.com/products")

    def test_task_payload_preserves_cloudflare_cooldown_details(self) -> None:
        timestamp = app_module.now_iso()
        cooldown_until = "2026-07-07T00:10:00+00:00"
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, restock_template, soldout_template,
                    enabled, last_error, blocked_count, last_blocked_at, cooldown_until, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Cooling",
                    "https://example.com/products",
                    "Cooling",
                    "{name}",
                    "{name} sold out",
                    1,
                    app_module.protected_source_cooldown_message(cooldown_until),
                    2,
                    timestamp,
                    cooldown_until,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        payload = app_module.to_task_payload(row)

        self.assertEqual(payload["last_error_kind"], "cloudflare_challenge")
        self.assertIn(cooldown_until, payload["last_error_detail"])
        self.assertIn("Webhook", payload["last_error_detail"])
        self.assertEqual(payload["blocked_count"], 2)
        self.assertEqual(payload["cooldown_until"], cooldown_until)

    def test_task_payload_classifies_browser_disconnect_errors(self) -> None:
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, restock_template, soldout_template,
                    enabled, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "JP.TYO.INTL.Sonic",
                    "https://example.com/products",
                    "Sonic",
                    "{name}",
                    "{name} sold out",
                    1,
                    "与页面的连接已断开。版本: 4.1.1.4",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        payload = app_module.to_task_payload(row)
        self.assertEqual(payload["last_error_kind"], "browser_connection")
        self.assertIn("与页面的连接已断开", payload["last_error"])
        self.assertEqual(payload["last_error_detail"], "与页面的连接已断开。版本: 4.1.1.4")

    def test_update_settings_rejects_debug_port_collisions(self) -> None:
        _, headers = self.login()

        same_port = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"monitor_debug_port": 9223, "test_debug_port": 9223},
        )
        self.assertEqual(same_port.status_code, 400)
        self.assertIn("不能重复", same_port.get_json()["message"])

        app_port_collision = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"monitor_debug_port": 7777, "test_debug_port": 9334},
        )
        self.assertEqual(app_port_collision.status_code, 400)
        self.assertIn("面板监听端口", app_port_collision.get_json()["message"])

        catalog_port_update = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"catalog_debug_port": 9446},
        )
        self.assertEqual(catalog_port_update.status_code, 200)
        self.assertTrue(catalog_port_update.get_json()["ok"])

    def test_firecrawl_settings_save_and_snapshot_masks_api_key(self) -> None:
        _, headers = self.login()
        secret = "fc-test-secret-1234567890"

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={
                "firecrawl_enabled": True,
                "firecrawl_api_url": "https://api.firecrawl.dev/",
                "firecrawl_api_key": secret,
                "firecrawl_timeout_seconds": 61,
                "firecrawl_max_age_ms": 0,
                "firecrawl_store_in_cache": False,
                "firecrawl_proxy_mode": "basic",
                "firecrawl_zero_data_retention": True,
                "firecrawl_use_for_monitor": False,
                "firecrawl_use_for_catalog": True,
                "firecrawl_catalog_limit": 51,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        payload = snapshot.get_json()
        self.assertTrue(payload["settings"]["firecrawl_enabled"])
        self.assertEqual(payload["settings"]["firecrawl_api_url"], "https://api.firecrawl.dev")
        self.assertEqual(payload["settings"]["firecrawl_api_key_masked"], app_module.mask_secret(secret))
        self.assertNotIn("firecrawl_api_key", payload["settings"])
        self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))
        self.assertEqual(payload["settings"]["firecrawl_timeout_seconds"], 61)
        self.assertEqual(payload["settings"]["firecrawl_catalog_limit"], 51)

    def test_scrapling_settings_save_and_snapshot(self) -> None:
        _, headers = self.login()

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={
                "scrapling_enabled": False,
                "scrapling_default_mode": "stealth",
                "scrapling_use_for_monitor": False,
                "scrapling_use_for_catalog": True,
                "scrapling_timeout_standard": 26,
                "scrapling_timeout_dynamic": 46,
                "scrapling_timeout_stealth": 76,
                "scrapling_domain_cooldown_standard": 1,
                "scrapling_domain_cooldown_dynamic": 61,
                "scrapling_domain_cooldown_stealth": 301,
                "scrapling_max_concurrency_standard": 4,
                "scrapling_max_concurrency_dynamic": 2,
                "scrapling_max_concurrency_stealth": 1,
                "scrapling_session_reuse": False,
                "scrapling_adaptive_selector": True,
                "scrapling_headless": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        payload = snapshot.get_json()
        settings = payload["settings"]
        self.assertFalse(settings["scrapling_enabled"])
        self.assertEqual(settings["scrapling_default_mode"], "stealth")
        self.assertFalse(settings["scrapling_use_for_monitor"])
        self.assertTrue(settings["scrapling_use_for_catalog"])
        self.assertEqual(settings["scrapling_timeout_standard"], 26)
        self.assertEqual(settings["scrapling_timeout_dynamic"], 46)
        self.assertEqual(settings["scrapling_timeout_stealth"], 76)
        self.assertEqual(settings["scrapling_domain_cooldown_standard"], 1)
        self.assertEqual(settings["scrapling_domain_cooldown_dynamic"], 61)
        self.assertEqual(settings["scrapling_domain_cooldown_stealth"], 301)
        self.assertEqual(settings["scrapling_max_concurrency_standard"], 4)
        self.assertEqual(settings["scrapling_max_concurrency_dynamic"], 2)
        self.assertEqual(settings["scrapling_max_concurrency_stealth"], 1)
        self.assertFalse(settings["scrapling_session_reuse"])
        self.assertTrue(settings["scrapling_adaptive_selector"])
        self.assertFalse(settings["scrapling_headless"])
        self.assertIn("scrapling_status", settings)
        self.assertIsInstance(settings["scrapling_status"].get("available"), bool)

    def test_scrapling_settings_test_endpoint_returns_safe_status(self) -> None:
        _, headers = self.login()

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/scrapling-test",
            headers=headers,
            base_url=BASE_URL,
            json={},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "Scrapling 检测完成。")
        result = payload["result"]
        self.assertIn("available", result)
        self.assertIn("status", result)
        self.assertIn("detail", result)
        self.assertIn("headed_detail", result)
        self.assertNotIn("api_key", json.dumps(payload, ensure_ascii=False).lower())

    def test_scrapling_invalid_mode_falls_back_to_standard(self) -> None:
        _, headers = self.login()
        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"scrapling_default_mode": "unknown-mode"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

        snapshot = self.client.get(
            f"{app_module.PORTAL_PATH}/api/snapshot",
            headers=self.browser_headers(),
            base_url=BASE_URL,
        )
        self.assertEqual(snapshot.get_json()["settings"]["scrapling_default_mode"], "standard")

    def test_firecrawl_settings_require_explicit_proxy_feature_flags(self) -> None:
        _, headers = self.login()

        blocked = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"firecrawl_proxy_mode": "auto"},
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("auto proxy", blocked.get_json()["message"])

        allowed = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"firecrawl_allow_auto_proxy": True, "firecrawl_proxy_mode": "auto"},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.get_json()["ok"])

    def test_firecrawl_settings_diagnostic_reports_success_and_masks_key(self) -> None:
        _, headers = self.login()
        secret = "fc-diagnostic-secret"
        calls: list[dict[str, object]] = []

        class FakeFirecrawlClient:
            def __init__(self, settings_payload: dict[str, object]) -> None:
                calls.append(dict(settings_payload))

            def scrape(self, url: str) -> app_module.FetchResult:
                self_url = url
                return app_module.FetchResult(
                    html="<html><body>ok</body></html>",
                    final_url=self_url,
                    status_code=200,
                    detail="ok",
                )

        original_client = app_module.FirecrawlClient
        app_module.FirecrawlClient = FakeFirecrawlClient
        try:
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/api/settings/firecrawl-test",
                headers=headers,
                base_url=BASE_URL,
                json={
                    "firecrawl_enabled": True,
                    "firecrawl_api_url": "https://api.firecrawl.dev/",
                    "firecrawl_api_key": secret,
                    "firecrawl_timeout_seconds": 33,
                    "firecrawl_max_age_ms": 0,
                    "firecrawl_store_in_cache": False,
                    "firecrawl_proxy_mode": "basic",
                    "firecrawl_zero_data_retention": False,
                },
            )
        finally:
            app_module.FirecrawlClient = original_client

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["status"], "ok")
        self.assertEqual(calls[0]["firecrawl_api_key"], secret)
        self.assertEqual(calls[0]["firecrawl_api_url"], "https://api.firecrawl.dev")
        self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))

    def test_firecrawl_settings_diagnostic_reports_auth_failure_without_leaking_key(self) -> None:
        _, headers = self.login()
        secret = "fc-bad-diagnostic-secret"

        class FakeFirecrawlClient:
            def __init__(self, settings_payload: dict[str, object]) -> None:
                self.settings_payload = settings_payload

            def scrape(self, url: str) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    status_code=401,
                    error_kind="firecrawl_auth_error",
                    detail=f"Firecrawl 认证失败，请检查 API Key。{self.settings_payload['firecrawl_api_key']}",
                )

        original_client = app_module.FirecrawlClient
        app_module.FirecrawlClient = FakeFirecrawlClient
        try:
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/api/settings/firecrawl-test",
                headers=headers,
                base_url=BASE_URL,
                json={
                    "firecrawl_enabled": True,
                    "firecrawl_api_url": "https://api.firecrawl.dev",
                    "firecrawl_api_key": secret,
                    "firecrawl_proxy_mode": "basic",
                },
            )
        finally:
            app_module.FirecrawlClient = original_client

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["status"], "failed")
        self.assertEqual(payload["result"]["error_kind"], "firecrawl_auth_error")
        self.assertIn("检查 API Key", payload["result"]["advice"])
        self.assertNotIn(secret, json.dumps(payload, ensure_ascii=False))

    def test_browser_fetcher_wraps_harness_success(self) -> None:
        class FakeHarness:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int]] = []

            def fetch_html(self, url, timeout_seconds):
                self.calls.append((url, timeout_seconds))
                return "<html>HK-CMI <strong>9</strong></html>"

            def rebuild(self, reason):
                raise AssertionError("rebuild should not be called")

        harness = FakeHarness()
        fetcher = app_module.BrowserFetcher(harness)
        result = fetcher.fetch("https://example.com/products", 25)

        self.assertEqual(result.html, "<html>HK-CMI <strong>9</strong></html>")
        self.assertEqual(result.final_url, "https://example.com/products")
        self.assertEqual(result.error_kind, "")
        self.assertEqual(harness.calls, [("https://example.com/products", 25)])

    def test_static_http_fetcher_returns_html_with_browser_headers(self) -> None:
        class FakeResponse:
            status_code = 200
            url = "https://example.com/products"
            text = "<html><title>Products</title><body>HK-CMI <strong>11</strong></body></html>"

        class FakeSession:
            def __init__(self) -> None:
                self.headers: dict[str, str] = {}
                self.timeout = None

            def get(self, url, headers=None, timeout=None, allow_redirects=None):
                self.headers = headers or {}
                self.timeout = timeout
                self.allow_redirects = allow_redirects
                return FakeResponse()

        session = FakeSession()
        fetcher = app_module.StaticHttpFetcher(session)
        result = fetcher.fetch("https://example.com/products", 25)

        self.assertIn("HK-CMI", result.html)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.error_kind, "")
        self.assertIn("Mozilla/5.0", session.headers["User-Agent"])
        self.assertEqual(session.timeout, 25)
        self.assertTrue(session.allow_redirects)

    def test_static_http_fetcher_classifies_timeout(self) -> None:
        class TimeoutSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=None):
                raise app_module.requests.Timeout("slow")

        result = app_module.StaticHttpFetcher(TimeoutSession()).fetch("https://example.com/products", 10)

        self.assertEqual(result.error_kind, "timeout")
        self.assertIn("请求超时", result.detail)

    def test_static_http_fetcher_classifies_cloudflare_challenge(self) -> None:
        class FakeResponse:
            status_code = 403
            url = "https://example.com/products"
            text = "<html><title>Just a moment...</title><body><div id=\"cf-turnstile\">Cloudflare</div></body></html>"

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=None):
                return FakeResponse()

        result = app_module.StaticHttpFetcher(FakeSession()).fetch("https://example.com/products", 10)

        self.assertEqual(result.error_kind, "cloudflare_challenge")
        self.assertIn("Cloudflare 验证页拦截", result.detail)

    def test_static_http_fetcher_classifies_http_errors(self) -> None:
        class FakeResponse:
            status_code = 429
            url = "https://example.com/products"
            text = "<html><title>Too Many Requests</title><body>rate limited</body></html>"

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=None):
                return FakeResponse()

        result = app_module.StaticHttpFetcher(FakeSession()).fetch("https://example.com/products", 10)

        self.assertEqual(result.error_kind, "http_error")
        self.assertIn("HTTP 429", result.detail)

    def firecrawl_settings(self, **overrides) -> dict[str, object]:
        settings = {
            "firecrawl_enabled": True,
            "firecrawl_api_url": "https://api.firecrawl.dev",
            "firecrawl_api_key": "fc-secret-token",
            "firecrawl_timeout_seconds": 60,
            "firecrawl_max_age_ms": 0,
            "firecrawl_store_in_cache": False,
            "firecrawl_proxy_mode": "basic",
            "firecrawl_zero_data_retention": False,
        }
        settings.update(overrides)
        return settings

    def scrapling_settings(self, **overrides) -> dict[str, object]:
        settings = {
            "scrapling_enabled": True,
            "scrapling_timeout_standard": 25,
            "scrapling_timeout_dynamic": 45,
            "scrapling_timeout_stealth": 75,
            "scrapling_use_for_monitor": True,
            "scrapling_use_for_catalog": True,
        }
        settings.update(overrides)
        return settings

    def test_firecrawl_fetcher_success_uses_raw_html_and_cache_controls(self) -> None:
        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "data": {
                        "rawHtml": "<html><title>Raw</title><body>RAW HK stock 9</body></html>",
                        "html": "<html><title>Html</title><body>HTML fallback</body></html>",
                        "markdown": "# Markdown fallback",
                        "metadata": {
                            "statusCode": 200,
                            "url": "https://merchant.example.com/final",
                        },
                    }
                }

        class FakeSession:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse()

        session = FakeSession()
        fetcher = app_module.FirecrawlFetcher(self.firecrawl_settings(), app_module.FirecrawlClient(self.firecrawl_settings(), session))
        result = fetcher.fetch("https://merchant.example.com/products", 25)

        self.assertIn("RAW HK stock 9", result.html)
        self.assertNotIn("HTML fallback", result.html)
        self.assertEqual(result.final_url, "https://merchant.example.com/final")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.error_kind, "")
        self.assertEqual(session.calls[0]["url"], "https://api.firecrawl.dev/v2/scrape")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer fc-secret-token")
        self.assertEqual(session.calls[0]["timeout"], 60)
        sent_payload = session.calls[0]["json"]
        self.assertEqual(sent_payload["formats"], ["rawHtml", "html", "markdown", "links"])
        self.assertEqual(sent_payload["maxAge"], 0)
        self.assertFalse(sent_payload["storeInCache"])
        self.assertFalse(sent_payload["zeroDataRetention"])
        self.assertEqual(sent_payload["proxy"], "basic")

    def test_firecrawl_map_returns_links_with_search_and_limit(self) -> None:
        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "data": {
                        "links": [
                            "https://merchant.example.com/cart.php?gid=1",
                            {"url": "https://merchant.example.com/store/hk-vps"},
                            {"href": "https://merchant.example.com/login"},
                        ],
                        "url": "https://merchant.example.com",
                    }
                }

        class FakeSession:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
                return FakeResponse()

        session = FakeSession()
        client = app_module.FirecrawlClient(self.firecrawl_settings(), session)
        result = client.map("https://merchant.example.com", "hk vps", 12)

        self.assertEqual(result.error_kind, "")
        self.assertEqual(session.calls[0]["url"], "https://api.firecrawl.dev/v2/map")
        self.assertEqual(session.calls[0]["json"]["search"], "hk vps")
        self.assertEqual(session.calls[0]["json"]["limit"], 12)
        self.assertEqual(session.calls[0]["json"]["sitemap"], "include")
        self.assertEqual(
            app_module.parse_firecrawl_map_links(result),
            [
                "https://merchant.example.com/cart.php?gid=1",
                "https://merchant.example.com/store/hk-vps",
                "https://merchant.example.com/login",
            ],
        )

    def test_merchant_import_firecrawl_map_discovers_scrapes_and_creates_tasks(self) -> None:
        engine = self.app.extensions["monitor_engine"]

        class ExplodingCatalogBrowser:
            def fetch_html(self, url, timeout_seconds):
                raise AssertionError("firecrawl_map discovery should not fetch the entry page with local browser")

            def rebuild(self, reason):
                raise AssertionError("firecrawl_map discovery should not rebuild local browser")

        class FakeFirecrawlCatalogProvider:
            map_calls: list[dict[str, object]] = []
            scrape_calls: list[str] = []

            def __init__(self, settings_payload, client=None) -> None:
                self.settings_payload = settings_payload

            def map(self, url: str, search: str = "", limit: int = 50) -> app_module.FetchResult:
                self.__class__.map_calls.append({"url": url, "search": search, "limit": limit})
                return app_module.FetchResult(
                    html=json.dumps(
                        {
                            "links": [
                                "https://merchant.example.com/store/hk-vps",
                                "https://merchant.example.com/cart.php?gid=8",
                                "https://merchant.example.com/login",
                                "https://other.example.com/store/outside",
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    final_url=url,
                    detail="ok",
                )

            def scrape(self, url: str) -> app_module.FetchResult:
                self.__class__.scrape_calls.append(url)
                if url.endswith("/store/hk-vps"):
                    html = """
                    <html><body>
                      <section class="product-card">
                        <h3>HK Premium VPS</h3>
                        <p>$9.90/mo</p>
                        <a href="/cart.php?a=add&pid=88">Order Now</a>
                      </section>
                    </body></html>
                    """
                elif "cart.php?gid=8" in url:
                    html = """
                    <html><body>
                      <div class="package">
                        <h3>SG Lite VPS</h3>
                        <button disabled>Out of Stock</button>
                      </div>
                    </body></html>
                    """
                else:
                    html = "<html><body>ignored</body></html>"
                return app_module.FetchResult(html=html, final_url=url, status_code=200, detail="ok")

        original_browser = engine.catalog_browser
        original_provider = app_module.FirecrawlCatalogProvider
        engine.catalog_browser = ExplodingCatalogBrowser()
        app_module.FirecrawlCatalogProvider = FakeFirecrawlCatalogProvider
        try:
            result = engine.import_merchant_source(
                "https://merchant.example.com/pricing",
                "",
                "IDC",
                {**engine.get_runtime_settings(), **self.firecrawl_settings(), "firecrawl_catalog_limit": 20},
                auto_promote=True,
                catalog_options={
                    "catalog_discovery_strategy": "firecrawl_map",
                    "catalog_scrape_strategy": "firecrawl",
                    "default_fetch_strategy": "generic_pricing_table",
                    "default_extractor": "generic_pricing_table",
                    "search_keyword": "vps",
                    "max_discovered_urls": 10,
                    "max_import_items": 10,
                    "include_sold_out": True,
                },
            )
        finally:
            engine.catalog_browser = original_browser
            app_module.FirecrawlCatalogProvider = original_provider

        self.assertEqual(result.scanned_count, 2)
        self.assertEqual(result.promoted_count, 2)
        self.assertEqual(FakeFirecrawlCatalogProvider.map_calls, [{"url": "https://merchant.example.com/pricing", "search": "vps", "limit": 10}])
        self.assertEqual(
            FakeFirecrawlCatalogProvider.scrape_calls,
            ["https://merchant.example.com/store/hk-vps", "https://merchant.example.com/cart.php?gid=8"],
        )
        self.assertEqual(sorted(item["title"] for item in result.items), ["HK Premium VPS", "SG Lite VPS"])

        with app_module.open_connection() as connection:
            task_rows = connection.execute(
                "SELECT fetch_strategy, source_config FROM tasks ORDER BY name"
            ).fetchall()
        self.assertEqual([row["fetch_strategy"] for row in task_rows], ["generic_pricing_table", "generic_pricing_table"])
        configs = [json.loads(row["source_config"]) for row in task_rows]
        self.assertTrue(all(config["catalog_backend"] == "firecrawl" for config in configs))
        self.assertTrue(all(config["catalog_discovery_source"] == "firecrawl_map" for config in configs))

    def test_firecrawl_fetcher_classifies_http_errors(self) -> None:
        class FakeResponse:
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

            def json(self):
                return {"success": False}

        class FakeSession:
            def __init__(self, status_code: int) -> None:
                self.status_code = status_code

            def post(self, url, headers=None, json=None, timeout=None):
                return FakeResponse(self.status_code)

        cases = {
            401: "firecrawl_auth_error",
            403: "firecrawl_permission_error",
            402: "firecrawl_credit_required",
            429: "firecrawl_rate_limited",
            503: "firecrawl_upstream_error",
        }
        for status_code, expected_kind in cases.items():
            with self.subTest(status_code=status_code):
                client = app_module.FirecrawlClient(self.firecrawl_settings(), FakeSession(status_code))
                result = app_module.FirecrawlFetcher(self.firecrawl_settings(), client).fetch("https://example.com", 25)
                self.assertEqual(result.error_kind, expected_kind)
                self.assertEqual(result.status_code, status_code)

        class ZdrResponse:
            status_code = 403

            def json(self):
                return {"success": False, "error": "Zero Data Retention (ZDR) is not enabled for your team."}

        class ZdrSession:
            def post(self, url, headers=None, json=None, timeout=None):
                return ZdrResponse()

        zdr_result = app_module.FirecrawlClient(self.firecrawl_settings(firecrawl_zero_data_retention=True), ZdrSession()).scrape("https://example.com")
        self.assertEqual(zdr_result.error_kind, "firecrawl_zdr_not_enabled")
        self.assertIn("关闭 zeroDataRetention", zdr_result.detail)

    def test_firecrawl_fetcher_classifies_timeout_and_cloudflare(self) -> None:
        class TimeoutSession:
            def post(self, url, headers=None, json=None, timeout=None):
                raise app_module.requests.Timeout("slow")

        timeout_result = app_module.FirecrawlClient(self.firecrawl_settings(), TimeoutSession()).scrape("https://example.com")
        self.assertEqual(timeout_result.error_kind, "timeout")

        class CloudflareResponse:
            status_code = 200

            def json(self):
                return {
                    "data": {
                        "rawHtml": "<html><title>Just a moment...</title><body><div id=\"cf-turnstile\">Cloudflare</div></body></html>",
                        "metadata": {"statusCode": 403, "sourceURL": "https://example.com/protected"},
                    }
                }

        class CloudflareSession:
            def post(self, url, headers=None, json=None, timeout=None):
                return CloudflareResponse()

        challenge_result = app_module.FirecrawlClient(self.firecrawl_settings(), CloudflareSession()).scrape("https://example.com")
        self.assertEqual(challenge_result.error_kind, "cloudflare_challenge")
        self.assertEqual(challenge_result.final_url, "https://example.com/protected")

    def test_firecrawl_fetcher_masks_api_key_in_request_errors(self) -> None:
        class FailingSession:
            def post(self, url, headers=None, json=None, timeout=None):
                raise app_module.requests.RequestException("boom fc-secret-token leak")

        result = app_module.FirecrawlClient(self.firecrawl_settings(), FailingSession()).scrape("https://example.com")

        self.assertEqual(result.error_kind, "firecrawl_request_error")
        self.assertNotIn("fc-secret-token", result.detail)
        self.assertIn("<hidden-firecrawl-key>", result.detail)

    def test_firecrawl_strategy_parses_stock_without_browser(self) -> None:
        class FakeFirecrawlFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="<html><body><section>HK-CMI <a>Order Now</a></section></body></html>",
                    final_url=url,
                    status_code=200,
                    detail="ok",
                )

        class ExplodingHarness:
            def fetch_html(self, url, timeout_seconds):
                raise AssertionError("firecrawl strategy must not use local browser")

        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                firecrawl_fetcher=FakeFirecrawlFetcher(),
            )
            result = engine.scrape_task(
                {
                    "name": "HK-CMI",
                    "monitor_url": "https://merchant.example.com/products",
                    "target_keyword": "HK-CMI",
                    "fetch_strategy": "firecrawl",
                    "source_config": "{}",
                },
                {
                    "request_timeout_seconds": 25,
                    **self.firecrawl_settings(),
                },
                use_test_browser=True,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 1)
        self.assertEqual(result.error_kind, "")

    def test_legacy_firecrawl_monitor_uses_scrapling_not_external_backend(self) -> None:
        class ExplodingFirecrawlFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                raise AssertionError("scheduled monitor must not call Firecrawl")

        class FakeScraplingResponse:
            url = "https://merchant.example.com/products"
            status = 200
            html_content = "<html><body><section>Credit Safe VM <a>Order Now</a></section></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse()

        scrapling_client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                firecrawl_fetcher=ExplodingFirecrawlFetcher(),
                scrapling_client=scrapling_client,
            )
            result = engine.scrape_task(
                {
                    "name": "Credit Safe VM",
                    "monitor_url": "https://merchant.example.com/products",
                    "target_keyword": "Credit Safe VM",
                    "fetch_strategy": "firecrawl",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25, **self.firecrawl_settings(firecrawl_use_for_monitor=False)},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 1)
        self.assertEqual(result.error_kind, "")
        self.assertEqual(result.backend_used, "scrapling_stealth")
        self.assertEqual(scrapling_client.calls, ["stealth"])
        self.assertEqual([attempt.backend for attempt in result.fetch_attempts or []], ["scrapling_stealth"])

    def test_firecrawl_credit_error_enters_long_cooldown(self) -> None:
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, fetch_strategy, restock_template, soldout_template,
                    enabled, last_stock, last_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Credit Limited VM",
                    "https://merchant.example.com/products",
                    "Credit Limited VM",
                    "firecrawl",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    2,
                    "in_stock",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task_id = cursor.lastrowid
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

        result = app_module.ScrapeResult(
            stock=None,
            fragment="",
            detail="Firecrawl 额度不足或需要付费额度；尝试后端：firecrawl:failed/firecrawl_credit_required",
            used_test_browser=False,
            error_kind="firecrawl_credit_required",
            backend_used="firecrawl",
            fetch_attempts=[
                app_module.FetchAttempt(
                    backend="firecrawl",
                    started_at=timestamp,
                    ended_at=timestamp,
                    status="failed",
                    error_kind="firecrawl_credit_required",
                    detail="credit required",
                    final_url="https://merchant.example.com/products",
                )
            ],
        )

        engine = self.app.extensions["monitor_engine"]
        processed = engine.apply_task_result(
            task,
            {"telegram_bot_token": "", "telegram_chat_ids": "", **self.firecrawl_settings()},
            result,
            checked_at=app_module.parse_iso_datetime(timestamp),
        )

        self.assertFalse(processed)
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 2)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["last_fetch_backend"], "firecrawl")
        self.assertTrue(row["cooldown_until"])
        checked_at = app_module.parse_iso_datetime(row["last_checked_at"])
        cooldown_until = app_module.parse_iso_datetime(row["cooldown_until"])
        self.assertIsNotNone(checked_at)
        self.assertIsNotNone(cooldown_until)
        self.assertGreaterEqual((cooldown_until - checked_at).total_seconds(), 6 * 60 * 60 - 2)

        with app_module.open_connection() as connection:
            cooling_task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        cooldown_result = engine.scrape_task(
            cooling_task,
            {"request_timeout_seconds": 25, **self.firecrawl_settings(firecrawl_use_for_monitor=True)},
            use_test_browser=False,
        )
        self.assertEqual(cooldown_result.error_kind, "firecrawl_credit_required")
        self.assertTrue(cooldown_result.cooldown_skip)
        self.assertIn("已暂停外部抓取", cooldown_result.detail)

    def test_task_stock_check_updates_inventory_without_telegram_push(self) -> None:
        _, headers = self.login()
        create_response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/tasks",
            headers=headers,
            base_url=BASE_URL,
            json={
                "name": "HKG.AS3.Pro.TINY",
                "group_name": "DMIT",
                "monitor_url": "https://merchant.example.com/cart.php?region=hong-kong&generation=as3",
                "target_keyword": "HKG.AS3.Pro.TINY",
                "fetch_strategy": "firecrawl",
                "restock_template": app_module.DEFAULT_RESTOCK_TEMPLATE,
                "soldout_template": app_module.DEFAULT_SOLDOUT_TEMPLATE,
                "enabled": True,
            },
        )
        self.assertEqual(create_response.status_code, 200)
        task_id = create_response.get_json()["task_id"]

        class FakeFirecrawlFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="<main><plan-card>HKG.AS3.Pro.TINY <a>Add to Cart</a></plan-card></main>",
                    final_url=url,
                    status_code=200,
                    detail="ok",
                )

        class FailingTelegram:
            def send_message(self, *args, **kwargs):
                raise AssertionError("stock check must not send Telegram messages")

            def edit_message(self, *args, **kwargs):
                raise AssertionError("stock check must not edit Telegram messages")

        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        original_telegram = engine.telegram
        try:
            engine.fetcher_selector = app_module.FetcherSelector(firecrawl_fetcher=FakeFirecrawlFetcher())
            engine.telegram = FailingTelegram()
            response = self.client.post(
                f"{app_module.PORTAL_PATH}/api/tasks/{task_id}/check",
                headers=headers,
                base_url=BASE_URL,
                json={},
            )
        finally:
            engine.fetcher_selector = original_selector
            engine.telegram = original_telegram

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["stock"], 1)
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT last_stock, last_state, last_error FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 1)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["last_error"], "")

    def test_external_input_fetch_strategy_does_not_use_browser(self) -> None:
        class ExplodingHarness:
            def fetch_html(self, url, timeout_seconds):
                raise AssertionError("manual/webhook strategy must not fetch target pages")

            def rebuild(self, reason):
                raise AssertionError("manual/webhook strategy must not rebuild browsers")

        fetcher = app_module.FetcherSelector().select({"fetch_strategy": "manual"}, ExplodingHarness())
        result = fetcher.fetch("https://example.com/products", 25)

        self.assertEqual(result.error_kind, "manual_pending")
        self.assertIn("不会请求目标页面", result.detail)

    def test_scrape_task_static_http_strategy_parses_stock(self) -> None:
        class FakeResponse:
            status_code = 200
            url = "https://example.com/cart.php?gid=12"
            text = "Kawasaki <section>Available</section><span hidden>x</span><strong>17</strong>"

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=None):
                return FakeResponse()

        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(app_module.StaticHttpFetcher(FakeSession()))
            result = engine.scrape_task(
                {
                    "name": "Kawasaki",
                    "monitor_url": "https://example.com/cart.php?gid=12",
                    "target_keyword": "Kawasaki",
                    "fetch_strategy": "static_http",
                },
                {"request_timeout_seconds": 25},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 17)
        self.assertIn("Available", result.fragment)
        self.assertEqual(result.error_kind, "")

    def test_scrapling_fetcher_standard_success_returns_html(self) -> None:
        class FakeScraplingResponse:
            url = "https://example.com/products"
            status = 200
            html_content = "<html><body>Tokyo VPS <a>Order Now</a></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, int]] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append((mode, url, timeout_seconds))
                return FakeScraplingResponse()

        client = FakeScraplingClient()
        fetcher = app_module.ScraplingFetcher(self.scrapling_settings(), "standard", client)
        result = fetcher.fetch("https://example.com/products", 12)

        self.assertEqual(result.error_kind, "")
        self.assertIn("Tokyo VPS", result.html)
        self.assertEqual(result.detail, "Scrapling standard ok")
        self.assertEqual(client.calls, [("standard", "https://example.com/products", 25)])

    def test_monitor_url_for_fetch_keeps_idc_cart_category_url_by_default(self) -> None:
        task = {
            "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
            "target_keyword": "DMIT Hong Kong HKG.AS3.Pro.TINY",
            "fetch_strategy": "scrapling_adaptive",
        }

        fetch_url = app_module.monitor_url_for_fetch(task)

        self.assertEqual(fetch_url, task["monitor_url"])

    def test_monitor_url_for_fetch_adds_idc_product_query_when_enabled(self) -> None:
        task = {
            "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
            "target_keyword": "DMIT Hong Kong HKG.AS3.Pro.TINY",
            "fetch_strategy": "scrapling_adaptive",
            "source_config": {"enable_product_query": True},
        }

        fetch_url = app_module.monitor_url_for_fetch(task)

        self.assertIn("product=hkg.as3.pro.tiny", fetch_url)
        self.assertIn("region=hong-kong", fetch_url)

    def test_fetch_cache_key_preserves_idc_cart_category_url_by_default(self) -> None:
        base_url = "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3"
        tiny_key = app_module.fetch_cache_key(
            {
                "monitor_url": base_url,
                "target_keyword": "HKG.AS3.Pro.TINY",
                "fetch_strategy": "scrapling_adaptive",
            }
        )
        starter_key = app_module.fetch_cache_key(
            {
                "monitor_url": base_url,
                "target_keyword": "HKG.AS3.Pro.STARTER",
                "fetch_strategy": "scrapling_adaptive",
            }
        )

        self.assertEqual(tiny_key, f"scrapling_adaptive|{base_url}")
        self.assertEqual(starter_key, f"scrapling_adaptive|{base_url}")

    def test_fetch_cache_key_separates_idc_cart_products_when_query_enabled(self) -> None:
        base_url = "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3"
        tiny_key = app_module.fetch_cache_key(
            {
                "monitor_url": base_url,
                "target_keyword": "HKG.AS3.Pro.TINY",
                "fetch_strategy": "scrapling_adaptive",
                "source_config": {"enable_product_query": True},
            }
        )
        starter_key = app_module.fetch_cache_key(
            {
                "monitor_url": base_url,
                "target_keyword": "HKG.AS3.Pro.STARTER",
                "fetch_strategy": "scrapling_adaptive",
                "source_config": {"enable_product_query": True},
            }
        )

        self.assertIn("product=hkg.as3.pro.tiny", tiny_key)
        self.assertIn("product=hkg.as3.pro.starter", starter_key)
        self.assertNotEqual(tiny_key, starter_key)

    def test_scrapling_browser_kwargs_use_system_chromium_path(self) -> None:
        original_find_browser_binary = app_module.find_browser_binary
        try:
            app_module.find_browser_binary = lambda: "/usr/bin/chromium"
            kwargs = app_module.ScraplingFetcher(self.scrapling_settings(), "stealth").browser_kwargs(75)
        finally:
            app_module.find_browser_binary = original_find_browser_binary

        self.assertEqual(kwargs["executable_path"], "/usr/bin/chromium")
        self.assertIs(kwargs["headless"], True)
        self.assertIn("--no-sandbox", kwargs["extra_flags"])
        self.assertIs(kwargs["solve_cloudflare"], True)

    def test_scrapling_browser_kwargs_can_use_headed_browser(self) -> None:
        original_find_browser_binary = app_module.find_browser_binary
        original_ensure_display = app_module.ensure_scrapling_display_for_headed
        try:
            app_module.find_browser_binary = lambda: "/usr/bin/chromium"
            app_module.ensure_scrapling_display_for_headed = lambda: ":99"
            kwargs = app_module.ScraplingFetcher(
                self.scrapling_settings(scrapling_headless=False),
                "stealth",
            ).browser_kwargs(75)
        finally:
            app_module.find_browser_binary = original_find_browser_binary
            app_module.ensure_scrapling_display_for_headed = original_ensure_display

        self.assertIs(kwargs["headless"], False)
        self.assertIn("--window-size=1720,1120", kwargs["extra_flags"])
        self.assertEqual(kwargs["executable_path"], "/usr/bin/chromium")

    def test_scrape_task_scrapling_standard_strategy_parses_stock(self) -> None:
        class FakeScraplingResponse:
            url = "https://example.com/products"
            status = 200
            html_content = "<html><body><section>Osaka VPS <a>Order Now</a><strong>库存 8</strong></section></body></html>"

        class FakeScraplingClient:
            def fetch(self, mode: str, url: str, timeout_seconds: int):
                return FakeScraplingResponse()

        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=FakeScraplingClient())
            result = engine.scrape_task(
                {
                    "name": "Osaka VPS",
                    "monitor_url": "https://example.com/products",
                    "target_keyword": "Osaka VPS",
                    "fetch_strategy": "scrapling_standard",
                },
                {"request_timeout_seconds": 25, **self.scrapling_settings()},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 8)
        self.assertEqual(result.backend_used, "scrapling_standard")
        self.assertEqual([attempt.backend for attempt in result.fetch_attempts or []], ["scrapling_standard"])

    def test_scrape_task_keeps_dmit_category_url_before_scrapling_fetch(self) -> None:
        class FakeScraplingResponse:
            status = 200
            html_content = "<html><body><section>HKG.AS3.Pro.TINY <a>Order Now</a></section></body></html>"

            def __init__(self, url: str) -> None:
                self.url = url

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.urls.append(url)
                return FakeScraplingResponse(url)

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            result = engine.scrape_task(
                {
                    "name": "DMIT Hong Kong HKG.AS3.Pro.TINY",
                    "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
                    "target_keyword": "HKG.AS3.Pro.TINY",
                    "fetch_strategy": "scrapling_standard",
                },
                {"request_timeout_seconds": 25, **self.scrapling_settings()},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 1)
        self.assertEqual(client.urls, ["https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3"])

    def test_scrapling_adaptive_does_not_use_public_pricing_reference_for_dmit_cart(self) -> None:
        class FakeScraplingResponse:
            url = "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3"
            status = 403
            html_content = "<html><title>Just a moment...</title><body><div>cf-turnstile</div></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse()

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            result = engine.scrape_task(
                {
                    "name": "DMIT Hong Kong HKG.AS3.Pro.TINY",
                    "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
                    "target_keyword": "HKG.AS3.Pro.TINY",
                    "fetch_strategy": "scrapling_adaptive",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25, **self.scrapling_settings()},
                use_test_browser=True,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertIsNone(result.stock)
        self.assertEqual(client.calls, ["standard", "dynamic", "stealth"])
        self.assertEqual(
            [attempt.backend for attempt in result.fetch_attempts or []],
            ["scrapling_standard", "scrapling_dynamic", "scrapling_stealth"],
        )
        self.assertFalse(any("public" in attempt.backend for attempt in result.fetch_attempts or []))
        self.assertNotIn("public_pricing", (result.detail or "").lower())

    def test_dmit_protected_cooldown_is_not_bypassed_by_pricing_reference(self) -> None:
        class FakeScraplingResponse:
            url = "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3"
            status = 403
            html_content = "<html><title>Just a moment...</title><body>cf-turnstile</body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse()

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            result = engine.scrape_task(
                {
                    "name": "DMIT Hong Kong HKG.AS3.Pro.TINY",
                    "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
                    "target_keyword": "HKG.AS3.Pro.TINY",
                    "fetch_strategy": "scrapling_adaptive",
                    "source_config": "{}",
                    "cooldown_until": (app_module.now_utc() + app_module.timedelta(minutes=10)).isoformat(timespec="seconds"),
                    "last_error": app_module.protected_source_cooldown_message("future"),
                },
                {"request_timeout_seconds": 25, **self.scrapling_settings()},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertIsNone(result.stock)
        self.assertTrue(result.cooldown_skip)
        self.assertEqual(result.error_kind, "cloudflare_challenge")
        self.assertEqual(client.calls, [])

    def test_dmit_lax_cart_out_of_stock_card_parses_sold_out(self) -> None:
        class FakeScraplingResponse:
            url = "https://www.dmit.io/cart.php?region=los-angeles&network=premium&generation=as3"
            status = 200
            html_content = """
            <html><body>
              <section class="product-card">
                <h2>LAX.AS3.Pro.TINY</h2>
                <span>Out of Stock</span>
                <button disabled>Out of Stock</button>
              </section>
              <section class="product-card">
                <h2>LAX.AS3.Pro.STARTER</h2>
                <a>Order Now</a>
              </section>
            </body></html>
            """

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.urls.append(url)
                return FakeScraplingResponse()

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            result = engine.scrape_task(
                {
                    "name": "LAX.AS3.Pro.TINY",
                    "monitor_url": "https://www.dmit.io/cart.php?region=los-angeles&network=premium&generation=as3",
                    "target_keyword": "LAX.AS3.Pro.TINY",
                    "fetch_strategy": "scrapling_standard",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25, **self.scrapling_settings()},
                use_test_browser=True,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 0)
        self.assertEqual(client.urls, ["https://www.dmit.io/cart.php?region=los-angeles&network=premium&generation=as3"])

    def test_dmit_hkg_cart_orderable_card_parses_in_stock(self) -> None:
        class FakeScraplingResponse:
            url = "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3"
            status = 200
            html_content = """
            <html><body>
              <section class="product-card">
                <h2>HKG.AS3.Pro.TINY</h2>
                <span>$ 6.90 USD</span>
                <a href="/cart.php?a=confproduct&i=1">Order Now</a>
              </section>
              <section class="product-card">
                <h2>HKG.AS3.Pro.MINI</h2>
                <button disabled>Out of Stock</button>
              </section>
            </body></html>
            """

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.urls.append(url)
                return FakeScraplingResponse()

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            result = engine.scrape_task(
                {
                    "name": "DMIT Hong Kong HKG.AS3.Pro.TINY",
                    "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
                    "target_keyword": "HKG.AS3.Pro.TINY",
                    "fetch_strategy": "scrapling_standard",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25, **self.scrapling_settings()},
                use_test_browser=True,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 1)
        self.assertEqual(client.urls, ["https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3"])

    def test_scrapling_adaptive_escalates_after_cloudflare_challenge(self) -> None:
        class FakeScraplingResponse:
            def __init__(self, mode: str) -> None:
                self.url = "https://example.com/products"
                self.status = 200
                if mode == "standard":
                    self.html_content = "<html><title>Just a moment...</title><body>cloudflare</body></html>"
                else:
                    self.html_content = "<html><body><section>Seoul VPS <a>Order Now</a></section></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse(mode)

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            result = engine.scrape_task(
                {
                    "name": "Seoul VPS",
                    "monitor_url": "https://example.com/products",
                    "target_keyword": "Seoul VPS",
                    "fetch_strategy": "scrapling_adaptive",
                },
                {"request_timeout_seconds": 25, **self.scrapling_settings()},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 1)
        self.assertEqual(client.calls, ["standard", "dynamic"])
        self.assertEqual(result.backend_used, "scrapling_dynamic")
        self.assertEqual([attempt.backend for attempt in result.fetch_attempts or []], ["scrapling_standard", "scrapling_dynamic"])

    def test_scrapling_stealth_challenge_failure_enters_protected_cooldown(self) -> None:
        class FakeScraplingResponse:
            url = "https://example.com/products"
            status = 200
            html_content = "<html><title>Just a moment...</title><body>Checking your browser before accessing Cloudflare.</body></html>"

        class FakeScraplingClient:
            def fetch(self, mode: str, url: str, timeout_seconds: int):
                return FakeScraplingResponse()

        result = app_module.ScraplingFetcher(self.scrapling_settings(), "stealth", FakeScraplingClient()).fetch(
            "https://example.com/products",
            75,
        )

        self.assertEqual(result.error_kind, "cloudflare_challenge")
        self.assertIn("Scrapling 高兼容已尝试处理 Cloudflare managed challenge", result.detail)
        self.assertGreater(
            app_module.scrapling_domain_cooldown_seconds("scrapling_stealth", result.error_kind, self.scrapling_settings()),
            0,
        )

    def test_scrapling_fetcher_unavailable_is_user_readable(self) -> None:
        class MissingScraplingClient:
            def fetch(self, mode: str, url: str, timeout_seconds: int):
                raise ImportError("curl_cffi")

        result = app_module.ScraplingFetcher(self.scrapling_settings(), "dynamic", MissingScraplingClient()).fetch(
            "https://example.com/products",
            45,
        )

        self.assertEqual(result.error_kind, "scrapling_unavailable")
        self.assertIn("依赖未安装", result.detail)

    def test_static_then_firecrawl_monitor_uses_scrapling_without_firecrawl(self) -> None:
        class FailingStaticFetcher:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                self.calls += 1
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    error_kind="empty_response",
                    detail="static returned no useful content",
                )

        class SuccessfulFirecrawlFetcher:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                self.calls += 1
                return app_module.FetchResult(
                    html="<html><body><section>HK-CMI <a>Order Now</a></section></body></html>",
                    final_url=url,
                    status_code=200,
                    detail="ok",
                )

        class FakeScraplingResponse:
            url = "https://merchant.example.com/products"
            status = 200
            html_content = "<html><body><section>HK-CMI <a>Order Now</a></section></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse()

        static_fetcher = FailingStaticFetcher()
        firecrawl_fetcher = SuccessfulFirecrawlFetcher()
        scrapling_client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                static_http_fetcher=static_fetcher,
                firecrawl_fetcher=firecrawl_fetcher,
                scrapling_client=scrapling_client,
            )
            result = engine.scrape_task(
                {
                    "name": "HK-CMI",
                    "monitor_url": "https://merchant.example.com/products",
                    "target_keyword": "HK-CMI",
                    "fetch_strategy": "static_then_firecrawl",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25, **self.firecrawl_settings(), "firecrawl_use_for_monitor": True},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 1)
        self.assertEqual(static_fetcher.calls, 0)
        self.assertEqual(firecrawl_fetcher.calls, 0)
        self.assertEqual(scrapling_client.calls, ["standard"])
        self.assertEqual(result.backend_used, "scrapling_standard")
        self.assertEqual([attempt.backend for attempt in result.fetch_attempts or []], ["scrapling_standard"])

    def test_firecrawl_then_browser_monitor_uses_scrapling_without_browser(self) -> None:
        class RateLimitedFirecrawlFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    status_code=429,
                    error_kind="firecrawl_rate_limited",
                    detail="rate limited",
                )

        class BrowserHarnessStub:
            def __init__(self) -> None:
                self.calls = 0
                self.rebuilds: list[str] = []

            def fetch_html(self, url, timeout_seconds):
                self.calls += 1
                return "<html><body><section>Tokyo NVMe <a>Order Now</a></section></body></html>"

            def rebuild(self, reason):
                self.rebuilds.append(reason)

        class FakeScraplingResponse:
            url = "https://merchant.example.com/products"
            status = 200
            html_content = "<html><body><section>Tokyo NVMe <a>Order Now</a></section></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse()

        scrapling_client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        original_browser = engine.monitor_browser
        browser = BrowserHarnessStub()
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                firecrawl_fetcher=RateLimitedFirecrawlFetcher(),
                scrapling_client=scrapling_client,
            )
            engine.monitor_browser = browser
            result = engine.scrape_task(
                {
                    "name": "Tokyo NVMe",
                    "monitor_url": "https://merchant.example.com/products",
                    "target_keyword": "Tokyo NVMe",
                    "fetch_strategy": "firecrawl_then_browser",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25, **self.firecrawl_settings(), "firecrawl_use_for_monitor": True},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector
            engine.monitor_browser = original_browser

        self.assertEqual(result.stock, 1)
        self.assertEqual(browser.calls, 0)
        self.assertEqual(browser.rebuilds, [])
        self.assertEqual(scrapling_client.calls, ["stealth"])
        self.assertEqual(result.backend_used, "scrapling_stealth")
        self.assertEqual([attempt.backend for attempt in result.fetch_attempts or []], ["scrapling_stealth"])

    def test_adaptive_monitor_uses_scrapling_pipeline_without_firecrawl(self) -> None:
        class CloudflareStaticFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    status_code=403,
                    error_kind="cloudflare_challenge",
                    detail="static_http 被 Cloudflare 验证页拦截",
                )

        class SuccessfulFirecrawlFetcher:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                self.calls += 1
                return app_module.FetchResult(
                    html="<html><body><section>Premium VPS <a>Order Now</a></section></body></html>",
                    final_url=url,
                    status_code=200,
                    detail="ok",
                )

        class BrowserHarnessStub:
            def fetch_html(self, url, timeout_seconds):
                raise AssertionError("adaptive cloudflare should not try local browser before firecrawl")

            def rebuild(self, reason):
                raise AssertionError("cloudflare challenge must not rebuild browser")

        class FakeScraplingResponse:
            def __init__(self, mode: str) -> None:
                self.url = "https://merchant.example.com/products"
                self.status = 200
                self.html_content = "<html><body><section>Premium VPS <a>Order Now</a></section></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse(mode)

        firecrawl_fetcher = SuccessfulFirecrawlFetcher()
        scrapling_client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        original_browser = engine.monitor_browser
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                static_http_fetcher=CloudflareStaticFetcher(),
                firecrawl_fetcher=firecrawl_fetcher,
                scrapling_client=scrapling_client,
            )
            engine.monitor_browser = BrowserHarnessStub()
            result = engine.scrape_task(
                {
                    "name": "Premium VPS",
                    "monitor_url": "https://merchant.example.com/products",
                    "target_keyword": "Premium VPS",
                    "fetch_strategy": "adaptive",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25, **self.firecrawl_settings(), "firecrawl_use_for_monitor": True},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector
            engine.monitor_browser = original_browser

        self.assertEqual(result.stock, 1)
        self.assertEqual(firecrawl_fetcher.calls, 0)
        self.assertEqual(scrapling_client.calls, ["standard"])
        self.assertEqual([attempt.backend for attempt in result.fetch_attempts or []], ["scrapling_standard"])

    def test_firecrawl_challenge_enters_protected_source_cooldown(self) -> None:
        class CloudflareStaticFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    status_code=403,
                    error_kind="cloudflare_challenge",
                    detail="static_http 被 Cloudflare 验证页拦截",
                )

        class ChallengeFirecrawlFetcher:
            def __init__(self) -> None:
                self.calls = 0

            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                self.calls += 1
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    status_code=403,
                    error_kind="cloudflare_challenge",
                    detail="Firecrawl 返回的内容仍是 Cloudflare / Turnstile 验证页。",
                )

        class BrowserHarnessStub:
            def fetch_html(self, url, timeout_seconds):
                raise AssertionError("cloudflare fallback must not return to local browser")

            def rebuild(self, reason):
                raise AssertionError("cloudflare challenge must not rebuild browser")

        class FakeScraplingResponse:
            def __init__(self, mode: str) -> None:
                self.url = "https://merchant.example.com/products"
                self.status = 403
                self.html_content = "<html><title>Just a moment...</title><body>cf-turnstile</body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse(mode)

        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, fetch_strategy, restock_template, soldout_template,
                    enabled, last_stock, last_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Protected Firecrawl VM",
                    "https://merchant.example.com/products",
                    "Protected Firecrawl VM",
                    "adaptive",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    5,
                    "in_stock",
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task_id = cursor.lastrowid
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

        firecrawl_fetcher = ChallengeFirecrawlFetcher()
        scrapling_client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        original_browser = engine.monitor_browser
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                static_http_fetcher=CloudflareStaticFetcher(),
                firecrawl_fetcher=firecrawl_fetcher,
                scrapling_client=scrapling_client,
            )
            engine.monitor_browser = BrowserHarnessStub()
            result = engine.scrape_task(
                task,
                {"request_timeout_seconds": 25, **self.firecrawl_settings(), "firecrawl_use_for_monitor": True},
                use_test_browser=False,
            )
            processed = engine.apply_task_result(
                task,
                {"telegram_bot_token": "", "telegram_chat_ids": "", **self.firecrawl_settings()},
                result,
            )
        finally:
            engine.fetcher_selector = original_selector
            engine.monitor_browser = original_browser

        self.assertFalse(processed)
        self.assertEqual(firecrawl_fetcher.calls, 0)
        self.assertEqual(scrapling_client.calls, ["standard", "dynamic", "stealth"])
        self.assertEqual(
            [attempt.backend for attempt in result.fetch_attempts or []],
            ["scrapling_standard", "scrapling_dynamic", "scrapling_stealth"],
        )
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        self.assertEqual(row["last_stock"], 5)
        self.assertEqual(row["last_state"], "in_stock")
        self.assertEqual(row["last_fetch_backend"], "scrapling_stealth")
        self.assertEqual(row["last_protected_source_backend"], "scrapling_stealth")
        self.assertEqual(row["blocked_count"], 1)
        self.assertTrue(row["cooldown_until"])
        self.assertIn("Scrapling 高兼容", row["last_error"])

    def test_fetch_pipeline_attempts_are_saved_to_task_payload(self) -> None:
        class FailingStaticFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    error_kind="empty_response",
                    detail="empty",
                )

        class SuccessfulFirecrawlFetcher:
            def fetch(self, url: str, timeout_seconds: int) -> app_module.FetchResult:
                return app_module.FetchResult(
                    html="",
                    final_url=url,
                    error_kind="firecrawl_bad_response",
                    detail="Firecrawl 响应未包含 rawHtml/html/markdown 内容。",
                )

        class FakeScraplingResponse:
            url = "https://merchant.example.com/products"
            status = 200
            html_content = "<html><body><section>HK-CMI <p>规格展示</p></section></body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append(mode)
                return FakeScraplingResponse()

        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, fetch_strategy, restock_template, soldout_template,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "HK-CMI",
                    "https://merchant.example.com/products",
                    "HK-CMI",
                    "static_then_firecrawl",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        scrapling_client = FakeScraplingClient()
        try:
            engine.fetcher_selector = app_module.FetcherSelector(
                static_http_fetcher=FailingStaticFetcher(),
                firecrawl_fetcher=SuccessfulFirecrawlFetcher(),
                scrapling_client=scrapling_client,
            )
            result = engine.scrape_task(
                task,
                {"request_timeout_seconds": 25, **self.firecrawl_settings(), "firecrawl_use_for_monitor": True},
                use_test_browser=False,
            )
            changed = engine.apply_task_result(
                task,
                {"telegram_bot_token": "", "telegram_chat_ids": "", **self.firecrawl_settings()},
                result,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertFalse(changed)
        with app_module.open_connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task["id"],)).fetchone()
        payload = app_module.to_task_payload(row)
        self.assertEqual(payload["last_fetch_backend"], "scrapling_standard")
        self.assertEqual([attempt["backend"] for attempt in payload["last_fetch_attempts"]], ["scrapling_standard"])
        self.assertEqual(scrapling_client.calls, ["standard"])
        self.assertNotIn("fc-secret-token", json.dumps(payload, ensure_ascii=False))

    def test_cycle_context_reuses_same_url_fetch_result(self) -> None:
        class FakeScraplingResponse:
            url = "https://merchant.example.com/products"
            status = 200
            html_content = """
            <html>
              <body>
                <section><h2>Tokyo Alpha</h2><p>库存 2</p><a>Order Now</a></section>
                <section><h2>Tokyo Beta</h2><p>库存 5</p><a>Order Now</a></section>
              </body>
            </html>
            """

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, int]] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append((mode, url, timeout_seconds))
                return FakeScraplingResponse()

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            context = app_module.MonitorCycleContext()
            settings = {"request_timeout_seconds": 25, **self.scrapling_settings()}
            first = engine.scrape_task(
                {
                    "name": "Tokyo Alpha",
                    "monitor_url": "https://merchant.example.com/products",
                    "target_keyword": "Tokyo Alpha",
                    "fetch_strategy": "scrapling_standard",
                },
                settings,
                use_test_browser=False,
                cycle_context=context,
            )
            second = engine.scrape_task(
                {
                    "name": "Tokyo Beta",
                    "monitor_url": "https://merchant.example.com/products",
                    "target_keyword": "Tokyo Beta",
                    "fetch_strategy": "scrapling_standard",
                },
                settings,
                use_test_browser=False,
                cycle_context=context,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(client.calls, [("standard", "https://merchant.example.com/products", 25)])
        self.assertEqual(first.stock, 2)
        self.assertEqual(second.stock, 5)
        self.assertIn("复用同轮抓取结果", second.detail)
        self.assertEqual(second.shared_fetch_backend, "scrapling_standard")

    def test_scrapling_challenge_sets_domain_cooldown_for_same_domain(self) -> None:
        class FakeScraplingResponse:
            def __init__(self, url: str) -> None:
                self.url = url
                self.status = 200
                self.html_content = "<html><title>Just a moment...</title><body>Cloudflare checking your browser</body></html>"

        class FakeScraplingClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str, int]] = []

            def fetch(self, mode: str, url: str, timeout_seconds: int):
                self.calls.append((mode, url, timeout_seconds))
                return FakeScraplingResponse(url)

        client = FakeScraplingClient()
        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(scrapling_client=client)
            context = app_module.MonitorCycleContext()
            settings = {"request_timeout_seconds": 25, **self.scrapling_settings()}
            first = engine.scrape_task(
                {
                    "name": "Protected One",
                    "monitor_url": "https://merchant.example.com/a",
                    "target_keyword": "Protected One",
                    "fetch_strategy": "scrapling_adaptive",
                },
                settings,
                use_test_browser=False,
                cycle_context=context,
            )
            second = engine.scrape_task(
                {
                    "name": "Protected Two",
                    "monitor_url": "https://merchant.example.com/b",
                    "target_keyword": "Protected Two",
                    "fetch_strategy": "scrapling_adaptive",
                },
                settings,
                use_test_browser=False,
                cycle_context=context,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(
            [call[0] for call in client.calls],
            ["standard", "dynamic", "stealth"],
        )
        self.assertEqual(first.error_kind, "cloudflare_challenge")
        self.assertTrue(first.domain_cooldown_until)
        self.assertIn("Scrapling 高兼容已尝试处理 Cloudflare managed challenge", first.detail)
        self.assertEqual(second.error_kind, "cloudflare_challenge")
        self.assertTrue(second.cooldown_skip)
        self.assertEqual(second.domain_cooldown_until, first.domain_cooldown_until)
        self.assertIn("同域名保护等待", second.detail)

    def test_generic_pricing_table_extractor_handles_order_and_soldout_buttons(self) -> None:
        fetch_result = app_module.FetchResult(html="", final_url="https://example.com/pricing")
        in_stock_html = """
        <main>
          <section class="plan-card">
            <h2>HK Tier 1</h2>
            <p>International optimization network</p>
            <a href="/cart">Order Now</a>
          </section>
        </main>
        """
        sold_out_html = """
        <main>
          <section class="plan-card">
            <h2>HK Tier 2</h2>
            <button disabled>Out of Stock</button>
          </section>
        </main>
        """

        in_stock = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            in_stock_html,
            "HK Tier 1",
            {"fetch_strategy": "generic_pricing_table"},
            fetch_result,
        )
        sold_out = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            sold_out_html,
            "HK Tier 2",
            {"fetch_strategy": "generic_pricing_table"},
            fetch_result,
        )

        self.assertEqual(in_stock.stock, 1)
        self.assertIn("Order Now", in_stock.fragment)
        self.assertIn("generic_pricing_table", in_stock.detail)
        self.assertEqual(sold_out.stock, 0)
        self.assertIn("售罄", sold_out.detail)

    def test_generic_pricing_table_handles_idc_cart_cards_without_vendor_strategy(self) -> None:
        fetch_result = app_module.FetchResult(html="", final_url="https://example.com/cart.php?region=hong-kong&generation=as3")
        filler = " feature " * 220
        html_text = f"""
        <main class="cart-products">
          <plan-card>
            <strong>HKG.AS3.Pro.STARTER</strong>
            <p>{filler}</p>
            <a href="/cart.php?a=add&pid=101">Order Now</a>
          </plan-card>
          <plan-card>
            <strong>HKG.AS3.Pro.TINY</strong>
            <p>{filler}</p>
            <a href="/cart.php?a=add&pid=102">Add to Cart</a>
          </plan-card>
          <plan-card>
            <strong>LAX.AS3.Pro.TINY</strong>
            <button disabled>Out of Stock</button>
          </plan-card>
        </main>
        """

        hk_tiny = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            html_text,
            "HKG.AS3.Pro.TINY",
            {"fetch_strategy": "generic_pricing_table"},
            fetch_result,
        )
        lax_tiny = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            html_text,
            "LAX.AS3.Pro.TINY",
            {"fetch_strategy": "generic_pricing_table"},
            fetch_result,
        )

        self.assertEqual(hk_tiny.stock, 1)
        self.assertIn("HKG.AS3.Pro.TINY", hk_tiny.fragment)
        self.assertIn("Add to Cart", hk_tiny.fragment)
        self.assertIn("generic_pricing_table", hk_tiny.detail)
        self.assertEqual(lax_tiny.stock, 0)
        self.assertIn("LAX.AS3.Pro.TINY", lax_tiny.fragment)
        self.assertIn("售罄", lax_tiny.detail)

    def test_generic_pricing_table_treats_selected_idc_checkout_page_as_in_stock(self) -> None:
        fetch_result = app_module.FetchResult(
            html="",
            final_url="https://www.example.com/cart.php?region=hong-kong&network=tier-1&generation=as3&product=hkg.as3.t1.wee",
        )
        filler = " routing cpu ram ssd transfer " * 260
        html_text = f"""
        <main>
          <section>
            <h2>選擇實例類型</h2>
            <article class="plan-card active">
              <h3>HKG.AS3.T1.WEE</h3>
              <p>$ 36.90 USD / 年繳</p>
              <p>{filler}</p>
            </article>
            <article class="plan-card">
              <h3>HKG.AS3.T1.TINY</h3>
              <p>$ 6.90 USD / 月繳</p>
            </article>
          </section>
          <footer class="cart-summary">
            <button type="button">繼續</button>
          </footer>
        </main>
        """

        result = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            html_text,
            "HKG.AS3.T1.WEE",
            {
                "fetch_strategy": "firecrawl",
                "monitor_url": "https://www.example.com/cart.php?product=hkg.as3.t1.wee",
            },
            fetch_result,
        )

        self.assertEqual(result.stock, 1)
        self.assertIn("HKG.AS3.T1.WEE", result.fragment)
        self.assertIn("可继续下单页面", result.detail)

    def test_generic_pricing_table_handles_dmit_tier1_selected_product_url(self) -> None:
        fetch_result = app_module.FetchResult(
            html="",
            final_url="https://www.dmit.io/cart.php?region=hong-kong&network=tier-1&generation=as3&product=hkg.as3.t1.wee",
        )
        html_text = """
        <main>
          <section>
            <h2>選擇網絡類型</h2>
            <button>Premium</button>
            <button>Tier 1</button>
          </section>
          <section>
            <h2>選擇實例類型</h2>
            <article class="product-card selected">
              <h3>HKG.AS3.T1.WEE</h3>
              <p>$ 36.90 USD / 年繳</p>
              <p>1 vCores</p>
              <p>1.0GB RAM</p>
              <p>20GB SSD</p>
              <p>1000GB @ 4Gbps</p>
            </article>
            <article class="product-card">
              <h3>HKG.AS3.T1.TINY</h3>
              <p>$ 6.90 USD / 月繳</p>
              <p>1 vCores</p>
              <p>1.0GB RAM</p>
              <p>20GB SSD</p>
              <p>2000GB @ 4Gbps</p>
            </article>
          </section>
          <footer class="cart-summary">
            <button type="button">繼續</button>
          </footer>
        </main>
        """

        result = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            html_text,
            "Dmit HKG.AS3.T1.WEE",
            {
                "fetch_strategy": "firecrawl",
                "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=tier-1&generation=as3&product=hkg.as3.t1.wee",
            },
            fetch_result,
        )

        self.assertEqual(result.stock, 1)
        self.assertIn("HKG.AS3.T1.WEE", result.fragment)
        self.assertIn("按有货处理", result.detail)

    def test_generic_pricing_table_handles_dmit_premium_category_page(self) -> None:
        fetch_result = app_module.FetchResult(
            html="",
            final_url="https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
        )
        html_text = """
        <main>
          <section>
            <h2>選擇網絡類型</h2>
            <button>Premium</button>
            <button>Eyeball</button>
            <button>Tier 1</button>
          </section>
          <section>
            <h2>選擇實例類型</h2>
            <article class="product-card">
              <h3>HKG.AS3.Pro.STARTER</h3>
              <p>$ 12.90 USD / 月繳</p>
              <p>1 vCores</p>
              <p>2.0GB RAM</p>
              <p>40GB SSD</p>
              <p>4000GB @ 10Gbps</p>
            </article>
            <article class="product-card selected">
              <h3>HKG.AS3.Pro.TINY</h3>
              <p>$ 6.90 USD / 月繳</p>
              <p>1 vCores</p>
              <p>1.0GB RAM</p>
              <p>20GB SSD</p>
              <p>2000GB @ 4Gbps</p>
            </article>
          </section>
          <footer class="cart-summary">
            <button type="button">繼續</button>
          </footer>
        </main>
        """

        result = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            html_text,
            "HKG.AS3.Pro.TINY",
            {
                "fetch_strategy": "scrapling_adaptive",
                "monitor_url": "https://www.dmit.io/cart.php?region=hong-kong&network=premium&generation=as3",
            },
            fetch_result,
        )

        self.assertEqual(result.stock, 1)
        self.assertIn("HKG.AS3.Pro.TINY", result.fragment)
        self.assertIn("按有货处理", result.detail)

    def test_generic_pricing_table_does_not_override_target_soldout_with_continue_button(self) -> None:
        fetch_result = app_module.FetchResult(
            html="",
            final_url="https://www.dmit.io/cart.php?region=los-angeles&network=premium&generation=as3&product=lax.as3.pro.tiny",
        )
        html_text = """
        <main>
          <section>
            <h2>選擇實例類型</h2>
            <article class="product-card">
              <h3>HKG.AS3.Pro.TINY</h3>
              <p>$ 6.90 USD / 月繳</p>
              <p>1 vCores 1.0GB RAM 20GB SSD</p>
            </article>
            <article class="product-card selected">
              <h3>LAX.AS3.Pro.TINY</h3>
              <p>$ 6.90 USD / 月繳</p>
              <button disabled>Out of Stock</button>
            </article>
          </section>
          <footer class="cart-summary">
            <button type="button">繼續</button>
          </footer>
        </main>
        """

        result = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            html_text,
            "Dmit LAX.AS3.Pro.TINY",
            {
                "fetch_strategy": "firecrawl",
                "monitor_url": "https://www.dmit.io/cart.php?region=los-angeles&network=premium&generation=as3&product=lax.as3.pro.tiny",
            },
            fetch_result,
        )

        self.assertEqual(result.stock, 0)
        self.assertIn("LAX.AS3.Pro.TINY", result.fragment)
        self.assertIn("售罄", result.detail)

    def test_generic_pricing_table_unknown_detail_explains_missing_signal_or_target(self) -> None:
        fetch_result = app_module.FetchResult(html="", final_url="https://example.com/pricing")
        missing_signal_html = """
        <main>
          <article class="product-card">
            <h3>HK Premium VPS</h3>
            <p>$ 9.90 USD / month</p>
            <p>1 vCPU 1GB RAM 20GB SSD</p>
          </article>
        </main>
        """
        no_target = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            missing_signal_html,
            "Tokyo Premium VPS",
            {"fetch_strategy": "generic_pricing_table"},
            fetch_result,
        )
        missing_signal = app_module.extract_stock_for_strategy(
            "generic_pricing_table",
            missing_signal_html,
            "HK Premium VPS",
            {"fetch_strategy": "generic_pricing_table"},
            fetch_result,
        )

        self.assertIsNone(no_target.stock)
        self.assertIn("未找到目标商品标题", no_target.detail)
        self.assertIsNone(missing_signal.stock)
        self.assertIn("缺少明确购买入口或售罄标记", missing_signal.detail)

    def test_rule_extractor_css_selector_detects_in_stock(self) -> None:
        html_text = """
        <main>
          <article class="product-card">
            <h3>Tokyo Basic</h3>
            <span class="inventory">库存 12</span>
          </article>
        </main>
        """
        result = app_module.extract_stock_for_strategy(
            "scrapling_adaptive",
            html_text,
            "Tokyo Basic",
            {
                "fetch_strategy": "scrapling_adaptive",
                "source_config": json.dumps(
                    {
                        "stock_rule_type": "css_selector",
                        "target_scope_selector": ".product-card",
                        "stock_selector": ".inventory",
                    }
                ),
            },
            app_module.FetchResult(html=html_text, final_url="https://example.com/pricing"),
        )

        self.assertEqual(result.stock, 12)
        self.assertIn("css_selector", result.detail)

    def test_rule_extractor_xpath_detects_sold_out(self) -> None:
        html_text = """
        <main>
          <article class="product-card">
            <h3>Osaka Pro</h3>
            <button disabled>Out of Stock</button>
          </article>
        </main>
        """
        result = app_module.extract_stock_for_strategy(
            "scrapling_adaptive",
            html_text,
            "Osaka Pro",
            {
                "fetch_strategy": "scrapling_adaptive",
                "source_config": {
                    "stock_rule_type": "xpath",
                    "stock_selector": "//article[contains(., 'Osaka Pro')]//button",
                },
            },
            app_module.FetchResult(html=html_text, final_url="https://example.com/pricing"),
        )

        self.assertEqual(result.stock, 0)
        self.assertIn("xpath", result.detail)

    def test_rule_extractor_regex_detects_stock_number(self) -> None:
        html_text = "<html><body>plan=HK-CMI stock_count: 42</body></html>"
        result = app_module.extract_stock_for_strategy(
            "scrapling_standard",
            html_text,
            "HK-CMI",
            {
                "fetch_strategy": "scrapling_standard",
                "source_config": {
                    "stock_rule_type": "regex",
                    "regex_pattern": r"stock_count:\s*(?P<stock>\d+)",
                },
            },
            app_module.FetchResult(html=html_text, final_url="https://example.com/pricing"),
        )

        self.assertEqual(result.stock, 42)
        self.assertIn("regex", result.detail)

    def test_rule_extractor_text_near_keyword_limits_to_target_card(self) -> None:
        html_text = """
        <main>
          <article class="product-card">
            <h3>Basic VPS</h3>
            <button>Order Now</button>
          </article>
          <article class="product-card">
            <h3>Premium VPS</h3>
            <button disabled>Out of Stock</button>
          </article>
        </main>
        """
        result = app_module.extract_stock_for_strategy(
            "scrapling_adaptive",
            html_text,
            "Premium VPS",
            {
                "fetch_strategy": "scrapling_adaptive",
                "source_config": {
                    "stock_rule_type": "text_near_keyword",
                    "soldout_keywords": ["Out of Stock"],
                    "in_stock_keywords": ["Order Now"],
                },
            },
            app_module.FetchResult(html=html_text, final_url="https://example.com/pricing"),
        )

        self.assertEqual(result.stock, 0)
        self.assertIn("自定义售罄关键词", result.detail)

    def test_rule_extractor_json_path_detects_availability(self) -> None:
        html_text = """
        <html>
          <script type="application/json">
            {"products": [{"sku": "HK", "availability": "InStock"}]}
          </script>
        </html>
        """
        result = app_module.extract_stock_for_strategy(
            "scrapling_adaptive",
            html_text,
            "HK",
            {
                "fetch_strategy": "scrapling_adaptive",
                "source_config": {
                    "stock_rule_type": "json_path",
                    "json_path": "$.products[0].availability",
                },
            },
            app_module.FetchResult(html=html_text, final_url="https://example.com/pricing"),
        )

        self.assertEqual(result.stock, 1)
        self.assertIn("json_path", result.detail)

    def test_rule_extractor_returns_readable_reason_when_rule_fails(self) -> None:
        html_text = "<main><article><h3>HK VPS</h3><p>$9.90</p></article></main>"
        result = app_module.extract_stock_for_strategy(
            "scrapling_adaptive",
            html_text,
            "HK VPS",
            {
                "fetch_strategy": "scrapling_adaptive",
                "source_config": {
                    "stock_rule_type": "css_selector",
                    "stock_selector": ".missing-stock",
                },
            },
            app_module.FetchResult(html=html_text, final_url="https://example.com/pricing"),
        )

        self.assertIsNone(result.stock)
        self.assertIn("自定义规则未能判断库存", result.detail)

    def test_scrape_task_generic_pricing_table_limits_to_target_product(self) -> None:
        class FakeResponse:
            status_code = 200
            url = "https://example.com/pricing"
            text = """
            <section class="plans">
              <div class="plan">
                <h3>Basic VPS</h3>
                <a href="/cart/basic">Order Now</a>
              </div>
              <div class="plan">
                <h3>Premium VPS</h3>
                <button disabled>Out of Stock</button>
              </div>
            </section>
            """

        class FakeSession:
            def get(self, url, headers=None, timeout=None, allow_redirects=None):
                return FakeResponse()

        engine = self.app.extensions["monitor_engine"]
        original_selector = engine.fetcher_selector
        try:
            engine.fetcher_selector = app_module.FetcherSelector(app_module.StaticHttpFetcher(FakeSession()))
            result = engine.scrape_task(
                {
                    "name": "Basic VPS",
                    "monitor_url": "https://example.com/pricing",
                    "target_keyword": "Basic VPS",
                    "fetch_strategy": "generic_pricing_table",
                    "source_config": "{}",
                },
                {"request_timeout_seconds": 25},
                use_test_browser=False,
            )
        finally:
            engine.fetcher_selector = original_selector

        self.assertEqual(result.stock, 1)
        self.assertIn("Basic VPS", result.fragment)
        self.assertNotIn("Premium VPS", result.fragment)
        self.assertIn("generic_pricing_table", result.detail)

    def test_whmcs_extractor_handles_target_keyword_and_pid_links(self) -> None:
        html_text = """
        <div class="products">
          <div class="package">
            <h3>Tokyo NVMe</h3>
            <a class="btn btn-success" href="cart.php?a=confproduct&pid=21">Configure</a>
          </div>
          <div class="package">
            <h3>Osaka NVMe</h3>
            <button disabled>Out of Stock</button>
          </div>
        </div>
        """
        fetch_result = app_module.FetchResult(html=html_text, final_url="https://example.com/cart.php?gid=12")

        pid_result = app_module.extract_stock_for_strategy(
            "whmcs",
            html_text,
            "",
            {
                "fetch_strategy": "whmcs",
                "monitor_url": "https://example.com/cart.php?a=add&pid=21",
                "source_config": "{}",
            },
            fetch_result,
        )
        sold_out_result = app_module.extract_stock_for_strategy(
            "whmcs",
            html_text,
            "Osaka NVMe",
            {
                "fetch_strategy": "whmcs",
                "monitor_url": "https://example.com/cart.php?gid=12",
                "source_config": "{}",
            },
            fetch_result,
        )

        self.assertEqual(pid_result.stock, 1)
        self.assertIn("Tokyo NVMe", pid_result.fragment)
        self.assertNotIn("Osaka NVMe", pid_result.fragment)
        self.assertIn("WHMCS", pid_result.detail)
        self.assertEqual(sold_out_result.stock, 0)
        self.assertIn("售罄", sold_out_result.detail)

    def test_browser_auto_heal_recognizes_chinese_connection_failure(self) -> None:
        self.assertTrue(
            app_module.should_auto_heal(
                RuntimeError("浏览器连接失败。地址：127.0.0.1:9223 提示：用户文件夹和已打开的浏览器冲突")
            )
        )

    def test_browser_auto_heal_rejects_cloudflare_challenge(self) -> None:
        self.assertFalse(
            app_module.should_auto_heal(
                app_module.ProtectedSourceError(
                    "monitor 浏览器被 Cloudflare 验证页拦截：https://example.com/products"
                )
            )
        )
        self.assertFalse(app_module.should_auto_heal(RuntimeError("Cloudflare Turnstile challenge: just a moment")))

    def test_browser_fetch_html_stops_immediately_on_cloudflare_challenge_page(self) -> None:
        harness = app_module.BrowserHarness("catalog", 9444, True, "")

        class FakeWait:
            def doc_loaded(self, timeout=None, raise_err=None):
                return True

        class FakePage:
            def __init__(self) -> None:
                self.html = "<html><title>Just a moment...</title><body><div id=\"cf-turnstile\">Cloudflare</div></body></html>"
                self.title = "Just a moment..."
                self.wait = FakeWait()
                self.refresh_calls = 0

            def get(self, url, timeout=None, retry=None, interval=None):
                return True

            def refresh(self, ignore_cache=False):
                self.refresh_calls += 1
                self.html = "<html><title>Products</title><body><section>HK-CMI <strong>7</strong></section></body></html>"
                self.title = "Products"

            def quit(self, timeout=5, force=True, del_data=False):
                return None

        page = FakePage()
        original_ensure_page = harness.ensure_page
        try:
            harness.ensure_page = lambda: page
            with self.assertRaises(app_module.ProtectedSourceError) as ctx:
                harness.fetch_html("https://example.com/products", 10)
        finally:
            harness.ensure_page = original_ensure_page
            harness.shutdown()

        self.assertIn("Cloudflare 验证页", str(ctx.exception))
        self.assertEqual(page.refresh_calls, 0)

    def test_browser_fetch_html_raises_after_persistent_cloudflare_challenge(self) -> None:
        harness = app_module.BrowserHarness("catalog", 9444, True, "")

        class FakeWait:
            def doc_loaded(self, timeout=None, raise_err=None):
                return True

        class FakePage:
            def __init__(self) -> None:
                self.html = "<html><title>Just a moment...</title><body><div id=\"cf-turnstile\">Cloudflare</div></body></html>"
                self.title = "Just a moment..."
                self.wait = FakeWait()
                self.refresh_calls = 0

            def get(self, url, timeout=None, retry=None, interval=None):
                return True

            def refresh(self, ignore_cache=False):
                self.refresh_calls += 1

            def quit(self, timeout=5, force=True, del_data=False):
                return None

        page = FakePage()
        original_ensure_page = harness.ensure_page
        try:
            harness.ensure_page = lambda: page
            with self.assertRaises(app_module.ProtectedSourceError) as ctx:
                harness.fetch_html("https://example.com/products", 10)
        finally:
            harness.ensure_page = original_ensure_page
            harness.shutdown()

        self.assertIn("Cloudflare 验证页", str(ctx.exception))
        self.assertEqual(page.refresh_calls, 0)

    def test_browser_profile_lock_cleanup_removes_stale_chrome_locks(self) -> None:
        harness = app_module.BrowserHarness("unit", 9444, True, "")
        try:
            for filename in app_module.BROWSER_LOCK_FILENAMES:
                path = harness.profile_dir / filename
                path.write_text("stale", encoding="utf-8")

            harness._clear_profile_locks()

            for filename in app_module.BROWSER_LOCK_FILENAMES:
                self.assertFalse((harness.profile_dir / filename).exists())
        finally:
            harness.shutdown()

    def test_browser_harness_roles_use_isolated_profiles_and_ports(self) -> None:
        monitor = app_module.BrowserHarness("monitor", 9441, True, "")
        test = app_module.BrowserHarness("test", 9442, True, "")
        catalog = app_module.BrowserHarness("catalog", 9445, True, "")
        try:
            self.assertEqual(monitor.port, 9441)
            self.assertEqual(test.port, 9442)
            self.assertEqual(catalog.port, 9445)
            self.assertNotEqual(monitor.profile_dir, test.profile_dir)
            self.assertNotEqual(monitor.profile_dir, catalog.profile_dir)
            self.assertNotEqual(test.profile_dir, catalog.profile_dir)
            self.assertTrue(str(catalog.profile_dir).endswith("browser-catalog"))
        finally:
            monitor.shutdown()
            test.shutdown()
            catalog.shutdown()

    def test_catalog_browser_port_busy_reports_configuration_error(self) -> None:
        harness = app_module.BrowserHarness("catalog", 9445, True, "")

        class FakeProcess:
            pid = 4242

            def name(self) -> str:
                return "python"

        try:
            harness._foreign_port_listeners = lambda: [FakeProcess()]
            with self.assertRaises(app_module.CatalogBrowserPortBusyError) as ctx:
                harness._assert_port_available_for_role()
        finally:
            harness.shutdown()

        self.assertIn("商品入库浏览器端口 9445 已被其他进程占用", str(ctx.exception))
        self.assertIn("CATALOG_DEBUG_PORT", str(ctx.exception))

    def test_scrape_task_auto_heals_browser_connection_failure(self) -> None:
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, fetch_strategy, restock_template, soldout_template,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Kawasaki",
                    "https://example.com/cart.php?gid=12",
                    "Kawasaki",
                    "browser",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        class FlakyBrowser:
            def __init__(self) -> None:
                self.calls = 0
                self.rebuilds: list[str] = []

            def fetch_html(self, url, timeout_seconds):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError(
                        "浏览器连接失败。地址：127.0.0.1:9223 提示：用户文件夹和已打开的浏览器冲突"
                    )
                return "Kawasaki <section>Available</section><span hidden>x</span><strong>17</strong>"

            def rebuild(self, reason):
                self.rebuilds.append(reason)

        engine = self.app.extensions["monitor_engine"]
        original_browser = engine.monitor_browser
        flaky_browser = FlakyBrowser()
        try:
            engine.monitor_browser = flaky_browser
            result = engine.scrape_task(
                task,
                {
                    "monitor_debug_port": 9223,
                    "test_debug_port": 9334,
                    "poll_interval_seconds": 45,
                    "request_timeout_seconds": 25,
                },
                use_test_browser=False,
            )
        finally:
            engine.monitor_browser = original_browser

        self.assertEqual(flaky_browser.calls, 2)
        self.assertEqual(len(flaky_browser.rebuilds), 1)
        self.assertEqual(result.stock, 17)
        self.assertIn("Available", result.fragment)

    def test_scrape_task_protected_source_does_not_rebuild_browser(self) -> None:
        timestamp = app_module.now_iso()
        with app_module.open_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    name, monitor_url, target_keyword, fetch_strategy, restock_template, soldout_template,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "Protected",
                    "https://example.com/products",
                    "Protected",
                    "browser",
                    "{name} {stock}",
                    "{name} sold out",
                    1,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            task = connection.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()

        class ProtectedBrowser:
            def __init__(self) -> None:
                self.calls = 0
                self.rebuilds: list[str] = []

            def fetch_html(self, url, timeout_seconds):
                self.calls += 1
                raise app_module.ProtectedSourceError(f"monitor 浏览器被 Cloudflare 验证页拦截：{url}")

            def rebuild(self, reason):
                self.rebuilds.append(reason)

        engine = self.app.extensions["monitor_engine"]
        original_browser = engine.monitor_browser
        protected_browser = ProtectedBrowser()
        try:
            engine.monitor_browser = protected_browser
            result = engine.scrape_task(
                task,
                {
                    "monitor_debug_port": 9223,
                    "test_debug_port": 9334,
                    "poll_interval_seconds": 45,
                    "request_timeout_seconds": 25,
                },
                use_test_browser=False,
            )
        finally:
            engine.monitor_browser = original_browser

        self.assertEqual(protected_browser.calls, 1)
        self.assertEqual(protected_browser.rebuilds, [])
        self.assertIsNone(result.stock)
        self.assertEqual(result.error_kind, "cloudflare_challenge")
        self.assertIn("Cloudflare 验证页拦截", result.detail)

    def test_update_profile_duplicate_username_returns_400(self) -> None:
        bootstrap, headers = self.login()
        self.insert_admin("duplicate-admin", "AnotherStrongPass123")

        response = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/profile",
            headers=headers,
            base_url=BASE_URL,
            json={
                "current_password": bootstrap["password"],
                "new_username": "duplicate-admin",
                "new_password": "",
                "confirm_password": "",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("用户名已存在", response.get_json()["message"])

    def test_slice_fragment_and_stock_parser_cover_html_noise(self) -> None:
        html_text = "A" * 80 + "HK-CMI" + "<div>库存</div><span> </span><i> </i><strong>12</strong>" + "B" * 1500
        fragment = app_module.slice_fragment(html_text, "HK-CMI")

        self.assertTrue(fragment.startswith("A" * 50))
        self.assertEqual(len(fragment), 50 + len("HK-CMI") + 1200)

        stock, detail = app_module.parse_stock(fragment)
        self.assertEqual(stock, 12)
        self.assertIn("库存数字", detail)

        sold_out_stock, sold_out_detail = app_module.parse_stock("<div>Sold Out</div>")
        self.assertEqual(sold_out_stock, 0)
        self.assertIn("售罄", sold_out_detail)

    def test_stock_parser_handles_common_merchant_restock_signals(self) -> None:
        escaped_fragment = app_module.slice_fragment(
            "A" * 60 + "Sonic &amp; Kawasaki" + "<span data-stock=\"9\"></span>",
            "Sonic & Kawasaki",
        )
        self.assertIn("data-stock", escaped_fragment)
        stock, detail = app_module.parse_stock(escaped_fragment)
        self.assertEqual(stock, 9)
        self.assertIn("结构化库存", detail)

        json_ld_stock, json_ld_detail = app_module.parse_stock(
            """
            <script type="application/ld+json">
            {"@type":"Product","name":"HK-CMI","offers":{"availability":"https://schema.org/InStock"}}
            </script>
            """
        )
        self.assertEqual(json_ld_stock, 1)
        self.assertIn("可购买", json_ld_detail)

        whmcs_stock, whmcs_detail = app_module.parse_stock(
            """
            <div class="package">
              <h3>Tokyo NVMe</h3>
              <a class="btn btn-success" href="cart.php?a=add&pid=21">Order Now</a>
            </div>
            """
        )
        self.assertEqual(whmcs_stock, 1)
        self.assertIn("可下单", whmcs_detail)

        left_stock, left_detail = app_module.parse_stock("<div>Only <span>2</span> left today</div>")
        self.assertEqual(left_stock, 2)
        self.assertIn("库存数字", left_detail)

        sold_out_stock, sold_out_detail = app_module.parse_stock(
            '<button class="btn disabled">Currently Out of Stock</button>'
        )
        self.assertEqual(sold_out_stock, 0)
        self.assertIn("售罄", sold_out_detail)

        json_quantity_stock, json_quantity_detail = app_module.parse_stock(
            """
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Product","inventory_quantity":"8","availabilityDate":"2026-06-05"}
            </script>
            """
        )
        self.assertEqual(json_quantity_stock, 8)
        self.assertIn("JSON", json_quantity_detail)
        self.assertIn("2026-06-05", json_quantity_detail)

        restock_stock, restock_detail = app_module.parse_stock(
            """
            <div class="status">预计补货：2026年6月5日</div>
            <button disabled>Out of Stock</button>
            """
        )
        self.assertEqual(restock_stock, 0)
        self.assertIn("补货信息", restock_detail)
        self.assertIn("2026年6月5日", restock_detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
