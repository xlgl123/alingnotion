#!/usr/bin/env bash
set -euo pipefail

token_path="/etc/cloudflared/notion-mcp.token"
unit_path="/etc/systemd/system/notion-mcp-cloudflared.service"

IFS= read -r tunnel_token
tunnel_token=${tunnel_token%$'\r'}
if [[ ! "${tunnel_token}" =~ ^eyJ[A-Za-z0-9_-]+$ ]]; then
  echo "Invalid Cloudflare Tunnel token input" >&2
  exit 1
fi

token_tmp=$(mktemp)
unit_tmp=$(mktemp)
cleanup() {
  rm -f "${token_tmp}" "${unit_tmp}"
}
trap cleanup EXIT

printf '%s\n' "${tunnel_token}" >"${token_tmp}"
cat >"${unit_tmp}" <<'UNIT'
[Unit]
Description=Cloudflare Tunnel for Aling Notion MCP
Documentation=https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
Wants=network-online.target
After=network-online.target notion-mcp.service

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate --metrics 127.0.0.1:20244 run --token-file /etc/cloudflared/notion-mcp.token
Restart=on-failure
RestartSec=5s
TimeoutStopSec=20s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
AmbientCapabilities=
SystemCallArchitectures=native
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT

sudo -n install -d -o root -g root -m 0755 /etc/cloudflared
sudo -n install -o root -g root -m 0600 "${token_tmp}" "${token_path}"
sudo -n install -o root -g root -m 0644 "${unit_tmp}" "${unit_path}"
sudo -n systemctl daemon-reload
sudo -n systemctl enable --now notion-mcp-cloudflared.service

for _ in $(seq 1 30); do
  if sudo -n systemctl is-active --quiet notion-mcp-cloudflared.service; then
    break
  fi
  sleep 1
done

sudo -n systemctl is-active --quiet notion-mcp-cloudflared.service
echo "TUNNEL_SERVICE_OK"
