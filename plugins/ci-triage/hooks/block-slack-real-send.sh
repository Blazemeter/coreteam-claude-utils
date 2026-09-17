#!/usr/bin/env bash
# PreToolUse hook — hard backstop for ci-culprit-check's "never sends a Slack
# message on its own" promise. Blocks the two real-send Slack tools; drafts
# and all read/search tools pass through untouched.

TOOL=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)

BLOCKED=(
  "mcp__claude_ai_Slack__slack_send_message"
  "mcp__claude_ai_Slack__slack_schedule_message"
)

for blocked in "${BLOCKED[@]}"; do
  if [[ "$TOOL" == "$blocked" ]]; then
    echo "BLOCKED: '$TOOL' sends a real Slack message. ci-culprit-check must only ever draft (slack_send_message_draft) and let a human send it." >&2
    exit 2
  fi
done

exit 0
