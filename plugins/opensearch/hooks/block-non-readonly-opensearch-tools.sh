#!/usr/bin/env bash
# PreToolUse hook — enforces that only approved read-only OpenSearch MCP tools are called.
# Receives tool call JSON on stdin; exits 0 to allow, non-zero to block.

TOOL=$(python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)

ALLOWED=(
  "mcp__opensearch-reader__ping"
  "mcp__opensearch-reader__list_indices"
  "mcp__opensearch-reader__search_logs"
)

for allowed in "${ALLOWED[@]}"; do
  [[ "$TOOL" == "$allowed" ]] && exit 0
done

echo "BLOCKED: '$TOOL' is not in the approved read-only OpenSearch MCP tool list." >&2
echo "Only read/search operations are permitted. To add a new read tool, update hooks/block-non-readonly-opensearch-tools.sh and hooks.json." >&2
exit 2
