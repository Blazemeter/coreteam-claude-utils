---
name: mend-blz
description: End-to-end Mend vulnerability remediation for Blazemeter components (a.blazemeter, dagger, search, crane components). Composes the mend, dep-remediation, jenkins, github, and jira skills into one loop — Mend alerts → dependency fix on a fresh date-stamped branch → Jenkins green → [crane only] a.blazemeter.com branch with updated HarborVersionsSettings.php → denv deploy + fix-related API tests (fix verified in denv) → Confluence report → Jira (MOB, created first) → squash commits with child ticket id → PR (opened with the ticket id already in the title) → Jira description updated with the PR link. Load when the user wants to fix/remediate Mend/WhiteSource vulnerabilities for a Blazemeter service.
---

# When to use

Load this recipe to run the **full Mend remediation loop** for a Blazemeter component. It is the
composer — the reusable knowledge lives in five skills it drives:

| Step | Skill |
|------|-------|
| Fetch/triage Mend alerts, resolve project token, severity | **mend** |
| Apply the fix (golden rule, advisory cross-check, defer majors, per-stack recipe, local build+test) | **dep-remediation** |
| Trigger the branch build with `PUSH_TO_GCR=true` + `PERFORM_WHITESOURCE_SCAN=true` and gate on green | **jenkins** |
| [Crane repos only] Via GitHub API (no clone): create matching branch in `a.blazemeter.com`, patch `HarborVersionsSettings.php` version to `latest-<fix-branch>`, commit | this skill (step 6b) |
| Deploy the branch's image to denv, then run the fix-related API tests against it and gate on them | **jenkins** |
| Upsert currently-unfixable libraries to the Confluence tracking page | this skill (see [references/mend-confluence-report.md](references/mend-confluence-report.md)) |
| Create the MOB ticket (In Progress, assignee = owner) **before the PR exists** — description covers dependencies fixed + Jenkins + Confluence link when deferred alerts exist | **jira** |
| Squash all commits to one with child ticket id, force-push, open PR **with the ticket id already in the title** (commits used `parent_key` prefix during CI to satisfy the Jira-id-in-commit check) | **github** |
| Edit the MOB ticket's description to add the PR link, now that the PR exists | **jira** |

These auto-load alongside this recipe; defer to them for the "how," and follow the order/gates below.

# Invocation (arguments)

Argument-driven — read what the user asks; don't assume:

