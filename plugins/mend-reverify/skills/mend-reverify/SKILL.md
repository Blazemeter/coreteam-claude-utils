---
name: mend-reverify
description: Re-run the denv API-test gate for a Mend remediation ticket and update the ticket if it now passes. Use when the mend-blz denv API-test gate failed on environmental flakiness (pod/agent recycled, Taurus engine-start timeout, intermittent POST /proxy 400 / vault 500 / metrics progress-100 timeout) and the dependency fix itself is good — deploys the ticket's fix branch to the svc-automation denv if it isn't already deployed, re-runs API-TEST-SELECTED-DEV-ENV for the component's api_tests there, and on green comments on the MOB ticket and flips its denv-API-test verification line to passed. Load when the user runs /orch run mend-reverify.
---

# When to use

Load this skill when the user runs `/orch run mend-reverify` — a **standalone re-check** of the denv
API-test gate for a Mend ticket whose gate failed for **environmental** reasons, not because of the
fix. The mend-blz denv API-test gate (step 7/8) flakes on denv infrastructure: a recycled
pod/agent, a Taurus cloud engine that takes just over the start timeout, an intermittent
`POST /proxy 400`, a vault `500`, missing live monitoring data, etc. When the ticket's notes already
record such an environmental failure and the fix is otherwise green everywhere else, this skill
re-runs just the API tests and, if they pass, records that on the ticket.

It does **not** re-run the whole mend loop or re-build the image — but it **will (re)deploy the fix
branch** to the svc-automation denv if it isn't already deployed (denvs stop nightly), then run the
denv API-test job.

# Invocation

```
/orch run mend-reverify --target <component> --scope <MOB-ticket>[,<PR>]
```

- **`--target`** — component name; match against the component registry (`config/services.json` in
  blz-claude-orchestrator) to get `repo` and `api_tests`. e.g. `happysocks`, `proxy-recorder`,
  `secrets-manager`, `dagger`, `search`.
- **`--scope`** — the `<MOB-ticket>` to update (e.g. `MOB-54634`), optionally followed by `,<PR>` (a
  GitHub PR URL or number) to reference in the ticket comment. Parse by splitting on the first comma.

The denv is always **`svc-automation`** — the service account that runs the mend flow from Slack, so
`USERNAME=svc-automation` and the tests run against the svc-automation denv (the same env the
original run used). There is no per-user denv param.

# Steps

Run **headless** — a single, non-interactive turn. Poll the Jenkins build **synchronously** in a
loop; **never exit the turn while waiting** (there is no next turn). Poll every 60s, up to 60 min.

## 1. Parse arguments

- `component` ← `--target`
- `ticket` ← first part of `--scope`; `pr` ← second part if present (optional).

Look up `component` in the registry (`config/services.json`):
- `repo` — e.g. `Blazemeter/happysocks`
- `api_tests` — the curated list of `api_testing/tests/…` paths for this component's gate.

Resolve the **fix branch** for this run (needed to deploy it in step 2): the PR's head ref if `<PR>`
was given, otherwise the `mend-fix-<timestamp>` branch recorded in the ticket description (mend
tickets state the branch and link the PR). If it can't be resolved, stop and ask for the PR/branch.

If the component is not found → list the registry keys and stop. **If `api_tests` is empty** (e.g.
`scaleron`, deploy-only) → there is nothing to re-run; report that and stop without touching the
ticket.

## 2. Ensure the fix branch is deployed on the svc-automation denv — via **jenkins**

Re-running the API tests only means something if the ticket's fix is actually deployed on the denv.
Denvs **stop nightly and get recycled**, so do not assume the original deploy is still live.

**Check first:** the svc-automation denv must be **started**, and the `Deploy environment / master`
job should have a **recent SUCCESS** build with `GIRO_BRANCH=<fix_branch>` **and**
`USERNAME=svc-automation`. If the denv is up and that deploy is current → the fix is already
deployed, skip to step 3.

