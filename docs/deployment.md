# Deploying fathm

Real-deployment packaging for the pieces already built: the API+console server, the Telegram
planner chat bot, and the weekly C6 planner sweep. See `docs/telegram-bot-setup.md` for the chat
bot's own setup detail (BotFather registration, planner provisioning); this doc covers the API
server and how all four systemd units fit together.

## 1. What runs where

Four systemd units under `deploy/systemd/`, one process each, all owned by a dedicated `fathm`
service user on the deployment box (a Pi or similar local-first host, per
`docs/DESIGN-FATHM-SYSTEM.md` section 20's local-first posture - no hosting model beyond that has
been decided):

| Unit | Type | Runs | Purpose |
|---|---|---|---|
| `fathm-api.service` | simple, `Restart=on-failure` | `ap-api` (`uvicorn ap_api.app:app`) | the JSON API (`ap_api`) and the manager console (`ap_console`, mounted on the same app) - `docs/DESIGN-FATHM-SYSTEM.md` section 15 |
| `fathm-chat-telegram.service` | simple, `Restart=on-failure` | `fathm-chat-telegram` | the Telegram planner-chat bot (C20) - see `docs/telegram-bot-setup.md` |
| `fathm-planner-sweep.service` + `.timer` | oneshot, weekly | `python3 -m ap_planner_bot.sweep` | the C6 drift-detection + proposal-drafting sweep |

All three long-running units talk to the same on-disk state (`AP_STORE_ROOT`, `AP_INDEX_ROOT`,
`AP_AUTH_DB`) - they must run on the same box (or share a mounted volume) as each other, since none
of this is a hosted/networked storage layer today.

## 2. Install

```bash
# As root, on the deployment box, with the repo checked out to /opt/fathm (adjust paths in every
# unit file below if you use a different layout):
sudo useradd --system --home-dir /home/fathm --create-home fathm
cd /opt/fathm && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

sudo cp deploy/systemd/fathm-api.service /etc/systemd/system/
sudo cp deploy/systemd/fathm-chat-telegram.service /etc/systemd/system/
sudo cp deploy/systemd/fathm-planner-sweep.service /etc/systemd/system/
sudo cp deploy/systemd/fathm-planner-sweep.timer /etc/systemd/system/
sudo mkdir -p /etc/fathm
```

Adjust `User=`/`WorkingDirectory=`/`ExecStart=`/`ReadWritePaths=` in each unit for the real
deployment path first - they ship with placeholder values (`/opt/fathm`, a `fathm` service user),
same as `fathm-chat-telegram.service` always has.

## 3. Environment variables

Each unit reads its own `EnvironmentFile=` under `/etc/fathm/` (not committed - these are secrets
plus box-specific paths). The full set a real deploy needs, split by which unit(s) read it:

