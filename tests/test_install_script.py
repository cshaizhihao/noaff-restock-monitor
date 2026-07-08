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
        self.assertIn("--reset-password", output)
        self.assertIn("--uninstall", output)

    def test_validate_only_accepts_complete_configuration(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                ACCESS_MODE=domain-cf \
                FQDN=monitor.example.com \
                CF_ZONE_NAME=example.com \
                CF_API_TOKEN=test-token \
                CERTBOT_EMAIL=ops@noaff.dev \
                bash install.sh --validate-only
                """
            )
        )
        self.assertIn("NOAFF installer validation passed.", output)
        self.assertIn("APP_BIND:          127.0.0.1:7777", output)
        self.assertIn("PUBLIC_HTTPS_PORT: 443", output)
        self.assertIn("MONITOR/TEST/CAT CDP: 9223/9334/9445", output)

    def test_python_runtime_bootstrap_installs_python3_when_missing(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                source ./install.sh
                command_exists() {
                  [[ "$1" != "python3" ]]
                }
                apt_get_update() {
                  printf 'update-called\n'
                }
                apt_install() {
                  printf 'apt-install:%s\n' "$*"
                }
                ensure_python_runtime
                """
            )
        )
        self.assertIn("检测到系统尚未安装 Python 3", output)
        self.assertIn("update-called", output)
        self.assertIn("apt-install:python3", output)

    def test_validate_only_accepts_ip_mode_without_domain(self) -> None:
        output = self.assert_shell_ok("ACCESS_MODE=ip APP_PORT=7777 bash install.sh --validate-only")
        self.assertIn("ACCESS_MODE:       ip", output)
        self.assertIn("FQDN:              IP mode", output)
        self.assertIn("ENABLE_TLS:        false", output)

    def test_validate_only_does_not_bootstrap_python_runtime(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                source ./install.sh

                ensure_python_runtime() {
                  printf 'bootstrap-called\n'
                  return 1
                }

                python3() {
                  printf 'python3-called\n'
                  return 1
                }

                ACCESS_MODE=domain-direct \
                FQDN=monitor.example.com \
                CERTBOT_EMAIL=ops@noaff.dev \
                main --validate-only
                """
            )
        )
        self.assertIn("NOAFF installer validation passed.", output)
        self.assertNotIn("bootstrap-called", output)
        self.assertNotIn("python3-called", output)

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
                CERTBOT_EMAIL=ops@noaff.dev \
                CF_RECORD_PROXIED=false \
                bash install.sh --validate-only
                """
            )
        )
        self.assertIn("ACCESS_MODE:       domain-direct", output)
        self.assertIn("CERT_MODE:         http", output)
        self.assertIn("CF_RECORD_PROXIED: false", output)

    def test_validate_only_rejects_placeholder_certbot_email(self) -> None:
        result = self.run_bash(
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
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CERTBOT_EMAIL must be a real email address", result.stderr)

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

    def test_nginx_tls_config_always_writes_ssl_snippet(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                source ./install.sh
                printf '%s\n' "$(declare -f configure_nginx)"
                printf '%s\n' "$(declare -f write_ssl_nginx_snippet)"
                """
            )
        )
        self.assertIn("write_ssl_nginx_snippet", output)
        self.assertIn('cat > "$SSL_SNIPPET"', output)

    def test_http_certificate_failure_can_fallback_to_http_install(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export ACCESS_MODE=domain-direct
                export FQDN=monitor.example.com
                export CERT_MODE=http
                export ENABLE_TLS=true
                export CERTBOT_EMAIL=ops@noaff.dev
                export CERTBOT_BIN=fake_certbot
                source ./install.sh
                write_acme_challenge_nginx() { :; }
                fake_certbot() { return 1; }
                detect_origin_ips() { ORIGIN_IPV4=203.0.113.10; }
                has_tty() { return 0; }
                prompt_yes_no() { return 0; }
                issue_certificate_http
                printf 'tls=%s cert=%s secure=%s\n' "$ENABLE_TLS" "$CERT_MODE" "$SESSION_COOKIE_SECURE"
                """
            )
        )
        self.assertIn("HTTPS 证书申请失败：公网 HTTP-01 验证没有通过", output)
        self.assertIn("tls=false cert=none secure=false", output)

    def test_http_mode_summary_warns_about_https_only_browsers(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export ACCESS_MODE=domain-direct
                export ENABLE_TLS=false
                export FQDN=monitor.example.com
                source ./install.sh
                normalize_access_mode
                print_install_summary
                final_summary
                """
            )
        )
        self.assertIn("当前为 HTTP 模式，请直接访问 http://monitor.example.com", output)
        self.assertIn("HTTPS-Only / HSTS", output)

    def test_nginx_tls_config_uses_modern_http2_directive(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                source ./install.sh
                printf '%s\n' "$(declare -f configure_nginx)"
                """
            )
        )
        self.assertIn("http2 on;", output)
        self.assertNotIn("ssl http2", output)

    def test_nginx_tls_config_keeps_acme_challenge_locations(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                source ./install.sh
                printf '%s\n' "$(declare -f configure_nginx)"
                """
            )
        )
        self.assertGreaterEqual(output.count("location /.well-known/acme-challenge/"), 2)
        self.assertIn('root ${ACME_WEBROOT};', output)

    def test_cloudflare_lockdown_does_not_block_real_visitors_after_realip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir).as_posix()
            output = self.assert_shell_ok(
                textwrap.dedent(
                    f"""
                    set -Eeuo pipefail
                    export NOAFF_INSTALL_LIBRARY_MODE=true
                    export ENABLE_NGINX=true
                    export ENABLE_TLS=true
                    export ORIGIN_LOCKDOWN_TO_CLOUDFLARE=true
                    export FQDN=monitor.example.com
                    export TLS_DOMAINS=monitor.example.com
                    export APP_HOST=127.0.0.1
                    export APP_PORT=7777
                    export PUBLIC_HTTP_PORT=80
                    export PUBLIC_HTTPS_PORT=443
                    source ./install.sh
                    NGINX_SITE_PATH='{temp_path}/site.conf'
                    NGINX_SITE_LINK='{temp_path}/site-link.conf'
                    SSL_SNIPPET='{temp_path}/ssl.conf'
                    CF_REALIP_SNIPPET='{temp_path}/realip.conf'
                    CF_ALLOW_SNIPPET='{temp_path}/allow.conf'
                    ACME_WEBROOT='{temp_path}/acme'
                    restart_nginx_safely() {{ :; }}
                    configure_nginx
                    cat "$NGINX_SITE_PATH"
                    """
                )
            )
        self.assertIn(f"include {temp_path}/allow.conf;", output)
        self.assertNotIn(f"include {temp_path}/realip.conf;", output)
        self.assertIn("try_files /__noaff_https_redirect__ @noaff_https_redirect;", output)
        self.assertIn("location @noaff_https_redirect", output)
        self.assertIn("proxy_set_header X-Real-IP $http_cf_connecting_ip;", output)
        self.assertIn("proxy_set_header X-Forwarded-For $http_cf_connecting_ip;", output)

    def test_nginx_restart_can_reclaim_only_stale_nginx_ports(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                source ./install.sh
                printf '%s\n' "$(declare -f restart_nginx_safely)"
                printf '%s\n' "$(declare -f nginx_managed_ports_held_only_by_nginx)"
                printf '%s\n' "$(declare -f stop_stale_nginx_processes)"
                """
            )
        )
        self.assertIn("nginx_managed_ports_held_only_by_nginx", output)
        self.assertIn("stop_stale_nginx_processes", output)
        self.assertIn("pkill -TERM nginx", output)
        self.assertIn("安装脚本不会杀掉其他服务", output)

    def test_domain_modes_force_standard_public_ports_and_clean_url(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export ACCESS_MODE=domain-cf
                export FQDN=https://monitor.example.com:20443/portal_old
                export CERT_MODE=dns
                export CF_ZONE_NAME=example.com
                export CF_API_TOKEN=test-token
                export CERTBOT_EMAIL=ops@noaff.dev
                export PUBLIC_HTTP_PORT=81
                export PUBLIC_HTTPS_PORT=20443
                export TLS_DOMAINS=https://monitor.example.com:20443/portal_old,www.example.com:9443
                source ./install.sh
                validate_runtime_config
                printf 'ports=%s/%s url=%s tls=%s\n' "$PUBLIC_HTTP_PORT" "$PUBLIC_HTTPS_PORT" "$(build_public_url)" "$TLS_DOMAINS"
                """
            )
        )
        self.assertIn("ports=80/443 url=https://monitor.example.com", output)
        self.assertIn("tls=monitor.example.com,www.example.com", output)
        self.assertNotIn("20443", output)
        self.assertNotIn("portal_old", output)

    def test_installer_does_not_destroy_existing_nginx(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("killall", script)
        self.assertNotIn("rm -f /etc/nginx/sites-enabled/default", script)
        self.assertIn("pkill -TERM nginx", script)
        self.assertIn("nginx_managed_ports_held_only_by_nginx", script)

    def test_installer_does_not_restart_existing_docker_daemon(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl restart docker", script)

    def test_management_cli_contains_safe_uninstall_menu(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                export CLI_SCRIPT="${temp_dir}/noaff"
                mkdir -p "$APP_DIR"
                source ./install.sh
                write_management_cli
                test -x "$CLI_SCRIPT"
                grep -F '清理/卸载 NOAFF' "$CLI_SCRIPT"
                grep -F 'docker_compose down --remove-orphans' "$CLI_SCRIPT"
                grep -F 'rm -f "$NGINX_SITE_LINK" "$NGINX_SITE_PATH"' "$CLI_SCRIPT"
                grep -F '用法: noaff [status|logs|restart|upgrade|reset-password|uninstall]' "$CLI_SCRIPT"
                """
            )
        )
        self.assertIn("清理/卸载 NOAFF", output)
        self.assertIn("docker_compose down --remove-orphans", output)

    def test_install_script_can_uninstall_without_management_cli(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                export CLI_SCRIPT="${temp_dir}/noaff"
                export DELETE_APP_DIR=true
                mkdir -p "$APP_DIR/data"
                printf 'db' > "$APP_DIR/data/monitor.db"
                printf 'shortcut' > "$CLI_SCRIPT"
                source ./install.sh
                command_exists() { return 1; }
                uninstall_noaff_installation
                test ! -e "$APP_DIR"
                test ! -e "$CLI_SCRIPT"
                printf 'uninstalled\n'
                """
            )
        )
        self.assertIn("uninstalled", output)

    def test_uninstall_does_not_bootstrap_python_runtime(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                export CLI_SCRIPT="${temp_dir}/noaff"
                mkdir -p "$APP_DIR/data"
                source ./install.sh
                INSTALL_LOG="${temp_dir}/install.log"

                require_root() { :; }
                ensure_python_runtime() {
                  printf 'bootstrap-called\n'
                  return 1
                }
                python3() {
                  printf 'python3-called\n'
                  return 1
                }
                uninstall_noaff_installation() {
                  printf 'uninstall-called\n'
                }

                main --uninstall
                """
            )
        )
        self.assertIn("uninstall-called", output)
        self.assertNotIn("bootstrap-called", output)
        self.assertNotIn("python3-called", output)

    def test_native_installs_management_cli_before_certificate_steps(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        clone_step = 'run_step "拉取或更新应用源码" clone_or_update_repo'
        cli_step = 'run_step "安装 noaff 快捷管理命令" write_management_cli'
        certbot_step = 'run_step "安装 Certbot 证书运行环境" setup_certbot_env'
        self.assertLess(script.rindex(clone_step), script.rindex(cli_step))
        self.assertLess(script.rindex(cli_step), script.rindex(certbot_step))

    def test_installer_marks_existing_checkout_as_safe_directory(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn("safe.directory", script)
        self.assertIn("prepare_git_checkout_permissions", script)

    def test_installer_waits_for_application_health_before_success(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn('run_step "验证 Docker 面板启动状态" wait_for_application_ready', script)
        self.assertIn('run_step "验证应用启动状态" wait_for_application_ready', script)
        self.assertIn("/healthz", script)
        self.assertIn("HEALTHCHECK_LAST_STATUS", script)
        self.assertIn("print_healthcheck_diagnostics", script)

    def test_native_ip_install_step_count_succeeds_without_tls(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export DEPLOY_MODE=native
                export ACCESS_MODE=ip
                export APP_PORT=7777
                export CERT_MODE=none
                source ./install.sh
                normalize_access_mode
                set_total_steps
                printf 'steps=%s nginx=%s tls=%s\n' "$TOTAL_STEPS" "$ENABLE_NGINX" "$ENABLE_TLS"
                """
            )
        )
        self.assertIn("steps=10 nginx=false tls=false", output)

    def test_native_install_releases_only_noaff_owned_port_before_start(self) -> None:
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn("release_native_app_port", script)
        self.assertIn('systemctl stop "${APP_NAME}"', script)
        self.assertIn("stop_existing_noaff_container", script)
        self.assertIn('-e "/opt/noaff_monitor"', script)
        self.assertIn('"/opt/noaff_monitor/app.py"', script)
        self.assertIn("安装器不会误杀非 NOAFF 进程", script)
        self.assertIn("iproute2 lsof", script)

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
        self.assertIn("wireDirtyTracking(input)", app_js)
        self.assertIn("input.dataset.inputDirty", app_js)
        self.assertIn("syncInputValue(els.settingsChatIds", app_js)
        self.assertIn("syncInputValue(els.settingsMonitorPort", app_js)
        self.assertIn("syncInputValue(els.profileUsername", app_js)
        self.assertNotIn("els.profileUsername.value = admin.username", app_js)

    def test_dashboard_polling_updates_task_cards_in_place(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("let taskStateSignature = \"\"", app_js)
        self.assertIn("function updateTaskCard(task)", app_js)
        self.assertIn("const detail = task.last_error_detail || task.last_error", app_js)
        self.assertIn("data-task-status", app_js)
        self.assertIn("data-task-stock", app_js)
        self.assertIn("data-task-log", app_js)
        self.assertIn("data-task-meta", app_js)
        self.assertIn("data-task-toggle", app_js)
        self.assertIn("data-task-keyword-text", app_js)
        self.assertIn("data-task-group-section", app_js)
        self.assertIn("data-task-group-error", app_js)

    def test_dashboard_manual_and_webhook_controls_are_wired(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")
        self.assertIn('id="task-fetch-strategy"', portal_html)
        self.assertIn('value="generic_pricing_table"', portal_html)
        self.assertIn('value="whmcs"', portal_html)
        self.assertIn('value="manual"', portal_html)
        self.assertIn('value="webhook"', portal_html)
        task_strategy_block = portal_html.split('id="task-fetch-strategy"', 1)[1].split("</select>", 1)[0]
        self.assertLess(task_strategy_block.index('value="adaptive"'), task_strategy_block.index('value="firecrawl"'))
        self.assertLess(task_strategy_block.index('value="browser"'), task_strategy_block.index('value="firecrawl"'))
        self.assertIn("自适应低成本（推荐）", task_strategy_block)
        self.assertIn("Firecrawl 外部兜底（消耗 credits）", task_strategy_block)
        self.assertIn('id="task-strategy-help"', portal_html)
        self.assertIn('id="task-strategy-summary"', portal_html)
        self.assertIn("Firecrawl 属于外部付费兜底，默认不参与定时监控", portal_html)
        self.assertIn('id="task-webhook-hint"', portal_html)
        self.assertIn('id="task-first-check-hint"', portal_html)
        self.assertIn("保存或编辑完成后，建议点击“保存并立即检测”", portal_html)
        self.assertIn("function fetchStrategyHelp", app_js)
        self.assertIn('return "adaptive";', app_js)
        self.assertIn("不会默认消耗 Firecrawl credits", app_js)
        self.assertIn("function updateTaskStrategyUi", app_js)
        self.assertIn("只有 Webhook 任务才会显示 Token 重置操作", app_js)
        self.assertIn("els.taskFetchStrategy?.addEventListener(\"change\", updateTaskStrategyUi)", app_js)
        self.assertIn("data-task-manual-actions", app_js)
        self.assertIn('data-action="manual-in-stock"', app_js)
        self.assertIn('data-action="manual-sold-out"', app_js)
        self.assertIn("data-task-webhook-meta", app_js)
        self.assertIn('data-action="webhook-token"', app_js)
        self.assertIn('data-task-webhook-action>重置 Token</button>', app_js)
        self.assertIn('normalizedStrategy === "webhook" ? "" : "hidden"', app_js)
        self.assertIn("data-task-check-action", app_js)
        self.assertIn('data-action="check"', app_js)
        self.assertIn("/api/tasks/${taskId}/check", app_js)
        self.assertIn('id="task-save-check-button"', portal_html)
        self.assertIn("保存并立即检测", portal_html)
        self.assertIn("runTaskStockCheck(savedTaskId, { showToast: false })", app_js)
        self.assertIn("节点已创建", app_js)
        self.assertIn("节点已更新", app_js)
        self.assertIn("检测结果：", app_js)
        self.assertIn("/manual-stock", app_js)
        self.assertIn("/webhook-token", app_js)
        self.assertIn("copyText(token)", app_js)

    def test_dashboard_task_error_labels_are_user_readable(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('case "firecrawl_monitor_disabled":', app_js)
        self.assertIn("Firecrawl 定时监控未启用", app_js)
        self.assertIn('case "firecrawl_credit_required":', app_js)
        self.assertIn("Firecrawl 额度不足", app_js)
        self.assertIn('case "firecrawl_rate_limited":', app_js)
        self.assertIn("Firecrawl 频率受限", app_js)
        self.assertIn('case "firecrawl_upstream_error":', app_js)
        self.assertIn("Firecrawl 服务异常", app_js)
        self.assertIn('case "firecrawl_bad_response":', app_js)
        self.assertIn("Firecrawl 响应异常", app_js)
        self.assertIn('case "parse_unknown":', app_js)
        self.assertIn("解析器无法判断库存", app_js)
        self.assertIn('case "catalog_browser_port_busy":', app_js)
        self.assertIn("商品入库浏览器端口被占用", app_js)

    def test_dashboard_template_editor_controls_are_wired(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")
        self.assertIn("【补货提醒】", app_js)
        self.assertIn("【售罄提醒】", app_js)
        self.assertIn('id="task-template-help-button"', portal_html)
        self.assertIn('id="template-help-modal"', portal_html)
        self.assertIn('id="task-template-test-kind"', portal_html)
        self.assertIn('id="task-template-test-chat-ids"', portal_html)
        self.assertIn('id="task-template-test-button"', portal_html)
        self.assertIn("{source_name}", portal_html)
        self.assertIn("{source_url}", portal_html)
        self.assertIn("function collectTemplateTestPayload", app_js)
        self.assertIn("function sendTemplateTestPush", app_js)
        self.assertIn("/api/template-test-push", app_js)
        self.assertIn("openTemplateHelpModal", app_js)
        self.assertIn("closeTemplateHelpModal", app_js)

    def test_release_notes_capture_protected_source_boundary(self) -> None:
        release_notes = (ROOT_DIR / "docs" / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        self.assertIn("does not bypass Cloudflare / Turnstile / CAPTCHA", release_notes)
        self.assertIn("Cloudflare / Turnstile / CAPTCHA challenge pages are treated as protected sources", release_notes)
        self.assertIn("Webhook tokens are stored as HMAC hashes", release_notes)
        self.assertIn("152 tests passing", release_notes)
        self.assertIn("Firecrawl connection diagnostics", release_notes)
        self.assertIn("product intake noise filtering", release_notes)
        self.assertIn("does not save or expose plaintext API keys", release_notes)
        self.assertIn("FIRECRAWL_MAX_AGE_MS=0", release_notes)
        self.assertIn("catalog_discovery_strategy: firecrawl_map", release_notes)

    def test_env_example_documents_firecrawl_and_catalog_defaults(self) -> None:
        env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
        self.assertIn("FIRECRAWL_ENABLED=false", env_example)
        self.assertIn("FIRECRAWL_MAX_AGE_MS=0", env_example)
        self.assertIn("FIRECRAWL_STORE_IN_CACHE=false", env_example)
        self.assertIn("FIRECRAWL_USE_FOR_MONITOR=false", env_example)
        self.assertIn("FIRECRAWL_USE_FOR_CATALOG=true", env_example)
        self.assertIn("CATALOG_DISCOVERY_STRATEGY=local", env_example)
        self.assertIn("CATALOG_SCRAPE_STRATEGY=browser", env_example)
        self.assertIn("CATALOG_DEFAULT_FETCH_STRATEGY=browser", env_example)
        self.assertIn("CATALOG_DEFAULT_EXTRACTOR=generic_pricing_table", env_example)
        self.assertIn("CATALOG_DEDUPE_POLICY=by_url", env_example)

    def test_dashboard_polling_does_not_replay_task_reveal_animation(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("let tasksRendered = false", app_js)
        self.assertIn("const animateCards = initial || !tasksRendered || taskIdsSignature !== nextTaskIdsSignature", app_js)
        self.assertIn('const rowClass = animateCards ? "task-row reveal" : "task-row"', app_js)
        self.assertIn("renderSnapshot(data, initial)", app_js)

    def test_dashboard_polling_skips_unchanged_logs_and_merchant_sections(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("let logsSignature = null", app_js)
        self.assertIn("let merchantSignature = null", app_js)
        self.assertIn("const nextLogsSignature = Array.isArray(logs)", app_js)
        self.assertIn("if (logsSignature !== null && nextLogsSignature === logsSignature) {", app_js)
        self.assertIn("const nextMerchantSignature = [", app_js)
        self.assertIn("if (merchantSignature !== null && nextMerchantSignature === merchantSignature) {", app_js)

    def test_dashboard_backup_controls_are_wired(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        app_css = (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8")
        app_py = (ROOT_DIR / "app.py").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")
        readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("backupExportButton", app_js)
        self.assertIn("backupRestoreButton", app_js)
        self.assertIn("backupFileInput", app_js)
        self.assertIn("exportBackup", app_js)
        self.assertIn("restoreBackup", app_js)
        self.assertNotIn("cdn.tailwindcss.com", portal_html)
        self.assertNotIn("window.APP_CONTEXT", portal_html)
        self.assertNotIn('style="animation-delay:', portal_html)
        self.assertIn('tailwind.css', portal_html)
        self.assertNotIn("fonts.googleapis.com", app_css)
        self.assertNotIn("fonts.gstatic.com", app_css)
        self.assertNotIn("unsafe-inline", app_py)
        self.assertNotIn("shields.io", readme)
        self.assertIn('id="backup-export-button"', portal_html)
        self.assertIn('id="backup-file-input"', portal_html)
        self.assertIn('id="backup-restore-button"', portal_html)
        self.assertIn('name="username"', portal_html)
        self.assertIn('name="password"', portal_html)
        self.assertIn('name="profile_username"', portal_html)
        self.assertIn('name="current_password"', portal_html)
        self.assertIn('name="new_password"', portal_html)
        self.assertIn('name="confirm_password"', portal_html)
        self.assertGreaterEqual(portal_html.count('autocomplete="username"'), 2)
        self.assertIn('autocomplete="current-password"', portal_html)
        self.assertEqual(portal_html.count('autocomplete="new-password"'), 2)

    def test_dashboard_uses_accessible_ops_visual_system(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        app_css = (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")
        self.assertNotIn("ambient-blob", portal_html)
        self.assertIn("--color-accent: #22c55e", app_css)
        self.assertIn("focus-visible", app_css)
        self.assertIn("prefers-reduced-motion", app_css)
        self.assertIn(".task-actions", app_css)
        self.assertIn('class="task-actions', app_js)
        self.assertNotIn("精准狙击关键词", portal_html)
        self.assertNotIn("库存嗅探", app_js)

    def test_dashboard_supports_hierarchical_sortable_task_cards(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        app_css = (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")
        self.assertIn('taskGroup: document.getElementById("task-group")', app_js)
        self.assertIn('taskGroupCustomWrap: document.getElementById("task-group-custom-wrap")', app_js)
        self.assertIn('taskGroupCustom: document.getElementById("task-group-custom")', app_js)
        self.assertIn('taskSubgroup: document.getElementById("task-subgroup")', app_js)
        self.assertIn('taskSubgroupCustomWrap: document.getElementById("task-subgroup-custom-wrap")', app_js)
        self.assertIn('taskSubgroupCustom: document.getElementById("task-subgroup-custom")', app_js)
        self.assertIn('settingsChatIds: document.getElementById("settings-chat-ids")', app_js)
        self.assertIn('merchantGroup: document.getElementById("merchant-group")', app_js)
        self.assertIn('merchantGroupCustomWrap: document.getElementById("merchant-group-custom-wrap")', app_js)
        self.assertIn('merchantGroupCustom: document.getElementById("merchant-group-custom")', app_js)
        self.assertIn("let taskBrowserPath", app_js)
        self.assertIn("let taskDragState", app_js)
        self.assertIn('view: "children"', app_js)
        self.assertIn("function collectTaskBrowserGroups", app_js)
        self.assertIn("function collectChildSubgroups", app_js)
        self.assertIn("function taskBrowserView", app_js)
        self.assertIn("function setTaskBrowserPath", app_js)
        self.assertIn("function collectGroupNames", app_js)
        self.assertIn("function renderTaskGroupOptions", app_js)
        self.assertIn("function renderTaskSubgroupOptions", app_js)
        self.assertIn("function renderMerchantGroupOptions", app_js)
        self.assertIn("function setTaskGroupSelection", app_js)
        self.assertIn("function setTaskSubgroupSelection", app_js)
        self.assertIn("function readTaskGroupValue", app_js)
        self.assertIn("function readTaskSubgroupValue", app_js)
        self.assertIn("function readMerchantGroupValue", app_js)
        self.assertIn("data-group-open", app_js)
        self.assertIn("data-subgroup-open", app_js)
        self.assertIn("data-task-products-open", app_js)
        self.assertIn("data-task-products-back", app_js)
        self.assertIn("data-task-browser-back", app_js)
        self.assertIn("data-task-crumb-group", app_js)
        self.assertIn('data-group-action="rename"', app_js)
        self.assertIn('data-group-action="delete"', app_js)
        self.assertIn('data-group-action="bulk-delete"', app_js)
        self.assertIn('data-subgroup-action="create"', app_js)
        self.assertIn('data-subgroup-action="rename"', app_js)
        self.assertIn('data-subgroup-action="bulk-delete"', app_js)
        self.assertIn("data-task-subgroup-section", app_js)
        self.assertIn("data-task-select", app_js)
        self.assertIn('data-drag-kind="group"', app_js)
        self.assertIn('data-drag-kind="subgroup"', app_js)
        self.assertIn('data-drag-kind="task"', app_js)
        self.assertIn('draggable="true"', app_js)
        self.assertIn("function handleTaskDragStart", app_js)
        self.assertIn("function persistTaskDragOrder", app_js)
        self.assertIn("/api/tasks/bulk-delete", app_js)
        self.assertIn("/api/task-groups/delete", app_js)
        self.assertIn("/api/task-subgroups/delete", app_js)
        self.assertIn("/api/task-groups/reorder", app_js)
        self.assertIn("/api/task-subgroups/reorder", app_js)
        self.assertIn("/api/tasks/reorder", app_js)
        self.assertIn(".task-browser-grid", app_css)
        self.assertIn(".task-browser-card", app_css)
        self.assertIn(".task-browser-card-products", app_css)
        self.assertIn(".task-products-panel", app_css)
        self.assertIn(".task-drag-handle", app_css)
        self.assertIn(".is-dragging", app_css)
        self.assertIn("const groupName = readTaskGroupValue();", app_js)
        self.assertIn("const subgroupName = readTaskSubgroupValue();", app_js)
        self.assertIn("group_name: groupName", app_js)
        self.assertIn("subgroup_name: subgroupName", app_js)
        self.assertIn('id="task-group"', portal_html)
        self.assertIn('id="task-group-custom-wrap"', portal_html)
        self.assertIn('id="task-group-custom"', portal_html)
        self.assertIn('id="task-subgroup"', portal_html)
        self.assertIn('id="task-subgroup-custom-wrap"', portal_html)
        self.assertIn('id="task-subgroup-custom"', portal_html)
        self.assertIn('value="__custom__"', portal_html)
        self.assertIn('id="settings-chat-ids"', portal_html)
        self.assertIn('id="merchant-group"', portal_html)
        self.assertIn('id="merchant-group-custom-wrap"', portal_html)
        self.assertIn('id="merchant-group-custom"', portal_html)

    def test_settings_ui_splits_product_intake_and_firecrawl_integration(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        app_css = (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")

        self.assertIn('id="nav-merchant"', portal_html)
        self.assertIn('id="merchant-view"', portal_html)
        self.assertIn('id="settings-view"', portal_html)
        self.assertIn("Firecrawl 集成", portal_html)
        self.assertIn('id="settings-firecrawl-api-key" type="password"', portal_html)
        self.assertIn('id="settings-firecrawl-test-button"', portal_html)
        self.assertIn('id="settings-firecrawl-test-result"', portal_html)
        self.assertIn("测试 Firecrawl 连接", portal_html)
        self.assertIn("不会保存 Key，也不会在响应里返回 Key", portal_html)
        self.assertIn('settingsFirecrawlApiKey: document.getElementById("settings-firecrawl-api-key")', app_js)
        self.assertIn('settingsFirecrawlTestButton: document.getElementById("settings-firecrawl-test-button")', app_js)
        self.assertIn("function collectFirecrawlDiagnosticPayload", app_js)
        self.assertIn("function testFirecrawlConnection", app_js)
        self.assertIn("/api/settings/firecrawl-test", app_js)
        self.assertIn('settingsFirecrawlTestButton?.addEventListener("click", testFirecrawlConnection)', app_js)
        self.assertIn("firecrawl_api_key", app_js)
        self.assertIn(".settings-layout", app_css)
        self.assertIn(".settings-nav-item", app_css)
        self.assertIn('id="settings-home"', portal_html)
        self.assertIn('id="settings-pages"', portal_html)
        self.assertIn('data-settings-target="settings-runtime"', portal_html)
        self.assertIn("data-settings-back", portal_html)
        self.assertIn("function openSettingsHome", app_js)
        self.assertIn("function openSettingsPage", app_js)
        self.assertIn("function openFirecrawlGuideModal", app_js)
        self.assertIn("function renderFirecrawlGuide", app_js)
        self.assertIn("translateX(-${firecrawlGuideIndex * 100}%)", app_js)
        self.assertIn('id="firecrawl-guide-modal"', portal_html)
        self.assertIn('id="firecrawl-guide-track"', portal_html)
        self.assertIn('id="firecrawl-guide-prev"', portal_html)
        self.assertIn('id="firecrawl-guide-next"', portal_html)
        self.assertIn('data-firecrawl-step="4"', portal_html)
        self.assertIn("Firecrawl 集成使用步骤", portal_html)
        self.assertIn("程序已经集成 Firecrawl", portal_html)
        self.assertIn("API Key 绑定你的账号、额度和费用", portal_html)
        self.assertIn("https://www.firecrawl.dev/app", portal_html)
        self.assertIn("settings-firecrawl", app_js)
        self.assertIn(".settings-firecrawl-grid", app_css)
        self.assertIn(".firecrawl-test-box", app_css)
        self.assertIn(".firecrawl-test-result.is-ok", app_css)
        self.assertIn(".firecrawl-test-result.is-error", app_css)
        self.assertIn(".settings-log-box", app_css)
        self.assertIn(".firecrawl-guide-track", app_css)
        self.assertIn(".firecrawl-guide-slide", app_css)
        self.assertIn(".firecrawl-guide-dots", app_css)
        self.assertNotIn("firecrawl-guide-steps", portal_html)
        self.assertNotIn("firecrawl-guide-copy", portal_html)
        self.assertIn("settings-entry-top", portal_html)
        self.assertIn("settings-entry-bottom", portal_html)
        self.assertEqual(portal_html.count("settings-entry-top"), 3)
        self.assertEqual(portal_html.count("settings-entry-bottom"), 3)
        self.assertIn("grid-template-columns: repeat(3", app_css)
        settings_home = portal_html.split('id="settings-home"', 1)[1].split('id="settings-pages"', 1)[0]
        self.assertNotIn("升级与维护", settings_home)

        settings_block = portal_html.split('id="settings-view"', 1)[1].split('id="task-modal"', 1)[0]
        self.assertNotIn('id="merchant-form"', settings_block)
        self.assertNotIn('id="merchant-discovery-strategy"', settings_block)
        self.assertNotIn('id="merchant-default-extractor"', settings_block)
        combined_ui = portal_html + app_css
        self.assertNotIn("column-count", combined_ui)
        self.assertNotIn("grid-auto-flow: dense", combined_ui)
        self.assertNotIn("masonry", combined_ui.lower())
        self.assertNotIn("waterfall", combined_ui.lower())

    def test_dashboard_uses_linear_lists_instead_of_waterfall_cards(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        app_css = (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")

        self.assertIn("task-list-stack", app_js)
        self.assertIn(".task-list-stack", app_css)
        self.assertIn("task-browser-shell", app_js)
        self.assertIn("task-browser-grid", app_js)
        self.assertIn(".task-browser-shell", app_css)
        self.assertIn(".task-browser-card", app_css)
        self.assertIn("[data-drag-scope]", app_css)
        self.assertIn(".task-row", app_css)
        self.assertIn("min-height: 0;", app_css)
        self.assertIn("align-content: start;", app_css)
        self.assertIn("align-items: start;", app_css)
        self.assertIn("grid-auto-rows: min-content;", app_css)
        self.assertIn("intake-results-stack", portal_html)
        self.assertNotIn("min-height: min(64vh", app_css)
        self.assertNotIn("task-table-shell", app_js)
        self.assertNotIn(".task-table-shell", app_css)
        self.assertNotIn("task-table-head", app_js)
        self.assertNotIn(".task-table-head", app_css)
        self.assertNotIn("task-card", app_js)
        self.assertNotIn(".task-card", app_css)
        self.assertNotIn("add-card", app_js)
        self.assertNotIn(".add-card", app_css)
        self.assertNotIn("md:grid-cols-2 xl:grid-cols-3", app_js)
        self.assertNotIn("md:grid-cols-2 xl:grid-cols-3", portal_html)
        self.assertNotIn("xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]", portal_html)
        self.assertNotIn("column-count", app_css)
        self.assertNotIn("grid-auto-flow: dense", app_css)

    def test_product_intake_workbench_exposes_round7_controls(self) -> None:
        app_js = (ROOT_DIR / "static" / "app.js").read_text(encoding="utf-8")
        portal_html = (ROOT_DIR / "templates" / "portal.html").read_text(encoding="utf-8")

        for element_id in (
            "merchant-stepper",
            "merchant-step-source",
            "merchant-step-strategy",
            "merchant-step-rules",
            "merchant-step-review",
            "merchant-step-sources",
            "merchant-step-items",
            "merchant-step-recovery",
            "merchant-review-summary",
            "merchant-preview-scrape-button",
            "merchant-preview-commit-button",
            "merchant-preview-url-count",
            "merchant-source-url",
            "merchant-discovery-strategy",
            "merchant-scrape-strategy",
            "merchant-default-extractor",
            "merchant-search-keyword",
            "merchant-target-keyword",
            "merchant-target-keyword-mode",
            "merchant-dedupe-policy",
            "merchant-max-discovered-urls",
            "merchant-max-import-items",
            "merchant-timeout-seconds",
            "merchant-bulk-promote-button",
            "merchant-firecrawl-state",
        ):
            self.assertIn(f'id="{element_id}"', portal_html)

        self.assertIn('data-merchant-step-target="source"', portal_html)
        self.assertIn('data-merchant-step-target="items"', portal_html)
        self.assertIn('data-merchant-internal-scroll', portal_html)
        self.assertIn(".merchant-workbench", (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn(".merchant-stepper", (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn(".merchant-scroll-box", (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8"))
        self.assertIn("function setMerchantStep", app_js)
        self.assertIn("function renderMerchantReviewSummary", app_js)
        self.assertIn("function discoverMerchantCandidateUrls", app_js)
        self.assertIn("function scrapeMerchantPreviewUrls", app_js)
        self.assertIn("function commitMerchantPreviewItems", app_js)
        self.assertIn("/api/merchant/discover", app_js)
        self.assertIn("/api/merchant/preview", app_js)
        self.assertIn("/api/merchant/commit", app_js)
        self.assertNotIn("/api/merchant/import\", {", app_js)
        self.assertIn("confidence", app_js)
        self.assertIn("include_reason", app_js)
        self.assertIn("需要人工确认", app_js)
        self.assertIn("merchant-preview-summary", app_js)
        self.assertIn("merchant-preview-help", app_js)
        self.assertIn("merchant-signal-box", app_js)
        self.assertIn("merchant-preview-section-title", app_js)
        app_css = (ROOT_DIR / "static" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".merchant-preview-summary", app_css)
        self.assertIn(".merchant-preview-help", app_css)
        self.assertIn("发现结果", portal_html)
        self.assertIn("商品预览", portal_html)
        self.assertIn("错误恢复建议", portal_html)
        self.assertIn("按“来源 → 采集 → 规则 → 执行 → 发现结果 → 商品预览”逐步入库", portal_html)
        self.assertIn("第一步只发现候选 URL", portal_html)
        self.assertIn("进入“发现结果”后再抓取选中 URL", portal_html)
        self.assertIn("语言切换、导航、步骤标题、页脚、无价格/无规格的候选", portal_html)
        self.assertIn("导入异常时优先填写商品型号、地区或线路关键词", portal_html)
        discovery_block = portal_html.split('id="merchant-discovery-strategy"', 1)[1].split("</select>", 1)[0]
        scrape_block = portal_html.split('id="merchant-scrape-strategy"', 1)[1].split("</select>", 1)[0]
        task_strategy_block = portal_html.split('id="merchant-default-fetch-strategy"', 1)[1].split("</select>", 1)[0]
        self.assertLess(discovery_block.index('value="firecrawl_map"'), discovery_block.index('value="local"'))
        self.assertLess(scrape_block.index('value="firecrawl"'), scrape_block.index('value="browser"'))
        self.assertLess(task_strategy_block.index('value="firecrawl"'), task_strategy_block.index('value="browser"'))
        self.assertIn("catalog_browser_port_busy", portal_html)
        self.assertIn("firecrawl_zdr_not_enabled", portal_html)
        self.assertIn("firecrawl_credit_required", portal_html)
        self.assertIn("cloudflare_challenge", portal_html)

        self.assertIn("function updateMerchantFirecrawlOptions", app_js)
        self.assertIn('setOptionAvailability(els.merchantDiscoveryStrategy, ["firecrawl_map", "hybrid"], enabled)', app_js)
        self.assertIn('setOptionAvailability(els.merchantScrapeStrategy, ["firecrawl"], enabled)', app_js)
        self.assertIn('setOptionAvailability(els.merchantDefaultExtractor, ["firecrawl_product_hint"], enabled)', app_js)
        self.assertIn("function catalogErrorAdvice", app_js)
        self.assertIn("function merchantStockStatusMeta", app_js)
        self.assertIn("function extractorLabel", app_js)
        self.assertIn("function catalogDiscoveryLabel", app_js)
        self.assertIn("/api/merchant/items/bulk-promote", app_js)
        self.assertIn("backend_used", app_js)
        self.assertIn("任务采集", app_js)

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
        script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn("docker_noaff_container_publishes_port", script)

    def test_docker_health_check_failure_stops_installer(self) -> None:
        result = self.run_bash(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export DEPLOY_MODE=docker
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
        self.assertIn("Docker 应用健康检查失败", result.stderr)

    def test_docker_summary_prefers_domain_without_port_or_entry_path(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export DEPLOY_MODE=docker
                export FQDN=https://monitor.example.com:8787/portal_test
                export APP_PORT=7777
                export PUBLIC_APP_PORT=8787
                source ./install.sh
                detect_origin_ips() {
                  printf 'should-not-detect\n'
                  ORIGIN_IPV4=203.0.113.10
                }
                normalize_access_mode
                print_install_summary
                final_summary
                """
            )
        )
        self.assertIn("https://monitor.example.com", output)
        self.assertNotIn("should-not-detect", output)
        self.assertNotIn("monitor.example.com:8787", output)
        self.assertNotIn("/portal_test", output)

    def test_docker_summary_without_domain_uses_ip_and_public_port(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export DEPLOY_MODE=docker
                export APP_PORT=7777
                export PUBLIC_APP_PORT=8787
                source ./install.sh
                detect_origin_ips() {
                  ORIGIN_IPV4=203.0.113.20
                }
                normalize_access_mode
                print_install_summary
                final_summary
                """
            )
        )
        self.assertIn("http://203.0.113.20:8787", output)
        self.assertNotIn("http://203.0.113.20:7777", output)

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
EOF
                source ./install.sh
                has_tty() { return 1; }
                choose_existing_install_action
                printf 'skip=%s mode=%s port=%s\n' "$SKIP_INTERACTIVE_WIZARD" "$DEPLOY_MODE" "$PUBLIC_APP_PORT"
                """
            )
        )
        self.assertIn("skip=true mode=docker port=8787", output)

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
                CERTBOT_EMAIL=ops@noaff.dev
                CF_RECORD_PROXIED=false
                CATALOG_DEBUG_PORT=9446
                write_env_file
                grep -E '^(DEPLOY_MODE|ACCESS_MODE|ENABLE_NGINX|ENABLE_TLS|CERT_MODE|APP_PORT|PUBLIC_APP_PORT|FQDN|CERTBOT_EMAIL|CF_RECORD_PROXIED|CATALOG_DEBUG_PORT)=' "$APP_DIR/.env"
                """
            )
        )
        self.assertIn("DEPLOY_MODE=docker", output)
        self.assertIn("ACCESS_MODE=ip", output)
        self.assertIn("PUBLIC_APP_PORT=8787", output)
        self.assertIn("FQDN=monitor.example.com", output)
        self.assertIn("CERTBOT_EMAIL=ops@noaff.dev", output)
        self.assertIn("CATALOG_DEBUG_PORT=9446", output)

    def test_non_git_existing_app_dir_is_backed_up_and_data_restored(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                mkdir -p "$APP_DIR/data"
                printf 'APP_PORT=7788\n' > "$APP_DIR/.env"
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
        self.assertIn("APP_PORT=7788", output)
        self.assertIn("data=db", output)

    def test_reset_password_updates_sqlite_admin(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                export APP_DIR="${temp_dir}/app"
                export RESET_ADMIN_USERNAME=operator
                export RESET_ADMIN_PASSWORD=NewStrongPass123
                mkdir -p "$APP_DIR/data"
                python3 - "$APP_DIR/data/monitor.db" <<'PY'
import sqlite3
import sys

db_path = sys.argv[1]
with sqlite3.connect(db_path) as connection:
    connection.execute(
        "CREATE TABLE admins ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT NOT NULL UNIQUE, "
        "password_hash TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )
    connection.execute(
        "INSERT INTO admins (username, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("operator", "old-hash", "old", "old"),
    )
    connection.commit()
PY
                source ./install.sh
                reset_admin_password
                python3 - "$APP_DIR/data/monitor.db" <<'PY'
import hashlib
import sqlite3
import sys

db_path = sys.argv[1]
with sqlite3.connect(db_path) as connection:
    username, password_hash = connection.execute(
        "SELECT username, password_hash FROM admins LIMIT 1"
    ).fetchone()
algorithm, salt, digest = password_hash.split("$", 2)
assert algorithm == "pbkdf2:sha256:1000000"
expected = hashlib.pbkdf2_hmac(
    "sha256",
    "NewStrongPass123".encode("utf-8"),
    salt.encode("utf-8"),
    1_000_000,
).hex()
print(username, digest == expected)
PY
                cat "$APP_DIR/data/bootstrap_admin.txt"
                """
            )
        )
        self.assertIn("operator True", output)
        self.assertIn("username=operator", output)
        self.assertIn("password=NewStrongPass123", output)
        self.assertNotIn("panel_path=", output)

    def test_panel_upgrade_policy_is_opt_in(self) -> None:
        install_script = (ROOT_DIR / "install.sh").read_text(encoding="utf-8")
        self.assertIn('ENABLE_PANEL_UPGRADE="${ENABLE_PANEL_UPGRADE:-false}"', install_script)
        self.assertIn("PANEL_UPGRADE_ENABLED=${ENABLE_PANEL_UPGRADE}", install_script)
        self.assertIn("write_panel_upgrade_policy", install_script)
        self.assertIn("org.freedesktop.systemd1.manage-units", install_script)
        self.assertIn('action.lookup("unit") == "${APP_NAME}-upgrade.service"', install_script)
        self.assertIn('subject.user == "${SERVICE_USER}"', install_script)

    def test_panel_upgrade_policy_writes_and_removes_polkit_rule(self) -> None:
        output = self.assert_shell_ok(
            textwrap.dedent(
                r"""
                set -Eeuo pipefail
                temp_dir="$(mktemp -d)"
                export NOAFF_INSTALL_LIBRARY_MODE=true
                source ./install.sh
                restart_polkit_service() {
                  printf 'restart-polkit\n'
                }
                PANEL_UPGRADE_POLKIT_RULE="${temp_dir}/49-noaff-monitor-upgrade.rules"
                DEPLOY_MODE=native
                ENABLE_PANEL_UPGRADE=true
                APP_NAME=noaff-monitor
                SERVICE_USER=noaffmon
                write_panel_upgrade_policy
                grep -F 'noaff-monitor-upgrade.service' "$PANEL_UPGRADE_POLKIT_RULE"
                grep -F 'subject.user == "noaffmon"' "$PANEL_UPGRADE_POLKIT_RULE"
                ENABLE_PANEL_UPGRADE=false
                write_panel_upgrade_policy
                test ! -e "$PANEL_UPGRADE_POLKIT_RULE"
                """
            )
        )
        self.assertIn("noaff-monitor-upgrade.service", output)
        self.assertIn('subject.user == "noaffmon"', output)
        self.assertIn("restart-polkit", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
