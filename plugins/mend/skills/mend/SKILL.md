---
name: mend
description: Read and interpret Mend (formerly WhiteSource) SCA data — authenticate to the REST API v1.3, look up a project token, fetch SECURITY_VULNERABILITY alerts, and classify CVE severity. Load whenever the work involves Mend/WhiteSource, CVEs from Mend, or fetching/triaging vulnerability alerts. Generic SCA-read knowledge; the fix workflow lives in dep-remediation + the mend-blz recipe.
---

# When to use

Load this skill for any Mend/WhiteSource read: fetching a project's alerts, resolving a project
token, or interpreting CVE severity. It does **not** apply fixes — pair it with **dep-remediation**
(how to fix), and the **mend-blz** recipe drives the end-to-end loop.

# Credentials

Three values, from environment or `~/.claude/team-config.md`:

- `MEND_URL` — `https://saas-eu.whitesourcesoftware.com`
- `MEND_USER_KEY` — per-user key (issued to `TCohen@perforce.com`; the value is a secret, the email only identifies the owner). `getOrganizationProjectVitals` needs an **org-admin** key; `getProjectAlertsByType` works for any member once the project token is known.
- `MEND_ORG_TOKEN` — the Blazemeter org token, exported under **both** `Blazemeter` and `Blazemeter_GHC` (**same value**, different code paths read different names). No org selection/fallback logic.

**Never echo these** to logs, Slack, PRs, or Jira. Validate presence at the start and abort with an actionable error if any is missing.

# Quick reference (REST v1.3)

All calls are POSTs to `${MEND_URL}/api/v1.3` with a JSON body carrying `userKey` + `orgToken`. Full request/response shapes and examples: [references/api.md](references/api.md).

| Task | requestType | Key params |
|------|-------------|-----------|
| Find a project's token | `getOrganizationProjectVitals` | match `projectVitals[].name` against the target's Mend project name |
| Fetch alerts | `getProjectAlertsByType` | `userKey` + `projectToken` + `alertType: SECURITY_VULNERABILITY` |

## Project-name matching (in order)

Mend project names drift from repo names (e.g. `a.blazemeter.com` → `BZA-Backend`).
1. Exact (case-insensitive) match of the configured Mend project name against `projectVitals[].name`.
2. Substring match either direction.
3. No match → abort and list the first 10 project names so the user can spot the mismatch.

## Severity

- Mend returns severity **lowercase** (`"low"`/`"medium"`/`"high"`/`"critical"`) — **always compare case-insensitively**; a `== "HIGH"` check silently misses real alerts.
- Two fields: legacy `severity` and `cvss3_severity`/`cvss3_score` — **prefer cvss3 when present**.
- Fix hint is `fixResolutionText` (human string) + `topFix`/`allFixes` (structured). There is no `fixResolution` field.
- Library identity = `library.name` + `library.version` (`artifactId` may be a filename; `groupId` only meaningful for Maven).
- **Default scope = HIGH + CRITICAL** when the caller doesn't specify; MEDIUM/LOW are deferred unless requested.

# Triage guard — a "clean" result only counts from a fresh scan of the integration branch

`getProjectAlertsByType` returns the state of the project's **last scan**, whatever branch produced
it. A build on a `mend-fix-*` branch runs `PERFORM_WHITESOURCE_SCAN=true` and **overwrites the shared
project** with the branch's (already-fixed) tree — so right after a remediation the project can report
**zero alerts while the integration branch is still vulnerable** (the fix PR hasn't merged). Treating
that as "clean" silently skips a real vulnerability. (Observed on `crane`, `proxy-recorder`, `secrets`,
whose last scan was a `mend-fix-*` branch, not `master`.)

Before concluding a project is clean, read two fields from the matched `getOrganizationProjectVitals`
entry: **`lastScanComment`** (the branch of the last scan, e.g. `master`, `develop`,
`mend-fix-20261118-152738`) and **`lastUpdatedDate`** (freshness).

When `alerts[]` is empty, apply this guard:
1. `lastScanComment` is a `mend-fix-*` branch (or any non-integration branch) → **do NOT report clean.**
   The last scan was a fix branch, so the integration branch's state is **unverified**. Surface it —
   *"0 alerts, but last scan was `<lastScanComment>`, not the integration branch — state unverified"* —
   and do not skip the repo.
2. `lastScanComment` is empty/`null`, or `lastUpdatedDate` is older than 7 days → **not a current
   view**; surface it as stale, don't call it clean.
3. `lastScanComment` is the integration branch (`master`/`develop`) and fresh → trust the result.

The integration branch's true state only returns once the fix PR merges and a build **on the
integration branch** re-scans (then `lastScanComment` flips back to `master`/`develop`). A non-empty
`alerts[]` is always actionable regardless of which branch last scanned.

# Gotchas

- **Empty `alerts[]` does NOT mean clean** — may mean "not scanned recently" or "last scan was a fix branch." Check `lastUpdatedDate` and `lastScanComment` and apply the **Triage guard** above before reporting clean.
- **No on-demand rescan in v1.3.** A re-query right after a fix shows the *last* scan, not local edits. Absent alerts → likely cleared at the resolved-tree layer; still-present → label `pending Mend rescan`, not `failed fix`. Final confirmation is the Jenkins **mend** stage.
- **API version `v1.3`.** A newer GraphQL API exists, but the creds are wired for v1.3 REST — don't migrate without re-validating creds.
- **Dual-name org token.** `Blazemeter` and `Blazemeter_GHC` are the same value — never branch logic on which.

## Test mode

With a `test` flag, skip the API entirely and read pre-seeded JSON from `/tmp/mend-<component>-vulns.json` (same shape as `getProjectAlertsByType`). Missing file → abort with a clear error pointing at the expected path.

# References

- [api.md](references/api.md) — endpoint specs, request/response shapes, field notes, examples.
