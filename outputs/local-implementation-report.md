# 精简版 Notion MCP 实施与部署报告

> 完成日期：2026-07-21  
> 当前阶段：服务器和 Cloudflare Tunnel 部署完成，公网只读验收通过  
> 数据安全：没有创建、修改或删除任何 Notion 内容

## 1. 交付结论

已按照《精简版 Notion MCP 服务完整实施方案》完成本地实现、服务器部署、Cloudflare Tunnel 发布和公网只读验收。

已实现且只暴露以下 8 个 MCP 工具：

1. `write_diary`
2. `search_memory`
3. `read_page`
4. `fetch_recent_diary`
5. `create_page`
6. `update_page`
7. `query_database`
8. `append_content`

传输为无状态 Streamable HTTP，单一入口 `POST /mcp`。旧 `/sse` 不存在。

## 2. 已完成的功能

### 日记

- 固定写入 Data Source `11111111-2222-4333-8444-555555555555`。
- `content` 是完整正文，`明日待办` 不单独拆参数。
- 支持现有日记使用的一级标题、二级标题、段落、分割线和待办区块。
- 支持通用三级标题、列表、引用和代码块。
- 默认生成上海当天日期和中文标题。
- 校验五个现有心情选项。
- 创建前检查同日期日记，默认拒绝重复创建。
- 页面创建成功但正文失败时返回 `PARTIAL_WRITE` 和页面 ID，不假装完整成功。
- 写入后重新读取页面和区块数量进行回验。

### 搜索与读取

- 页面 ID 和 Notion URL 自动解析。
- Block 分页与子区块递归读取。
- 最近 N 天日记按 `日期 1` 和 Asia/Shanghai 自然日查询。
- SQLite 本地全文索引支持中文正文子串搜索。
- Notion 网络读取并发、本地 SQLite 写入串行，避免 `database is locked` 漏页。
- 索引只做可重建缓存，Notion 是唯一真实数据源。
- 索引刷新超过配置上限时明确返回 warning，不把不完整结果冒充完整结果。

### 通用编辑

- 在普通 Page 或 Data Source 下创建页面。
- Database 只有一个 Data Source 时自动解析；多个时拒绝猜测并要求明确指定。
- 按真实 Schema 编码 title、rich_text、select、status、date、checkbox、number、URL、关系等属性。
- 页面属性修改、Block 定点修改、正文追加和经确认后的全文替换。
- 全文替换必须传 `confirm_replace=true`。
- 支持 `expected_last_edited_time` 冲突检测。
- 不暴露页面永久删除、归档或 Schema 修改工具。

### 安全与运行

- MCP Access Token 与 Notion Token 分离。
- Bearer Token 使用恒定时间比较。
- 双层 Host / Origin 校验，防止 DNS rebinding。
- 服务实际只监听 `127.0.0.1:8091`。
- 非 `/mcp` 路径返回 404，非 POST 返回 405。
- 日志不记录 Authorization、Notion Token 或完整正文。
- 写操作只记录页面 ID、动作、日期和区块数量等元数据。
- 已部署 `notion-mcp.service` 和独立 `notion-mcp-cloudflared.service`，两者均为 `active`、`enabled`。
- Cloudflare Tunnel Token 和应用环境文件均为 `root:root 600`。

## 3. 已完成的验证

### 自动测试

最终结果：`33 passed`。

覆盖内容：

- ID/URL 解析
- 日记 Markdown 与 Block 转换
- 长文本 2000 字符安全分片
- 100 Block 分批追加
- 属性 Schema 编码和只读字段拒绝
- Place 不支持时明确报错
- Notion 分页、递归与错误脱敏
- 并发 Notion 请求的 request_id 完整收集
- 重复日期保护
- 部分写入如实返回
- 全文替换确认与编辑冲突
- 中文正文搜索
- SQLite 连接关闭与文件可清理
- 8 工具 Schema
- HTTP 鉴权、Host、Origin、单一端点
- MCP `initialize`、`tools/list`、`tools/call`

第三方 Starlette TestClient 有一条自身的弃用提示，不影响服务功能或测试结果。

### 真实 Notion 只读联调

已通过：

- 读取日记 Data Source 和 6 个真实字段。
- 查询最近 3 天日记，得到 2 篇现有记录。
- 读取最新页面完整结构，共 58 个顶层 Block。
- 在全新临时索引中刷新最近 20 篇日记，无页面刷新失败。
- 自动选择一个不在标题和属性中的正文片段，`search_memory` 成功以 `content` 命中。
- 测试过程没有打印所选私人正文片段。

