#!/usr/bin/env bash
set -euo pipefail

if [[ "${CONFIRM_GLOBAL_UNAUTHENTICATED:-}" != "I_UNDERSTAND_THIS_MAKES_MCP_PUBLIC" ]]; then
  echo "Refusing to disable MCP authentication. Set CONFIRM_GLOBAL_UNAUTHENTICATED=I_UNDERSTAND_THIS_MAKES_MCP_PUBLIC to continue." >&2
  exit 2
fi

package_path="${PACKAGE_PATH:?Set PACKAGE_PATH to the release archive}"
package_sha256="${PACKAGE_SHA256:?Set PACKAGE_SHA256 to the release archive checksum}"
install_dir="${INSTALL_DIR:-/opt/notion-mcp}"
env_path="${ENV_PATH:-/etc/notion-mcp.env}"
service_url="${MCP_VERIFY_URL:-http://127.0.0.1:8091/mcp}"
public_host="${NOTION_MCP_PUBLIC_HOST:?Set NOTION_MCP_PUBLIC_HOST}"

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
    -X POST "${service_url}" \
    -H "Host: ${public_host}" \
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
  -X POST "${service_url}" \
  -H 'Host: evil.test' \
  -H 'Content-Type: application/json' \
  --data '{}')
if [[ "${invalid_host_status}" != "421" ]]; then
  echo "Expected invalid Host status 421, got ${invalid_host_status}" >&2
  exit 1
fi

echo "GLOBAL_UNAUTH_DEPLOY_OK"
