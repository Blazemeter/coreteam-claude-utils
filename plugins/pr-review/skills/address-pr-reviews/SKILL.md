---
name: address-pr-reviews
description: >
  Use when the user provides a GitHub PR URL or number and asks to address, action, or
  incorporate review comments for any repo. Also use when continuing an existing PR
  comment cycle after a new push. Stack-agnostic — auto-detects the target repo's own
  test/lint commands rather than assuming a specific language.
---

# Address PR Review Comments

Automates the PR review-comment lifecycle: fetch → validate → incorporate → test → lint → review → commit → reply → poll.

> **Scope:** Address only what reviewers explicitly commented on. No refactors, cleanups, or
> fixes beyond comment scope.
> **Never merge:** Never run `git merge`, `git rebase` onto another branch, or `gh pr merge`.

---

## Step 1 — Auth + detect login

```bash
gh auth status
gh api user --jq '.login'   # store as <your_login>
```

Stop if not authenticated.

---

## Step 2 — Parse PR

```bash
gh pr view <PR_URL_OR_NUMBER> \
  --json title,headRefName,baseRefName,files,baseRepository \
  --jq '{title:.title, branch:.headRefName, base:.baseRefName,
         REPO:.baseRepository.name, OWNER:.baseRepository.owner.login,
         files:[.files[].path]}'
```

Store `<OWNER>` and `<REPO>` (base repository — owns the PR number) — used in Steps 5 and 14 API calls.

Derive `<ticket_id>` from the branch name by matching `[A-Z][A-Z0-9_]+-[0-9]+` (e.g. `MOB-12345-fix-thing` → `MOB-12345`, `secvuln_1508-desc` → `SECVULN-1508`). If no match, leave `<ticket_id>` empty — don't invent one.

---

## Step 3 — Checkout PR branch

```bash
git checkout <pr_branch>       # or: gh pr checkout <PR_NUMBER> if not local or from a fork
git pull origin <pr_branch>    # ensure latest remote changes; for forks use gh pr checkout
```

---

## Step 4 — Stash uncommitted changes

```bash
git status --short
git stash                      # if dirty; pop after Step 13
```

---

## Step 5 — Fetch and classify comments

```bash
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/comments --paginate \
  --jq '[.[] | {id:.id, in_reply_to_id:.in_reply_to_id, path:.path, line:.line, body:.body, user:.user.login}]'

gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/reviews --paginate \
  --jq '[.[] | select(.body != "") | {id:.id, body:.body, user:.user.login, state:.state}]'
```

Group by thread (`in_reply_to_id` → root `id`). Classify using `<your_login>`:

| Bucket | Criteria |
|--------|----------|
| **Unaddressed** | No reply from `<your_login>` — action these |
| **Verify** | Has your reply — check code actually reflects it; if not, treat as unaddressed |
| **Skip** | Your reply confirmed AND code matches |

---

## Step 6 — Validate each unaddressed comment

| Verdict | Criteria |
|---------|----------|
| **Valid** | Real issue in PR changed lines: bug, style violation, missing test, logic error |
| **Invalid** | Wrong assumption, already fixed, subjective, or contradicts the repo's own conventions |
| **Needs discussion** | Ambiguous — flag to user, no code change |

**Conventions come from the target repo, not this skill.** Check (in order) for `CLAUDE.md`,
`CONTRIBUTING.md`, a documented style guide, or linter config in the repo root before judging
"Invalid" on style grounds — cite the specific rule/file when you do. If the repo has no
documented convention on the point raised, fall back to general engineering judgement
(correctness, safety, test coverage) rather than inventing a house style.

---

## Step 7 — Incorporate valid comments

- Make the **minimal change** only — no surrounding refactors or docstrings.
- If fix requires touching lines **outside the original PR diff**: ask user approval before editing.
- If fix is a **major change** (API schema, DB model, auth logic, cross-file rename): ask user approval.
- Record what was changed (used in Step 14 reply).

---

## Step 8 — Run tests

Skip this step if no code changed in Step 7.

Detect the test command from repo signals — try in order, use the **first** match rather than
running every possible one:

| Signal in repo root | Command |
|---|---|
| `CLAUDE.md` / `CONTRIBUTING.md` documents a test command | use that command verbatim — it's authoritative |
| `Makefile` with a `test` target | `make test` |
| `package.json` with a `"test"` script | `npm test` |
| `composer.json` | `composer test` (or the `Makefile` target above, if present) |
| `pyproject.toml` / `requirements.txt` / `setup.py` | `.venv/bin/pytest` if `.venv/` exists, else `pytest` |
| `go.mod` | `go test ./...` |
| `pom.xml` | `mvn test` |
| `build.gradle` / `build.gradle.kts` | `./gradlew test` |

If none match, or more than one plausibly applies and it's not obvious which, **ask the user**
for the test command rather than guessing — running the wrong one wastes a cycle and a wrong
"tests pass" is worse than no test run.

All tests must pass. If failures exist that are unrelated to Step 7 changes, stop and report them
to the user — do not auto-fix beyond comment scope. Do not proceed until the full test suite is green.

