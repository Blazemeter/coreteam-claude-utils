---
name: jenkins
description: Trigger and gate on a Blazemeter blazect Jenkins multibranch build — POST buildWithParameters with PUSH_TO_GCR=true and PERFORM_WHITESOURCE_SCAN=true, track the queue item to the specific triggered build number and poll that (not lastBuild, which races with the branch's own auto-triggered build) until green (unit-test/prisms/mend stages), fix-forward on red, and never gate on the slow API_TESTS-CI suite. Also deploys a green branch's image to a denv environment via the shared 'Deploy environment' job (GIRO_BRANCH + USERNAME) and gates on that deploy job going green. Load when a flow needs to run, deploy, or wait on a Blazemeter CI build.
---

# Blazemeter CI gate

Server: `https://blazect-jenkins.blazemeter.com`. Auth with `JENKINS_USER` + `JENKINS_API_TOKEN`.
Each component has a **multibranch** folder (e.g. `BACKEND-CI`, `DAGGER-CI`, `SEARCH-CI`); a branch
build lives at `/job/<folder>/job/<branch>/`.

## Trigger with PUSH_TO_GCR + PERFORM_WHITESOURCE_SCAN

After pushing the branch, kick a parameterized build so the remediated image publishes to GCR
(`gcr.io/verdant-bulwark-278`; image libs `bm-backend`, `bm-dagger`, …) and the build re-scans the
branch with Mend/WhiteSource (so fixed alerts show as resolved on the next **mend** triage instead
of lingering as stale/open):

```
POST https://blazect-jenkins.blazemeter.com/job/<folder>/job/<branch>/buildWithParameters?PUSH_TO_GCR=true&PERFORM_WHITESOURCE_SCAN=true
```

- **`PUSH_TO_GCR`** (boolean, default `False`) is the **"push to GCR" checkbox** — always check it, on **every** component's job (BACKEND-CI, DAGGER-CI, SEARCH-CI, and any repo added later).
- **`PERFORM_WHITESOURCE_SCAN`** (boolean, default `False`) triggers the Mend/WhiteSource scan stage — always check it too, same components, so the branch's Mend project reflects the fix.
- Leave the other boolean params (`RUN_UNIT_TESTS`, other `PERFORM_*_SCAN` flags, `FAIL_JOB_ON_SCAN_FAILURES`, `NO_CACHE_FLAG`, `UPDATE_VERSION`) at their defaults.
- **Expect a second build to already be running or queued.** Pushing the branch itself
  auto-triggers a build via Jenkins' own branch-indexing/webhook (default params, no
  `PUSH_TO_GCR`/`PERFORM_WHITESOURCE_SCAN`) — that's normal multibranch-pipeline behavior, not a
  bug in this flow. This `buildWithParameters` call is a **second, explicit** build; gate on that
  one (see below), not the auto-triggered one.

## Gate on green

The `buildWithParameters` POST's response `Location` header points at a **queue item**, not a
build directly — poll that queue item until it resolves to an `executable` with a build number,
then poll `…/job/<folder>/job/<branch>/<that number>/` until it finishes. **Don't poll `lastBuild`
blindly** — with the auto-triggered build from above also in flight, `lastBuild` can point at the
wrong one depending on which finishes first. A build runs **unit-test · prisms · mend** stages.

- **Never gate on `API_TESTS-CI`** — that shared suite is >1h, flaky/not-green, and run manually at developer discretion.
- **If RED:** **fix forward** on the same branch and re-push (re-triggers the build); reverting/deferring a breaking dependency counts as fixing forward. **Cap at 3 fix attempts per run** (local-test + Jenkins failures combined). Still red after the 3rd → **stop** (no PR, no Jira) and record the reason. A run that goes green after deferring some breaking deps still proceeds with the fixes that passed.
- **If GREEN:** continue downstream (denv deploy, then PR, ticket).

## Deploy to denv and gate

Once the branch build is green, deploy that build's image to a **denv** environment and gate on the
deploy job. A green deploy proves the image **starts**; the fix-related API tests in the next
section then prove it didn't **break behavior**. The green build above already pushed the image as
`gcr.io/verdant-bulwark-278/blazemeter/<component>:<branch>-<buildNumber>` (plus a moving
`latest-<branch>` tag); the deploy job resolves a branch to that image, so you pass the **branch**,
not the tag.

