#!/usr/bin/env bash
set -euo pipefail

package_path="${PACKAGE_PATH:?Set PACKAGE_PATH to the release archive}"
package_sha256="${PACKAGE_SHA256:?Set PACKAGE_SHA256 to the release archive checksum}"
install_dir="${INSTALL_DIR:-/opt/notion-mcp}"
env_path="${ENV_PATH:-/etc/notion-mcp.env}"
service_url="${MCP_VERIFY_URL:-http://127.0.0.1:8091/mcp}"
public_host="${NOTION_MCP_PUBLIC_HOST:?Set NOTION_MCP_PUBLIC_HOST}"
claude_cidrs="${CLAUDE_MCP_UNAUTHENTICATED_CIDRS:?Set CLAUDE_MCP_UNAUTHENTICATED_CIDRS explicitly}"
claude_test_ip="${CLAUDE_MCP_TEST_IP:?Set CLAUDE_MCP_TEST_IP to an address inside the trusted CIDR}"

echo "${package_sha256}  ${package_path}" | sha256sum -c -
sudo -n tar -xzf "${package_path}" -C "${install_dir}"

env_tmp=$(mktemp)
cleanup() {
  rm -f "${env_tmp}"
}
trap cleanup EXIT
sudo -n awk -v cidrs="${claude_cidrs}" '
  BEGIN { found = 0 }
  /^CLAUDE_MCP_UNAUTHENTICATED_CIDRS=/ { print "CLAUDE_MCP_UNAUTHENTICATED_CIDRS=" cidrs; found = 1; next }
  { print }
  END { if (!found) print "CLAUDE_MCP_UNAUTHENTICATED_CIDRS=" cidrs }
' "${env_path}" >"${env_tmp}"
sudo -n install -o root -g root -m 0600 "${env_tmp}" "${env_path}"

sudo -n "${install_dir}/.venv/bin/pip" install --no-cache-dir --no-deps "${install_dir}"
sudo -n systemctl restart notion-mcp.service

unauthorized_status="000"
for _ in $(seq 1 20); do
  unauthorized_status=$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST "${service_url}" \
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
  -X POST "${service_url}" \
  -H "Host: ${public_host}" \
  -H "CF-Connecting-IP: ${claude_test_ip}" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"claude-network-check","version":"1.0"}}}')
if ! grep -q 'Aling Notion' <<<"${claude_response}"; then
  echo "Claude network unauthenticated initialize check failed" >&2
  exit 1
fi

echo "CLAUDE_UNAUTH_DEPLOY_OK"