| Variable | Default | Read by | Meaning |
|---|---|---|---|
| `AP_STORE_ROOT` | `~/.fathm/ap_store` | api, sweep | package store root (`ap_store.PackageStore`) |
| `AP_INDEX_ROOT` | `~/.fathm/ap_index` | api, sweep | C4 FTS5 search index root (`ap_index.IndexStore`) |
| `AP_AUTH_DB` | `~/.fathm/auth.sqlite3` | api | credentials/sessions DB (`ap_auth.AuthStore`) - provision the first admin with `ap-auth adduser ... --roles admin` before starting the service |
| `AP_STANDARD_REGISTRY_ROOT` | unset (falls back to the repo's `profiles/`) | api, sweep | versioned profile registry root (`ap_registry.ProfileRegistry`) - set this for a real deployment so Standard-change proposals (C6/C7) actually version instead of resolving to the read-only repo copy |
| `ANTHROPIC_API_KEY` | unset (required) | api, sweep | the C4/C6 LLM egress client (`ap_manager_bot.llm_client.AnthropicHTTPClient`) - see the egress-posture note in `CLAUDE.md`'s C4 section. **Missing this does not crash the server** (see §4 below) - the Ask panel, JSON chat route, and sweep button each fail cleanly per-request instead |
| `AP_MANAGER_BOT_MODEL` | unset (required, no default - D6) | api, sweep | the model id the captain's egress posture approves; must be pinned explicitly, see `CLAUDE.md`'s C4 section and `llm_client.py`'s module docstring |
| `AP_API_HOST` / `AP_API_PORT` | `127.0.0.1` / `8000` | api | bind address - keep this loopback-only and front it with `tailscale serve` (§5), don't bind a public interface directly |
| `AP_GATE_BEFORE_REVIEW` / `AP_ALLOW_SELF_REVIEW` | `true` / `false` | api | `ap_review.ReviewPolicy` knobs - only override for a non-default review posture |
| `TELEGRAM_BOT_TOKEN` | unset (required for chat) | chat | BotFather token - see `docs/telegram-bot-setup.md` step 1 |
| `AP_CHAT_ALLOWLIST_PATH` | `~/.fathm/chat_telegram_allowlist.json` | chat | Telegram-user-id -> fathm-identity mapping - provisioned via the console's Admin -> Team bot access screen, not hand-edited in a real deploy |
| `AP_CHAT_NOTIFY_CHAT_ID` | unset (notifications off) | api (and chat, if the sweep should also notify) | C6/C7 proposal-lifecycle Telegram notifications - see `docs/telegram-bot-setup.md` §7 |
| `AP_ACTOR_ID` / `AP_ACTOR_ROLES` | n/a | sweep | same-machine identity for the weekly sweep's service account (`ap_auth.identity.identity_from_env`) - provision with `ap-auth adduser --no-password` first |

Example `/etc/fathm/api.env`:

```bash
AP_STORE_ROOT=/home/fathm/.fathm/ap_store
AP_INDEX_ROOT=/home/fathm/.fathm/ap_index
AP_AUTH_DB=/home/fathm/.fathm/auth.sqlite3
AP_STANDARD_REGISTRY_ROOT=/home/fathm/.fathm/standard_registry
ANTHROPIC_API_KEY=sk-ant-...
AP_MANAGER_BOT_MODEL=claude-sonnet-5
AP_CHAT_NOTIFY_CHAT_ID=-1001234567890
```

`fathm-chat-telegram.service` and `fathm-planner-sweep.service` each need their own env file
(`/etc/fathm/chat-telegram.env`, `/etc/fathm/planner-sweep.env`) with the subset of the table above
each one reads - `docs/telegram-bot-setup.md` §4 and `fathm-planner-sweep.service`'s own comments
cover those two in full.

## 4. Missing `ANTHROPIC_API_KEY` is a supported, non-fatal state

The API server starts and serves every non-LLM route fine with no key configured - useful for
standing up package storage/review/lifecycle/console browsing before the LLM egress decision is
wired in for a given box. Once a request actually needs the LLM (the Ask panel's SSE stream, the
JSON `/chat/manager` route, or the console's "Run planner sweep" button), it fails with a clean,
in-band error naming the missing variable - never a raw 500 or a hung connection
(`tests/test_llm_missing_config_error_paths.py` is the acceptance test for this across all three
call sites; see `ap_manager_bot/llm_client.py`'s module docstring for why the check is deferred to
first use rather than raised at construction).

## 5. Fronting with `tailscale serve`

The API server binds loopback-only (`AP_API_HOST=127.0.0.1`, the default) - no public port is ever
opened directly. `tailscale serve` puts it on the tailnet with a real HTTPS cert and no inbound
firewall rule needed:

```bash
sudo tailscale serve --bg 8000
```

This serves `https://<device-name>.<tailnet>.ts.net/` -> `http://127.0.0.1:8000` for every device
on the tailnet. Use `tailscale serve --bg --set-path /console 8000` variants or `tailscale funnel`
only if a specific narrower/public exposure is actually needed - the default `serve` (tailnet-only)
is the right posture for an internal manager tool. Planners and reviewers then log into
`https://<device-name>.<tailnet>.ts.net/console/login` from any device on the tailnet; the Telegram
bot and planner-sweep processes reach the API over plain loopback
(`AP_CHAT_MANAGER_BASE_URL=http://127.0.0.1:8000`, the default) and never need tailnet routing
themselves since they run on the same box.

## 6. Start everything

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fathm-api
sudo systemctl enable --now fathm-chat-telegram
sudo systemctl enable --now fathm-planner-sweep.timer   # the .service itself is oneshot, triggered by the timer
sudo tailscale serve --bg 8000
```

Check status: `systemctl status fathm-api fathm-chat-telegram fathm-planner-sweep.timer`.
Logs: `journalctl -u fathm-api -f` (and the equivalent for the other two units).

## 7. Reliability notes

Same posture as `docs/telegram-bot-setup.md` §5 describes for the chat bot: systemd's
`Restart=on-failure` is the outer safety net for `fathm-api` and `fathm-chat-telegram` if the
process itself dies (unhandled exception, OOM); `fathm-planner-sweep` is `Type=oneshot` triggered
weekly by its `.timer` (`Persistent=true`, so a missed run while the box was off still fires once
it's back), not a long-running process that needs its own restart policy.
