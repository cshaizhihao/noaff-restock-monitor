# Release Notes Draft

## Title

Firecrawl-assisted IDC intake and protected-source aware monitoring

## Summary

This release completes the IDC restock monitoring path for public product pages:

- public page fetching
- strategy-based fetchers
- optional Firecrawl scrape/map backend
- Firecrawl connection diagnostics in settings
- product intake URL discovery and preview workflow
- product intake noise filtering for navigation/locale/section text
- IDC / WHMCS page extractors
- protected-source cooldown for Cloudflare challenge pages
- Telegram state machine reuse for crawler, manual, and webhook inputs

The project intentionally does not bypass Cloudflare / Turnstile / CAPTCHA challenges.
If Firecrawl returns normal page content, NOAFF can parse it. If Firecrawl returns a challenge page, NOAFF still treats it as a protected source.

## Highlights

- Added task fetch strategies:
  - `browser`
  - `static_http`
  - `generic_pricing_table`
  - `whmcs`
  - `firecrawl`
  - `firecrawl_then_static`
  - `static_then_firecrawl`
  - `firecrawl_then_browser`
  - `adaptive`
  - `manual`
  - `webhook`
- Split Cloudflare challenge handling from browser auto-heal.
- Added `ProtectedSourceError` and `cloudflare_challenge` classification.
- Added protected-source cooldown:
  - first block: 1 minute
  - second block: 3 minutes
  - third and later: 10 minutes
- Added fetcher abstraction:
  - `StaticHttpFetcher`
  - `BrowserFetcher`
  - `FirecrawlFetcher`
  - `ExternalInputFetcher`
  - `FetcherSelector`
- Added Firecrawl client/catalog integration:
  - `/v2/scrape`
  - `/v2/map`
  - rawHtml/html/markdown parsing
  - `maxAge=0`
  - `storeInCache=false`
  - API key masking
  - explicit proxy feature flags for enhanced/auto
- Added Firecrawl settings diagnostic:
  - tests current unsaved form values
  - reports auth, ZDR, credit, rate limit, proxy, timeout, challenge, and bad-response states
  - does not save or expose plaintext API keys
- Added Firecrawl-style fallback pipeline with bounded attempts and frontend attempt summaries.
- Added IDC extractors:
  - `generic_pricing_table`
  - `whmcs`
- Added product intake workbench:
  - discovery strategy
  - scrape strategy
  - extractor selection
  - target keyword mode
  - dedupe policy
  - discovered result list
  - product preview
  - bulk task creation
  - user-readable recovery suggestions
- Product intake now demotes language switches, navigation/footer links, category/step headings, and no-price/no-spec candidates into manual review instead of auto-promoting them.
- Added hierarchical task browsing:
  - main group cards
  - nested subgroup cards
  - current-layer product lists
  - drag sorting and bulk delete controls
- Added manual stock update API and dashboard controls.
- Added webhook ingest API with one-time plaintext token generation.
- Webhook tokens are stored as HMAC hashes; snapshots/logs do not expose plaintext tokens.
- Improved Telegram templates with clearer default copy, variable help, and send-test support for the current edited template.
- Split product intake settings out of system settings.
- Updated README, `.env.example`, release notes, and handoff documentation.

## Migration Notes

Existing tasks continue to work. The default `fetch_strategy` is `browser`.

The database migration adds these task columns:

- `fetch_strategy TEXT DEFAULT 'browser'`
- `source_config TEXT DEFAULT '{}'`
- `blocked_count INTEGER DEFAULT 0`
- `last_blocked_at TEXT`
- `cooldown_until TEXT`
- `ingest_token_hash TEXT DEFAULT ''`
- `ingest_token_hint TEXT DEFAULT ''`
- `last_fetch_backend TEXT DEFAULT ''`
- `last_fetch_attempts TEXT DEFAULT ''`
- `last_protected_source_backend TEXT DEFAULT ''`

No manual migration is required for SQLite databases initialized by the app.

New settings defaults include Firecrawl and product intake keys:

- `firecrawl_enabled`
- `firecrawl_api_url`
- `firecrawl_api_key`
- `firecrawl_timeout_seconds`
- `firecrawl_max_age_ms`
- `firecrawl_store_in_cache`
- `firecrawl_proxy_mode`
- `firecrawl_allow_auto_proxy`
- `firecrawl_allow_enhanced_proxy`
- `firecrawl_zero_data_retention`
- `firecrawl_use_for_monitor`
- `firecrawl_use_for_catalog`
- `firecrawl_catalog_limit`
- `catalog_discovery_strategy`
- `catalog_scrape_strategy`
- `catalog_default_fetch_strategy`
- `catalog_default_extractor`
- `catalog_default_group`
- `catalog_include_sold_out`
- `catalog_auto_create_tasks`
- `catalog_dedupe_policy`
- `catalog_max_discovered_urls`
- `catalog_max_import_items`
- `catalog_timeout_seconds`

