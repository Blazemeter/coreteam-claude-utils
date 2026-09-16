---
name: investigate-master
description: Use when investigating why a specific BlazeMeter master/test/session behaved unexpectedly — stuck, wrong metric, silent failure, intermittent, customer-reported. Requires one or more master IDs and the environment they ran in (denv/bzdev/ci/staging/prod). Runs a preflight dependency check for that environment before starting, including whether the session's artifact files can be fetched directly via `gcloud storage` (falls back to asking the user if not). Applies across a.blazemeter.com, taurus-cloud, taurus, bzm-crane. Not for general code review or feature work.
allowed-tools: mcp__opensearch-reader__ping, mcp__opensearch-reader__search_logs, Bash(gcloud auth list*), Bash(gcloud storage ls*), Bash(gcloud storage cp*)
---

## Why this skill exists

Distilled from MOB-52978 (JPMC "RPS stuck at 1 RPS" investigation): a multi-day investigation that went through three different root-cause theories — a plausible-but-wrong code theory, a CPU/memory theory that had to be walked back, and finally the real cause — before the actual answer turned up in the one place it should have been checked first: the engine's own raw execution log. This skill exists so that sequence doesn't repeat.

## Dependencies this skill assumes

- The `opensearch` plugin in this marketplace (bundles the `opensearch-reader` MCP server used below).
- A Mongo MCP server connected to BlazeMeter's main and bigdata clusters (server name varies by install — e.g. `mongodb-production` / `mongodb-bigdata-production` — this skill refers to them generically as "main Mongo" / "bigdata Mongo").
- `gcloud` CLI installed and authenticated (`gcloud auth list`) for the session artifact fetches in Phase 1.

If any of these aren't available for the requested environment, say so plainly per the Step 0 table below rather than silently skipping a phase.

## Required inputs — ask if not given

- One or more **master IDs** to investigate.
- The **environment** they ran in: `denv`, `bzdev`, `ci`, `staging`, or `prod`. Don't guess this — it determines which OpenSearch index and Mongo connections are even reachable (see Step 0).
- Ideally, **at least one comparable master that did *not* exhibit the problem**. If not provided, ask for one before going deep — see Phase 4.

## Step 0 — Preflight: check what's actually available for this environment

Do not assume prod-level access works everywhere. Verify against this table before starting, and say plainly which legs are unavailable for the given environment rather than silently skipping a phase or guessing from an empty result:

| Env | OpenSearch | Mongo (main) | Mongo (bigdata) |
|---|---|---|---|
| **prod** | available | available | available |
| **denv** | available (shared index across all developers, not scoped to one user) | available via a Mongo MCP server, but depends on a live `kubectl port-forward` — verify it's actually up, don't assume | not configured |
| **bzdev** | available, but log shipping has been stopped since 2026-07-05 — flag this if bzdev is selected and results look sparse | not configured | not configured |
| **staging** | available | not configured | not configured |
| **ci** | available | not configured | not configured |

- Ping OpenSearch for the given env first (`mcp__opensearch-reader__ping`, from the `opensearch` plugin). If it fails, report that and stop rather than searching further with no results.
- If Mongo access is needed for the given env and isn't configured, say so explicitly — don't skip Phase 2 quietly.
- **Artifact files can often be fetched directly via `gcloud storage` — try this before asking the user.** Session artifacts live at `gs://blazemeter-gcp/masters/<masterId>/sessions/<sessionId>/`. Two things have to hold for this to work, and neither is guaranteed — check both explicitly, don't assume:
  - **A valid, non-expired `gcloud` auth session.** Check with `gcloud auth list`. If it's expired, you cannot refresh it yourself (`gcloud auth login` is interactive) — ask the user to run `gcloud auth login` themselves, then retry.
  - **IAM read access to the `blazemeter-gcp` bucket for that identity.** Valid auth doesn't imply this. Confirm with `gcloud storage ls gs://blazemeter-gcp/masters/<masterId>/` before assuming either way.
  - You need the **session ID**, not just the master ID, to build the full path — `gcloud storage ls .../masters/<masterId>/sessions/` to get it, or pull it from the main Mongo `sessions` collection.
  - `bzt.log`, `jmeter.log`, `jmeter.err`/`jmeter.out`, `effective.json`/`effective.yml`, `merged.json`/`merged.yml`, the test's raw/modified JMX (or scenario) file, `artifacts.zip`, and `admin-artifacts.zip` sit directly at that session path.
  - `cloud-launcher.log`, `atop.log`/`atop.binlog`, `atop-launcher.log`, `jetpack.log`, `jetpack-download.log`, `process-cleanup.log`, and the effective/merged config are bundled *inside* `admin-artifacts.zip` — download and unzip it; don't expect them at the top level.
  - `network_checking.log` was empirically confirmed absent for at least one real session — its absence is expected sometimes, not a sign the fetch is broken.
  - **If `gcloud storage` access genuinely isn't available** (no auth, no IAM permission even after a fresh login, or the environment doesn't map to this bucket), fall back to asking the user for the files via the BZA UI/API. Don't block the investigation on it, but don't skip trying the direct fetch first either.
  - **A missing session artifact folder is itself a finding, not just a dead end** — a session that never uploaded any artifact folder usually means it never got far enough to run (died during provisioning/bootstrap). Cross-check against Mongo session records (Phase 2) rather than treating the empty listing as "nothing to investigate here."

