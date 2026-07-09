# Release Notes Draft

## Title

Multi-engine-first IDC monitoring and grouped task management

## Summary

This release moves NOAFF to a Data Collector + multi-engine-first collection model for public IDC product pages. The default `multi_engine` path uses `curl_cffi` browser-fingerprint HTTP first, then escalates to Scrapling standard, dynamic, and stealth modes only when needed. Firecrawl is kept as an optional external fallback / diagnostics path instead of a high-frequency default.

The project intentionally does not bypass Cloudflare / Turnstile / CAPTCHA challenges. Cloudflare / Turnstile / CAPTCHA challenge pages are treated as protected sources, cooled down, and reported to the user without changing inventory state or sending Telegram messages.

## Highlights

- Added multi-engine-first fetch strategies:
  - `multi_engine`
  - `curl_cffi`
  - `scrapling_standard`
  - `scrapling_dynamic`
  - `scrapling_stealth`
  - `scrapling_adaptive`
  - `manual`
  - `webhook`
- Reworked the default task and product-intake strategy to `multi_engine`.
- Added a Data Collector abstraction for `direct`, `curl_cffi`, `external_solver`, `webhook`, and `manual`.
- Added optional external enhanced collector configuration and diagnostics without making it a hard dependency.
- Added bounded adaptive escalation: curl_cffi -> standard -> dynamic -> stealth.
- Added domain-level fetch sharing so one polling cycle can reuse page results across tasks on the same URL/domain.
- Added domain-level cooldown so protected or failing domains are not repeatedly hit by every task in the same group.
- Added selector/rule-driven stock parsing:
  - CSS selector
  - XPath
  - regex
  - JSON path
  - target scope selector
  - stock/sold-out selectors
  - button/disabled selector
  - custom in-stock and sold-out keyword lists
- Upgraded product intake to a low-friction guided workflow:
  - fill merchant page
  - automatic discovery
  - preview and confirm
  - create monitor tasks
  - advanced collection and filter parameters are collapsed by default
- Product intake noise filtering now demotes locale switches, navigation, footers, category headings, empty titles, and no-price/no-spec candidates instead of creating junk products.
- Added hierarchical task browsing with main groups, nested subgroups, current-layer product lists, drag sorting, bulk delete, subgroup rename/delete, and cross-group task movement.
- Added `POST /api/tasks/move` for moving one or more products to another main group or subgroup without losing state, Telegram message IDs, or source metadata.
- Simplified task editing so users choose human-readable modes:
  - standard
  - enhanced
  - high compatibility
  - manual
  - webhook
  - external fallback
- Simplified system settings around:
  - account and security
  - notification and Telegram
  - Scrapling collection engine
  - Firecrawl external fallback
  - backup and restore
  - runtime logs
- System settings entry cards are constrained to a compact 4+4 layout, avoiding waterfall/masonry layouts and oversized one-page setting stacks.
- Added Scrapling install/runtime verification to native install, upgrade, and Docker build paths.
- Firecrawl connection diagnostics remain available, but Firecrawl is no longer the recommended realtime monitor backend.
- External enhanced collector diagnostics remain available for operator-owned endpoints, but they are opt-in and disabled for scheduled monitoring by default.
- External enhanced collector URLs are normalized, so `127.0.0.1:8191`, `http://127.0.0.1:8191`, and `http://127.0.0.1:8191/v1/` resolve to the same service root.
- The upgrade service now marks the app checkout as Git `safe.directory` before fetching, avoiding `dubious ownership` failures on older installs.
- New installs use a more conservative default polling interval of 90 seconds and a 300-second high-compatibility domain cooldown to reduce small-VPS CPU spikes.

## Migration Notes

The database migration is automatic. Existing tasks continue working and are mapped to multi-engine-first strategies where possible.

The default `fetch_strategy` is now:

```text
multi_engine
```

One-time strategy migration marker:

```text
scrapling_fetch_strategy_migration_v1
```

Strategy migration mapping:

| Old strategy | New strategy | Notes |
| --- | --- | --- |
| `browser` | `scrapling_dynamic` | JS-rendered pages |
| `static_http` | `curl_cffi` | lightweight browser-fingerprint HTTP |
| `adaptive` | `multi_engine` | bounded multi-engine escalation |
| `firecrawl` | `scrapling_stealth` | avoids default credit consumption |
| `firecrawl_then_browser` | `scrapling_stealth` | high-compat local path |
| `firecrawl_then_static` | `scrapling_stealth` | high-compat local path |
| `static_then_firecrawl` | `scrapling_standard` | lightweight local browser path |
| `generic_pricing_table` | `multi_engine` | extractor preserved in `source_config.extractor` |
| `whmcs` | `multi_engine` | extractor preserved in `source_config.extractor` |
| `manual` | `manual` | unchanged |
| `webhook` | `webhook` | unchanged |

New or expanded task fields include:

- `fetch_strategy`
- `source_config`
- `blocked_count`
- `last_blocked_at`
- `cooldown_until`
- `ingest_token_hash`
- `ingest_token_hint`
- `last_fetch_backend`
- `last_fetch_attempts`
- `last_protected_source_backend`
- `domain_cooldown_until`
- `last_shared_fetch_key`
- `last_shared_fetch_backend`

