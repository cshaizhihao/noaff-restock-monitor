import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def find_bash() -> str | None:
    found = shutil.which("bash")
    if found:
        return found
    candidate = Path("C:/Program Files/Git/bin/bash.exe")
    if candidate.exists():
        return str(candidate)
    return None


class InstallScriptTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bash = find_bash()
        cls.shim_dir = ROOT_DIR / ".test-bin"
        if cls.shim_dir.exists():
            shutil.rmtree(cls.shim_dir)
        cls.shim_dir.mkdir(parents=True, exist_ok=True)
        python_shim = cls.shim_dir / "python3"
        python_shim.write_text(
            f'#!/usr/bin/env bash\nexec "{Path(sys.executable).as_posix()}" "$@"\n',
            encoding="utf-8",
        )
        python_shim.chmod(0o755)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.shim_dir, ignore_errors=True)

    def run_bash(self, script: str) -> subprocess.CompletedProcess[str]:
        if not self.bash:
            self.skipTest("bash is not available")
        shim_dir = ".test-bin"
        env = os.environ.copy()
        return subprocess.run(
            [self.bash, "-c", f"export PATH='{shim_dir}':\"$PATH\"\n{script}"],
            cwd=ROOT_DIR,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )

    def assert_shell_ok(self, script: str) -> str:
        result = self.run_bash(script)
        self.assertEqual(result.returncode, 0, msg=f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result.stdout

    def test_bash_syntax_is_valid(self) -> None:
        result = self.run_bash("bash -n install.sh")
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_help_mode_does_not_require_root(self) -> None:
        output = self.assert_shell_ok("bash install.sh --help")
        self.assertIn("NOAFF Restock Monitor installer", output)
        self.assertIn("--validate-only", output)

    def test_validate_only_accepts_complete_configuration(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                ACCESS_MODE=domain-cf \
                FQDN=monitor.example.com \
                CF_ZONE_NAME=example.com \
                CF_API_TOKEN=test-token \
                CERTBOT_EMAIL=ops@example.com \
                bash install.sh --validate-only
                """
            )
        )
        self.assertIn("NOAFF installer validation passed.", output)
        self.assertIn("APP_BIND:          127.0.0.1:7777", output)
        self.assertIn("PUBLIC_HTTPS_PORT: 443", output)

    def test_validate_only_accepts_ip_mode_without_domain(self) -> None:
        output = self.assert_shell_ok("ACCESS_MODE=ip APP_PORT=7777 bash install.sh --validate-only")
        self.assertIn("ACCESS_MODE:       ip", output)
        self.assertIn("FQDN:              IP mode", output)
        self.assertIn("ENABLE_TLS:        false", output)

    def test_validate_only_accepts_docker_mode_without_domain(self) -> None:
        output = self.assert_shell_ok("DEPLOY_MODE=docker PUBLIC_APP_PORT=7777 bash install.sh --validate-only")
        self.assertIn("ACCESS_MODE:       ip", output)
        self.assertIn("ENABLE_NGINX:      false", output)
        self.assertIn("ENABLE_TLS:        false", output)

    def test_validate_only_accepts_domain_direct_without_cloudflare_token(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                ACCESS_MODE=domain-direct \
                FQDN=monitor.example.com \
                CERTBOT_EMAIL=ops@example.com \
                CF_RECORD_PROXIED=false \
                bash install.sh --validate-only
                """
            )
        )
        self.assertIn("ACCESS_MODE:       domain-direct", output)
        self.assertIn("CERT_MODE:         http", output)
        self.assertIn("CF_RECORD_PROXIED: false", output)

    def test_cloudflare_zone_and_dns_record_json_parsing(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export CF_API_TOKEN=test-token
                export CF_ZONE_NAME=example.com
                export FQDN=monitor.example.com
                source ./install.sh

                calls=()
                cf_api() {
                  local method="$1"
                  local endpoint="$2"
                  local payload="${3:-}"
                  calls+=("${method} ${endpoint} ${payload}")
                  case "$endpoint" in
                    /zones?name=example.com\&status=active\&per_page=1)
                      printf '{"result":[{"id":"zone_123"}]}'
                      ;;
                    /zones/zone_123/dns_records?type=A\&name=monitor.example.com\&per_page=1)
                      printf '{"result":[{"id":"record_abc"}]}'
                      ;;
                    /zones/zone_123/dns_records/record_abc)
                      printf '{"success":true}'
                      ;;
                    *)
                      printf '{"result":[]}'
                      ;;
                  esac
                }

                resolve_zone_id
                upsert_dns_record monitor.example.com A 203.0.113.10

                [[ "$CF_ZONE_ID" == "zone_123" ]]
                printf 'zone=%s\n' "$CF_ZONE_ID"
                printf '%s\n' "${calls[@]}"
                """
            )
        )
        self.assertIn("zone=zone_123", output)
        self.assertIn("PUT /zones/zone_123/dns_records/record_abc", output)
        self.assertIn('"content": "203.0.113.10"', output)
        self.assertIn('"proxied": true', output)

    def test_cloudflare_nginx_snippets_parse_ip_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir).as_posix()
            output = self.assert_shell_ok(
                textwrap.dedent(
                    f"""
                    set -Eeuo pipefail
                    export NOAFF_INSTALL_LIBRARY_MODE=true
                    source ./install.sh
                    CF_REALIP_SNIPPET='{temp_path}/realip.conf'
                    CF_ALLOW_SNIPPET='{temp_path}/allow.conf'
                    SSL_SNIPPET='{temp_path}/ssl.conf'
                    fetch_cloudflare_ips() {{
                      printf '%s' '{{"result":{{"ipv4_cidrs":["203.0.113.0/24"],"ipv6_cidrs":["2001:db8::/32"]}}}}'
                    }}
                    write_cloudflare_nginx_snippets
                    cat "$CF_REALIP_SNIPPET"
                    printf '%s\\n' '---'
                    cat "$CF_ALLOW_SNIPPET"
                    """
                )
            )
        self.assertIn("set_real_ip_from 203.0.113.0/24;", output)
        self.assertIn("set_real_ip_from 2001:db8::/32;", output)
        self.assertIn("allow 203.0.113.0/24;", output)
        self.assertIn("deny all;", output)

    def test_runtime_config_rejects_unsupported_cloudflare_ports(self) -> None:
        result = self.run_bash(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export ACCESS_MODE=domain-cf
                export FQDN=monitor.example.com
                export CERT_MODE=dns
                export CF_ZONE_NAME=example.com
                export CF_API_TOKEN=test-token
                export CERTBOT_EMAIL=ops@example.com
                export PUBLIC_HTTP_PORT=81
                source ./install.sh
                validate_runtime_config
                """
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not supported by Cloudflare orange-cloud proxy", result.stderr)

    def test_installer_does_not_destroy_existing_nginx(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("pkill", script)
        self.assertNotIn("killall", script)
        self.assertNotIn("rm -f /etc/nginx/sites-enabled/default", script)

    def test_installer_does_not_restart_existing_docker_daemon(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl restart docker", script)

    def test_installer_marks_existing_checkout_as_safe_directory(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn("safe.directory", script)
        self.assertIn("prepare_git_checkout_permissions", script)

    def test_installer_waits_for_application_health_before_success(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn('run_step "验证 Docker 面板启动状态" wait_for_application_ready', script)
        self.assertIn('run_step "验证应用启动状态" wait_for_application_ready', script)

    def test_xauth_is_installed_for_xvfb_runtime(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        dockerfile = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("xauth", script)
        self.assertIn("xauth", dockerfile)

    def test_docker_version_reporting_uses_env_without_heavy_git_context(self) -> None:
        dockerignore = (ROOT_DIR / ".dockerignore").read_text(encoding="utf-8")
        dockerfile = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn(".git", dockerignore)
        self.assertNotIn("        git \\", dockerfile)
        self.assertIn("APP_VERSION=", script)
        self.assertIn("APP_BRANCH=", script)
        self.assertIn("--docker-upgrade", script)

    def test_docker_deploy_avoids_compose_bake_builds(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("docker_compose up -d --build", script)
        self.assertIn('docker build --pull=false -t "${APP_NAME}-noaff:latest" .', script)
        self.assertIn("docker_compose up -d --no-build --force-recreate noaff", script)

    def test_dashboard_polling_preserves_dirty_settings_inputs(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function syncInputValue", app_js)
        self.assertIn("document.activeElement === input || hasLocalEdit", app_js)
        self.assertIn("syncInputValue(els.settingsChatId", app_js)
        self.assertIn("syncInputValue(els.settingsMonitorPort", app_js)
        self.assertIn("syncInputValue(els.profileUsername", app_js)
        self.assertNotIn("els.profileUsername.value = admin.username", app_js)

    def test_docker_publish_port_conflict_is_reported_cleanly(self) -> None:
        result = self.run_bash(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export PUBLIC_APP_PORT=7777
                source ./install.sh
                command_exists() {
                  [[ "$1" == "ss" || "$1" == "docker" ]]
                }
                ss() {
                  printf '%s\n' 'State  Recv-Q Send-Q Local Address:Port Peer Address:Port Process'
                  printf '%s\n' 'LISTEN 0      4096         0.0.0.0:7777      0.0.0.0:*'
                }
                docker() {
                  if [[ "$1" == "inspect" ]]; then
                    return 1
                  fi
                  return 0
                }
                ensure_docker_publish_port_available
                """
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PUBLIC_APP_PORT=7777 is already in use", result.stderr)

    def test_docker_health_check_failure_stops_installer(self) -> None:
        result = self.run_bash(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export DEPLOY_MODE=docker
                export PORTAL_PATH=/portal_test
                export PUBLIC_APP_PORT=7788
                export APP_STARTUP_TIMEOUT_SECONDS=1
                source ./install.sh
                docker_noaff_container_running() { return 1; }
                docker_compose() { printf 'compose %s\n' "$*"; }
                probe_local_panel() { return 1; }
                sleep() { :; }
                wait_for_application_ready
                """
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Docker app failed health check", result.stderr)

    def test_existing_env_defaults_are_loaded_before_repeat_install(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                mkdir -p "$APP_DIR"
                cat > "$APP_DIR/.env" <<'EOF'
DEPLOY_MODE=docker
ACCESS_MODE=ip
APP_PORT=7788
PUBLIC_APP_PORT=8787
DOCKER_BIND_HOST=127.0.0.1
PORTAL_PATH=/portal_keep
TELEGRAM_CHAT_ID=keep-chat
EOF
                source ./install.sh
                load_existing_env_defaults
                normalize_access_mode
                printf '%s %s %s %s %s %s\n' "$DEPLOY_MODE" "$ACCESS_MODE" "$APP_PORT" "$PUBLIC_APP_PORT" "$DOCKER_BIND_HOST" "$TELEGRAM_CHAT_ID"
                """
            )
        )
        self.assertIn("docker ip 7788 8787 127.0.0.1 keep-chat", output)

    def test_repeat_install_defaults_to_overwrite_update_without_tty(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                mkdir -p "$APP_DIR"
                cat > "$APP_DIR/.env" <<'EOF'
DEPLOY_MODE=docker
APP_PORT=7788
PUBLIC_APP_PORT=8787
PORTAL_PATH=/portal_keep
EOF
                source ./install.sh
                has_tty() { return 1; }
                choose_existing_install_action
                printf 'skip=%s mode=%s port=%s portal=%s\n' "$SKIP_INTERACTIVE_WIZARD" "$DEPLOY_MODE" "$PUBLIC_APP_PORT" "$PORTAL_PATH"
                """
            )
        )
        self.assertIn("skip=true mode=docker port=8787 portal=/portal_keep", output)

    def test_write_env_file_persists_install_context_for_idempotency(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                mkdir -p "$APP_DIR"
                source ./install.sh
                DEPLOY_MODE=docker
                ACCESS_MODE=ip
                ENABLE_NGINX=false
                ENABLE_TLS=false
                CERT_MODE=none
                APP_PORT=7788
                PUBLIC_APP_PORT=8787
                FQDN=monitor.example.com
                CERTBOT_EMAIL=ops@example.com
                CF_RECORD_PROXIED=false
                write_env_file
                grep -E '^(DEPLOY_MODE|ACCESS_MODE|ENABLE_NGINX|ENABLE_TLS|CERT_MODE|APP_PORT|PUBLIC_APP_PORT|FQDN|CERTBOT_EMAIL|CF_RECORD_PROXIED)=' "$APP_DIR/.env"
                """
            )
        )
        self.assertIn("DEPLOY_MODE=docker", output)
        self.assertIn("ACCESS_MODE=ip", output)
        self.assertIn("PUBLIC_APP_PORT=8787", output)
        self.assertIn("FQDN=monitor.example.com", output)
        self.assertIn("CERTBOT_EMAIL=ops@example.com", output)

    def test_non_git_existing_app_dir_is_backed_up_and_data_restored(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                mkdir -p "$APP_DIR/data"
                printf 'PORTAL_PATH=/old\n' > "$APP_DIR/.env"
                printf 'db' > "$APP_DIR/data/monitor.db"
                printf 'stale' > "$APP_DIR/stale.txt"
                source ./install.sh
                git() {
                  if [[ "$1" == "clone" ]]; then
                    local target="${@: -1}"
                    mkdir -p "$target"
                    printf 'new' > "$target/app.py"
                    return 0
                  fi
                  return 0
                }
                clone_or_update_repo
                test -f "$APP_DIR/app.py"
                test -f "$APP_DIR/.env"
                test -f "$APP_DIR/data/monitor.db"
                backup_count="$(find "$temp_dir" -maxdepth 1 -type d -name 'app.backup.*' | wc -l)"
                printf 'backup=%s env=%s data=%s\n' "$backup_count" "$(cat "$APP_DIR/.env")" "$(cat "$APP_DIR/data/monitor.db")"
                """
            )
        )
        self.assertIn("backup=1", output)
        self.assertIn("PORTAL_PATH=/old", output)
        self.assertIn("data=db", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
