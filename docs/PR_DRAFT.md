# PR Draft

## Commit Message

```text
feat: add firecrawl-assisted intake and protected-source monitoring
```

## PR Title

Add Firecrawl-assisted intake and protected-source aware IDC monitoring

## Summary

This PR completes the public-page IDC restock monitoring path without implementing Cloudflare / Turnstile / CAPTCHA bypasses.

It adds strategy-based fetching, optional Firecrawl scrape/map support, IDC/WHMCS extractors, protected-source cooldown, product intake discovery/preview, and external inventory inputs through manual updates and webhook ingest. Telegram send/edit/sold-out behavior is reused through one state machine for crawler, manual, and webhook sources.

## What Changed

- Added task fetch strategies:
  - `browser`
  - `static_http`
  - `generic_pricing_table`
  - `whmcs`
  - `firecrawl`
  - `static_then_firecrawl`
  - `firecrawl_then_static`
  - `firecrawl_then_browser`
  - `adaptive`
  - `manual`
  - `webhook`
- Added fetcher abstraction:
  - `FetchResult`
  - `StaticHttpFetcher`
  - `BrowserFetcher`
  - `FirecrawlFetcher`
  - `ExternalInputFetcher`
  - `FetcherSelector`
- Added Firecrawl catalog support:
  - `/v2/map` URL discovery
  - `/v2/scrape` page capture
  - `maxAge=0`
  - `storeInCache=false`
  - API key masking
  - explicit enhanced/auto proxy flags
- Split Cloudflare challenge handling from browser auto-heal:
  - challenge pages return `cloudflare_challenge`
  - challenge pages do not trigger browser rebuild
  - protected sources enter 1 / 3 / 10 minute cooldown
- Added IDC extractors:
  - `generic_pricing_table`
  - `whmcs`
- Added product intake workbench:
  - discovery strategy
  - scrape strategy
  - extractor selection
  - target keyword mode
  - dedupe policy
  - preview result state
  - bulk task creation
- Added manual stock update API and dashboard controls.
- Added webhook ingest API with one-time plaintext token reset.
- Store webhook tokens as HMAC hashes; expose only token hints in snapshots.
- Added Telegram template variable help and send-test support for the currently edited template.
- Added dashboard display for fetch strategy, protected-source notices, manual actions, and webhook metadata.
- Updated README, `.env.example`, handoff notes, release notes, and PR draft.

## Database Migration

The app auto-adds these task columns:

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

Existing tasks keep working as `browser` strategy.

## Behavior Notes

- The app only monitors public pages.
- Cloudflare / Turnstile / CAPTCHA pages are treated as protected sources.
- During protected-source cooldown:
  - Chromium is not started for that task.
  - The target site is not requested.
  - Inventory state is not changed.
  - Telegram is not sent.
- `manual` / `webhook` tasks do not fetch target pages while waiting for external inventory input.
- Sensitive keys are stripped from `source_config`.
- Firecrawl is optional and disabled for realtime monitor polling by default.
- Firecrawl hosted may improve complex-page success rates; self-host does not include hosted Fire-engine advanced anti-blocking capabilities.
- If Firecrawl returns a challenge page, it is still classified as protected source.
- Inventory-sensitive Firecrawl requests use `maxAge=0` and default cache-disabled behavior.

## Test Plan

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/test_install_script.py
node --check static/app.js
bash -n install.sh
```

Current result:

- 135 tests passing
- Python compile check passing
- `static/app.js` syntax check passing
- `install.sh` syntax check passing

## Manual Smoke Test

- Create a `generic_pricing_table` task and verify `Order Now` maps to in stock.
- Create a `whmcs` task and verify `Out of Stock` maps to sold out.
- Import one merchant page and verify discovered products enter preview before task creation.
- If Firecrawl is configured, run product intake with `firecrawl_map` and verify backend_used is shown.
- Bulk-create preview items twice and verify the second run syncs existing tasks instead of duplicating them.
- Create a `manual` task, click “有货” and “售罄”, and verify Telegram state transitions.
- Create a `webhook` task, reset token, POST `stock`, then POST `status=sold_out`.
- Verify webhook plaintext token and Firecrawl API key do not appear in snapshot/log output.
- Verify a Cloudflare challenge fixture/page shows protected-source cooldown and does not rebuild Chromium repeatedly.

## Risk

- Extractors are heuristic; add offline HTML fixtures for new merchant layouts.
- Automated tests do not use live merchant pages.
- Firecrawl hosted sends page content to an external provider and may have cost/rate-limit implications.
- Browser behavior still needs VPS smoke testing with the installed Chromium binary.
