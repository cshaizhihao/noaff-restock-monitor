# PR Draft

## Commit Message

```text
feat: add protected-source aware IDC restock strategies
```

## PR Title

Add protected-source aware IDC restock strategies

## Summary

This PR completes the public-page IDC restock monitoring path without implementing Cloudflare / Turnstile / CAPTCHA bypasses.

It adds strategy-based fetching, IDC/WHMCS extractors, protected-source cooldown, and external inventory inputs through manual updates and webhook ingest. Telegram send/edit/sold-out behavior is reused through one state machine for crawler, manual, and webhook sources.

## What Changed

- Added task fetch strategies:
  - `browser`
  - `static_http`
  - `generic_pricing_table`
  - `whmcs`
  - `manual`
  - `webhook`
- Added fetcher abstraction:
  - `FetchResult`
  - `StaticHttpFetcher`
  - `BrowserFetcher`
  - `ExternalInputFetcher`
  - `FetcherSelector`
- Split Cloudflare challenge handling from browser auto-heal:
  - challenge pages return `cloudflare_challenge`
  - challenge pages do not trigger browser rebuild
  - protected sources enter 1 / 3 / 10 minute cooldown
- Added IDC extractors:
  - `generic_pricing_table`
  - `whmcs`
- Added manual stock update API and dashboard controls.
- Added webhook ingest API with one-time plaintext token reset.
- Store webhook tokens as HMAC hashes; expose only token hints in snapshots.
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

## Test Plan

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py tests/test_app.py tests/test_install_script.py
bash -n install.sh
```

Current result:

- 104 tests passing
- Python compile check passing
- `install.sh` syntax check passing

## Manual Smoke Test

- Create a `generic_pricing_table` task and verify `Order Now` maps to in stock.
- Create a `whmcs` task and verify `Out of Stock` maps to sold out.
- Create a `manual` task, click “有货” and “售罄”, and verify Telegram state transitions.
- Create a `webhook` task, reset token, POST `stock`, then POST `status=sold_out`.
- Verify webhook plaintext token does not appear in snapshot/log output.
- Verify a Cloudflare challenge fixture/page shows protected-source cooldown and does not rebuild Chromium repeatedly.

## Risk

- Extractors are heuristic; add offline HTML fixtures for new merchant layouts.
- Automated tests do not use live merchant pages.
- Browser behavior still needs VPS smoke testing with the installed Chromium binary.
