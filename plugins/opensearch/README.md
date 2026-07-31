# opensearch

Search BlazeMeter logs across `denv`, `bzdev`, `ci`, `staging`, and `prod` OpenSearch
clusters. Bundles a read-only `opensearch-reader` MCP server plus a skill that builds
safe Lucene queries and returns condensed results — no raw JSON dumps, no back-and-forth
query building with the user.

## What's in this plugin

```
opensearch/
├── .claude-plugin/plugin.json   # manifest
├── .mcp.json                    # bundles + auto-starts the opensearch-reader MCP server
├── mcp/server.py                # the MCP server itself (ping / list_indices / search_logs)
├── hooks.json + hooks/          # PreToolUse guard — restricts this plugin to read-only tools
└── skills/opensearch/SKILL.md   # query-construction rules + result presentation
```

## Prerequisites

Export OpenSearch credentials in your shell **before** starting Claude Code — the
bundled MCP server reads them from its environment via `.mcp.json`'s `${VAR}`
substitution:

| Env var | Required for |
|---|---|
| `OPENSEARCH_HOST`, `OPENSEARCH_USER`, `OPENSEARCH_PASSWORD` | `denv` / `bzdev` (share one cluster today) |
| `OPENSEARCH_HOST_CI`, `OPENSEARCH_USER_CI`, `OPENSEARCH_PASSWORD_CI`, `OPENSEARCH_INDEX_CI` | `ci` |
| `OPENSEARCH_HOST_STAGING`, `OPENSEARCH_USER_STAGING`, `OPENSEARCH_PASSWORD_STAGING`, `OPENSEARCH_INDEX_STAGING` | `staging` |
| `OPENSEARCH_HOST_PROD`, `OPENSEARCH_USER_PROD`, `OPENSEARCH_PASSWORD_PROD`, `OPENSEARCH_INDEX_PROD` | `prod` |

Any environment whose vars are unset returns a clear "not configured" error from
`ping`/`search_logs` rather than guessing or silently returning nothing — see the
skill's "Environment status" section.

## Configuring `ci` / `staging` / `prod` access

Only `denv`/`bzdev` (one shared dev cluster) work out of the box. To wire up any of
the other three environments:

1. **Get the OpenSearch Dashboards base URL** for that cluster from your
   infra/platform team — the same URL you'd open in a browser to view Dashboards
   for that environment (e.g. `https://opensearch-<env>.blazemeter.net`). This
   plugin talks to Dashboards' console proxy (`/api/console/proxy`), not a raw
   OpenSearch API port, so the raw cluster endpoint won't work here.
2. **Get read-only credentials** (username + password) for a service account
   scoped to that cluster. Ask infra for a **read-only** account specifically —
   this plugin never needs write access, and the bundled `PreToolUse` hook only
   ever calls `ping`/`list_indices`/`search_logs` anyway.
3. **Export the env vars** for that environment before starting Claude Code, using
   the uppercase env-name suffix:
   ```bash
   export OPENSEARCH_HOST_STAGING="https://opensearch-staging.blazemeter.net"
   export OPENSEARCH_USER_STAGING="<read-only-username>"
   export OPENSEARCH_PASSWORD_STAGING="<read-only-password>"
   # optional — override the default index pattern:
   export OPENSEARCH_INDEX_STAGING="logstash-staging*"
   ```
   Same pattern with `_PROD` or `_CI` in place of `_STAGING`. Put these in your
   shell profile or a secrets-manager-backed env loader (e.g. `direnv`,
   1Password CLI) — **never** commit real values anywhere in this repo, and never
   paste them into `.mcp.json`, `SKILL.md`, or chat.
4. **Default index patterns** if you don't override them: `logstash-ci*`,
   `logstash-staging*`, `logstash-blazemeter*` (prod). Confirm these match your
   actual index naming before relying on results — if they don't, set
   `OPENSEARCH_INDEX_<ENV>` explicitly.
5. **Restart Claude Code** (or `/reload-plugins`) — the MCP server only reads
   these env vars once, at process start.
6. **Verify** by asking Claude to `ping opensearch for staging` (or `prod`/`ci`).
   Expect `{"status": "connected", ...}`. If you still get a "not configured"
   error, double-check the exact var names above — a typo'd suffix silently
   falls through to "not configured" rather than erroring on the typo itself.

## Install

```
/plugin marketplace add <path-or-url-to-this-repo>
/plugin install opensearch@coreteam-claude-base
/reload-plugins   # or restart Claude Code — MCP servers register at startup
```

## Use

Ask naturally — the skill's trigger phrases cover things like:

- `search opensearch for master 82747221 in denv`
- `check logs for fallback errors on bzdev`
- `opensearch prod <lucene query>`

Claude will `ping` the resolved environment first, build a safely-quoted/qualified
Lucene query, call `search_logs`, and present condensed `Time | channel | message`
lines — never raw JSON.

## Uninstall (after local testing)

```
/plugin uninstall opensearch@coreteam-claude-base
/plugin marketplace remove coreteam-claude-base
```

## Known caveats

- **bzdev**: log shipping into this cluster appears to have stopped since
  2026-07-05 — anything after that date shows zero hits. This is an upstream
  log-shipping gap, not a query problem.
- **ci / staging / prod**: not configured out of the box; wire up the env vars above
  to enable them.
