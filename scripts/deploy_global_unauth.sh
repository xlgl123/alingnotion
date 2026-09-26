#!/usr/bin/env bash
set -euo pipefail

package_path="/home/ubuntu/aling-notion-mcp-global-unauth-20260722.tar.gz"
package_sha256="efd656b93f74de643437e46c97b68f1b18cf1732ed286482bc75d1ca4289959c"
install_dir="/opt/notion-mcp"
env_path="/etc/notion-mcp.env"

echo "${package_sha256}  ${package_path}" | sha256sum -c -
sudo -n tar -xzf "${package_path}" -C "${install_dir}"

env_tmp=$(mktemp)
cleanup() {
  rm -f "${env_tmp}"
}
trap cleanup EXIT
sudo -n awk '
  BEGIN { found = 0 }
  /^MCP_ALLOW_UNAUTHENTICATED=/ { print "MCP_ALLOW_UNAUTHENTICATED=true"; found = 1; next }
  { print }
  END { if (!found) print "MCP_ALLOW_UNAUTHENTICATED=true" }
' "${env_path}" >"${env_tmp}"
sudo -n install -o root -g root -m 0600 "${env_tmp}" "${env_path}"

sudo -n "${install_dir}/.venv/bin/pip" install --no-cache-dir --no-deps "${install_dir}"
sudo -n systemctl restart notion-mcp.service

initialize_response=""
for _ in $(seq 1 20); do
  initialize_response=$(curl -fsS \
    -X POST http://127.0.0.1:8091/mcp \
    -H 'Host: notion.example.com' \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"global-unauth-check","version":"1.0"}}}' 2>/dev/null || true)
  if grep -q 'Aling Notion' <<<"${initialize_response}"; then
    break
  fi
  sleep 1
done
sudo -n systemctl is-active --quiet notion-mcp.service
if ! grep -q 'Aling Notion' <<<"${initialize_response}"; then
  echo "Global unauthenticated initialize check failed" >&2
  exit 1
fi

invalid_host_status=$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST http://127.0.0.1:8091/mcp \
  -H 'Host: evil.test' \
  -H 'Content-Type: application/json' \
  --data '{}')
if [[ "${invalid_host_status}" != "421" ]]; then
  echo "Expected invalid Host status 421, got ${invalid_host_status}" >&2
  exit 1
fi

echo "GLOBAL_UNAUTH_DEPLOY_OK"