## Behavior Changes

- Cloudflare / Turnstile / CAPTCHA challenge pages are treated as protected sources.
- Challenge pages do not trigger browser rebuild.
- During protected-source cooldown:
  - Chromium is not started for that task.
  - The target site is not requested.
  - `last_state` is not changed.
  - Telegram messages are not sent.
- `manual` and `webhook` tasks do not poll target pages.
- `source_config` strips sensitive keys such as `token`, `secret`, `webhook_token`, and `ingest_token`.
- Firecrawl is optional and disabled for realtime monitor use by default.
- Product intake may use Firecrawl when configured because intake is manually triggered and user-visible.
- Firecrawl hosted enhanced/auto proxy modes are opt-in and labeled as external provider behavior, not built-in NOAFF bypass logic.
- Product intake bulk creation dedupes existing tasks by `source_item_id`.

## Firecrawl Usage

Minimum backend configuration:

```env
FIRECRAWL_ENABLED=true
FIRECRAWL_API_URL=https://api.firecrawl.dev
FIRECRAWL_API_KEY=fc-...
FIRECRAWL_MAX_AGE_MS=0
FIRECRAWL_STORE_IN_CACHE=false
FIRECRAWL_USE_FOR_MONITOR=false
FIRECRAWL_USE_FOR_CATALOG=true
```

Recommended first use is product intake:

```text
catalog_discovery_strategy: firecrawl_map
catalog_scrape_strategy: firecrawl
search_keyword: vps hk pricing
default_extractor: generic_pricing_table
default_fetch_strategy: generic_pricing_table
```

Hosted Firecrawl may improve complex page success rates. Self-host Firecrawl does not include hosted Fire-engine advanced IP block / robot detection capabilities.

## Webhook Usage

Reset a webhook token from the dashboard or:

```text
POST /api/tasks/<task_id>/webhook-token
```

External stock write:

```bash
curl -X POST 'https://your-panel.example.com/api/webhooks/restock/123' \
  -H 'Authorization: Bearer <ingest_token>' \
  -H 'Content-Type: application/json' \
  -d '{"stock": 3, "detail": "provider push"}'
```

Sold-out write:

```bash
curl -X POST 'https://your-panel.example.com/api/webhooks/restock/123' \
  -H 'X-NOAFF-Token: <ingest_token>' \
  -H 'Content-Type: application/json' \
  -d '{"status": "sold_out"}'
```

## Verification

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/test_install_script.py
node --check static/app.js
bash -n install.sh
```

Current baseline:

- 152 tests passing
- Python compile check passing
- `static/app.js` syntax check passing
- `install.sh` bash syntax check passing

## Manual Smoke Test Checklist

- Create a `generic_pricing_table` task using a static fixture-like IDC pricing page and confirm `Order Now` is detected as in stock.
- Create a `whmcs` task with a known product title or `pid` and confirm `Out of Stock` is detected as sold out.
- Import one merchant page with local discovery and confirm discovered products enter preview before task creation.
- If Firecrawl is configured, run product intake with `firecrawl_map` and confirm backend_used is displayed as Firecrawl.
- In Firecrawl settings, run connection diagnostics with a valid key and an invalid key; confirm actionable messages and no plaintext key exposure.
- Bulk-create preview items twice and confirm the second run syncs existing tasks rather than duplicating them.
- Create a `manual` task and click dashboard “有货” and “售罄”; confirm Telegram send/edit behavior.
- Create a `webhook` task, reset token, POST `stock`, then POST `status=sold_out`; confirm Telegram send/edit behavior.
- Force a Cloudflare challenge fixture/page and confirm `cloudflare_challenge`, cooldown UI, no repeated browser rebuild.
- Confirm dashboard snapshot does not expose webhook plaintext tokens or Firecrawl API keys.

## Remaining Risks

- IDC page extractors are heuristic; each new merchant layout should get offline HTML fixture tests.
- Live merchant pages were not used in automated tests.
- Sites protected by Cloudflare / Turnstile / CAPTCHA require manual/webhook/alternate public-source workflows.
- Firecrawl hosted sends page URLs/content to an external provider; users must decide whether that is acceptable for their deployment.
- Firecrawl API pricing/rate limits are external and should be monitored by the operator.
- Browser-based behavior should be smoke-tested on the target VPS with the installed Chromium binary.