### 真实本地 HTTP 端到端联调

已通过：

- 无 MCP Token 请求返回 401。
- `initialize` 返回服务名 `Aling Notion`。
- `tools/list` 只返回规划中的 8 个工具。
- `tools/call read_page` 通过本地 `/mcp` 真实读取 Notion 页面。
- 临时服务进程已停止。
- 运行日志不含 Notion Token 或 MCP Access Token。

### 服务器与公网验收

已通过：

- 服务器应用进程以独立 `notion-mcp` 低权限账户运行。
- 应用仅绑定 `127.0.0.1:8091`，Cloudflare 指标仅绑定 `127.0.0.1:20244`。
- Tunnel 建立 4 条 Cloudflare 连接，Dashboard 显示 `Healthy`。
- Published application 和 CNAME 已创建，公网入口为 `https://notion.example.com/mcp`。
- 无 Token 公网请求返回 `401`。
- 已创建仅匹配 MCP 主机名及 `/mcp` 的 Cloudflare Configuration Rule，关闭 Browser Integrity Check，避免程序客户端收到 Error 1010。
- 公网 `initialize` 成功。
- 公网 `tools/list` 恰好返回规划中的 8 个工具。
- 公网 `fetch_recent_diary(days=1)` 完成真实 Notion 只读调用。

尚未补做：根路径、旧 `/sse` 和 `GET /mcp` 的公网状态检查；最后一次远程命令因 Codex 执行额度耗尽未获执行，不应写成已经通过。

## 4. 尚未执行的验证

没有执行真实 Notion 写入测试，因为该测试会创建或修改使用者的线上 Notion 内容，当前没有取得单独的写入测试确认。

因此目前的证据范围是：

- 写入逻辑已通过 Mock Notion API 的自动测试。
- 真实 Notion 读取、查询、全文搜索和 MCP HTTP 链路已通过。
- 真实 `write_diary`、`create_page`、`update_page`、`append_content` 仍需在获得明确同意后，用测试页面完成一次真实验收。

## 5. Notion 官方限制

Notion API `2026-03-11` 会返回 `Place` 字段，但官方公开 API 当前不支持写入 Place 值。

本服务不会偷偷忽略 `place`：传入非空 `place` 时会在创建页面前返回 `UNSUPPORTED_PROPERTY`。

## 6. 本地文件

核心代码：

- `notion_mcp/server.py`
- `notion_mcp/services.py`
- `notion_mcp/notion_client.py`
- `notion_mcp/markdown_blocks.py`
- `notion_mcp/search_index.py`
- `notion_mcp/properties.py`
- `notion_mcp/auth.py`
- `notion_mcp/settings.py`
- `notion_mcp/errors.py`
- `notion_mcp/audit.py`

部署准备：

- `deploy/notion-mcp.service`
- `deploy/notion-mcp.env.template`
- `scripts/smoke_mcp.py`
- `scripts/install_server.sh`
- `scripts/install_cloudflare_tunnel.sh`
- `scripts/verify_server.py`

仓库中保留了早期的 Nginx 模板，但服务器最终采用现有 Cloudflare Tunnel 架构，该模板未部署。

测试：

- `tests/` 下共 7 个测试文件、33 项测试。

依赖：

- `pyproject.toml`
- `requirements.txt`
- `requirements-test.txt`
- F 盘虚拟环境：`F:\Codex\venvs\notion-mcp`
- F 盘 pip 缓存：`F:\Codex\pip-cache`

源码与文档中没有真实 Notion Token。

## 7. 清理结果

- F 盘只读联调临时 SQLite 数据库已删除。
- F 盘端到端运行日志已删除。
- 本地临时 MCP 进程已停止。
- C 盘 `.pytest_cache`、`__pycache__` 和 editable-install 元数据已删除。
- 保留 F 盘虚拟环境和 pip 缓存，供后续部署前复测；它们不在 C 盘。
- 服务器上传包、安装脚本和公网诊断脚本尚未清理，因为最后一组远程操作受到本次执行额度限制。

## 8. 剩余事项

1. 经使用者明确确认后，执行一篇测试日记或测试页面的真实写入验收。
2. 轮换已在聊天中出现的 Notion Token 和 Cloudflare Tunnel Token，并更新服务器 root-only 配置。
3. 向使用者交付 MCP Access Token，供真实客户端配置使用。
4. 补做根路径、旧 `/sse` 和 `GET /mcp` 状态检查。
5. 清理服务器与 F 盘部署临时文件，保留三份已校验备份和运行所需文件。
