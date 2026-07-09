# PR Draft

## Commit Message

```text
feat: switch monitoring to multi-engine collection
```

## PR Title

Complete multi-engine IDC monitoring, product intake, and grouped task management

## Summary

This PR moves NOAFF from a Firecrawl/browser-heavy collector into a Data Collector + multi-engine IDC restock monitor. The default `multi_engine` path uses `curl_cffi` browser-fingerprint HTTP first, then escalates to Scrapling standard, dynamic, and stealth modes only when needed. Firecrawl remains available as an optional external fallback / diagnostics tool, but it is no longer the default high-frequency polling path.

The project still only monitors public pages. It does not bypass Cloudflare / Turnstile / CAPTCHA. Challenge pages are classified as protected sources and cooled down without changing stock state or sending Telegram messages.

## What Changed

- Added multi-engine collection modes:
  - `multi_engine`
  - `curl_cffi`
  - `scrapling_standard`
  - `scrapling_dynamic`
  - `scrapling_stealth`
  - `scrapling_adaptive`
- Made `multi_engine` the default strategy for new tasks and product-intake-created tasks.
- Added a Data Collector layer with `direct`, `curl_cffi`, `external_solver`, `webhook`, and `manual`.
- Added optional external enhanced collector settings and diagnostics.
- Added bounded fallback: curl_cffi -> standard -> dynamic -> stealth.
- Added domain-level result sharing and cooldown to avoid repeatedly fetching the same IDC page/domain in one polling cycle.
- Added configurable stock parsing rules:
  - CSS selector
  - XPath
  - regex
  - JSON path
  - target scope selector
  - stock/sold-out selectors
  - button/disabled selector
  - custom keyword lists
- Rebuilt product intake around a low-friction workflow:
  - fill merchant page
  - automatic discovery
  - preview and confirm
  - create tasks
  - advanced options collapsed by default
- Reduced product-intake junk by filtering language switches, navigation, footer links, category/step labels, empty titles, and no-price/no-spec candidates.
- Added task movement:
  - single-product move
  - bulk move
  - move into another main group
  - move into another subgroup
  - auto-create target groups/subgroups
  - preserve state, message ID, webhook metadata, and source metadata
- Added subgroup management:
  - enter
  - rename
  - delete
  - drag sort within the current layer
- Refactored the task dashboard into a compact hierarchical workspace:
  - compressed metric cards
  - breadcrumb path
  - current-layer actions
  - subgroup grid
  - compact product list
  - collapsible error detail
- Simplified task editing so users select human-readable modes rather than backend internals:
  - standard
  - enhanced
  - high compatibility
  - manual
  - webhook
  - external fallback
- Simplified system settings:
  - account and security
  - notification and Telegram
  - Scrapling collection engine
  - Firecrawl external fallback
  - backup and restore
  - runtime logs
- Kept settings entry cards constrained to a compact 4+4 layout; no masonry/waterfall layout.
- Added Scrapling/curl_cffi runtime checks in native install, upgrade, and Docker build flows.
- Normalized external enhanced collector URLs in installer/backend configuration handling.
- Hardened the upgrade service by adding Git `safe.directory` before fetch.
- Lowered new-install polling pressure with a 90-second default interval and 300-second high-compatibility domain cooldown.
- Updated README, handoff notes, release notes, PR draft, and environment documentation.

## Database Migration

The app auto-migrates old strategy names into multi-engine equivalents.

One-time marker:

```text
scrapling_fetch_strategy_migration_v1
```

Default strategy:

```text
multi_engine
```

Migration mapping:

| Old strategy | New strategy |
| --- | --- |
| `browser` | `scrapling_dynamic` |
| `static_http` | `curl_cffi` |
| `adaptive` | `multi_engine` |
| `firecrawl` | `scrapling_stealth` |
| `firecrawl_then_browser` | `scrapling_stealth` |
| `firecrawl_then_static` | `scrapling_stealth` |
| `static_then_firecrawl` | `scrapling_standard` |
| `generic_pricing_table` | `multi_engine` with extractor preserved |
| `whmcs` | `multi_engine` with extractor preserved |
| `manual` | unchanged |
| `webhook` | unchanged |

No manual SQLite migration is required for databases initialized by the app.

## Firecrawl Notes

- Firecrawl is now an external fallback / diagnostics option.
- Firecrawl is disabled for scheduled monitoring by default.
- Firecrawl credit and rate-limit errors enter cooldown to avoid repeated credit consumption.
- Firecrawl diagnostics can test current form values without saving the key.
- Firecrawl API keys are masked in snapshots, logs, and backups.
- Inventory-sensitive Firecrawl settings keep `FIRECRAWL_MAX_AGE_MS=0` and cache-disabled behavior.

## External Enhanced Collector Notes

- External enhanced collectors are operator-configured and disabled by default.
- Scheduled monitoring does not call an external collector unless explicitly enabled.
- The integration is an adapter layer, not built-in challenge-solving logic.
- Diagnostics can test connectivity without exposing sensitive configuration in snapshots or logs.
- The URL field accepts `host:port`, `http(s)://host:port`, and `/v1`-suffixed forms; the app normalizes these to the service root.

## Protected Source Behavior

- Cloudflare / Turnstile / CAPTCHA challenge pages are treated as protected sources.
- Challenge pages do not trigger browser rebuild.
- During cooldown:
  - local browser fetchers are not started
  - Firecrawl is not called
  - the target site is not requested
  - `last_state` is not changed
  - Telegram is not sent

## Test Plan

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/test_install_script.py
node --check static/app.js
bash -n install.sh
git diff --check
```

Current result:

- 233 tests passing
- Python compile check passing
- `static/app.js` syntax check passing
- `install.sh` bash syntax check passing
- `git diff --check` passing

## Manual Smoke Test

Detailed release validation lives in `docs/RELEASE_CHECKLIST.md`.

- Create tasks in standard, enhanced, high-compatibility, manual, and webhook modes.
- Save a task and run “save and check now”.
- Configure a CSS selector rule and verify only the target product is parsed.
- Run product intake and confirm preview items are real products, not language/navigation/footer text.
- Bulk-create preview items twice and verify dedupe behavior.
- Move one product to another main group.
- Bulk-move selected products to another subgroup.
- Rename and delete a subgroup.
- Drag-sort cards within the current layer.
- Trigger a protected-source fixture and confirm cooldown/no Telegram/no state change.
- Run Firecrawl diagnostics and confirm no plaintext key is returned.
- Run install/upgrade on a clean environment and confirm Scrapling runtime detection reports clearly.

## Risk

- New IDC layouts still need offline HTML fixtures.
- Scrapling browser modes depend on the target VPS browser dependencies.
- Protected sources that require CAPTCHA / Turnstile completion still need manual, webhook, or alternate public-source workflows.
- Firecrawl remains useful as an external fallback, but should not be used as the default high-frequency monitoring backend.
