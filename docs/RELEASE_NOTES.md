# Release Notes Draft

## Title

Protected-source aware IDC restock monitoring

## Summary

This release completes the IDC restock monitoring path for public product pages:

- public page fetching
- strategy-based fetchers
- IDC / WHMCS page extractors
- protected-source cooldown for Cloudflare challenge pages
- Telegram state machine reuse for crawler, manual, and webhook inputs

The project intentionally does not bypass Cloudflare / Turnstile / CAPTCHA challenges.

## Highlights

- Added task fetch strategies:
  - `browser`
  - `static_http`
  - `generic_pricing_table`
  - `whmcs`
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
  - `ExternalInputFetcher`
  - `FetcherSelector`
- Added IDC extractors:
  - `generic_pricing_table`
  - `whmcs`
- Added manual stock update API and dashboard controls.
- Added webhook ingest API with one-time plaintext token generation.
- Webhook tokens are stored as HMAC hashes; snapshots/logs do not expose plaintext tokens.
- Updated README, `.env.example`, and handoff documentation.

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

No manual migration is required for SQLite databases initialized by the app.

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
python -m unittest discover -s tests -v
python -m py_compile app.py tests/test_app.py tests/test_install_script.py
bash -n install.sh
```

Current baseline:

- 104 tests passing
- Python compile check passing
- `install.sh` bash syntax check passing

## Manual Smoke Test Checklist

- Create a `generic_pricing_table` task using a static fixture-like IDC pricing page and confirm `Order Now` is detected as in stock.
- Create a `whmcs` task with a known product title or `pid` and confirm `Out of Stock` is detected as sold out.
- Create a `manual` task and click dashboard “有货” and “售罄”; confirm Telegram send/edit behavior.
- Create a `webhook` task, reset token, POST `stock`, then POST `status=sold_out`; confirm Telegram send/edit behavior.
- Force a Cloudflare challenge fixture/page and confirm `cloudflare_challenge`, cooldown UI, no repeated browser rebuild.
- Confirm dashboard snapshot does not expose webhook plaintext tokens.

## Remaining Risks

- IDC page extractors are heuristic; each new merchant layout should get offline HTML fixture tests.
- Live merchant pages were not used in automated tests.
- Sites protected by Cloudflare / Turnstile / CAPTCHA require manual/webhook/alternate public-source workflows.
- Browser-based behavior should be smoke-tested on the target VPS with the installed Chromium binary.
