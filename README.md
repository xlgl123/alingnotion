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

## 已知 Notion 限制

当前 Notion API `2026-03-11` 会返回 `Place` 属性，但不支持通过公开 API 写入 Place 值。因此 `write_diary(place=...)` 会明确返回不支持错误，不会静默忽略。

