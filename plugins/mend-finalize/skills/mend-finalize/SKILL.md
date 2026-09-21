---
name: mend-finalize
description: Phase 2 of the crane Mend flow — after the crane PR merges to the integration branch and the CI build completes, reads the real semantic version from the VERSION file at HEAD of the integration branch, updates HarborVersionsSettings.php in the a.blazemeter.com branch from latest-<fix-branch> to the real semantic version via GitHub API, opens the a.blazemeter.com PR into develop, and updates the MOB ticket description with the PR link. Triggered after the user merges the crane PR opened by mend-blz phase 1.
---

# When to use

Load this skill when the user runs `/orch run mend-finalize` — phase 2 of the crane Mend
remediation flow. Phase 1 (`mend-blz`) opened the crane PR and left a.blazemeter.com pinned to
`latest-<fix-branch>`. This skill completes the flow by pinning the real production version once
the crane PR has merged to the component's `integration_branch` and that branch's CI build has
produced a semantic version.

# Invocation

```
/orch run mend-finalize --target <component> --scope <fix-branch>,<MOB-ticket>
```

- **`--target`** — crane component name (e.g. `torero`, `proxy-recorder`, `apm-manager`, `bzm-crane`, `richrach`). Match against the component registry (`config/services.json` in blz-claude-orchestrator) to get `repo`, `jenkins_folder`, and `harbor_php_key`.
- **`--scope`** — comma-separated `<fix-branch>,<MOB-ticket>` (e.g. `mend-fix-20260916-123456,MOB-1234`). Parse by splitting on the first comma: everything before = fix branch, everything after = MOB ticket number.

# Steps

## 1. Parse arguments

From `--scope`, extract:
- `fix_branch` — the branch name from phase 1 (e.g. `mend-fix-20260916-123456`)
- `ticket` — the MOB ticket (e.g. `MOB-1234`)

From `--target`, look up the component in the registry:
- `repo` — e.g. `Blazemeter/torero`
- `jenkins_folder` — e.g. `CRANE-TORERO-CI`
- `harbor_php_key` — e.g. `RESOURCE_TORERO`
- `integration_branch` — the branch that gets merged to (e.g. `master`) — use this everywhere "master" appears below; never assume it is `master`

## 2. Check the crane PR is merged

```bash
gh api "/repos/<repo>/pulls?state=closed&head=Blazemeter:<fix-branch>&per_page=5" \
  --jq '.[0] | {number: .number, merged_at: .merged_at, url: .html_url}'
```

- If `merged_at` is null or empty → the PR is not merged yet. Stop and reply:
  > "The crane PR for `<fix-branch>` is not merged yet. Merge it first, then re-run this command."
- If `merged_at` has a timestamp → record `merge_timestamp` and continue.

## 3. Find the integration-branch build that ran after the merge

Poll `<jenkins_folder>/<integration_branch>` builds for a completed `SUCCESS` build with `timestamp > merge_timestamp`. The merge triggers a Jenkins build via webhook — it may still be queued or running when this command is invoked.

```bash
# Poll every 60s, up to 60 minutes
curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" \
  "https://blazect-jenkins.blazemeter.com/job/<jenkins_folder>/job/<integration_branch>/api/json?tree=builds[number,result,timestamp,displayName,building]{0,10}"
```

Pick the build where:
- `timestamp` (ms) > `merge_timestamp` (convert to ms)
- `result == "SUCCESS"` (not still `building`)

If no such build found after 60 minutes → stop and reply:
> "Build after merge not found within 60 minutes. Check `<jenkins_folder>/<integration_branch>` manually, then re-run."

## 4. Read the semantic version

Once the successful build is confirmed, read the `VERSION` file from the **HEAD of `<integration_branch>`** — the CI increments the version as part of the build, so HEAD reflects what was actually built and pushed to GCR. If subsequent commits landed after the mend merge, HEAD may be newer than that specific build's displayName — that is expected; use the HEAD value.

```bash
gh api "/repos/<repo>/contents/VERSION?ref=<integration_branch>" \
  --jq '.content' | python3 -c "import sys,base64; print(base64.b64decode(sys.stdin.read()).decode().strip())"
# → "4.6.190"
```

## 5. Update HarborVersionsSettings.php in a.blazemeter.com branch

Same GitHub API approach as phase 1 step 6b — no clone:

```bash
FILE_PATH="src/blazemeter/Settings/HarborVersionsSettings.php"

# Fetch current file + SHA from the fix branch
FILE_JSON=$(gh api "/repos/Blazemeter/a.blazemeter.com/contents/$FILE_PATH?ref=<fix-branch>")
FILE_SHA=$(echo "$FILE_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])")
CONTENT=$(echo "$FILE_JSON" | python3 -c "import sys,json,base64; print(base64.b64decode(json.load(sys.stdin)['content']).decode())")

# Replace latest-<fix-branch> with the real semantic version for this component's block
PATCHED=$(echo "$CONTENT" | python3 -c "
import sys, re
src = sys.stdin.read()
pattern = r\"(HarborRepository::<harbor_php_key>[\s\S]*?'version'\s*=>\s*')[^']+(')\"\
result = re.sub(pattern, r\"\g<1><version>\g<2>\", src, count=1)
print(result, end='')
")

NEW_CONTENT=$(echo "$PATCHED" | python3 -c "import sys,base64; print(base64.b64encode(sys.stdin.buffer.read()).decode())")

gh api --method PUT "/repos/Blazemeter/a.blazemeter.com/contents/$FILE_PATH" \
  -f message="<fix-branch>: pin <harbor_php_key> to <version>" \
  -f content="$NEW_CONTENT" \
  -f sha="$FILE_SHA" \
  -f branch="<fix-branch>"
```

## 6. Open the a.blazemeter.com PR

```bash
gh pr create \
  --repo Blazemeter/a.blazemeter.com \
  --head <fix-branch> \
  --base develop \
  --title "<ticket> <fix-branch>: pin <harbor_php_key> to <version>" \
  --body "Pins <harbor_php_key> to <version> following crane PR merge. Part of <ticket>."
```

Record the PR URL.

## 7. Update the MOB ticket description

Append the a.blazemeter.com PR link to the existing MOB ticket description — via **jira**. Add a line:
> `a.blazemeter.com PR: <PR URL>`

## 8. Output summary

```
mend-finalize complete for <component>:
  Crane PR:          merged ✅
  Master version:    <version>
  a.blazemeter PR:   <PR URL>
  MOB ticket:        <ticket> updated ✅
```

# Notes

- **Never exit the turn while polling** for the master build — poll synchronously in a loop. Do not use background polling or scheduled wakeups.
- **This skill has no test gate** — the fix was already validated in phase 1 (denv deploy + API tests). This step is version-pinning only.
- If the a.blazemeter.com branch `<fix-branch>` does not exist, it means phase 1 did not run for a crane component — stop and inform the user.
