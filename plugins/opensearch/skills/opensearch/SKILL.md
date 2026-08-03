---
name: opensearch
description: Search BlazeMeter logs in a given environment (denv, bzdev, ci, staging, or prod) for a given subject, and return a condensed, relevant result list. Trigger phrases - "search opensearch for X in denv", "check logs for master 386 on bzdev", "opensearch <env> <subject>".
allowed-tools: mcp__opensearch-reader__ping, mcp__opensearch-reader__list_indices, mcp__opensearch-reader__search_logs, Bash(python3 *)
---

# OpenSearch Log Search

## Purpose

Take two inputs — an **environment** and a **search subject** — and directly return
condensed, relevant log lines. No back-and-forth query building with the user; this
skill constructs the Lucene query itself and prunes noise from the output.

## Args

`ARGUMENTS` is `<env> <search subject...>` — the first whitespace-separated token is
the environment, everything after it is the search subject (free text, a master ID,
or a raw Lucene query).

Valid environments: `denv`, `bzdev`, `ci`, `staging`, `prod` (case-insensitive).

If the first token isn't one of these, ask the user which environment before
proceeding — do not guess.

## Environment status (as of this skill's creation)

- **denv** — working. Shared index across ALL developers' personal denvs (not scoped
  to one user) — hostnames look like `<denv-namespace>-<service>-deployment-...`.
- **bzdev** — connects, but has a known caveat: log shipping into this cluster appears
  to have stopped since 2026-07-05 (verified: earliest and latest doc in the index
  pattern are the same date). Anything after that date will show zero hits — this is
  an upstream log-shipping gap, not a query problem. Always surface this caveat to the
  user when `bzdev` returns few/no hits, so it doesn't read as "nothing happened."
- **ci / staging / prod** — **not configured out of the box**. This plugin bundles the
  `opensearch-reader` MCP server, but the host/credentials for these three environments
  must be supplied via env vars before it can reach them (see `.mcp.json` in this
  plugin's root: `OPENSEARCH_HOST_<ENV>` / `OPENSEARCH_USER_<ENV>` /
  `OPENSEARCH_PASSWORD_<ENV>`). Calling `search_logs`/`ping` for an unconfigured
  environment returns a clear "not configured" error naming the missing env vars. If
  the user picks one of these, run the tool anyway, then relay that error message
  directly — don't apologize at length or retry with a different query, there is
  nothing a different query can fix.

## Workflow

1. **Ping first.** Call `ping` for the resolved environment. If it errors (including
   "not configured"), stop and report that — do not attempt `search_logs`.

2. **Build the Lucene query from the search subject:**
   - If the subject is purely numeric (e.g. a master ID), it's ambiguous which field
     holds it in a given log line (schema varies — sometimes `masterId`, sometimes only
     inside `raw_message` JSON text, sometimes not indexed as its own field at all).
     Try in this order, stop at the first that returns hits:
     a. `masterId:"<subject>"`
     b. `raw_message:"<subject>"`
     c. bare `<subject>` (no field qualifier)
   - If the subject already looks like a real Lucene query (contains `:`, `"`, or
     boolean operators), pass it through mostly as-is.
   - Otherwise (freeform natural language, e.g. "fallback errors for master 386"):
     strip generic filler words (find, show, get, me, please, search, logs, for, the,
     a, an, in, on) and AND-join the remaining significant keywords. This is the
     "limit unnecessary words" step — don't send a whole sentence as a literal phrase
     match, it won't match real log lines.
   - **Mandatory safety rule #1:** quote any token containing a hyphen that isn't
     already inside quotes (e.g. a denv namespace like `himanshu-perforce`, or a
     compound term). Lucene's `query_string` parser treats an unquoted `-` as a NOT
     operator — e.g. `host.name:himanshu-perforce*` silently becomes
     `himanshu AND NOT perforce*` and matches nothing, with no error. Always write
     `host.name:"himanshu-perforce"` instead.
   - **Mandatory safety rule #2:** never AND-join bare/unqualified keyword terms (no
     `field:` prefix) — a bare term expands across every dynamically-mapped field in
     the index, and 2+ of them ANDed together can exceed OpenSearch's maxClauseCount
     (1024), throwing a 500 `too_many_nested_clauses` error. Always qualify freeform
     keywords to a field, usually `message:<word>` — e.g. write
     `message:master AND message:status`, not `master AND status`.

3. **Call `search_logs`** with the constructed query for the resolved environment.
   Leave `time_from`/`time_to` unset by default (search all available data) unless the
   user's subject specifies a time window — the `size` cap (default 20) already limits
   result volume. Use the `mcp__opensearch-reader__search_logs` tool — this plugin
   bundles and auto-starts the `opensearch-reader` MCP server, so it should already be
   loaded. If it isn't (MCP servers only register on Claude Code restart / plugin
   reload), fall back to invoking the module directly, relying on the same
   `OPENSEARCH_*` env vars the MCP server itself reads — never hardcode credentials in
   this skill file or in chat output:
   ```bash
   python3 -c "
   import sys
   sys.path.insert(0, '\${CLAUDE_PLUGIN_ROOT}/mcp')
   import server
   print(server.search_logs('<QUERY>', environment='<ENV>', size=20))
   "
   ```

4. **If zero hits**, retry with the next fallback query variant (step 2) before
   reporting empty. If all variants are empty, say so plainly, surface the `bzdev`
   caveat if relevant, and suggest broadening the query rather than guessing further.

5. **Present results condensed** — never dump the raw JSON response into chat. For
   each hit, show only: `Time | channel | message`, plus any `context` fields that are
   clearly relevant to the search subject. Strip boilerplate noise from every hit
   before showing it: `_transactionId`, `_ip`, `_uri`, `_clientId`, `_clientVersion`,
   `_userId`, `_loggedInUserId`, `_header_X_Bzm_*`, `formatted`, `@version`, `agent.*`,
   `ecs.version`, `log.offset`, `tags`. If `total_matches` exceeds what was returned,
   say how many more exist and offer to narrow further (e.g. by time range or an
   additional keyword) rather than dumping all of them.

## Do not

- Do not embed the OpenSearch password in this file, in code, or in chat — read it
  from the `OPENSEARCH_*` environment variables at runtime only.
- Do not attempt ci/staging/prod queries speculatively — always `ping` first and
  relay the "not configured" error verbatim if that's what comes back.
- Do not present raw JSON hits to the user — always condense per step 5.
