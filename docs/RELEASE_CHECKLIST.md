# NOAFF Release Checklist

Use this checklist before tagging or announcing a release.

## Automated Validation

Run from the repository root:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/test_install_script.py
bash -n install.sh
node --check static/app.js
git diff --check
```

Current expected baseline:

- 233 tests passing
- Python compile check passing
- `install.sh` syntax check passing
- `static/app.js` syntax check passing
- `git diff --check` passing

## Resource Safety

- Confirm no Playwright/Chrome validation processes remain:

```bash
pgrep -af '[p]laywright-core|[c]hrome.*playwright_chromiumdev_profile|[g]oogle-chrome|[c]hromedriver' || true
/usr/local/sbin/zaki-playwright-cleanup
```

- Confirm the default polling interval for new installs is `POLL_INTERVAL_SECONDS=90`.
- Confirm high-compatibility collection has `SCRAPLING_DOMAIN_COOLDOWN_STEALTH=300`.
- On a 1-2 vCPU VPS, avoid setting multiple high-compatibility tasks on the same domain to run every 45 seconds.
- Watch `top` / `htop` during one polling cycle. Sustained CPU above the provider limit means the site should use longer intervals, manual, webhook, or external collector fallback.

## UI Smoke Test

- Log in to the dashboard.
- Confirm the left navigation is visible on desktop.
- Open `监控任务`, `商品入库`, and `系统设置`.
- Confirm the task page uses compact cards, not waterfall/long-row layout.
- Confirm product cards do not overlap at narrow browser widths.
- Confirm product intake is step-based and advanced fields are collapsed by default.
- Confirm system settings shows the entry grid and each panel has a back action.
- Confirm no horizontal page overflow on desktop and mobile widths.
- Confirm browser console has no errors during the smoke flow.

## Collection Smoke Test

- Create a default `multi_engine` task on an offline fixture-like IDC page or controlled test page.
- Verify an in-stock product parses as `stock=1` or a positive inventory number.
- Verify a sold-out product parses as `stock=0`.
- Verify an unknown product keeps `last_state` unchanged and does not send Telegram.
- Verify the task card shows backend/attempt summary without leaking secrets.
- Verify `curl_cffi` runs before browser-heavy modes in `multi_engine`.
- Verify high-compatibility failures enter cooldown and do not relaunch the browser every cycle.

## Parser Smoke Test

- DMIT-style category page:
  - in-stock selected/target card returns stock.
  - sold-out target card returns `0`.
  - a global continue button does not override a target card's sold-out marker.
- WHMCS-style page:
  - `pid` links and `cart.php?gid=` product cards are scoped to the target keyword.
- Explicit rules:
  - CSS selector rule.
  - XPath rule.
  - Regex inventory rule.
  - `target_scope_selector` around one product card.

## Product Intake Smoke Test

- Run source URL discovery.
- Confirm language switches, navigation, footers, login/register/privacy/contact, and empty titles are not promoted as products.
- Scrape selected candidates.
- Confirm product preview shows backend used, parser, title, URL, and stock status.
- Bulk-create selected products once.
- Bulk-create the same products again and confirm dedupe prevents duplicates.

## Group And Movement Smoke Test

- Create a main group.
- Create a nested subgroup.
- Rename a subgroup.
- Move one product from group A to group B.
- Move multiple selected products to another subgroup.
- Confirm moved products keep:
  - `last_state`
  - `last_stock`
  - Telegram `message_id`
  - webhook token metadata
  - source metadata
- Delete an empty subgroup.
- Delete selected products and confirm unrelated products remain.
- Drag-sort cards in the current layer.

## Telegram Smoke Test

- Use a test chat before a public group.
- Trigger an in-stock result and confirm `sendMessage`.
- Trigger an inventory count change and confirm `editMessage`.
- Trigger sold out and confirm the original message is updated/cleared according to the state machine.
- Trigger `stock=None` and confirm no Telegram message is sent.
- Run template test push after editing the template.

## External Fallback Smoke Test

- Firecrawl:
  - valid key diagnostic succeeds.
  - invalid key diagnostic returns auth error without leaking the key.
  - scheduled monitoring remains disabled unless explicitly enabled.
- Enhanced external collector:
  - `127.0.0.1:8191`, `http://127.0.0.1:8191`, and `/v1`-suffixed URLs normalize to the service root.
  - disabled monitor mode returns a user-readable error.
  - returned challenge HTML is still classified as protected source.

## Upgrade Smoke Test

- Existing checkout upgrade should run `git config --global --add safe.directory "$APP_DIR"` before `git fetch`.
- Panel upgrade:
  - unavailable when policy is disabled.
  - reports manual command in Docker/manual environments.
  - does not require interactive authentication when polkit/systemd permission is configured.
- Old tasks should migrate strategy names once and should not be remigrated after a user edits them.

## Release Risks To Mention

- Some protected sources only return challenge HTML without a user/session-specific public product page.
- The project does not solve CAPTCHA or Turnstile inside NOAFF.
- Browser-heavy modes can spike CPU on small VPS instances; use conservative intervals and domain cooldown.
- Firecrawl and external collectors are optional fallback/diagnostic paths, not default high-frequency monitors.
- New merchant layouts should be added with offline HTML fixtures before relying on them in production.
