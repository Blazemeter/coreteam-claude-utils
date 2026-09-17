---
name: ci-culprit-check
description: Use when triaging backend API_TESTS-CI failure noise in the BlazeMeter Slack channels (#bm-api-monitoring, #bm-notifications-jenkins-api-result-for-ci) to find which failures are real/persistent vs. flaky, identify the likely culprit commit, and check whether it's already being handled before drafting any notification. Backend-only — GUI/grid test failures (#blazemeter-ci) are out of scope. Runs end-to-end without stopping for intermediate confirmation, ends with one final verdict per failure (cause + owner + draft if any), and asks exactly one question at the very end: whether to send the draft(s). Never sends a Slack message on its own.
allowed-tools: Bash(gh *) WebFetch mcp__claude_ai_Slack__slack_search_channels mcp__claude_ai_Slack__slack_read_channel mcp__claude_ai_Slack__slack_read_thread mcp__claude_ai_Slack__slack_search_users mcp__claude_ai_Slack__slack_send_message_draft
---

See [`STANDARDS.md`](../../../../STANDARDS.md) for the JIRA-ID, attribution, and lifecycle rules that apply to any Claude-driven work this skill's findings lead to (e.g. filing a follow-up ticket).

## Why this skill exists

Distilled from a CI-failure investigation (`test_credits_overage.py`, MOB-50523) that got the culprit commit right but almost sent a notification to someone who had *already* opened and gotten approval on the fix — because the first pass only compared yesterday vs. today and never checked for an open PR. Three corrections came out of that:

1. **Never point at a person without checking for an in-flight fix first.** An open PR (even unmerged, even in review) that addresses the failure means don't raise it.
2. **Don't bound the investigation to "yesterday vs. today."** Use the current release branch's cut date as the start of the window — a test can have been broken for most of a sprint, and a 2-day window will miss both the real start date and the correlated commit.
3. **Run straight through to a verdict — don't stop mid-investigation to ask.** Make the best-effort call yourself (see Phase 5), note the confidence level in the final verdict, and let the one end-of-run question — send the draft(s) or not — be the only interruption. Mid-flow questions are for genuinely destructive/irreversible actions, not for routine judgment calls this skill is meant to make.

## Scope — backend (API_TESTS-CI) only, fixed, don't expand

- **This skill is backend-only.** It exists to triage the `API_TESTS-CI` Jenkins job specifically. GUI/grid/BBT test failures are a different domain (different repo — `BZA-Automation` — different owners, different failure shape) and are explicitly **out of scope**. Don't read `#blazemeter-ci` at all.
- **Channels:** `#bm-api-monitoring` (`C0BC2QRGBPA`) and `#bm-notifications-jenkins-api-result-for-ci` (`C074R1E7ZJR`) only. Resolve via `slack_search_channels` if IDs ever change.
- **Within those channels, filter to `API_TESTS-CI` entries only.** `#bm-api-monitoring` also posts `STAGING_BZM Monitoring | API_TESTS-STAGING_BZM` digests on the same channel — skip those, they're a different environment/job. `#bm-notifications-jenkins-api-result-for-ci` is already scoped to `API_TESTS-CI` by design.
- **Repos:** not fixed — determined per-investigation (see Phase 3). At minimum check the repo the root-cause commit landed in (usually `Blazemeter/a.blazemeter.com`) and the repo owning the failing test (`Blazemeter/api-testing`, which is where `API_TESTS-CI` test files live).
- Internal Jenkins (`blazect-jenkins.blazemeter.com`) is VPN/auth-gated — `WebFetch` will 403 on `/testReport`, `/consoleText`, `/allure`. Don't retry it. Rely on the Slack digest text (it already contains pass/fail counts, failing test names, and sometimes commit lists) plus `gh` CLI for everything else.

## The flow

### Phase 1 — Find the current sprint window
Release branches follow `release-yyyy-mm-dd` in the app repo (e.g. `a.blazemeter.com`), cut roughly every 2 weeks. Don't trust the branch's HEAD commit date — hotfix cherry-picks land on it after the cut and move it forward. Get the true cut date instead:
```
gh api repos/<org>/<repo>/branches --paginate --jq '.[].name' | grep -E '^release-[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort | tail -3
gh api repos/<org>/<repo>/compare/develop...<latest-release-branch> --jq '.merge_base_commit.commit.author.date'
```
That merge-base date is the window start. Sanity-check the ~2-week cadence against the previous release branch's cut date.

### Phase 2 — Pull the full window, not just 2 days
Read both channels from that cut date through now (`slack_read_channel` with `oldest` set to the cut-date epoch), filtered to `API_TESTS-CI` entries only per the scope note above. Build a per-day table of which test files failed. Classify each:
- **Resolved/flaky** — failed on some days, passed on the most recent run. No action.
- **Persistent** — still failing as of the latest run. Continue to Phase 3.

For a persistent failure, find the exact day it flipped from passing to failing — that's more informative than "it's been red for N days," since it pins down which commit(s) landed between the last green run and the first red one.

### Phase 3 — Identify the candidate commit(s)
Cross-reference the flip date against commit history in the implicated repo:
```
gh api "repos/<org>/<repo>/commits?sha=<branch>&per_page=30" --jq '.[] | "\(.sha[0:9]) \(.commit.author.date) \(.author.login // .commit.author.name): \(.commit.message | split("\n")[0])"'
```
Prefer a commit whose description semantically matches the failing test's subject (e.g. a "credits/VUH enforcement" commit against a `test_credits_overage.py` failure) over just picking whatever's chronologically closest. Confirm by reading the actual test file (`gh api repos/<org>/<repo>/contents/<path> --jq '.content' | base64 -d`) and the implicated source file/PR diff — don't stop at "the commit message sounds related."

If the failure already existed at the very first run inside the sprint window, say so plainly rather than forcing a within-window answer — the root cause predates this sprint and needs a wider bisection outside this skill's default scope.

### Phase 4 — Check for an open PR before drafting anything
This is the step that's easy to skip and changes the outcome. Search **open** PRs (not just merged commits) in every repo touched by Phase 3, plus the repo owning the failing test:
```
gh pr list -R <org>/<repo> --state open --search "<jira-id> <keywords>" --json number,title,author,url,createdAt
gh pr list -R <org>/<repo> --state open --limit 50 --json number,title,author,url,createdAt   # manual scan if search misses it
```
If a matching open PR exists, inspect it (`gh pr view <n> --json body,files,reviews,statusCheckRollup,state,mergeable`) to confirm it actually targets this gap. If it does:
- **Stop here. Do not draft a notification.** Report the PR (author, state, review/approval status, whether CI is green) as "already being handled" instead.
- If it's open but stale/unreviewed for a while, it's fine to note that as a mild nudge ("still needs review/merge") rather than a blame notification.

Only proceed to Phase 5 if no open PR covers it.

### Phase 5 — Resolve identity best-effort, then draft (never send, don't pause to ask)
GitHub handles don't map cleanly to Slack accounts. Try `slack_search_users` on the commit author's name/handle first. If that doesn't give an exact match, fall back to the org's `firstname + lastname-initial + number` convention (e.g. `avishaiw12` → Avishai Weingarten) as a best-effort guess. Don't stop to confirm this with the user — proceed with the best-effort match and flag it as "best guess, please verify" in the final verdict instead of pausing mid-run.

Create the draft with `slack_send_message_draft` (DM or channel, whichever fits — never send it). Do this for every persistent failure that has no open PR covering it, without asking permission per-failure.

## Output shape — one final verdict, one final question

Don't narrate phase-by-phase. Run all phases silently and end with a compact verdict block per persistent failure, e.g.:

> **Error 1 — `test_credits_overage.py`** (failing since 2026-09-09)
> Caused by: PR #8338 `MOB-50523` — avim9 / Avihay Mor (merged 2026-09-08)
> Status: already fixed — PR #2010 (api-testing) merged 2026-09-17 by avim9. No draft needed.
>
> **Error 2 — `test_scenario_definition_section.py`** (failing since <date>)
> Caused by: <commit/PR + owner, or "not yet identified — needs Jenkins/log access">
> Status: no open PR found. Draft prepared for <person> (best-effort Slack match, please verify):
> > <full drafted message text>

List every persistent failure this way — including ones with no clear owner yet (say so plainly rather than guessing a commit). Skip flaky/resolved ones from the verdict entirely; they don't need a verdict, just a one-line mention that they recovered.

After all verdicts, ask **exactly one** question: whether to send any of the prepared drafts (or leave them for manual review) — nothing else mid-flow.
