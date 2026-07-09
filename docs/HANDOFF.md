# NOAFF Handoff

Project: NOAFF IDC restock monitor

## Goal

- 公益 NOAFF IDC 补货监控应用。
- 主路线是公开页面采集、规则/页面适配器解析、Telegram 状态机推送。
- 不做 Cloudflare / Turnstile / CAPTCHA 绕过，不接入打码，不模拟真人过验证。

## Current Architecture

- Flask dashboard
- SQLite storage
- Data Collector + multi-engine-first fetch pipeline
- `curl_cffi` browser-fingerprint HTTP first layer
- Legacy DrissionPage / Chromium fallback
- Optional external enhanced collector adapter
- Optional Firecrawl external fallback / diagnostics
- Telegram send/edit/sold-out state machine

## Fetch Strategies

Primary user-facing modes:

- `multi_engine`: default, bounded curl_cffi -> standard -> dynamic -> stealth escalation
- `curl_cffi`: low-cost browser-fingerprint HTTP, no browser startup
- `scrapling_standard`: lightweight Scrapling fetcher
- `scrapling_dynamic`: JS-rendered pages
- `scrapling_stealth`: high-compatibility browser mode, low concurrency
- `manual`: dashboard-managed stock state
- `webhook`: external stock writes

Collector layer:

- `direct`: compatibility wrapper for legacy direct/static/browser fetchers
- `curl_cffi`: low-cost browser-fingerprint HTTP
- `external_solver`: optional operator-configured external enhanced collector endpoint
- `webhook`: external stock write path
- `manual`: dashboard-managed stock write path

`external_solver` is configuration-only. It can call an operator-owned endpoint such as a compatible solver API, but NOAFF core does not implement challenge solving and does not call an external solver unless explicitly enabled.

External collector URLs are normalized before use. Supported operator input examples:

- `127.0.0.1:8191`
- `http://127.0.0.1:8191`
- `http://127.0.0.1:8191/v1/`

All normalize to the service root so diagnostics and runtime calls do not accidentally double-append API paths.

Legacy/compatibility modes still exist but are not the default:

- `scrapling_adaptive`
- `browser`
- `static_http`
- `generic_pricing_table`
- `whmcs`
- `firecrawl`
- `firecrawl_then_static`
- `static_then_firecrawl`
- `firecrawl_then_browser`
- `adaptive`

Upgrade migration maps old strategies into multi-engine-first:

- `browser` -> `scrapling_dynamic`
- `static_http` -> `curl_cffi`
- `adaptive` -> `multi_engine`
- Firecrawl pipelines -> `scrapling_stealth`
- `generic_pricing_table` / `whmcs` -> `multi_engine` with original extractor preserved in `source_config.extractor`
- `manual` / `webhook` unchanged

The migration is marked by `scrapling_fetch_strategy_migration_v1` and runs once, so later manual strategy choices are not overwritten.

## Implemented Behavior

- `multi_engine` is the default monitor and catalog fetch strategy.
- `curl_cffi` is the first low-cost engine, followed by Scrapling standard/dynamic/stealth when the lightweight request is insufficient.
- Firecrawl is no longer the default for realtime polling; it remains an external fallback/diagnostic option.
- Domain-level fetch sharing avoids repeatedly fetching the same URL/domain in one cycle.
- Same-domain protected-source failures set cooldown and stop further hits in that cycle.
- Cloudflare challenge is classified as `cloudflare_challenge`.
- Cloudflare challenge does not trigger browser rebuild.
- Protected sources enter progressive cooldown:
  - first block: 1 minute
  - second block: 3 minutes
  - third and later: 10 minutes
- During cooldown the engine does not start Chromium, does not call Firecrawl, and does not request the target site.
- `generic_pricing_table` locates the product area around `target_keyword` and detects order/sold-out signals.
- `whmcs` supports common WHMCS pages, `cart.php?gid=xx`, `pid`, `configureproduct`, `Order Now`, `Out of Stock`.
- User-defined stock rules support CSS selector, XPath, regex, JSON path, target scope, button selector, disabled selector, and custom keyword lists.
- `manual` tasks can be marked in stock / sold out from the dashboard.
- `webhook` tasks accept external stock writes at `POST /api/webhooks/restock/<task_id>`.
- Webhook token plaintext is returned only once when reset. Database, snapshot, and logs do not expose plaintext tokens.
- Product intake is guided and multi-engine-first:
  - fill merchant page
  - automatic discovery
  - preview and confirm
  - create tasks
  - advanced collection/filter parameters are collapsed by default
