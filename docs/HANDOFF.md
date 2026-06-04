# NOAFF Handoff

Project: NOAFF restock monitor

Workspace layout on VPS:
- `/srv/noaff-monitor/repo` for the git checkout
- `/srv/noaff-monitor/data` for persistent data
- `/srv/noaff-monitor/logs` for logs
- `/srv/noaff-monitor/backups` for archives and bundles
- `/srv/noaff-monitor/sessions` for Paseo session exports or notes

Current focus:
- Flask dashboard
- SQLite storage
- Telegram push workflow
- DrissionPage scraping
- install script and deployment polish

Next step for the agent:
1. Read the repo.
2. Keep working only inside `/srv/noaff-monitor/repo`.
3. Use the sibling folders above for artifacts and long-lived files.
4. Continue from the current UI and install-script state.

Run example:
`cd /srv/noaff-monitor/repo && paseo run -d --provider codex --cwd /srv/noaff-monitor/repo "Read docs/HANDOFF.md and continue the NOAFF project"`
