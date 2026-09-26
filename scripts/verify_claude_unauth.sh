#!/usr/bin/env bash
set -euo pipefail

ordinary_status=$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST http://127.0.0.1:8091/mcp \
  -H 'Content-Type: application/json' \
  --data '{}')
if [[ "${ordinary_status}" != "401" ]]; then
  echo "Expected ordinary unauthenticated status 401, got ${ordinary_status}" >&2
  exit 1
fi

claude_initialize=$(curl -fsS \
  -X POST http://127.0.0.1:8091/mcp \
  -H 'Host: notion.example.com' \
  -H 'CF-Connecting-IP: 160.79.104.42' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"claude-network-check","version":"1.0"}}}')
if ! grep -q 'Aling Notion' <<<"${claude_initialize}"; then
  echo "Claude network initialize check failed" >&2
  exit 1
fi

claude_tools=$(curl -fsS \
  -X POST http://127.0.0.1:8091/mcp \
  -H 'Host: notion.example.com' \
  -H 'CF-Connecting-IP: 160.79.104.42' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')
tool_count=$(python3 -c 'import json, sys; print(len(json.load(sys.stdin)["result"]["tools"]))' <<<"${claude_tools}")
if [[ "${tool_count}" != "8" ]]; then
  echo "Expected 8 tools, got ${tool_count}" >&2
  exit 1
fi

echo "ORDINARY_AUTH_OK status=${ordinary_status}"
echo "CLAUDE_UNAUTH_OK tools=${tool_count}"
