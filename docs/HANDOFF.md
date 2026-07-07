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
- Telegram send/edit state machine
- Task fetch strategies:
  - `browser`
  - `static_http`
  - `generic_pricing_table`
  - `whmcs`
  - `manual`
  - `webhook`

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

Key Files:
- `app.py`
  - fetch strategy constants
  - database migrations
  - `FetchResult`, `ExtractorResult`, `ScrapeResult`
  - `BrowserFetcher`, `StaticHttpFetcher`, `ExternalInputFetcher`
  - `FetcherSelector`
  - `MonitoringEngine.scrape_task`
  - `MonitoringEngine.apply_task_result`
  - protected source cooldown helpers
  - extractor registry
  - manual/webhook API routes
- `static/app.js`
  - fetch strategy labels
  - protected source notice
  - manual quick actions
  - webhook endpoint/token hint display
- `templates/portal.html`
  - task form fetch strategy selector
- `tests/test_app.py`
  - migration tests
  - fetcher tests
  - protected source cooldown tests
  - IDC/WHMCS extractor tests
  - manual/webhook Telegram state machine tests

Validation Commands:

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py tests/test_app.py tests/test_install_script.py
bash -n install.sh
```

Current Passing Baseline:
- 101 tests pass.
- `py_compile` passes.
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

Known Limits:
- Sites behind Cloudflare / Turnstile / CAPTCHA are treated as protected sources.
- The app intentionally does not bypass protected source challenges.
- Extractors are heuristic and should be extended with offline HTML fixtures for each new IDC merchant pattern.
- Do not add live-network dependent tests for merchant pages.

Next Release Checklist:
- Run the validation commands above.
- Manually smoke test dashboard task creation for all fetch strategies.
- Create one `manual` task and verify in-stock / sold-out buttons update Telegram state.
- Create one `webhook` task, reset token, and POST stock/sold_out payloads.
- Confirm protected source tasks show cooldown and do not repeatedly request the target.
- Update changelog or GitHub release notes before tagging.
