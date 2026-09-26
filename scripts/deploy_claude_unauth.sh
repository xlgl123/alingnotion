#!/usr/bin/env bash
set -euo pipefail

package_path="/home/ubuntu/aling-notion-mcp-claude-20260722.tar.gz"
package_sha256="85bfdab2f92c47271dcfb184bb1e03f266c3ea7c54ece0a3024a58dac429ed8d"
install_dir="/opt/notion-mcp"
env_path="/etc/notion-mcp.env"

echo "${package_sha256}  ${package_path}" | sha256sum -c -
sudo -n tar -xzf "${package_path}" -C "${install_dir}"

if ! sudo -n grep -q '^CLAUDE_MCP_UNAUTHENTICATED_CIDRS=' "${env_path}"; then
  printf '%s\n' 'CLAUDE_MCP_UNAUTHENTICATED_CIDRS=160.79.104.0/21' | sudo -n tee -a "${env_path}" >/dev/null
fi
sudo -n chown root:root "${env_path}"
sudo -n chmod 0600 "${env_path}"

sudo -n "${install_dir}/.venv/bin/pip" install --no-cache-dir --no-deps "${install_dir}"
sudo -n systemctl restart notion-mcp.service

unauthorized_status="000"
for _ in $(seq 1 20); do
  unauthorized_status=$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST http://127.0.0.1:8091/mcp \
    -H 'Content-Type: application/json' \
    --data '{}' || true)
  if [[ "${unauthorized_status}" == "401" ]]; then
    break
  fi
  sleep 1
done
sudo -n systemctl is-active --quiet notion-mcp.service

if [[ "${unauthorized_status}" != "401" ]]; then
  echo "Expected ordinary unauthenticated status 401, got ${unauthorized_status}" >&2
  exit 1
fi

claude_response=$(curl -fsS \
  -X POST http://127.0.0.1:8091/mcp \
  -H 'Host: notion.example.com' \
  -H 'CF-Connecting-IP: 160.79.104.42' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"claude-network-check","version":"1.0"}}}')
if ! grep -q 'Aling Notion' <<<"${claude_response}"; then
  echo "Claude network unauthenticated initialize check failed" >&2
  exit 1
fi

echo "CLAUDE_UNAUTH_DEPLOY_OK"
