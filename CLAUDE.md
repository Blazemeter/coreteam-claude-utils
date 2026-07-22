# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo (`Blazemeter/coreteam-claude-utils`) is the core team's **fork** of `Blazemeter/claude-base` — a project-agnostic **Claude Code plugin marketplace + governance framework**, not an application. It ships one bundled plugin (`base-tools`) containing skills, slash commands, sub-agents, and hooks, plus the policy and CI that govern them. Everything is configuration-as-code: YAML frontmatter + Markdown bodies. Tooling is Python-only with a single dependency (`pyyaml`) — there is no `node_modules` anywhere.

## Relationship to upstream (this is a fork)

This is a fork of `Blazemeter/claude-base`. The team customizes it here while pulling in upstream improvements.

- **Remotes:** `origin` → `Blazemeter/coreteam-claude-utils` (this fork), `upstream` → `Blazemeter/claude-base`.
- **Branch model:** `main` is kept as a **clean mirror of upstream** — do not commit to it directly. `develop` is the team integration branch and the repo's default branch; branch off `develop` and open PRs into `develop`.
- **Pull upstream changes (manual — never automatic):**
  ```bash
  gh repo sync Blazemeter/coreteam-claude-utils      # upstream main -> fork main, on GitHub
  # or locally:
  git fetch upstream && git checkout main && git merge upstream/main && git push origin main
  git checkout develop && git merge main && git push origin develop   # carry updates into team line
  ```
  If `main` has diverged, `gh repo sync` refuses rather than clobbering — reconcile locally with `merge`/`rebase` (only `--force` if `main` is meant to be a pure mirror).

- **Opening PRs (fork gotcha):** because this is a fork, `gh pr create` resolves the PR *base repo* to the upstream parent (`Blazemeter/claude-base`, which has no `develop` branch) unless told otherwise, and fails. Two defenses are in place — do both once per clone:
  ```bash
  gh repo set-default Blazemeter/coreteam-claude-utils      # one-time per clone; fixes gh's base resolution
  # always create PRs against this fork + develop explicitly:
  gh pr create --repo Blazemeter/coreteam-claude-utils --base develop --title 'MOB-1234: …' --body '…'
  ```
  The `enforce-jira-id.sh` hook now **blocks** any `gh pr create` that omits `--repo Blazemeter/coreteam-claude-utils` or `--base`, so the failure can't recur silently.

> **Upstream-only contract that does NOT govern this fork:** `Blazemeter/claude-base` is itself mirrored byte-for-byte with `PerfectoMobileDev/claude-base` via `.github/workflows/sync-to-sibling.yml` and `verify-sibling-sync.yml` (see `LINKED_REPOS.md`). Those workflow files were inherited by this fork but the sibling-sync contract is **not** this fork's workflow — review whether they should run here at all before relying on them, and ignore `LINKED_REPOS.md`'s "byte-for-byte identical" rule for this repo.

## Common commands

```bash
pip install -r scripts/requirements.txt              # one-time setup (only dep: pyyaml)

python scripts/validate.py --strict                  # main validator (schema, standards, tool policy)
python -m unittest discover -s scripts/tests -t scripts          # run validator unit tests
python -m unittest scripts.tests.test_validate -v                # run a single test module (note -t/module path)

shellcheck plugins/*/hooks/*.sh                       # lint bash hooks
ruff check plugins/*/hooks/*.py                       # lint python hooks

python scripts/behavioral_runner.py --lint           # validate tests/cases.yaml files (no API calls)
pip install -r scripts/requirements-eval.txt && ANTHROPIC_API_KEY=... python scripts/behavioral_runner.py   # opt-in, hits the real API, costs money

claude plugin validate .                              # Claude Code's canonical schema check
```

CI runs five jobs on every PR (`structural`, `sast`, `secret-scan`, `claude-cli`, `behavioral`); any failure blocks merge.

## Architecture

- **`plugins/base-tools/`** — the single bundled plugin. Subdirs: `skills/`, `commands/`, `agents/`, `hooks/` (scripts + `hooks.json` wiring), and `.claude-plugin/plugin.json`. Each artifact is YAML frontmatter + a Markdown body; `description` is the most important field. Add a new artifact by copying the matching `example-*` template. Skills follow progressive disclosure — keep `SKILL.md` under 500 lines and push heavy reference material into `references/`.
- **`policy/`** — governance config: `allowed-tools.yaml` (the tool allow/deny policy every artifact is validated against), `jira-lifecycle.yaml` (status names + transition IDs), `doc-task.yaml` (doc-planning task config, `project_key` is `__UNSET__` until an org configures it).
- **`scripts/`** — Python tooling: `validate.py` (main validator), `behavioral_runner.py`, `aggregate_telemetry.py`, and `tests/`.
- **`STANDARDS.md`** — the five numbered org rules (summarized below). **`.github/workflows/`** — the five CI jobs.

