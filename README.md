# Aling Notion MCP

面向使用者个人 Notion 工作区的精简 MCP 服务。它只暴露 8 个工具：

- `write_diary`
- `search_memory`
- `read_page`
- `fetch_recent_diary`
- `create_page`
- `update_page`
- `query_database`
- `append_content`

传输使用无状态 Streamable HTTP，入口为 `POST /mcp`，不提供旧 SSE。

完整设计见 [实施方案](outputs/notion-mcp-implementation-plan.md)。

## 本地运行

Python 依赖应安装到 F 盘虚拟环境，避免在 C 盘写入依赖缓存：

```powershell
python -m venv F:\Codex\venvs\notion-mcp
$env:PIP_CACHE_DIR = 'F:\Codex\pip-cache'
F:\Codex\venvs\notion-mcp\Scripts\python.exe -m pip install -e ".[test]"
```

设置环境变量后运行：

```powershell
$env:NOTION_TOKEN = '...'
$env:MCP_ACCESS_TOKEN = '...'
F:\Codex\venvs\notion-mcp\Scripts\aling-notion-mcp.exe
```

密钥不得写入 `.env`、源码、测试或日志。部署联调完成后应轮换聊天中曾出现过的 Notion 密钥。

## 安全默认值

- MCP 默认必须使用 `Authorization: Bearer ...`，`MCP_ALLOW_UNAUTHENTICATED` 保持为 `false`。
- `CLAUDE_MCP_UNAUTHENTICATED_CIDRS` 默认为空，不会自动信任任何公网网段。确需放行代理来源时，应在部署环境中显式设置，并先核对服务方公布的最新 CIDR。
- `scripts/deploy_claude_unauth.sh` 不再内置网段、验证 IP、域名、安装包路径或校验和；调用者必须通过环境变量提供这些值。
- `scripts/deploy_global_unauth.sh` 会默认拒绝执行。只有显式设置 `CONFIRM_GLOBAL_UNAUTHENTICATED=I_UNDERSTAND_THIS_MAKES_MCP_PUBLIC` 才能关闭鉴权。
- `PACKAGE_PATH`、`PACKAGE_SHA256` 与 `NOTION_MCP_PUBLIC_HOST` 是服务器安装脚本的必填变量；安装目录、状态目录和配置路径可分别通过 `INSTALL_DIR`、`STATE_DIR`、`ENV_PATH` 覆盖。

生产环境优先保持 Bearer Token 鉴权。若必须启用基于代理来源网段的例外，应同时确保应用只监听回环地址，且只有受控反向代理能访问应用端口。

## 已知 Notion 限制

当前 Notion API `2026-03-11` 会返回 `Place` 属性，但不支持通过公开 API 写入 Place 值。因此 `write_diary(place=...)` 会明确返回不支持错误，不会静默忽略。