**Otherwise** (not deployed, denv recycled, or you can't confirm it) → **deploy it first**:

```
POST https://blazect-jenkins.blazemeter.com/job/Deploy%20environment/job/master/buildWithParameters?GIRO_BRANCH=<fix_branch>&USERNAME=svc-automation
```

- `GIRO_BRANCH=<fix_branch>` — the plain branch name (the deploy job maps it to the freshly-built
  image), **not** an image tag.
- `USERNAME=svc-automation` — the denv to deploy into. It must equal the **authenticating account**
  (`JENKINS_USER`), which is `svc-automation` — so this deploy and the step-3 API test (which derives
  its env from `BUILD_USER`) target the **same** denv.

Gate on the deploy job going **green** (per the **jenkins** skill — queue item → build number →
result). The deploy picks up the `<fix_branch>` image for the component and, for **crane**
components, the matching `a.blazemeter.com` branch of the same name (updated
`HarborVersionsSettings.php`) — so one deploy covers both. Only continue once the deploy is green; if
it fails, **stop and report** (don't run the tests against a half-deployed denv, and don't touch the
ticket).

## 3. Trigger the denv API-test job — via **jenkins**

Now re-run the API tests (no rebuild) against the svc-automation denv:

```
POST https://blazect-jenkins.blazemeter.com/job/API-TEST-SELECTED-DEV-ENV/buildWithParameters?TARGET_ENV=DEnv&TESTS_TO_RUN=<first-test-relative-path>&TESTS_TO_RUN_MANUAL=<space-separated api_testing/tests/… paths>&API_TESTING_BRANCH=develop&SDK_BRANCH=master
```

- `TESTS_TO_RUN_MANUAL` = the component's `api_tests`, space-separated, verbatim (the curated set —
  don't guess paths).
- `TESTS_TO_RUN` = the first `api_tests` entry with the `api_testing/tests/` prefix removed.
- **No `USERNAME` param here** — unlike the deploy job, the API-test job has no `USERNAME` parameter;
  it derives the denv from **`BUILD_USER`** (the authenticating Jenkins account). Because the
  orchestrator runs as **svc-automation**, `BUILD_USER = JENKINS_USER = svc-automation`, so it runs
  against the svc-automation denv automatically — the same account/env as the step-2 deploy.

Follow the **jenkins** skill to turn the queue item into the specific triggered build number and poll
**that** build (not `lastBuild`, which races). This is a **single run** — do not auto-retry.

## 4a. If the build is GREEN → update the ticket — via **jira**

The fix is verified; record it on `<ticket>`:

1. **Comment** on the ticket:
   > denv API-test re-run **passed** — `API-TEST-SELECTED-DEV-ENV` [build #<n>](<build-url>)
   > (`TESTS_TO_RUN_MANUAL=<paths>`, svc-automation denv). The earlier gate failure was
   > environmental; the fix is verified in denv.
   > _(include `PR: <pr>` when `<PR>` was passed.)_

2. **Rewrite the denv-API-test verification line** in the ticket **description**: find the existing
   line describing the denv API-test gate (it mentions `denv API test` / `API-TEST-SELECTED-DEV-ENV`
   / the test file, usually prefixed ⚠️ or "failed … pre-existing environmental") and replace it with
   a passed line, e.g.:
   > ✅ denv API test (`<test file(s)>`): passed on re-run — [build #<n>](<build-url>).
   Replace **only** that line; leave the rest of the description unchanged.

## 4b. If the build is RED → report, do not touch the ticket

Report the result with the failing test(s) and the failure signature, and note whether it **matches**
the environmental reason already recorded on the ticket (same signature = still environmental; a new
signature = investigate, may be real). Do **not** comment "passed", do **not** edit the ticket. The
operator decides whether to re-run again or dig in.

## 5. Output summary

```
mend-reverify <component> (<ticket>):
  denv deploy:     <already current | deployed #<n> | FAILED>
  denv API test:   <PASSED|FAILED> — API-TEST-SELECTED-DEV-ENV #<n>
  tests:           <TESTS_TO_RUN_MANUAL>
  ticket updated:  <yes: comment + verification line | no (still red / deploy failed)>
```

# Notes

- **Never exit the turn while polling** for the deploy or the API-test build — poll synchronously,
  every 60s up to 60 minutes each. No background polling or scheduled wakeups.
- **Deploy-if-needed, then a single API-test run.** It will (re)deploy the fix branch to the
  svc-automation denv when it isn't already deployed, but it **never changes code or rebuilds** — if a
  red run needs a code change, that's a new mend-blz run, not this. The API test itself runs once (no
  fix-forward).
- **Only marks green as passed.** A failed deploy or a red API-test run never updates the ticket — so
  a flaky re-run can't produce a false "verified."
- Denv is always `svc-automation`; the fix branch comes from the PR/ticket; the `repo` and `api_tests`
  come from the component registry — this skill supplies no test paths of its own.
