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
        }

        app_module.DATA_DIR = self.data_dir
        app_module.DB_PATH = self.data_dir / "monitor.db"
        app_module.BOOTSTRAP_CREDENTIALS_PATH = self.data_dir / "bootstrap_admin.txt"
        app_module.SECRET_KEY_PATH = self.data_dir / ".secret_key"
        app_module.SECRET_KEY = "test-secret-key"
        app_module.PORTAL_PATH = "/portal_test"
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

    def get_portal_csrf(self) -> str:
        response = self.client.get(app_module.PORTAL_PATH, headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
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

    def test_hidden_portal_and_browser_header_gate(self) -> None:
        root_response = self.client.get("/", headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        self.assertEqual(root_response.status_code, 404)

        blocked_response = self.client.get(app_module.PORTAL_PATH, base_url=BASE_URL)
        self.assertEqual(blocked_response.status_code, 404)

        allowed_response = self.client.get(app_module.PORTAL_PATH, headers={"User-Agent": BROWSER_UA}, base_url=BASE_URL)
        self.assertEqual(allowed_response.status_code, 200)
        html = allowed_response.get_data(as_text=True)
        self.assertIn('id="dashboard-shell" class="hidden flex h-screen flex-col overflow-hidden md:flex-row"', html)
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
                "monitor_url": "https://example.com/cart.php?gid=1",
                "target_keyword": "HK-CMI",
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
        self.assertIn("system", payload)
        self.assertIn("version", payload["system"])

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
                self.sent.append({"token": token, "chat_id": chat_id, "text": text, "buttons": buttons})
                return 901

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
            "telegram_chat_id": "chat",
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
                    "SELECT last_stock, last_state, message_id FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            self.assertEqual(row["last_stock"], 5)
            self.assertEqual(row["last_state"], "in_stock")
            self.assertEqual(row["message_id"], 901)
            self.assertEqual(len(fake_telegram.sent), 1)
            self.assertEqual(len(fake_telegram.edited), 0)

            stock_box["value"] = 7
            self.assertTrue(engine.process_task(fetch_task(), settings_payload, use_test_browser=False))
            with app_module.open_connection() as connection:
                row = connection.execute(
                    "SELECT last_stock, last_state, message_id FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            self.assertEqual(row["last_stock"], 7)
            self.assertEqual(row["last_state"], "in_stock")
            self.assertEqual(row["message_id"], 901)
            self.assertEqual(len(fake_telegram.sent), 1)
            self.assertEqual(len(fake_telegram.edited), 1)
            self.assertEqual(fake_telegram.edited[-1]["message_id"], 901)
            self.assertIn("stock=7", fake_telegram.edited[-1]["text"])

            stock_box["value"] = 0
            self.assertTrue(engine.process_task(fetch_task(), settings_payload, use_test_browser=False))
            with app_module.open_connection() as connection:
                row = connection.execute(
                    "SELECT last_stock, last_state, message_id FROM tasks WHERE id = ?",
                    (task_id,),
                ).fetchone()
            self.assertEqual(row["last_stock"], 0)
            self.assertEqual(row["last_state"], "sold_out")
            self.assertIsNone(row["message_id"])
            self.assertEqual(len(fake_telegram.sent), 1)
            self.assertEqual(len(fake_telegram.edited), 2)
            self.assertIn("sold out", fake_telegram.edited[-1]["text"])
        finally:
            engine.telegram = original_telegram
            engine.scrape_task = original_scrape_task

    def test_update_settings_rejects_debug_port_collisions(self) -> None:
        _, headers = self.login()

        same_port = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"monitor_debug_port": 9223, "test_debug_port": 9223},
        )
        self.assertEqual(same_port.status_code, 400)
        self.assertIn("不能相同", same_port.get_json()["message"])

        app_port_collision = self.client.post(
            f"{app_module.PORTAL_PATH}/api/settings/telegram",
            headers=headers,
            base_url=BASE_URL,
            json={"monitor_debug_port": 7777, "test_debug_port": 9334},
        )
        self.assertEqual(app_port_collision.status_code, 400)
        self.assertIn("面板监听端口", app_port_collision.get_json()["message"])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