## The flow

### Phase 0 — Understand intent before evidence
Read the test's own definition (JMX/YAML/scenario config — `effective.json`/`merged.json`, if included in the artifact bundle) for each master in question. Establish what's *supposed* to happen before looking at what did. Note anything customer/config-specific (private location, secrets, custom plugins, unusual scenario structure) that could be relevant.

### Phase 1 — Full per-session artifact set (fetch via `gcloud storage` per Step 0, fall back to asking the user)
Get the complete bundle, not just `bzt.log`:
- `bzt.log` — engine/Taurus orchestration log
- `jmeter.log`, `jmeter.err` / `jmeter.out` — JMeter's own internals (never skip these — they can show detail bzt.log doesn't, e.g. listener startup, property application, and JMeter's own timers/samplers stating their actual effective config directly — this is often the single most direct confirmation of a symptom available)
- `cloud-launcher.log` — pre-Taurus setup (proxy/secrets/env) — runs *before* bzt.log even starts; inside `admin-artifacts.zip`
- `network_checking.log` — network connectivity specifically, if present (it's on the "OK if missing" list in taurus-cloud's own config, and has been empirically confirmed absent on at least one real session — check for it, don't assume either way)
- `atop.log` / `atop.binlog` — OS-level resource monitor (CPU/mem/disk/network over time); inside `admin-artifacts.zip`; has a known code-level reliability caveat (a `TODO: BUG` comment sits right next to where it's started) — treat as supporting evidence, not a sole source
- `effective.json` / `effective.yml`, `merged.json` / `merged.yml` — the actual applied test config (see Phase 0) — sit at the top level of the session folder, and are also duplicated inside `admin-artifacts.zip`
- Note `artifacts.zip` and `admin-artifacts.zip` are two *separate* bundles — customer-facing vs. admin/diagnostic (atop and cloud-launcher.log live in the admin one, unzip it to reach them)
- **When a theory depends on *when* something was uploaded/written to cloud storage, check the object's own storage metadata (`gcloud storage ls -L <path>` — Creation/Update Time), not just what the log file's content narrates.** A log's content describes what the process did locally and can be written well before (or, via buffering, after) the data actually left the machine — the two timestamps can genuinely disagree, and only the storage metadata tells you when the upload really happened.

### Phase 2 — Database state (subject to the Step 0 table)
- Main Mongo: session/master records — status transitions, timestamps, config as actually stored. Master documents live in the `masterSessions` collection keyed by `_id`; session documents live in the `sessions` collection with a `master` field (not `masterId`) pointing back to it — check field names before assuming.
- Big-data Mongo: engine-health telemetry / metrics — supporting signal, not primary evidence
- **Run a fleet-wide aggregate before picking sessions to sample.** For any "why did some sessions behave differently" question, compute the discriminating metric (e.g. `lastPingTime - lastSampleTime`, `ended - lastSampleTime`, or presence/absence of `lastSampleTime` at all) across *every* session of the master in one query, not a hand-picked subset. A rare failure mode can affect only a small percentage of a large fleet — a sample of 20 "representative" sessions can miss all of them and produce a confident, wrong conclusion. Bucket the metric to see the shape (bimodal? one outlier? a spread?) before fetching a single log file.
- **Prefer a field that was designed to answer your exact question over inferring from behavior.** "Was this manually terminated?" has a direct answer on the Master model (`terminateWorkersExecuted`) plus corroborating fields (`Session.endedSource`, the `masterCommandRequests` collection) — check those first rather than building a case from timing/behavior that could be explained several ways.
- For batch/group-level provisioning or termination questions, the `instances` collection's `tags.batchId` (join key), `tags.name` (session id), and `raw.StateReason`/`raw.StateTransitionReason` (cloud-provider-reported shutdown cause) let you reconstruct exactly which sessions were provisioned/torn down together, in which AZ/zone, and whether the provider itself reports it as a manual/API-initiated shutdown vs. a crash — useful for confirming or refuting a "one slow member held up its whole group" theory, or a "batch was wrongly killed" theory, with real data instead of code-reading alone.

### Phase 3 — Centralized log search (OpenSearch, subject to the Step 0 table)
Cross-reference backend job/worker logs and ingress/network logs against Phase 1/2 findings, timestamp-correlated. Check retention coverage for the actual dates in question (list indices / check date coverage) before treating an empty result as "nothing happened" — a coverage gap and a real absence look identical in a raw search result.

**Never treat a timing coincidence as evidence — go check the logs for an actual event.** If a hypothesis rests on "X happened right around when Y was reported," that's a hypothesis to verify, not a conclusion to report. Run a broadened, unfiltered log search scoped to the specific session/master ID for the exact window in question; a narrowly-worded query that returns zero hits can mean "didn't happen," "wrong search terms," or "logged at a level/index that isn't shipped here" — indistinguishable without broadening the query first, and worth saying explicitly which of these it is once you've broadened and still get nothing.

**The onset-vs-resolution signature: when several independent things resolve together, check whether they also *started* together.** If N items enter a bad state at spread-out times but all recover/resolve within a tight window regardless of when each one started, that shape is only possible if something external and shared changed at one moment — it rules out each item independently hitting its own fixed-length timeout (which would keep the same spread, just shifted later). Conversely, if N items are created at the *same* moment and all resolve (or get killed) at the *same* moment shortly after, that's the signature of one shared batch decision, not N independent outcomes — reconstruct the batch (Phase 2) rather than treating each as its own case. This lets you distinguish "one shared external trigger" from "N unrelated timeouts" directly from timestamps, even when you can't find the trigger itself. Conversely, if resolution spread matches onset spread (offset by a roughly constant duration), that points to a per-item timeout instead.

### Phase 4 — Control sample
Repeat Phases 1–3 for at least one comparable case that did **not** exhibit the problem. A signal present in both the failing and working case isn't the differentiator — no matter how damning it looks when only the failing cases are compared to each other.

### Phase 5 — Verify against code, to interpret — not to originate
Once Phases 1–4 produce concrete signals (a log line, a metric, a timestamp gap), read the actual source (across the relevant repos — taurus, taurus-cloud, a.blazemeter.com, bzm-crane) to confirm what each one really means and where it really comes from. Code answers "what does this evidence actually tell me" — it is not where the theory should start.

If the theory involves engines being grouped/provisioned/torn down in batches, check the cloud provider's actual configured batch/group size (the relevant `*Settings.php`) rather than assuming one size fits all providers — it varies significantly (e.g. one session per group on one provider vs. 100+ per group on another) and directly changes the blast radius of a single misbehaving session. If a.blazemeter.com is one of the repos in play, its `.claude/master-session-lifecycle.md` (when present) documents exactly how batches finalize and terminate, including a known "batch-gating" blind spot — check it before re-deriving the termination logic from scratch.

### Phase 6 — Report confirmed vs. inferred, explicitly
State which conclusions are directly evidenced (with cross-referenced timestamps/sources) versus inferred by analogy from a similar-looking case. Don't upgrade "inferred" to "confirmed" without new evidence. When something earlier turns out wrong, say so plainly and revisit anything already built on it (a shipped fix, a posted comment, a sent message) — state whether it still applies, partially applies, or doesn't apply at all. Explicitly call out any pass/fail status the platform itself reported (e.g. a master marked "pass") if the evidence contradicts it — a status field lagging or missing the real symptom is itself a finding worth stating, not something to quietly work around.

## Common mistakes (from MOB-52978, don't repeat these)

- Checking only whichever log/tool is already loaded, instead of the most direct evidence for the specific claim.
- Treating a retention/coverage gap as "nothing happened."
- Assuming a resource/infra explanation (CPU, memory, "probably their network") without checking real telemetry.
- Assuming a recurring log pattern is a retry mechanism without reading the code that actually drives it.
- Not getting the artifact files up front (via `gcloud storage` or, failing that, from the user) — discovering that gap mid-investigation instead.
- Skipping the control/comparison sample and comparing only failing cases to each other.
- Letting a shipped fix or posted conclusion stand unqualified once the real cause turns out to be something else.
- Sampling a handful of sessions and generalizing, instead of running the discriminating check across the whole fleet first — a rare failure mode can hide entirely outside a "representative" sample.
- Treating a suspicious timing coincidence as the cause without directly querying logs for an actual triggering event in that window.
- Trusting a log file's own narrated timestamps for an upload/write-to-cloud-storage claim instead of checking the storage object's real metadata.
- Building a "was this manual/automated" conclusion from behavior/timing when a purpose-built field or record (a status flag, a command-log collection) can answer it directly.
- Trusting the platform's own reported status (e.g. "pass") as proof nothing went wrong — a status field and the underlying delivered behavior can diverge; verify the metric the status is supposedly summarizing.

## Related

- `opensearch` plugin (same marketplace) — provides the `opensearch-reader` MCP server this skill's Phase 3 depends on.
