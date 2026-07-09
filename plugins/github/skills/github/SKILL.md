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
