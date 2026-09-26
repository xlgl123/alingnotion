#!/usr/bin/env bash
set -euo pipefail

service_url="${MCP_VERIFY_URL:-http://127.0.0.1:8091/mcp}"
public_host="${NOTION_MCP_PUBLIC_HOST:?Set NOTION_MCP_PUBLIC_HOST}"
claude_test_ip="${CLAUDE_MCP_TEST_IP:?Set CLAUDE_MCP_TEST_IP to an address inside the explicitly configured trusted CIDR}"

ordinary_status=$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST "${service_url}" \
  -H 'Content-Type: application/json' \
  --data '{}')
if [[ "${ordinary_status}" != "401" ]]; then
  echo "Expected ordinary unauthenticated status 401, got ${ordinary_status}" >&2
  exit 1
fi

claude_initialize=$(curl -fsS \
  -X POST "${service_url}" \
  -H "Host: ${public_host}" \
  -H "CF-Connecting-IP: ${claude_test_ip}" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"claude-network-check","version":"1.0"}}}')
if ! grep -q 'Aling Notion' <<<"${claude_initialize}"; then
  echo "Claude network initialize check failed" >&2
  exit 1
fi

claude_tools=$(curl -fsS \
  -X POST "${service_url}" \
  -H "Host: ${public_host}" \
  -H "CF-Connecting-IP: ${claude_test_ip}" \
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
