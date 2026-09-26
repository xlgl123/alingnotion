#!/usr/bin/env bash
set -euo pipefail

package_path="/home/ubuntu/aling-notion-mcp-20260721.tar.gz"
package_sha256="d82f97c2d8df3233e60e16768b881edc1ad50d40c4e5bbcc99eb0125500baf09"
install_dir="/opt/notion-mcp"
state_dir="/var/lib/notion-mcp"
env_path="/etc/notion-mcp.env"
unit_path="/etc/systemd/system/notion-mcp.service"

IFS= read -r notion_token
if [[ -z "${notion_token}" ]]; then
  echo "NOTION_TOKEN input is empty" >&2
  exit 1
fi

echo "${package_sha256}  ${package_path}" | sha256sum -c -

if ! getent passwd notion-mcp >/dev/null; then
  sudo -n useradd \
    --system \
    --home-dir /nonexistent \
    --shell /usr/sbin/nologin \
    --user-group \
    notion-mcp
fi

sudo -n install -d -o root -g root -m 0755 "${install_dir}"
sudo -n tar -xzf "${package_path}" -C "${install_dir}"
sudo -n install -d -o notion-mcp -g notion-mcp -m 0700 "${state_dir}"

sudo -n python3 -m venv "${install_dir}/.venv"
sudo -n "${install_dir}/.venv/bin/pip" install --no-cache-dir -r "${install_dir}/requirements.txt"
sudo -n "${install_dir}/.venv/bin/pip" install --no-cache-dir --no-deps "${install_dir}"

mcp_token=$(sudo -n "${install_dir}/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')
env_tmp=$(mktemp)
cleanup() {
  rm -f "${env_tmp}"
}
trap cleanup EXIT

{
  printf 'NOTION_TOKEN=%s\n' "${notion_token}"
  printf 'MCP_ACCESS_TOKEN=%s\n' "${mcp_token}"
  printf 'MCP_ALLOW_UNAUTHENTICATED=false\n'
  printf 'NOTION_VERSION=2026-03-11\n'
  printf 'DIARY_DATA_SOURCE_ID=%s\n' "${DIARY_DATA_SOURCE_ID:?Set DIARY_DATA_SOURCE_ID}"
  printf 'TZ=Asia/Shanghai\n'
  printf 'NOTION_MCP_HOST=127.0.0.1\n'
  printf 'NOTION_MCP_PORT=8091\n'
  printf 'NOTION_MCP_PUBLIC_HOST=notion.example.com\n'
  printf 'NOTION_MCP_ALLOWED_ORIGINS=https://notion.example.com\n'
  printf 'CLAUDE_MCP_UNAUTHENTICATED_CIDRS=160.79.104.0/21\n'
  printf 'SEARCH_DB_PATH=/var/lib/notion-mcp/search.db\n'
  printf 'SEARCH_REFRESH_LIMIT=200\n'
} >"${env_tmp}"

sudo -n install -o root -g root -m 0600 "${env_tmp}" "${env_path}"
sudo -n install -o root -g root -m 0644 "${install_dir}/deploy/notion-mcp.service" "${unit_path}"
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now notion-mcp.service

unauthorized_status="000"
for _ in $(seq 1 20); do
  unauthorized_status=$(curl -sS -o /dev/null -w '%{http_code}' \
    -X POST http://127.0.0.1:8091/mcp \
    -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"deploy-check","version":"1.0"}}}' || true)
  if [[ "${unauthorized_status}" == "401" ]]; then
    break
  fi
  sleep 1
done

sudo -n systemctl is-active --quiet notion-mcp.service
if [[ "${unauthorized_status}" != "401" ]]; then
  echo "Expected unauthenticated /mcp status 401, got ${unauthorized_status}" >&2
  exit 1
fi

initialize_response=$(curl -fsS \
  -X POST http://127.0.0.1:8091/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H "Authorization: Bearer ${mcp_token}" \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"deploy-check","version":"1.0"}}}')
if ! grep -q 'Aling Notion' <<<"${initialize_response}"; then
  echo "Authenticated MCP initialize check failed" >&2
  exit 1
fi

echo "LOCAL_MCP_OK"