**Deploy job (one shared job, not per-component):** `job/Deploy environment/job/master`

```
POST https://blazect-jenkins.blazemeter.com/job/Deploy%20environment/job/master/buildWithParameters?GIRO_BRANCH=<fix-branch>&USERNAME=<denv-env-name>
```

- **`GIRO_BRANCH`** — the **fix branch you pushed** (e.g. `mend-fix-20260820-105216`), a plain
  branch name — **not** the image tag. The job maps the branch to its freshly-built image. (Real
  values seen: `master`, `develop`, `MOB-52582-…`.)
- **`USERNAME`** — the denv environment to deploy into (also a GitHub username). For an
  orchestrated run pass **`svc-automation`** — the automation's own Jenkins service-account
  identity, which is *also* the env `API-TEST-SELECTED-DEV-ENV` targets when the automation
  triggers it, so the deploy and the API test hit the **same** env. That env must be provisioned
  with the api-testing users/keys (see the deploy-verify prereqs). For a manual/local run by a
  person, pass that person's own denv env name instead.
- Both are uno-choice `DynamicReferenceParameter`s but accept a plain string via
  `buildWithParameters` (past builds submit plain values).

**Gate** exactly like the build gate: the POST returns a **queue item** in the `Location` header;
poll it to the executable build number, then poll
`…/job/Deploy environment/job/master/<number>/` until it finishes.
- **GREEN (`SUCCESS`)** → the image runs in denv → continue downstream (PR, ticket).
- **RED** → fix-forward and re-deploy, **cap 3 attempts**; still red → **stop** (no PR, no Jira),
  record the reason. Hard gate — same posture as the build gate above.

## Run the fix-related API tests against denv (functional gate)

A green deploy only proves the image *starts*. To prove the dependency fix didn't **break
behavior**, run the API tests covering the area the fixed library touches — against the denv env
just deployed. This is a **targeted** selected-tests run and is **distinct from** the slow full
`API_TESTS-CI` suite the build gate must never wait on.

**Job:** `job/API-TEST-SELECTED-DEV-ENV`

```
POST https://blazect-jenkins.blazemeter.com/job/API-TEST-SELECTED-DEV-ENV/buildWithParameters?TARGET_ENV=DEnv&TESTS_TO_RUN=<first-test-relative-path>&TESTS_TO_RUN_MANUAL=<space-separated test files>&API_TESTING_BRANCH=develop&SDK_BRANCH=master
```

- **`TARGET_ENV=DEnv`** — run against the denv environment (the one deployed above).
- **`TESTS_TO_RUN_MANUAL`** — space-separated `api_testing/tests/…` paths. When driven by a flow,
  use the **caller's per-repo test list** verbatim (e.g. mend passes the component's `api_tests`
  from the catalog) rather than guessing paths. Standalone, pick the file(s) matching the fixed
  area, e.g. a file-parsing fix → `api_testing/tests/test_file_parsing.py`. An empty list = skip
  this gate (deploy-only).
- **`TESTS_TO_RUN`** — the job's dropdown that otherwise defaults to the unrelated `test_account.py`.
  Set it to **the first of the fix-related tests**, as a path **relative to `api_testing/tests/`**
  (i.e. the same first entry as `TESTS_TO_RUN_MANUAL`, with the `api_testing/tests/` prefix removed) —
  e.g. `test_search_service/test_security.py` — so it reflects the selected tests, not the default.
- Leave `API_TESTING_BRANCH=develop`, `SDK_BRANCH=master`, `RUN_EXPENSIVE=1`, `SLEEP_TIME=2` at
  defaults unless a run needs otherwise.

**Gate** like the others (queue item → build number → poll to finish):
- **GREEN (`SUCCESS`)** → the fix behaves correctly → continue downstream (PR, ticket).
- **RED** → the dependency fix **changed/broke behavior**: treat it as a *fix* problem and
  **fix-forward** — pick a different version, or adjust code for an API/behavior shift, then re-push
  → re-build (build gate) → re-deploy → re-test. **Cap 3 attempts** (shared with the build-gate
  budget); still red → **stop** (no PR, no Jira) and record which test failed and why.
