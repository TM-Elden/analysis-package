# Telegram planner chat v0 - setup

Implements C20 (`docs/DESIGN-FATHM-SYSTEM.md` section 13k) for Telegram, per the captain-decided
platform choice (`fathm-phase3-readiness-decision-chat-platform`: "use telegram for now - will add
slack later"). Code: `src/ap_chat/` (platform-neutral core + runner) and `src/ap_chat/telegram/`
(the Telegram Bot API adapter) - see `src/ap_chat/__init__.py` for the module boundary.

## 1. Register the bot with BotFather

1. In Telegram, message `@BotFather` -> `/newbot`.
2. Pick a display name and a username ending in `bot` (e.g. `fathm_manager_bot`).
3. BotFather returns a token shaped like `123456789:AAExampleTokenDoNotUseThisOne` - this is
   `TELEGRAM_BOT_TOKEN` below. Treat it like any other credential (it's the whole bot identity);
   do not commit it.
4. If planners will @mention the bot inside a group chat, BotFather -> `/setprivacy` -> select the
   bot -> **Disable** (privacy mode ON means the bot only sees messages that already @mention it or
   reply to it, which is usually what you want and is the default - only disable it if the bot also
   needs to see all messages, e.g. for a future non-mention trigger; the v0 design doesn't need
   this, so leaving privacy mode ON is the recommended default).

## 2. Provision each planner (recommended: the console)

Per task requirement 3, a Telegram user only gets fathm answers after being added by an operator -
there is no self-service signup path. The recommended path is the console's **Admin → Team bot
access** screen (`/console/admin/team-bot`, P5.4): get the planner's numeric Telegram user id
(have them message @userinfobot, or read it off the first message they send the new bot, logged at
INFO level: "refusing message from unmapped platform user '<id>'"), then fill in the fathm user id,
display name, and Telegram user id (roles default to `team_reader`, the minimum role that gets any
C4 answers - `ap_manager_bot.scoping` - use a broader role only if that planner should also see
`internal_restricted` chunks). One submit creates the service account, issues its bearer token, and
writes the allowlist row - the raw token is never shown or logged. **No bot restart needed**: the
running `BotRunner` reloads the allowlist on its next resolve-miss and the planner's very first
message goes through (`ap_chat/runner.py`'s reload-on-miss). Revoking is a button on the same
screen (disables the user, which also revokes every token, and removes the allowlist row).

### Bootstrap / headless fallback (CLI)

Before any admin can log into the console (or in a fully headless deployment), provision the same
way by hand:

```bash
# 1. Get their numeric Telegram user id (see above).

# 2. Create a scoped, password-less service account (no-password = bearer-token-only, no login UI):
ap-auth adduser planner.alice --display-name "Alice Planner" --roles team_reader --no-password

# 3. Issue a bearer token for it (shown once - copy it now):
ap-auth token planner.alice
```

## 3. Write the allowlist file (only needed for the CLI fallback)

`AP_CHAT_ALLOWLIST_PATH` (default `~/.fathm/chat_telegram_allowlist.json`) - one entry per
provisioned planner, keyed by their Telegram user id:

```json
{
  "555000111": {"fathm_user_id": "planner.alice", "token": "<the ap-auth token output>"},
  "555000222": {"fathm_user_id": "planner.bob", "token": "<the ap-auth token output>"}
}
```

The console flow above writes this file for you (atomically, via `ap_chat.identity_map.add_entry`)
and the running bot picks up the new row on its next resolve-miss with no restart - see step 2. If
you edit the file by hand instead (the CLI fallback path), the same reload-on-miss behavior applies:
the *next* message from a newly-added id triggers the reload, so no restart is needed there either;
a restart (`sudo systemctl restart fathm-chat-telegram`) is only needed to pick up an edit before
anyone actually messages the bot.

## 4. Configure and run

Environment variables (`EnvironmentFile=` for the systemd unit, or export directly):

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(required)* | BotFather token from step 1 |
| `AP_CHAT_ALLOWLIST_PATH` | `~/.fathm/chat_telegram_allowlist.json` | identity mapping, step 3 |
| `AP_CHAT_OFFSET_PATH` | `~/.fathm/chat_telegram_offset.json` | persisted `getUpdates` offset, survives restarts |
| `AP_CHAT_MANAGER_BASE_URL` | `http://127.0.0.1:8000` | the running `ap-api` server (`POST /chat/manager`) |
| `AP_CHAT_CONSOLE_BASE_URL` | `<manager base>/console` | base URL for citation links into package detail pages |
| `AP_CHAT_POLL_TIMEOUT` | `30` | `getUpdates` long-poll wait, seconds |
| `AP_CHAT_UNAUTHORIZED_REPLY` | `true` | reply with a refusal to an unmapped Telegram user vs. silently drop |
| `AP_CHAT_NOTIFY_CHAT_ID` | *(unset = notifications off)* | C6/C7 proposal-lifecycle notify-v0 (§7 below) - the chat id `proposal.created`/`proposal.decision`/version-released messages post to |

Run directly:

```bash
PYTHONPATH=src TELEGRAM_BOT_TOKEN=... python3 -m ap_chat.telegram
# or, once installed: fathm-chat-telegram
```

Run as a service (survives reboots/crashes - task requirement 5):

```bash
sudo cp deploy/systemd/fathm-chat-telegram.service /etc/systemd/system/
sudo mkdir -p /etc/fathm && sudo tee /etc/fathm/chat-telegram.env <<'EOF'
TELEGRAM_BOT_TOKEN=...
AP_CHAT_MANAGER_BASE_URL=http://127.0.0.1:8000
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now fathm-chat-telegram
```

Adjust `User=`/`WorkingDirectory=`/`ExecStart=`/`ReadWritePaths=` in the unit file for the real
deployment path first - it ships with placeholder values (`/opt/fathm`, a `fathm` service user).

## 5. Reliability notes

- **Long-polling, not a webhook**: `getUpdates` is an outbound-only HTTPS call from the bot process
  to `api.telegram.org` - no public ingress needed on the Pi, same property Socket Mode would have
  given on Slack.
- **Reconnect/backoff**: a failed `getUpdates` call (network blip, Telegram outage) is caught by
  `ap_chat.runner.BotRunner.run_forever`, which backs off exponentially (1s -> 60s cap) and retries
  indefinitely - no manual restart needed for a transient failure. `tests/test_chat_runner.py`
  exercises this against an injected failing platform.
- **systemd `Restart=on-failure`** is the outer safety net if the process itself dies outright
  (unhandled exception, OOM) - the two layers are complementary, not redundant.
- **Offset persistence**: `AP_CHAT_OFFSET_PATH` is written after every poll cycle so a systemd
  restart doesn't cause Telegram to redeliver (and the bot to re-answer) every message since the
  last *process-lifetime* offset - it resumes from the last *persisted* one.

## 7. Proposal lifecycle notifications (C6/C7 notify-v0)

Separate from the planner-chat bot above: `AP_CHAT_NOTIFY_CHAT_ID` (a chat id, typically a
fathm-team group chat, not any one planner's DM) points `ap_api`'s and `ap_planner_bot`'s
`ProposalWorkflow` instances at a `TelegramProposalNotifier`
(`src/ap_chat/telegram/notify.py::notifier_from_env`), reusing the same `TELEGRAM_BOT_TOKEN` and
`TelegramBotClient` this doc already sets up - no second bot, no second token. Set it in the same
`ap-api`/console server environment (and in `fathm-planner-sweep`'s environment if the weekly
systemd sweep should also notify) to get short, factual posts when a proposal is drafted, decided,
or its approval bumps a profile version. Leaving it unset is a valid, supported state
(notifications off) - the gate's version pinning, not this channel, is what actually enforces a
Standard change; see `skills/fathm-planning/SKILL.md`'s "Check for a Standard update at session
start" section and CLAUDE.md's notify-v0 note.

## 8. Adding Slack later

Per the captain decision, only Telegram ships in this task. When Slack is added: implement
`ap_chat.core.ChatPlatform` against Slack's API (Socket Mode is the equivalent outbound-only
transport - see the readiness report section 5.5) in a new `ap_chat/slack/` subpackage and give it
its own entrypoint/systemd unit. `ap_chat.identity_map`, `ap_chat.manager_client`,
`ap_chat.formatting`, and `ap_chat.runner` are already platform-neutral and should not need to
change - see `src/ap_chat/__init__.py`'s module docstring for the boundary this relies on.
