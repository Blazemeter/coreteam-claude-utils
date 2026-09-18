# master-investigation

Structured playbook for investigating a misbehaving BlazeMeter master/test/session
— stuck, wrong metric, silent failure, intermittent, customer-reported — across
`denv`/`bzdev`/`ci`/`staging`/`prod`. Composes OpenSearch log search, Mongo (main +
bigdata) state, GCS session artifacts, and source-code verification across
`taurus`/`taurus-cloud`/`a.blazemeter.com`/`bzm-crane`.

## What's in this plugin

```
master-investigation/
├── .claude-plugin/plugin.json                  # manifest
├── hooks.json + hooks/                         # PreToolUse guard — blocks gcloud storage rm/mv
└── skills/investigate-master/SKILL.md           # the investigation playbook (Phases 0-6)
```

No bundled MCP server here — this skill uses whichever OpenSearch and Mongo MCP
servers your Claude Code environment already exposes, plus the `gcloud` CLI for
GCS artifact fetches and Cloud Audit Log checks. There's nothing for this repo
to start or manage on its own.

## Prerequisites

- **The `opensearch` plugin, installed separately** — this plugin bundles no MCP
  server of its own; it depends on `opensearch`'s `opensearch-reader` MCP server
  for Phase 3. Install both, or Phase 3 has nothing to call.
- **A Mongo MCP server** connected to BlazeMeter's main and bigdata clusters
  (server name varies by install — e.g. `mongodb-production` /
  `mongodb-bigdata-production`). Not bundled here either; the skill just uses
  whatever's already connected, and says plainly (per Step 0) when it isn't.
- **`gcloud` CLI installed and authenticated** (`gcloud auth list`) — used for
  fetching session artifacts from GCS (Phase 1) and, since MOB-54071, for
  checking GCP's own Cloud Audit Log when the question is "did a cloud-side
  action actually happen" (Phase 3). If auth has expired, this skill cannot
  refresh it for you (`gcloud auth login` is interactive) — it will ask you to
  run it yourself and retry.

## Install

```
/plugin marketplace add <owner>/<repo>
/plugin install master-investigation@coreteam-claude-base
/plugin install opensearch@coreteam-claude-base   # dependency — see Prerequisites
/reload-plugins
```

To verify:

```
/plugin list                 # confirms master-investigation (and opensearch) are installed
```

## Update

```
/plugin marketplace update coreteam-claude-base
/reload-plugins
```

Remember: the installed-plugin cache is keyed by version number
(`~/.claude/plugins/cache/coreteam-claude-base/master-investigation/<version>/`).
A skill/hook change that doesn't bump `version` in `plugin.json` (and the
matching entry in the repo-root `.claude-plugin/marketplace.json`) never
reaches anyone who already has this plugin installed — `marketplace update` +
`reload-plugins` is what actually re-fetches the new content, not
`/plugin install` again (that's a no-op once already installed).

## Use

Ask naturally, or invoke the skill directly:

```
/investigate-master
```

Claude will ask for the master ID(s) and environment if you don't give them,
run the Step 0 preflight for that environment, then work through Phases 0–6:
understand intent, pull the full per-session artifact bundle, check database
state (with a fleet-wide aggregate before sampling individual sessions),
cross-reference centralized logs (including, since MOB-54071, the cloud
provider's own audit log when a cloud-side action needs independent
confirmation), compare against a control sample that didn't exhibit the
problem, verify any resulting theory against the actual source, and finally
report which conclusions are directly evidenced versus inferred.

## Uninstall

```
/plugin uninstall master-investigation@coreteam-claude-base
/plugin marketplace remove coreteam-claude-base
```

## Safety guardrail

The bundled `PreToolUse` hook (`hooks/block-gcs-destructive-ops.sh`) blocks
`gcloud storage rm`/`gcloud storage mv` outright, matched anywhere in the
command string (so an appended/chained command is caught too, not just a
literal prefix). This skill only ever needs to *read* session artifacts from
the shared `gs://blazemeter-gcp` bucket — base-tools' own safety guardrail
covers `gcloud compute` mutations and Mongo/DynamoDB/Redis/S3 writes, but
explicitly not `gcloud storage`, so this plugin carries its own backstop
rather than assuming base-tools is installed alongside it.

`gcloud storage cp`'s direction (uploading vs. downloading) still isn't
distinguishable by this hook without more argument-position parsing than is
safe to rely on today — that one deliberately falls to the normal interactive
permission prompt per invocation instead (see `policy/allowed-tools.yaml`'s
exceptions entry for this skill for the full reasoning).

## Known limitations

- **Requires the `opensearch` plugin to be installed alongside this one.**
  There's no automatic dependency install in Claude Code plugins today — if
  you skip it, Phase 3 (centralized log search) has no MCP server to call and
  the skill will say so rather than silently skipping it.
- **Mongo access is environment-dependent.** `denv` requires a live
  `kubectl port-forward` that this skill can't establish on its own;
  `bzdev`/`staging`/`ci` don't have Mongo access configured at all as of this
  writing (see the SKILL.md Step 0 table).
- **A first-attempt failure against `prod` is often just a disconnected VPN**,
  not real unavailability — the skill retries once after asking you to check
  VPN before concluding a leg is genuinely down.
