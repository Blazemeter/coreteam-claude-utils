#!/usr/bin/env bash
# PreToolUse hook for Bash — blocks always-destructive `gcloud storage`
# operations (rm, mv) against the session-artifact bucket this skill reads
# from. Read-only calls (ls, ls -L, cp <gs://...> <local>) are unaffected —
# they're intentionally left to the normal interactive permission prompt
# instead (see policy/allowed-tools.yaml's exceptions entry for this skill):
# `cp`'s direction depends on argument position, which a hook here can check
# but a Bash(pattern*) allowed-tools entry cannot, so this hook only takes
# the unconditionally-destructive verbs off the table rather than trying to
# also arbitrate `cp` direction.
#
# Why: base-tools' own hooks cover `gcloud compute` mutations and
# DynamoDB/S3/Redis/Mongo writes, but explicitly NOT `gcloud storage` (see
# block-ec2-cloud-mutations.sh's own comment) — this plugin fetches session
# artifacts from a shared GCS bucket and needs its own backstop rather than
# assuming base-tools is installed alongside it.
#
# Matches `gcloud storage rm|mv` anywhere in the command string (not just as
# a prefix), so an appended/chained command (`gcloud storage ls ...; gcloud
# storage rm ...`) is still caught — a plain allowed-tools prefix match can't
# do this, which is exactly why this needs to be a hook and not a policy entry.
#
# Exit 2 = block. Honors a HUMAN-exported CLAUDE_SAFETY_OVERRIDE=1 (read from
# this hook's own environment — Claude inlining the var as a command prefix
# does NOT set it here, so it cannot self-bypass), same convention as
# base-tools/hooks/block-ec2-cloud-mutations.sh.

set -euo pipefail

LOG_DIR="${CLAUDE_PLUGIN_DATA:-${TMPDIR:-/tmp}}/master-investigation"
mkdir -p "$LOG_DIR"

payload="$(cat)"
cmd="$(echo "$payload" | jq -r '.tool_input.command // ""')"

if [ "${CLAUDE_SAFETY_OVERRIDE:-0}" = "1" ]; then
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[$ts] block-gcs-destructive-ops OVERRIDE: $cmd" >> "$LOG_DIR/safety-override.log"
  exit 0
fi

if [[ "$cmd" =~ gcloud[[:space:]]+storage[[:space:]]+(rm|mv)([[:space:]]|$) ]]; then
  echo "claude-base SAFETY guardrail: gcloud storage rm/mv blocked." >&2
  echo "" >&2
  echo "investigate-master only ever needs to READ session artifacts from" >&2
  echo "gs://blazemeter-gcp — deleting or moving objects in that bucket needs" >&2
  echo "a human. ls / ls -L / cp (fetching a copy locally) are unaffected." >&2
  echo "" >&2
  echo "Ask a human to run it, or — if you ARE the human — export" >&2
  echo "CLAUDE_SAFETY_OVERRIDE=1 in your shell for this session (logged &" >&2
  echo "audited). Do NOT inline it as a command prefix and do NOT try to" >&2
  echo "bypass this hook." >&2
  exit 2
fi

exit 0
