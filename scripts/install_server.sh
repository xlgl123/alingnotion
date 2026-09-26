#!/usr/bin/env bash
set -euo pipefail

package_path="${PACKAGE_PATH:?Set PACKAGE_PATH to the release archive}"
package_sha256="${PACKAGE_SHA256:?Set PACKAGE_SHA256 to the release archive checksum}"
install_dir="${INSTALL_DIR:-/opt/notion-mcp}"
state_dir="${STATE_DIR:-/var/lib/notion-mcp}"
env_path="${ENV_PATH:-/etc/notion-mcp.env}"
unit_path="${UNIT_PATH:-/etc/systemd/system/notion-mcp.service}"
public_host="${NOTION_MCP_PUBLIC_HOST:?Set NOTION_MCP_PUBLIC_HOST}"
allowed_origins="${NOTION_MCP_ALLOWED_ORIGINS:-https://${public_host}}"
claude_cidrs="${CLAUDE_MCP_UNAUTHENTICATED_CIDRS:-}"

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
unit_tmp=$(mktemp)
cleanup() {
  rm -f "${env_tmp}" "${unit_tmp}"
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
  printf 'NOTION_MCP_PUBLIC_HOST=%s\n' "${public_host}"
  printf 'NOTION_MCP_ALLOWED_ORIGINS=%s\n' "${allowed_origins}"
  printf 'CLAUDE_MCP_UNAUTHENTICATED_CIDRS=%s\n' "${claude_cidrs}"
  printf 'SEARCH_DB_PATH=%s/search.db\n' "${state_dir}"
  printf 'SEARCH_REFRESH_LIMIT=200\n'
} >"${env_tmp}"

python3 - "${install_dir}/deploy/notion-mcp.service" "${unit_tmp}" "${install_dir}" "${env_path}" "${state_dir}" <<'PY'
from pathlib import Path
import sys

template_path, output_path, install_dir, env_path, state_dir = sys.argv[1:]
content = Path(template_path).read_text(encoding="utf-8")
content = content.replace("__INSTALL_DIR__", install_dir)
content = content.replace("__ENV_PATH__", env_path)
content = content.replace("__STATE_DIR__", state_dir)
Path(output_path).write_text(content, encoding="utf-8")
PY

sudo -n install -o root -g root -m 0600 "${env_tmp}" "${env_path}"
sudo -n install -o root -g root -m 0644 "${unit_tmp}" "${unit_path}"
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