Webhook tokens are stored as HMAC hashes. Plaintext webhook tokens are shown only once when reset, and snapshots/logs/backups expose only token hints.

## Behavior Changes

- Scrapling is the primary realtime monitor engine.
- Product intake defaults to Scrapling, not Firecrawl.
- Firecrawl is an optional external fallback, diagnostics, and manual recovery tool.
- Firecrawl is not used by scheduled monitoring unless explicitly enabled.
- Firecrawl credit or rate-limit failures enter cooldown and do not keep consuming credits every polling round.
- Firecrawl diagnostics do not save or expose plaintext API keys, and the settings workflow does not save or expose plaintext API keys.
- Firecrawl external fallback still uses inventory-safe settings such as `FIRECRAWL_MAX_AGE_MS=0` and cache-disabled behavior.
- Protected-source cooldown prevents repeated local browser launches, repeated target requests, and repeated Firecrawl calls.
- High-compatibility Scrapling failures cool down by default before another browser-heavy attempt, reducing repeated CPU spikes on protected or unstable domains.
- `stock=None` does not change `last_state` and does not send Telegram.
- `manual` and `webhook` tasks do not poll target pages.
- Product movement keeps existing task state, message IDs, webhook metadata, and source metadata.
- Long error details are summarized in compact task rows and can be expanded when needed.

## Firecrawl External Fallback

Firecrawl external fallback remains supported for diagnostics and manual recovery:

```env
FIRECRAWL_ENABLED=false
FIRECRAWL_API_URL=https://api.firecrawl.dev
FIRECRAWL_API_KEY=
FIRECRAWL_MAX_AGE_MS=0
FIRECRAWL_STORE_IN_CACHE=false
FIRECRAWL_USE_FOR_MONITOR=false
FIRECRAWL_USE_FOR_CATALOG=true
```

Firecrawl hosted can improve some complex page captures, but it is an external provider with cost and privacy tradeoffs. It should not be the default high-frequency monitor backend for an open-source self-hosted restock monitor.

## External Enhanced Collector

NOAFF can optionally call an operator-configured external enhanced collector endpoint:

```env
ENHANCED_COLLECTOR_ENABLED=false
ENHANCED_COLLECTOR_API_URL=
ENHANCED_COLLECTOR_USE_FOR_MONITOR=false
ENHANCED_COLLECTOR_USE_FOR_CATALOG=true
```

The integration is deliberately opt-in. The core app does not implement challenge solving, does not call a solver when no URL is configured, and keeps scheduled monitoring disabled by default for external collectors.

The URL field accepts a host/port or full HTTP(S) URL. The installer and backend normalize compatible forms such as `127.0.0.1:8191/v1/` to the service root before saving or calling diagnostics.

## Product Intake Defaults

Product intake now prefers the local multi-engine path:

```text
CATALOG_DISCOVERY_STRATEGY=local
CATALOG_SCRAPE_STRATEGY=multi_engine
CATALOG_DEFAULT_FETCH_STRATEGY=multi_engine
CATALOG_DEFAULT_EXTRACTOR=generic_pricing_table
CATALOG_DEDUPE_POLICY=by_url
```

Firecrawl map/scrape can still be exposed as an external fallback button when the operator explicitly configures it, but the normal flow is: fill page, auto-discover candidates, preview confirmed products, and create tasks.

## Verification

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/test_install_script.py
node --check static/app.js
bash -n install.sh
git diff --check
```

Current baseline:

- 233 tests passing
- Python compile check passing
- `static/app.js` syntax check passing
- `install.sh` bash syntax check passing
- `git diff --check` passing

## Manual Smoke Test Checklist

- Create a standard Scrapling task on a static IDC/WHMCS-like page and verify in-stock detection.
- Create an enhanced Scrapling task on a JS-rendered page and verify page content is captured.
- Create a high-compatibility Scrapling task and confirm it is low-concurrency and cooled down on failure.
- Create a selector-based task using CSS/XPath/regex and verify only the target product is parsed.
- Run product intake from a merchant URL and confirm navigation/language/footer noise is not promoted as products.
- Create products from intake preview and confirm the default strategy is `scrapling_adaptive`.
- Move one product from group A to group B.
- Move multiple products from group A to group B / subgroup C.
- Rename and delete a subgroup without losing unrelated tasks.
- Create a `manual` task and verify in-stock / sold-out buttons update Telegram state.
- Create a `webhook` task, reset token, POST stock and sold-out payloads, and verify Telegram state.
- Run Firecrawl diagnostics with a valid and invalid key and confirm API keys are masked.
- Force a Cloudflare challenge fixture/page and confirm protected-source cooldown with no repeated rebuild or Telegram send.

## Remaining Risks

- IDC pages are inconsistent; new merchant layouts should get offline HTML fixture tests.
- Scrapling improves local collection reliability but does not guarantee access to protected sources.
- Sites requiring CAPTCHA / Turnstile completion still need manual, webhook, or alternate public-source workflows.
- Browser-dependent Scrapling modes should be smoke-tested on the target VPS after upgrade.
- Firecrawl hosted remains useful as an external fallback, but scheduled monitoring through Firecrawl can consume credits quickly.