- **Component** (required): match the name against the component registry (see [Component registry](#component-registry)) by key or `repo`. "a.blazemeter.com"/"a.blazemeter" → `a.blazemeter`; "dagger" → `dagger`. No match → list the registry keys and ask.
- **Severity scope** (optional): the level(s) named — `critical`/`high`/`medium`/`low` or combos ("high/critical", "all"). Act **only** on those (case-insensitive). **Default = HIGH + CRITICAL.**

> Example: *"fix mend for a.blazemeter.com for critical level"* → component `a.blazemeter`, scope = CRITICAL only.

# Component registry

The registry is **not bundled with this skill** — its single source of truth is
`config/services.json` in the **blz-claude-orchestrator** repo (onboard a repo by adding an entry
there). On an orchestrated run the orchestrator passes the resolved target entry into the prompt —
**use that, verbatim.** For a standalone/interactive run (this skill alone, without the
orchestrator), there is no local registry file to read — **ask the user for** (or copy from the
orchestrator's `config/services.json`) a per-component entry with these fields:

| Field | Meaning |
|-------|---------|
| `repo` | `org/name` under github.com (Blazemeter) — the PR target |
| `mend_project` | exact Mend project name (drifts from repo name; match against `projectVitals[].name`) — see the **mend** skill |
| `owner` | per-repo owner display name → resolved to the **Jira assignee** (empty → `tcohen`) — see the **jira** skill |
| `jenkins_folder` | multibranch folder on blazect Jenkins — see the **jenkins** skill |
| `integration_branch` | branch the fix branches off / PRs into (`develop`/`master`) |
| `stack` | drives the fix recipe + manifest (`php-composer`→`composer.json`, `gradle-springboot`→`build.gradle.kts`, `maven-springboot`→`pom.xml`) — see **dep-remediation** |
| `api_tests` | list of `api_testing/tests/…` paths for the denv API-test gate (step 7b) — run as `TESTS_TO_RUN_MANUAL`; empty = deploy-only (skip the API-test gate) — see the **jenkins** skill |
| `crane` | `true` for crane components (torero, apm-manager, proxy-recorder, bzm-crane, richrach) — triggers the a.blazemeter.com branch step (6b) before denv deploy |
| `harbor_php_key` | PHP constant name in `HarborRepository` (e.g. `RESOURCE_TORERO`) — used in step 6b to locate and update the `'version'` line in `HarborVersionsSettings.php` |
| `description` | human label |

# Fix loop

Order: **alerts → branch → fix → local compile+unit-test → push (commits prefixed `<parent_key>: `) → Jenkins green (GATE) → [crane only] a.blazemeter.com branch with updated HarborVersionsSettings.php (commit prefixed `<parent_key>: `) → [crane only] BACKEND-CI green (GATE) → denv deploy + fix-related API tests (GATE) → Confluence report → Jira created → squash commits to one with child ticket id + force-push → PR (opened with ticket id in title) → Jira description updated with PR link → [crane only] post mend-finalize follow-up command.** Commits use `parent_key` (always known from jira config) to satisfy the repo's `Jira id in the title` GitHub branch protection required status check; once the child ticket is created (step 9) the commits are squashed to one with the child ticket id before the PR is opened (step 9.5). Jenkins-green, denv deploy, and API-test gates are all hard — nothing downstream runs until all pass. Confluence report runs after gates regardless of outcome.

1. **Fetch alerts → triage to the requested scope** (default HIGH+CRITICAL, case-insensitive) — via **mend**. Resolve the project token first. Triage by the alert set, not by what's in flight (fix an in-scope alert even if it's in another open PR). Only fix alerts in the component's `stack` ecosystem; defer the rest to the summary.
2. **Create the dated branch** `mend-fix-<YYYYMMDD-HHMMSS>` off `integration_branch` — via **github**.
3. **Apply the fix** for every in-scope alert, batched into the branch, per the `stack` — via **dep-remediation** (golden rule, advisory cross-check, defer breaking majors to Notes).
4. **Compile + run unit tests locally** per stack — via **dep-remediation**. Only push if green.
5. **Commit + push** the branch — via **github**. Prefix every commit message with the parent ticket id from the Jira config (`parent_key`): `<parent_key>: <description>`. The child ticket does not exist yet — the parent key satisfies the repo's `Jira id in the title` GitHub branch protection required status check. After the child ticket is created (step 9), commits are squashed and updated to the child ticket id (step 9.5).
6. **Trigger the build with `PUSH_TO_GCR=true` + `PERFORM_WHITESOURCE_SCAN=true` and poll until
   green** — via **jenkins**. Red → fix-forward, cap **3 attempts**; still red → stop (no PR/Jira,
   but still do step 8) + Notes. Expect **two builds** after the push: the branch's own
   auto-trigger (webhook/branch-indexing, default params) plus this explicit parameterized one —
   gate on the **explicit** one, not the auto-triggered one.
6b. **[Crane repos only] Pin the fix's image tag in `a.blazemeter.com` via the GitHub API** —
    when `crane` is `true` in the catalog entry, after Jenkins green (step 6) and **before** denv
    deploy (step 7). No clone — use `gh api` (auth via `GH_TOKEN`) for three calls:

    **(i) Create the branch off `develop`:**
    ```
    # Get develop HEAD SHA
    DEV_SHA=$(gh api /repos/Blazemeter/a.blazemeter.com/git/refs/heads/develop --jq '.object.sha')
    # Create branch with the same name as the component fix branch
    gh api --method POST /repos/Blazemeter/a.blazemeter.com/git/refs \
      -f ref="refs/heads/<fix-branch>" -f sha="$DEV_SHA"
    ```

    **(ii) Fetch the file, patch the version, commit back:**
    ```
    FILE_PATH="src/blazemeter/Settings/HarborVersionsSettings.php"
    # Fetch current content + SHA (needed for the update)
    FILE_JSON=$(gh api /repos/Blazemeter/a.blazemeter.com/contents/$FILE_PATH?ref=<fix-branch>)
    FILE_SHA=$(echo "$FILE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])")
    CONTENT=$(echo "$FILE_JSON" | python3 -c "import sys,json,base64; print(base64.b64decode(json.load(sys.stdin)['content']).decode())")

    # Patch: find the block for harbor_php_key and replace its 'version' line
    # harbor_php_key e.g. RESOURCE_TORERO; fix-branch e.g. mend-fix-20260826-092258
    PATCHED=$(echo "$CONTENT" | python3 -c "
    import sys, re
    src = sys.stdin.read()
    # Replace 'version' => '...' in the block immediately following RESOURCE_<key>
    pattern = r\"(HarborRepository::<harbor_php_key>[\\s\\S]*?'version'\\s*=>\\s*')[^']+(')\"\
    result = re.sub(pattern, r\"\\g<1>latest-<fix-branch>\\g<2>\", src, count=1)
    print(result, end='')
    ")

    NEW_CONTENT=$(echo "$PATCHED" | python3 -c "import sys,base64; print(base64.b64encode(sys.stdin.buffer.read()).decode())")
    gh api --method PUT /repos/Blazemeter/a.blazemeter.com/contents/$FILE_PATH \
      -f message="<parent_key>: <fix-branch>: pin <harbor_php_key> to latest-<fix-branch>" \
      -f content="$NEW_CONTENT" \
      -f sha="$FILE_SHA" \
      -f branch="<fix-branch>"
    ```

    **(iii) Gate on the `BACKEND-CI` build for the a.blazemeter.com branch going green:**
    After pushing the branch, Jenkins triggers a `BACKEND-CI/<fix-branch>` build automatically.
    Poll it (same technique as step 6 — queue item → build number → result) until `SUCCESS`.
    Red → stop (no PR/Jira, but still do step 8) + Notes. Do **not** proceed to denv deploy until
    this build is green — denv needs the fresh a.blazemeter.com image alongside the crane image.

    When the denv deploy (step 7a) runs with `GIRO_BRANCH=<fix-branch>`, the deploy job finds
    **both** branches — the crane component's dep fix and `a.blazemeter.com`'s updated
    `HarborVersionsSettings.php` — and deploys the correct GCR image. For non-crane repos
    (`crane` absent or `false`) skip this step entirely.
7. **Deploy to denv, then verify the fix with the related API tests** — via **jenkins**. Two hard
   gates, in order:
   (a) **Deploy** the branch's freshly-built image (step 6, `PUSH_TO_GCR=true`) to denv — trigger
       the shared denv deploy job with the **fix branch you pushed** (`GIRO_BRANCH`) and gate on it
       going green (the image starts/runs in denv).
   (b) **Functionally verify** the fix — run this component's API tests against that denv env
       (`API-TEST-SELECTED-DEV-ENV`, `TARGET_ENV=DEnv`), and gate on them passing. Use the
       component's **`api_tests`** list from the catalog entry (passed in the target config) as
       `TESTS_TO_RUN_MANUAL`, verbatim — it is the curated, per-repo set (don't guess paths). **If
       `api_tests` is empty** (e.g. scaleron), **skip this API-test gate** and rely on the deploy
       gate (a) alone. A green deploy only proves the image starts; these tests prove the fix
       didn't break behavior.
   If either gate fails → **fix-forward** (a red API test means the dependency fix is wrong — change
   the version or adjust code, re-push → re-build → re-deploy → re-test), cap **3 attempts** total;
   still failing → stop (no PR/Jira, but still do step 8) + Notes. Nothing downstream (Jira/PR) runs
   until both the denv deploy and the fix-related API tests are green.
8. **Upsert currently-unfixable libraries to Confluence** — a manager-facing quick view, not a
   run log: only libraries genuinely un-fixable right now (breaking major required, no fix version
   upstream, or out-of-recipe ecosystem) get a row on the
   [Mend vulns](https://perforce.atlassian.net/wiki/spaces/BLZRD/pages/3332964371/Mend+vuls)
   Confluence page — **excluding** `pending Mend rescan` (already fixed, just waiting on Mend) and
   out-of-scope-severity (not attempted, not "can't fix") alerts. One row per (repo, library) —
   never write the same library+CVE twice: a repeat sighting of an already-listed CVE updates that
   row's Date in place, and a new CVE against an already-listed library is added into that same
   row rather than getting its own. Report the **primary/direct** library per the golden rule,
   never a transitive one. See
   [references/mend-confluence-report.md](references/mend-confluence-report.md) for the exact API
   calls, upsert matching, and column schema. Runs even when step 6 or 7 stopped early on a red
   build. Skip silently if nothing from this run qualifies.
9. **Create the MOB ticket** (In Progress, assignee = owner) unless `nojira` — via **jira**, passing
   the summary `Fix Mend vulnerabilities <repository name>` and the label **`mend_orch`** (so every
   orchestrator-created ticket is filterable via `labels = mend_orch`); jira owns project/board/
   fields/status — this recipe only supplies the ticket's name, label, and description content.
   Created **before**
   the PR exists, so the description at this point covers dependencies fixed and the Jenkins build
   link; if step 8 reported any deferred/unfixed alerts, it also links to the Confluence page (see
   the **jira** skill's description ordering) — omit that line if step 8 had nothing to report or
   was skipped via `noconfluence`. It cannot yet include a PR link (see step 11).
9.5. **Squash commits and update to child ticket id** — now that the child ticket exists, squash all
   commits on the fix branch into one and update the commit message to use the child ticket id:
   ```bash
   git reset --soft $(git merge-base HEAD origin/<integration_branch>)
   git commit -m "<ticket>: mend: fix Mend vulnerabilities in <repo>"
   git push --force-with-lease origin <fix-branch>
   ```
   Skip when `nojira`. This replaces the temporary `<parent_key>:` prefix with the child ticket id
   so the final commit history is clean. Do not wait for a new CI build — the code is unchanged.
10. **Open the PR** into `integration_branch` — via **github**. The MOB ticket already exists
   (step 9), so the title carries the `MOB-####` id **from creation** — never tagged on
   afterward. If `nojira` was set, open the PR without a ticket id in the title.
11. **Update the MOB ticket's description** to add the PR link, now that the PR exists — via
    **jira**. Skip when `nojira` (no ticket to update).
12. **[Crane repos only] Post the mend-finalize follow-up** — after step 11, output this message
    clearly so the user can copy it into Slack once the crane PR is merged:

    > **Crane PR open:** `<PR URL>`
    > After it merges to `<integration_branch>` and the CI build completes, run:
    > `/orch run mend-finalize --target <component> --scope <fix-branch>,<MOB-ticket>`
    > This pins the real semantic version in `a.blazemeter.com` and opens its PR.

    Use the actual values — e.g. `--target torero --scope mend-fix-20260916-123456,MOB-1234`.
    For non-crane repos (`crane` absent or `false`) skip this step entirely.

13. **Write the summary table** — one row per alert acted on:

    | Repository | Alert (CVE / library) | Fix (from → to) | Succeeded | Notes |
    |------------|-----------------------|-----------------|-----------|-------|
    | `<repo>` | CVE-… / `lib` | `x → y` | ✅ / ❌ | *(only if needed)* |

    "Succeeded" = fix landed **and** Jenkins went green. **Leave Notes empty on success** — fill only on ❌/deferred (failing stage + root cause, hit the 3-attempt cap, breaking major required, or the Mend fix version was itself under advisory). Below the table, also list: alerts deferred as out-of-recipe ecosystem, alerts outside the requested scope, and any `pending Mend rescan` items.

# Command flags

| Flag | Effect |
|------|--------|
| *(none)* | Full loop as above (Jenkins gate → [crane only] a.blazemeter.com branch → [crane only] BACKEND-CI gate → denv-deploy + fix-related API-test gate → Confluence → Jira → PR → Jira description update → [crane only] mend-finalize follow-up message). Red build, failed BACKEND-CI, failed denv deploy, **or** failed fix-related API test → fix-forward up to 3; still failing → stop + Notes. |
| `test` | Skip the Mend API; read pre-seeded JSON from `/tmp/mend-<component>-vulns.json` (see **mend**). |
| `nojenkins` | Skip the Jenkins-green gate — open the PR/Jira without waiting for the build. |
| `nojira` | Skip Jira create and the later description update; the PR opens without a ticket id in the title. |
| `noconfluence` | Skip the step-8 Confluence report (and the Jira description's link to it). |

# References

- Component registry (authoritative): `config/services.json` in **blz-claude-orchestrator**.
- Composed skills: **mend**, **dep-remediation**, **jenkins**, **github**, **jira** (this recipe
  supplies the ticket summary/name; jira owns project MOB/board/fields/status).
- Confluence report mechanics: [references/mend-confluence-report.md](references/mend-confluence-report.md).