- Product intake filters locale switches, navigation, footers, step/category headings, duplicate URLs, and no-price/no-spec candidates.
- Task dashboard supports hierarchical group/subgroup browsing, subgroup rename/delete, drag sorting, bulk delete, and moving tasks across groups/subgroups.
- System settings is split into concise 4+4 entry cards and system-level panels only.
- Scrapling settings include status and one-click runtime detection.
- Firecrawl settings include non-persistent connection diagnostics that do not save or expose the API key.

## Key Files

- `app.py`
  - strategy constants and migration mapping
  - `FetchResult`, `FetchPipelineResult`, `FetchAttempt`, `ScrapeResult`
  - `CurlCffiFetcher`, `ScraplingFetcher`, `ScraplingSessionManager`
  - `FirecrawlClient`, `FirecrawlFetcher`, `FirecrawlCatalogProvider`
  - `CollectorRequest`, `CollectorResult`, `ExternalSolverCollector`
  - `BrowserFetcher`, `StaticHttpFetcher`, `ExternalInputFetcher`
  - `FetcherSelector` and bounded fallback pipeline
  - `MonitoringEngine.scrape_task`
  - `MonitoringEngine.apply_task_result`
  - protected-source/domain cooldown helpers
  - extractor registry and rule parser
  - task move/group/manual/webhook/catalog/settings API routes
- `static/app.js`
  - task strategy cards
  - rule editor
  - hierarchical task browser
  - group/subgroup move modal
  - product intake workbench
  - Scrapling/Firecrawl settings UI
  - Telegram template helper and test push
- `templates/portal.html`
  - task modal
  - product intake workbench
  - system settings cards and panels
  - Firecrawl guide carousel
- `install.sh`
  - native/Docker installer
  - safe.directory handling
  - enhanced collector URL normalization in generated `.env`
  - Scrapling runtime verification
  - panel upgrade service
- `Dockerfile`
  - installs requirements
  - verifies Scrapling runtime imports during build
- `tests/test_app.py`
  - migration tests
  - Scrapling fetcher tests
  - protected-source and domain cooldown tests
  - rule parser tests
  - Firecrawl diagnostic tests
  - manual/webhook Telegram state tests
  - group/subgroup/move tests
- `tests/test_install_script.py`
  - installer and UI structure tests

## Validation Commands

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

## Recommended Task Examples

Multi-engine IDC page:

```text
monitor_url: https://provider.example.com/pricing
target_keyword: target product name
fetch_strategy: multi_engine
source_config: {"extractor":"generic_pricing_table"}
```

WHMCS page with preserved extractor:

```text
monitor_url: https://provider.example.com/cart.php?gid=12
target_keyword: product title
fetch_strategy: multi_engine
source_config: {"extractor":"whmcs","pid":123}
```

Selector-based rule:

```json
{
  "stock_rule_type": "css_selector",
  "target_scope_selector": ".product-card",
  "stock_selector": ".stock",
  "soldout_selector": ".sold-out"
}
```

## Known Limits

- Sites behind Cloudflare / Turnstile / CAPTCHA are treated as protected sources.
- The app intentionally does not bypass protected source challenges.
- External enhanced collectors are optional operator-owned integrations, not built-in challenge bypass.
- Scrapling improves local collection reliability but does not guarantee protected-site access.
- Extractors are heuristic and should be extended with offline HTML fixtures for each new IDC merchant pattern.
- Do not add live-network dependent tests for merchant pages.
- Firecrawl hosted may improve complex-page success rates, but it is an external provider with cost/privacy tradeoffs.
- Firecrawl self-host is useful as a scrape/map service, not as a guaranteed protected-site bypass.
- Inventory polling through Firecrawl must keep `maxAge=0` and avoid cache.

## Next Release Checklist

- Run all validation commands.
- Smoke test task creation for standard/enhanced/high-compatibility/manual/webhook modes.
- Smoke test product intake: local discovery, Scrapling preview, bulk create.
- Smoke test moving products across main groups and nested subgroups.
- Smoke test subgroup rename/delete and bulk product delete.
- Test Firecrawl diagnostics with valid and invalid keys; confirm no plaintext key exposure.
- Create one `manual` task and verify in-stock / sold-out buttons update Telegram state.
- Create one `webhook` task, reset token, and POST stock/sold_out payloads.
- Confirm protected source tasks show cooldown and do not repeatedly request the target.
- Confirm Firecrawl API key and webhook tokens do not appear in snapshot, logs, backup, or browser responses.
