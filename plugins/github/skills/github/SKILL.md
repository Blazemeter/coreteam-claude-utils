---
name: github
description: Blazemeter GitHub branch and PR conventions — create a unique date-stamped Docker-safe branch off the integration branch, commit with the Co-Authored-By trailer, push via SSO-authorized gh, open a PR back into the integration branch, and prepend the tracking ticket id to the PR title. Load for branch/push/PR work on Blazemeter repos.
---

# Branch strategy

- **One unique, date-stamped branch per run:** `mend-fix-<YYYYMMDD-HHMMSS>` (e.g. `mend-fix-$(date +%Y%m%d-%H%M%S)`), branched off the target's `integration_branch` (`develop`/`master`).
- **No component name / dots in the branch** — names like `a.blazemeter.com` contain dots (not Docker-tag-safe), and each component is its own repo, so the timestamp alone is unique. Never reuse a prior run's branch.
- Optionally close any prior **open** `mend-fix-*` PR in the repo with a "superseded by newer run" comment.

# Commit & push

- Commit with the `Co-Authored-By` attribution trailer (a global hook enforces it).
- Push via **`gh`** — authenticated and **SSO-authorized** for the `Blazemeter` org (a raw PAT 403s unless SSO-authorized). Auth = `GH_TOKEN` in the environment.

# Pull request

- Open the PR from `<branch>` into the `integration_branch`.
- **No GitHub reviewer is set** — ownership is tracked via the Jira assignee, not a GH reviewer.
- **Tag the PR title with the tracking ticket id** (prepended, HEAD), e.g. `MOB-51396: mend: bump guzzle 7.4 → 7.8`.
  If the caller's flow creates the ticket **before** opening the PR (e.g. **mend-blz**), include the
  id in the title at creation — never open untitled and tag after. Only fall back to tagging the
  title after the fact if the calling flow's order genuinely creates the ticket after the PR.

# PR body

Keep **all** of these blocks in order — intro + CVE table, `### Change`, `### Verification`, `Jira:`,
and (crane only) `### Next step`. Don't drop or rename blocks and don't free-form the structure; the
only per-run variation is the content inside each block.

```markdown
## Mend vulnerability remediation — <component>

Fixes <N> Mend SECURITY_VULNERABILITY alerts, all in **<lib> <version>** (<direct dep | transitive via `<parent>`>):

| CVE | Severity | Library | Fix |
|-----|----------|---------|-----|
| <CVE-id> | <High|Medium|Low> (CVSS <score>) | <lib> | <from> → <to> |

### Change
<Golden-rule narrative: which direct dep/BOM was bumped and in which file, how the transitive now
resolves to the fixed version, and the clean audit result (pip-audit / composer audit / etc.).>

### Verification
- <✅|❌> **Local:** <N> unit tests pass (<runtime/notes>); <audit tool> on the resolved tree reports no known vulnerabilities.
- <✅|❌> **Jenkins:** [<JENKINS-FOLDER> build #<n>](<build-url>) — SUCCESS (unit-test · prisms · mend · WhiteSource scan; PUSH_TO_GCR=true, PERFORM_WHITESOURCE_SCAN=true).
- <✅|❌> **a.blazemeter.com BACKEND-CI:** Harbor `<harbor_php_key>` pinned to `latest-<fix-branch>`; build green.   <!-- [crane only] -->
- <✅|❌> **denv deploy:** SUCCESS.
- <✅|⚠️|❌> **denv API tests** (<test file(s)>): <result>.

Jira: <MOB-id>

### Next step   <!-- [crane only] -->
After this PR merges to `<integration_branch>` and its CI build completes, run:

    /orch run mend-finalize --target <component> --scope <fix-branch>,<MOB-id>

to pin the real semantic version in a.blazemeter.com and open its PR.
```

**Status key** — use consistently: `✅` passed · `⚠️` passed with a known caveat (e.g. a pre-existing
environmental denv failure confirmed identical on an `integration_branch` baseline — state the caveat
inline, as in the `denv API tests` line) · `❌` failed.

**Rules:**
- **Non-crane components:** omit the two `[crane only]` pieces — the `a.blazemeter.com BACKEND-CI`
  verification bullet **and** the whole `### Next step` section. Keep every other block.
- **The `Next step` command must be fully substituted and copy-paste-ready** — fill `<component>`,
  `<fix-branch>`, and `<MOB-id>` with this run's real values, never leaving placeholders:

      /orch run mend-finalize --target <component> --scope <fix-branch>,<MOB-id>

  The reader should copy the line and run it without looking anything up. Keep it as an indented
  code line so it's one-click copyable.
- Every Verification bullet gets a leading status marker — this is the only change from the prior
  free-form style; the Fixes/Change/Verification/Jira blocks themselves stay.
