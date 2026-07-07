# NOAFF Handoff

Project: NOAFF IDC restock monitor

Goal:
- 公益 NOAFF IDC 补货监控应用。
- 主路线是公开页面爬取、页面适配器、Telegram 状态机推送。
- 不做 Cloudflare / Turnstile / CAPTCHA 绕过，不接入打码，不模拟真人过验证。

Current Architecture:
- Flask dashboard
- SQLite storage
- DrissionPage / Chromium browser fetcher
- `requests` static HTTP fetcher
- Optional Firecrawl fetcher/catalog provider
- Telegram send/edit state machine
- Task fetch strategies:
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
- Product intake pipeline:
  - entry URL
  - URL discovery: local page links / Firecrawl Map / hybrid
  - page scraping: static HTTP / catalog browser / Firecrawl / adaptive
  - extractor: generic pricing table / WHMCS / Firecrawl product hint / fallback keyword parser
  - preview
  - single or bulk task creation

Implemented Behavior:
- Cloudflare challenge is classified as `cloudflare_challenge`.
- Cloudflare challenge does not trigger browser rebuild.
- Protected sources enter progressive cooldown:
  - first block: 1 minute
  - second block: 3 minutes
  - third and later: 10 minutes
- During cooldown the engine does not start Chromium and does not request the target site.
- `generic_pricing_table` locates the product area around `target_keyword` and detects:
  - in stock: `Order Now`, `Buy Now`, `Configure`, `Available`, `Add to Cart`, `下单`, `购买`
  - sold out: `Out of Stock`, `Sold Out`, `Unavailable`, `缺货`, `售罄`, `无货`
- `whmcs` supports common WHMCS pages, `cart.php?gid=xx`, `pid`, `configureproduct`, `Order Now`, `Out of Stock`.
- `manual` tasks can be marked in stock / sold out from the dashboard.
- `webhook` tasks accept external stock writes at:
  - `POST /api/webhooks/restock/<task_id>`
  - token via `Authorization: Bearer <token>` or `X-NOAFF-Token`
- Webhook token plaintext is returned only once when reset. Database, snapshot, and logs do not expose plaintext tokens.
- Firecrawl is optional:
  - disabled by default for realtime monitor polling
  - enabled by default for catalog/intake use when configured
  - sends `maxAge=0` and `storeInCache=false` for inventory-sensitive scraping
  - masks API key from snapshot, backup, logs, and error details
  - hosted enhanced/auto proxy modes require explicit feature flags
- Firecrawl self-host note: self-hosted Firecrawl does not include hosted Fire-engine advanced anti-blocking capabilities.
- If Firecrawl returns normal page HTML, local extractors parse it. If Firecrawl returns a challenge page, the task/source is still treated as protected.
- Product intake UI is split from system settings. System settings stays system-level only; intake has its own workbench.
- Product intake supports bulk task creation and dedupes by existing `source_item_id`.

Key Files:
- `app.py`
  - fetch strategy constants
  - database migrations
  - `FetchResult`, `ExtractorResult`, `ScrapeResult`
  - `FirecrawlClient`, `FirecrawlFetcher`, `FirecrawlCatalogProvider`
  - `BrowserFetcher`, `StaticHttpFetcher`, `ExternalInputFetcher`
  - `FetcherSelector` and fallback pipeline attempts
  - `MonitoringEngine.scrape_task`
  - `MonitoringEngine.apply_task_result`
  - `MonitoringEngine.import_merchant_source`
  - protected source cooldown helpers
  - extractor registry
  - manual/webhook/catalog API routes
- `static/app.js`
  - fetch strategy labels
  - protected source notice
  - manual quick actions
  - webhook endpoint/token hint display
  - Telegram template help modal and edited-template test push
  - product intake workbench rendering
  - Firecrawl option lock/unlock in intake UI
  - bulk product promotion action
- `templates/portal.html`
  - task form fetch strategy selector
  - product intake workbench
  - system settings Firecrawl integration group
- `tests/test_app.py`
  - migration tests
  - fetcher tests
  - Firecrawl client/fetcher/catalog tests
  - protected source cooldown tests
  - IDC/WHMCS extractor tests
  - merchant intake discovery/bulk promote tests
  - manual/webhook Telegram state machine tests

Validation Commands:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/test_install_script.py
node --check static/app.js
bash -n install.sh
```

Current Passing Baseline:
- 135 tests pass.
- `py_compile` passes.
- `node --check static/app.js` passes.
- `bash -n install.sh` passes.

Recommended IDC Task Examples:

```text
monitor_url: https://www.dmit.io/pages/pricing
target_keyword: target product name
fetch_strategy: generic_pricing_table
```

```text
monitor_url: https://my.rfchost.com/index.php?rp=/store/hk-tier-1-international-optimization-network
target_keyword: product title
fetch_strategy: whmcs
source_config: {"pid": 123}
```

Firecrawl-backed catalog intake example:

```text
merchant_url: https://merchant.example.com/pricing
catalog_discovery_strategy: firecrawl_map
catalog_scrape_strategy: firecrawl
search_keyword: vps hk pricing
default_extractor: generic_pricing_table
default_fetch_strategy: generic_pricing_table
```

Known Limits:
- Sites behind Cloudflare / Turnstile / CAPTCHA are treated as protected sources.
- The app intentionally does not bypass protected source challenges.
- Extractors are heuristic and should be extended with offline HTML fixtures for each new IDC merchant pattern.
- Do not add live-network dependent tests for merchant pages.
- Firecrawl hosted may improve complex-page success rates, but it is an external provider with cost/privacy tradeoffs.
- Firecrawl self-host is useful as a scrape/map service, not as a guaranteed protected-site bypass.
- Inventory polling through Firecrawl must keep `maxAge=0` and avoid cache.

Next Release Checklist:
- Run the validation commands above.
- Manually smoke test dashboard task creation for all fetch strategies.
- Smoke test product intake: local discovery, Firecrawl Map if configured, preview, single create, bulk create.
- Create one `manual` task and verify in-stock / sold-out buttons update Telegram state.
- Create one `webhook` task, reset token, and POST stock/sold_out payloads.
- Confirm protected source tasks show cooldown and do not repeatedly request the target.
- Confirm Firecrawl API key and webhook tokens do not appear in snapshot, logs, backup, or browser responses.
- Update changelog or GitHub release notes before tagging.
