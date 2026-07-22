# Contributing to coreteam-claude-base

This repo is the shared base every team uses to publish Claude Code skills, slash commands, sub-agents, and hooks. Changes are gated by a four-job CI pipeline. Local-first workflow: validate before pushing.

## Linked repositories — read this first

This codebase is mirrored in **two** GitHub repositories that MUST stay byte-for-byte identical: `PerfectoMobileDev/claude-base` and `Blazemeter/claude-base`. You push to one, the auto-sync workflow propagates to the other. A required CI check (`Verify sibling sync`) blocks `main` merges when the two repos diverge.

**Before opening a PR**, confirm:

- You're committing to whichever side is most natural (either is fine — there is no source of truth).
- You did **not** push directly to the sibling out-of-band; if you did, see `LINKED_REPOS.md` → "Recovery procedure".
- Workflow files under `.github/workflows/sync-to-sibling.yml` and `verify-sibling-sync.yml` are off-limits except via coordinated PR on **both** repos. Editing them on only one side guarantees drift.

Full contract, race-condition handling, and the one-time PAT / branch-protection setup are in [`LINKED_REPOS.md`](./LINKED_REPOS.md).

## One-time setup

```bash
git clone https://github.com/<owner>/claude-base.git
cd claude-base
pip install -r scripts/requirements.txt
```

That installs the single Python dep (`pyyaml`). No `node_modules` anywhere in this repo.

## Make a change

Whichever artifact type you're adding (skill, command, agent, hook), the workflow is the same:

1. Copy the matching template from `plugins/base-tools/<kind>/example-*` (or create a new file alongside it).
2. Edit the YAML frontmatter (`description` is the most important field — see the [Claude Code plugin docs](https://docs.claude.com/en/docs/claude-code/plugins) for the full schema).
3. Write the body. For skills, follow progressive disclosure: keep `SKILL.md` under 500 lines and move heavy reference material into `references/`.
4. If your skill/agent declares new tools in `allowed-tools`/`tools`, make sure every entry is in `policy/allowed-tools.yaml`. Add an entry there in the same PR if needed.

See the "Adding new artifacts" section of `README.md` for the exact commands.

## Validate locally before opening a PR

```bash
python scripts/validate.py --strict
python -m unittest discover -s scripts/tests -t scripts
python scripts/behavioral_runner.py --lint       # validate test case files
```

If you touch hook scripts:

```bash
shellcheck plugins/*/hooks/*.sh    # apt install shellcheck (or choco install shellcheck on Windows)
pip install ruff && ruff check plugins/*/hooks/*.py
```

If you have the Claude CLI installed:

```bash
claude plugin validate .
```

If you want to run behavioral tests against the real API (optional, costs money):

```bash
pip install -r scripts/requirements-eval.txt
ANTHROPIC_API_KEY=... python scripts/behavioral_runner.py
```

## CI gates

Five jobs run on every PR; merge is blocked if any fails:

| Job | Catches |
|---|---|
| `structural` | Schema, standards, tool policy (incl. exceptions), smoke secrets, validator regression tests |
| `sast` | Dangerous shell patterns, broken Python in hook scripts |
| `secret-scan` | Comprehensive secret scan via gitleaks (history-aware) |
| `claude-cli` | Claude Code's canonical schema check |
| `behavioral` | Lints `tests/cases.yaml` files always; runs API tests if `ANTHROPIC_API_KEY` secret is set |

## Tool policy changes

`policy/allowed-tools.yaml` is **the** policy for what tools any skill/command/agent may declare. Three layers, evaluated in order:

1. **`forbidden:`** — always loses. Even an exception can't grant a forbidden tool.
2. **`allowed:`** — global allowlist for every artifact. Add a new entry here only if multiple skills will need the tool. Use the narrowest Bash scope possible.
3. **`exceptions:`** — per-artifact grants for tools that one specific skill legitimately needs. Each entry must include a `justification:` reviewed by CODEOWNERS at merge time.

Example exception:

```yaml
exceptions:
  - artifact: base-tools/skills/terraform-plan
    tools: [Bash(terraform plan)]
    justification: "plan-only summary; cannot run apply or destroy"
```

`Bash` (unscoped) and `Bash(*)` are forbidden by default. MCP tools (`mcp__*`) are exempt from this policy — they're governed by `.mcp.json`.

## Behavioral tests

Each skill can ship `tests/cases.yaml` next to its `SKILL.md`. Cases are linted on every PR; API-driven runs are opt-in via the `ANTHROPIC_API_KEY` repo secret. See `plugins/base-tools/skills/summarize-pr/tests/cases.yaml` for a worked example and `scripts/README.md` for the schema.

## Telemetry

The `PreSkill` hook (`hooks/log-skill-activation.py`) writes one JSON line per skill activation to `${CLAUDE_PLUGIN_DATA}/base-tools/skills.jsonl`. Run `python scripts/aggregate_telemetry.py` to see which skills your team actually uses — useful for deciding what to invest in, deprecate, or refine.

## Adding tests

If you fix a bug in `scripts/validate.py`, add a regression test under `scripts/tests/test_validate.py`. The tests use only the standard library (`unittest` + `tempfile`) — no extra dependencies. Each test should fail without your fix and pass with it.

## Code review

`CODEOWNERS` auto-assigns the right reviewers. Changes to `policy/`, `scripts/`, and `.github/` require an owner approval — these files affect every downstream team.

## Versioning

`base-tools` follows semver. Bump `plugin.json` `version` for every user-visible change:

- patch: bug fixes, doc updates
- minor: new skill / command / agent
- major: breaking change to a tool name, hook event, or policy

Leave the version field out entirely if you want every commit on `main` to be the latest release (the git SHA becomes the version).

## License

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