## Shipping a plugin change: bump the version, then upgrade with two commands

Skills/commands/agents/hooks are auto-discovered from `plugins/base-tools/` — adding one needs **no** manifest registration. But the installed-plugin cache is **keyed by version number** (`~/.claude/plugins/cache/coreteam-claude-base/base-tools/<version>/`), so a change that doesn't bump the version never reaches anyone who already has the plugin — they keep loading the stale cache for that version.

- **Every PR that touches a skill/command/agent/hook must bump `version` in `plugins/base-tools/.claude-plugin/plugin.json`** (and keep the matching entry in `.claude-plugin/marketplace.json` in sync — a mismatch trips a `validate.py` warning). `plugin.json` is the version that wins at install time.
- **To pick up a new version, the upgrade flow is `marketplace update` + `reload-plugins` — NOT `install`:**
  ```
  /plugin marketplace update coreteam-claude-base    # upgrades the installed plugin to the new version (re-fetches the cache)
  /reload-plugins                           # reloads the running session (or fully restart Claude Code)
  ```
  `/plugin install base-tools@coreteam-claude-base` is a **no-op once installed** — it checks by name, not version, and just reports "already installed globally." Use `marketplace update`, not `install`, to upgrade.
- Plugin skills are **namespaced** (`base-tools:grill-me`); they coexist with any personal `~/.claude/skills/` copy of the same short name (`grill-me`), which plugin install never touches.

## Hooks will block your git/JIRA operations

`plugins/base-tools/hooks.json` wires PreToolUse/PostToolUse/PreSkill hooks that actively **block** tool calls. Know these before running git or creating JIRA issues:

- **enforce-jira-id.sh** — `git checkout -b`, `git switch -c`, `git branch`, `git push -u`, and `gh pr create` require a real JIRA key matching `[A-Z][A-Z0-9_]+-[0-9]+`. All-zero placeholders like `MOB-00000` are rejected. It also blocks `gh pr create` unless it explicitly targets this fork (`--repo Blazemeter/coreteam-claude-utils --base <branch>`) — see the fork PR gotcha above. Work on this tooling itself lives under Epic `MOB-50371`.
- **enforce-claude-attribution.sh** — every `git commit` message must contain a `Co-Authored-By: Claude` trailer.
- **inject-ai-generated-label.sh** — JIRA issues created via the Atlassian MCP must include the `AI_generated` label.
- **Safety guardrails** (block destructive actions): pushes/force-push/reset on shared branches, EC2/GCP compute mutations, datastore mutations (DynamoDB/S3/Redis/Mongo writes), credentials in commits, test-skip edits (`@Disabled`, `pytest.mark.skip`, `-DskipTests`), and hook-bypass attempts (`--no-verify`, `core.hooksPath`, `HUSKY=0`).

**Escape hatches** (both logged and audited): `CLAUDE_STANDARDS_SKIP=1` for process rules, `CLAUDE_SAFETY_OVERRIDE=1` for safety guardrails. Note the hook-bypass guard rejects these when *inlined* as a command prefix — export them in the environment instead.

## Standards (see STANDARDS.md for detail)

1. Real JIRA key in branch names and PR descriptions (no placeholders).
2. `AI_generated` label on every JIRA issue created via an LLM tool path.
3. `Co-Authored-By: Claude` trailer on every commit.
4. Documentation-planning task (`DOC-ready:`) for customer-facing work, when confirmed needed (see `file-doc-task` skill).
5. Forward-only JIRA lifecycle transitions kept in step with the work (see `jira-lifecycle` skill).

## Tool policy gate

`policy/allowed-tools.yaml` is the authority on what tools any skill/command/agent may declare. If an artifact's `allowed-tools`/`tools` lists something not in that policy, the `structural` CI job fails — add the entry in the same PR. Bare `Bash`, `Bash(*)`, and patterns like `Bash(rm *)`, `Bash(sudo *)`, `Bash(curl|sh)` are forbidden.