---

## Step 9 — Code-review agent (incorporation changes only)

Skip this step if no code was changed in Step 7.

```bash
git diff origin/<pr_branch>    # pass this diff to the sub-agent
```

Sub-agent task (read-only) — **run exactly once:**
- **Input:** `git diff origin/<pr_branch>` output
- **Output:** list of `{file, line, severity, description}` findings
- **Restriction:** only findings directly tied to PR review comments and present in the diff
- May use broader PR files as context but must not report on unchanged lines

---

## Step 10 — Incorporate review agent findings

Same validate → incorporate loop as Steps 6–7. **One pass only — do not re-run the review agent after incorporating.** Only act on findings **in the diff from Step 9** that directly relate to a PR comment. Skip everything else.

---

## Step 11 — Lint changed files

Skip this step if no code changed in Step 7/10, or if no lint command can be confidently
identified for this repo (see detection table below) — say so in the summary rather than
guessing a tool that isn't actually configured.

| Signal in repo root | Command |
|---|---|
| `CLAUDE.md` / `CONTRIBUTING.md` documents a lint command | use that command verbatim |
| `Makefile` with a `lint`/`codestyle`/`phpstan` target | run it |
| `.eslintrc*` or an `eslintConfig` in `package.json` | `npx eslint <changed_files>` |
| `ruff.toml` / `[tool.ruff]` in `pyproject.toml` | `ruff check <changed_files>` |
| `.flake8` / `setup.cfg` with `[flake8]` | `flake8 <changed_files>` |
| `go.mod` | `go vet ./...` and `gofmt -l <changed_files>` |

Fix reported lines only. Repeat until clean.

---

## Step 12 — Final test run

Re-run the Step 8 command. **All tests must pass before committing.** If any test fails — including pre-existing failures — stop, report to user, and do not commit until resolved.

---

## Step 13 — Commit and push (only if code changed)

```bash
git add <modified_file1> <modified_file2> ...
git commit -m "<commit message>"
git push
```

Commit message is `<ticket_id>: Address PR review comments` when Step 2 found a ticket id,
otherwise plain `Address PR review comments`.

Stage specific files only — never `git add -A` or `git add .`. Never `--no-verify`. Push to PR feature branch only.

Pop stash if created in Step 4: `git stash pop`. Warn user on conflicts.

---

## Step 14 — Reply to every unaddressed comment

Always reply to the **root comment** (`id`) of each thread. Cross-check `path`+`line`+`body` before posting.

```bash
gh api repos/<OWNER>/<REPO>/pulls/<PR_NUMBER>/comments/<ROOT_COMMENT_ID>/replies \
  -X POST -f body="<reply_body>"
```

| Verdict | Reply format |
|---------|-------------|
| Incorporated | `Addressed. <one sentence on what changed>.` |
| Invalid | `Invalid — <one sentence citing the repo's convention or the incorrect assumption>.` |
| Needs discussion | `Flagged for discussion — <one sentence on ambiguity>.` |
| Out of scope | `Out of scope — touches lines outside this PR's diff. Skipped for this PR.` |

---

## Step 15 — Poll for new comments (opt-in)

Ask the user: "Want me to poll for new review comments? (polls every 15 min for 1 hour)"

If yes: 4 polls × 15-minute intervals. Before each poll:

```bash
gh pr view <PR_NUMBER> --json state --jq '.state'
```

Stop if `MERGED` or `CLOSED`. Re-run Steps 6–14 for any new unaddressed comments found.

---

## Summary Output

```
## PR Review Summary — <PR_TITLE>

| # | Comment | Verdict | Action |
|---|---------|---------|--------|
| 1 | "Missing error handling..." | Valid | Addressed — added null check |
| 2 | "Use X instead of Y here"    | Invalid | Invalid — repo's CONTRIBUTING.md specifies Y |

Tests     : PASS (<test command used>)
Lint      : PASS (<lint command used>, or "skipped — no lint command detected")
Committed : Yes — pushed to <branch>
```

---

## Usage notes for Claude

1. Trigger when user provides a GitHub PR URL and asks to address/action/incorporate review comments.
2. Always detect `<your_login>` via `gh api user --jq '.login'` in Step 1 — use it throughout to identify your replies.
3. **Scope is fixed:** Only address what reviewers explicitly commented on. No refactors, cleanups, or fixes beyond comment scope.
4. Always pull latest from remote after checkout (Step 3).
5. Auto-stash uncommitted changes (Step 4). Pop after Step 13. Warn on conflicts.
6. If no code changed after Step 7: skip Steps 9–12 entirely.
7. Review agent (Step 9) runs exactly once — never re-run after incorporating findings.
8. Never guess a test/lint command the repo doesn't actually use — detect it (Steps 8/11) or ask.
9. Ask user if they want polling (Step 15) — never start polling automatically.
10. Push to PR feature branch only. Never merge, rebase onto master, or run `gh pr merge`.
11. Major changes (API schema, DB models, auth logic, cross-file renames): require explicit user approval.
