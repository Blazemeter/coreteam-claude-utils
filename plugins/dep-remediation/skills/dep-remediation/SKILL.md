---
name: dep-remediation
description: Fix vulnerable dependencies correctly — the golden rule (bump the direct dependency / BOM, never pin the transitive), cross-check the fix version against ecosystem advisories, defer breaking-major upgrades, and compile + unit-test locally before pushing. Load for any dependency remediation or version-bump work in php-composer, gradle-springboot, maven-springboot, pip, or npm projects.
---

# Golden rule — fix the DIRECT dependency, never the transitive

If a vulnerable library **Y** is pulled in by a direct dependency **X**, bump **X** so it resolves a
fixed **Y**. Do **not** pin/override the transitive **Y** directly. For BOM-managed transitives
(Spring Framework, micrometer, logback, jackson under Spring Boot), bump the **Spring Boot BOM
version** — the one dep that brings them all — *not* individual `<spring-framework.version>` /
`<micrometer.version>` overrides. If no direct-dep / BOM bump resolves the alert, **defer and note
it** — never pin the transitive.

Two more non-negotiables:
- **Cross-check the fix version against the ecosystem advisory DB.** Mend's suggested version may
  itself be under advisory (e.g. `aws/aws-sdk-php` 3.368.0 was) — escalate to the latest
  non-advisory version.
- **Defer breaking majors.** If a fix needs a breaking/major upgrade that fails the build (within
  the attempt cap), **revert just that dependency**, keep the other fixes, and record the deferred
  one (e.g. "symfony/yaml 3.4 → major upgrade required, deferred"). Also **fix tests that a dep
  change legitimately breaks** (e.g. an SDK changing an error string).

**Only fix alerts in the project's own stack ecosystem.** Alerts in a different manifest (Python
`requirements.txt` or npm `package.json` under `tools/` in a PHP repo) are **deferred and listed**,
not fixed here.

# Fix recipe by stack

## `php-composer`
- Bump the **direct `require`** in `composer.json` (incl. the direct dep that pulls a vulnerable transitive, e.g. bump `guzzle` to pull a fixed `psr7`) → `composer update <vendor/pkg> --with-dependencies --ignore-platform-reqs` → commit `composer.lock`.
- **Always pass `--ignore-platform-reqs`** on the update. The sandbox resolving/locking versions
  here won't have every runtime PHP extension the app loads in production (e.g. `ext-mongodb`,
  `ext-grpc`, `ext-zstd`) — that's fine, since this step is dependency-graph math, not execution.
  It doesn't change which versions get resolved, only whether the solver requires the extension to
  be *present in this sandbox* to do the math. Real runtime correctness is still fully verified by
  `make test-docker-cov` below (which builds the repo's own Dockerfile, with the real extensions)
  and the Jenkins CI gate — neither is affected by this flag.
- **Cross-check:** `composer audit` (Mend's suggestion may be under a Packagist advisory).
- **Local build + test (pre-push):** `make phpstan` (static) + `make test-docker-cov` (the dockerized unit suite CI runs — needs Docker).
- **Internal forks** (`mongator`, `mondator`, `php-resque-ex`, `php-resque-ex-scheduler`, `PHP-Multivariate-Regression`, `Restler`, `mandrill-api-php`) resolve from `github.com/Blazemeter` git `repositories`, not Packagist — a CVE there is fixed **upstream in that repo + a ref bump**, not a registry version.

## `gradle-springboot`
- BOM-managed transitive → **bump the Spring Boot version** (not the individual transitive); a genuinely direct dep → bump its literal version in `build.gradle.kts`. Verify with `./gradlew dependencies`.
- **Local build + test (pre-push):** `./gradlew test`.

## `maven-springboot`
- BOM-managed transitive → **bump `<spring-boot.version>`** in `pom.xml` (the BOM), *not* individual `<spring-framework.version>` / `<micrometer.version>` overrides; a genuinely direct dep → bump its `<version>`. Verify with `mvn -q dependency:tree`.
- **Local build + test (pre-push):** `mvn -q -B verify`.
- **Repo note:** Blazemeter builds don't use `aws-nexus` (unrelated machine-global mirror). Let the repo's own build config resolve deps — don't inject a Nexus.

## `pip`
- No BOM concept in pip — bump the **direct dependency**'s pin. For a vulnerable transitive, bump
  the direct package that pulls it in (same golden rule: never pin the transitive directly).
- Pin location varies by repo: `requirements.txt` (`pkg==x.y.z`) is the common case; some repos pin
  in `setup.py`'s `install_requires` or `setup.cfg` instead — bump wherever the version is actually
  pinned. Regenerate any lock file the repo uses (e.g. `pip-compile`) if present.
- **Cross-check:** `pip-audit` (falls back to `safety check` if `pip-audit` isn't available) — Mend's
  suggested version may itself be under advisory on PyPI/OSV.
- **Local build + test (pre-push):** `pip install -r requirements.txt -r test-requirements.txt` (adjust
  filenames per repo) then `pytest`. Prefer the repo's own `Makefile`/CI target if one exists (e.g.
  `make test`) over calling `pytest` directly, so local runs match what CI actually runs.

## `npm`
- Bump the **direct dependency** in `package.json` (`dependencies`/`devDependencies`) to the fixed
  version — including the direct dep that pulls a vulnerable transitive. Do **not** reach for
  `overrides`/`resolutions` to pin the transitive directly; that's the golden rule's "never pin the
  transitive" applied to npm's own override mechanism.
- Update with `npm install <pkg>@<version> --save-exact` (or the repo's existing version-pinning
  style) so `package-lock.json` regenerates and gets committed alongside `package.json`.
- **Cross-check:** `npm audit` — Mend's suggested version may itself still be flagged. Don't reach
  for `npm audit fix --force`; it can pull in unrelated breaking majors indiscriminately instead of
  the targeted golden-rule bump.
- **Local build + test (pre-push):** `npm ci` then whatever the repo's `package.json` `scripts`
  actually define (commonly `npm test`; TypeScript repos often need `npm run build` first) — check
  `scripts` rather than assuming, so local runs match CI.

# Local build+test discipline

Compile + run the unit suite **locally before pushing** (fail fast — don't burn a CI cycle). Only
push if green; if local tests fail, fix forward locally first. If the local env can't run them
(e.g. Docker unavailable), say so and rely on the CI gate. `Code Insight`
(`codeinsight-project.yml`, Revenera) is separate license scanning — not the CVE flow.
