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
                export PUBLIC_HTTP_PORT=81
                source ./install.sh
                validate_runtime_config
                """
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not supported by Cloudflare orange-cloud proxy", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
