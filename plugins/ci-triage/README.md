# ci-triage

Triage backend `API_TESTS-CI` failure noise from the BlazeMeter Slack monitoring
channels: find which failures are persistent vs. flaky, identify the likely
culprit commit, check for an already-open PR before ever drafting a
notification, and end with one verdict per failure plus (only when warranted)
a Slack draft — never sent automatically.

## What's in this plugin

```
ci-triage/
├── .claude-plugin/plugin.json          # manifest
├── hooks.json + hooks/                 # PreToolUse guard — blocks real Slack sends, drafts/reads pass through
└── skills/ci-culprit-check/SKILL.md    # the triage workflow (release-window sizing, culprit-commit ID, open-PR gate)
```

No bundled MCP server here (unlike e.g. the `opensearch` plugin) — this skill
uses whichever `mcp__claude_ai_Slack__*` tools your Claude Code environment
already exposes via the Slack (claude.ai connector) integration, plus `gh`
CLI for everything GitHub-side. There's nothing for this repo to start or
manage.

## Prerequisites

- **`gh` CLI installed and authenticated** (`gh auth status`) with read access
  to the BlazeMeter GitHub org — the skill shells out to `gh api` / `gh pr
  list` / `gh pr view` for commit history and open-PR checks.
- **Slack (claude.ai connector) MCP integration connected** — check via
  Claude's connectors settings. If `mcp__claude_ai_Slack__*` tools aren't
  available in your session, the skill can't read the monitoring channels or
  create drafts. This plugin doesn't configure the connector for you.
- **Access to `#bm-api-monitoring` and `#bm-notifications-jenkins-api-result-for-ci`**
  in the BlazeMeter Slack workspace under the account the connector uses.

## Install

```
/plugin marketplace add <owner>/<repo>
/plugin install ci-triage@coreteam-claude-base
/reload-plugins
```

To verify:

```
/plugin list                 # confirms ci-triage is installed
```

To update:

```
/plugin marketplace update coreteam-claude-base
/reload-plugins
```

## Use

Ask naturally, or invoke the skill directly:

```
/ci-culprit-check
```

Claude pulls both channels bounded to the current release-branch cut date (not
just "yesterday vs. today"), classifies each failing test as persistent or
flaky, identifies the likely culprit commit for persistent ones, checks for an
already-open PR before ever pointing at a person, and ends with one compact
verdict block per failure. It asks exactly one question at the very end — send
the prepared draft(s) or not — never mid-run.

## Uninstall

```
/plugin uninstall ci-triage@coreteam-claude-base
/plugin marketplace remove coreteam-claude-base
```

## Safety guardrail

The bundled `PreToolUse` hook (`hooks/block-slack-real-send.sh`) blocks the two
"real send" Slack tools (`slack_send_message`, `slack_schedule_message`)
outright, for the whole session, while this plugin is installed — the skill
itself only ever calls `slack_send_message_draft`. This is a hard backstop for
the "never sends a message on its own" promise, not just a prose instruction
the model could drift from.

**Scope note:** the hook applies plugin-wide, not just while this skill is
active — if you need to send an actual Slack message some other way in the
same session, uninstall this plugin first (or have a human send the prepared
draft, which is the intended flow anyway).

## Known limitations

- Internal Jenkins (`blazect-jenkins.blazemeter.com`) is VPN/auth-gated — the
  skill relies on Slack digest text and `gh` CLI rather than fetching
  `testReport`/`consoleText`/`allure` pages directly.
- A failure that already existed at the very start of the current sprint
  window needs a wider bisection than this skill performs by default (see the
  SKILL.md note in Phase 3) — it will say so plainly rather than guessing.
