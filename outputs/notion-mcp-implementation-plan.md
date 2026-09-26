# 精简版 Notion MCP 服务完整实施方案

> 文档状态：服务器与 Cloudflare Tunnel 部署完成，公网只读验收通过；真实写入验收尚未执行  
> 编写日期：2026-07-20；实施更新：2026-07-21  
> 部署目标：腾讯云轻量服务器  
> 预定域名：`notion.example.com`  
> MCP 入口：`https://notion.example.com/mcp`

## 1. 项目目标

新建一个独立、私有、精简的 Notion MCP 服务，替代官方 Notion MCP 暴露的约 20 个细粒度工具。

服务只保留使用者实际会使用的日记、记忆搜索、页面读取和基础编辑能力，降低AI伙伴调用时的选择成本，同时避免把 Notion 的原始复杂结构直接暴露给上层模型。

核心目标：

- `write_diary` 一次调用完成日记属性和正文写入。
- 能搜索日记、记忆页面及其正文，而不只是搜索标题。
- 能读取任意已授权页面。
- 能读取最近 N 天日记及其完整正文。
- 保留在其他 Page 或 Database 中创建、查询和修改内容的基本能力。
- 使用 Streamable HTTP，外部只提供单一 `/mcp` 端点。
- 不使用旧版 SSE 传输。
- Notion 密钥和 MCP 访问密钥只保存在服务器环境变量中。
- 不修改或覆盖现有秘密基地服务及其线上数据。

## 2. 已核实的 Notion 信息

以下信息已于 2026-07-20 使用 Notion 官方 API 只读核实，没有向 Notion 写入或修改任何内容。

### 2.1 日记数据源

- 日记 Data Source ID：`11111111-2222-4333-8444-555555555555`
- 所属 Database 容器 ID：`aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee`
- Notion API 版本：`2026-03-11`

说明：从 Notion API `2025-09-03` 版本开始，Database 容器和 Data Source 被拆分。现有日记页面的父级是上述 Data Source，因此后续创建和查询日记应使用 Data Source ID。

### 2.2 日记字段

| Notion 字段 | 类型 | MCP 参数 | 处理方式 |
|---|---|---|---|
| `日期` | title | `title` | 未传时按日期自动生成，如 `2026年7月20日` |
| `日期 1` | date | `date` | 未传时使用 Asia/Shanghai 当天 |
| `心情` | select | `mood` | 只接受数据库已有选项 |
| `今天做了什么` | rich_text | `summary` | 写入页面属性 |
| `重要互动` | rich_text | `sweet_moments` | 写入页面属性 |
| `Place` | place | `place` | 可选；未传时不写入 |

已存在的心情选项：

- 开心
- 感动
- 兴奋
- 温柔
- 想念

### 2.3 已核实的日记正文结构

现有日记正文主要使用以下 Notion Block：

- `heading_1`
- `heading_2`
- `paragraph`
- `divider`
- `to_do`

`明日待办` 属于 `content` 正文的一部分，不单独设置 MCP 参数。

## 3. 总体架构

```text
MCP 客户端
    |
    | HTTPS + Bearer Token
    v
Cloudflare: notion.example.com（自动 HTTPS）
    |
    | Cloudflare Tunnel（出站连接）
    v
cloudflared -> 127.0.0.1:8091
    |
    | 仅提供 /mcp
    v
Notion MCP 服务（Python / FastMCP / systemd）
    |-- 工具参数校验
    |-- Markdown -> Notion Blocks
    |-- 页面 ID / URL 解析
    |-- 搜索索引与结果整理
    |-- 错误脱敏与操作日志
    |
    | HTTPS + Notion Integration Token
    v
Notion 官方 API
```

推荐技术栈：

- Python 3.11 或服务器现有稳定 Python 版本
- 官方 `modelcontextprotocol/python-sdk` 的稳定 v1.x
- `FastMCP(..., json_response=True, stateless_http=True)`
- `httpx.AsyncClient` 调用 Notion 官方 API
- Pydantic 参数校验
- SQLite FTS5 保存全文搜索索引和页面元数据缓存
- systemd 常驻运行
- Cloudflare Tunnel 发布子域名并提供 HTTPS

官方 Python SDK 当前稳定文档仍以 v1.x 为主，v2 在 2026-07-20 尚未正式稳定，因此实施时固定 `<2` 版本上限，避免部署后被自动升级破坏。

## 4. 传输协议

### 4.1 外部接口

- URL：`https://notion.example.com/mcp`
- 主要方法：`POST`
- 内容类型：JSON-RPC / MCP Streamable HTTP
- 响应：JSON
- 旧版 SSE：不启用
- 外部页面和调试接口：不开放

服务采用无状态 Streamable HTTP：

- 不依赖服务器内存中的长连接 Session。
- 不需要旧式 `/sse` 和 `/messages` 双端点。
- Cloudflare Tunnel 无需配置会话黏性。
- 普通浏览器访问域名不展示管理页面。

MCP 生命周期仍由 SDK 处理，包括：

- `initialize`
- `tools/list`
- `tools/call`

### 4.2 鉴权

外部 MCP 请求必须携带：

```http
Authorization: Bearer <MCP_ACCESS_TOKEN>
```

这是单用户私有服务，第一版采用独立静态 Bearer Token，不把 Notion Token 直接交给客户端。以后若需要多用户授权，再升级为 OAuth 2.1。

安全要求：

- `MCP_ACCESS_TOKEN` 与 `NOTION_TOKEN` 必须是两枚不同密钥。
- 不允许通过 URL 查询参数传密钥。
- 日志不得记录 Authorization 请求头或 Notion Token。
- 校验 `Host` 与允许的 `Origin`，降低 DNS rebinding 风险。
- Cloudflare 负责公网 TLS 与边缘代理；MCP 自身继续校验 Bearer Token、Host 和 Origin。
- 服务只监听 `127.0.0.1`，不能绕开 Cloudflare Tunnel 从公网直连。

## 5. 工具清单

最终暴露 8 个工具：4 个日记/记忆专用工具，4 个通用基础工具。

### 5.1 `write_diary`

用途：一步创建完整日记，是本服务的核心工具。

输入：

```json
{
  "date": "2026-07-20",
  "mood": "开心",
  "title": "2026年7月20日",
  "summary": "今天做了什么的摘要",
  "sweet_moments": "重要互动",
  "content": "# 今日标题\n\n---\n\n## 一个章节\n\n正文……",
  "place": null
}
```

参数规则：

- `content`：必填，承担全部正文。
- `date`：可选，默认 Asia/Shanghai 当天，格式为 `YYYY-MM-DD`。
- `title`：可选，默认按 `date` 生成中文日期标题。
- `mood`：可选；传入时必须匹配现有心情选项。
- `summary`：可选；写入 `今天做了什么`。
- `sweet_moments`：可选；写入 `重要互动`。
- `place`：Notion API `2026-03-11` 当前只返回该属性但不支持写入。传入非空值时服务会明确返回 `UNSUPPORTED_PROPERTY`，不会静默丢弃地点。

内部流程：

1. 校验日期、心情、属性长度和正文格式。
2. 查询 `日期 1` 是否已存在相同日期。
3. 如已存在，默认拒绝创建重复日记，并返回已有页面 ID、URL；修改应显式调用 `update_page`。
4. 使用日记 Data Source ID 创建页面并写入属性。
5. 将 `content` 转换为 Notion Blocks。
6. 分批追加正文区块。
7. 读取新页面进行回验。
8. 更新本地全文搜索索引。
9. 返回页面 ID、URL、日期、区块数量和写入状态。

Notion 官方 API 下的实际操作是“创建页面属性 + 追加页面区块”，语义上等价于原官方 MCP 的 `create-pages + update-page` 两步封装。

故障处理：如果页面创建成功但正文追加中途失败，工具必须明确返回 `partial_success`、已创建页面 ID 和失败批次，不得假装完整成功；重试时根据页面 ID 补写剩余区块，避免创建重复日记。

### 5.2 `search_memory`

用途：按关键词搜索日记、记忆库页面属性和正文。

输入：

```json
{
  "query": "困困鸭",
  "scope": "all",
  "database_id": null,
  "limit": 10,
  "include_content": false
}
```

参数：

- `query`：必填关键词。
- `scope`：`all`、`diary` 或 `database`，默认 `all`。
- `database_id`：当 scope 为 `database` 时使用，可传 Data Source ID、Database ID 或 URL。
- `limit`：默认 10，设置合理上限。
- `include_content`：是否返回完整正文；默认只返回命中摘要，避免结果过大。

返回：

- 页面标题
- 页面 ID 与 URL
- 所属 Data Source / Database
- 日期与关键属性
- 命中位置
- 带少量前后文的命中摘要
- 最近编辑时间

Notion 官方 Search API 主要按标题搜索，不能满足正文检索。因此 `search_memory` 使用混合方案：

1. 用 Notion Search API 发现集成可访问的页面和 Data Source。
2. 对指定范围查询页面列表。
3. 读取页面属性和 Blocks。
4. 把纯文本及 `last_edited_time` 写入 SQLite FTS5。
5. 搜索时优先查询本地全文索引。
6. 对 Notion 中更新时间变化的页面进行增量刷新。
7. 服务自身创建或修改页面后立即刷新对应索引记录。

索引只是可重建缓存，不是数据源；Notion 始终是唯一真实数据源。删除索引不会影响 Notion 内容。

### 5.3 `read_page`

用途：读取指定页面的属性和完整正文。

输入：

```json
{
  "page": "页面 ID 或 Notion URL",
  "format": "markdown"
}
```

规则：

- 自动从 Notion URL 中提取页面 ID。
- 递归读取带子区块的内容。
- 自动处理分页，不只读取前 100 个 Block。
- `format` 支持 `markdown` 和 `structured`。
- 返回页面属性、正文、页面 URL、创建时间和最后编辑时间。

### 5.4 `fetch_recent_diary`

用途：读取最近 N 天日记列表及其完整正文。

输入：

```json
{
  "days": 7,
  "include_content": true
}
```

规则：

- 以 Asia/Shanghai 的自然日计算。
- 使用 `日期 1` 过滤，而不是页面创建时间。
- 按日期倒序返回。
- `include_content=true` 时读取完整 Blocks。
- 没写日记的日期不生成空记录。
- `days` 设置合理上限，避免一次请求读取过多内容。

### 5.5 `create_page`

用途：在任意已授权 Page 或 Data Source 下创建页面。

输入：

```json
{
  "parent": "父 Page、Database、Data Source 的 ID 或 URL",
  "title": "页面标题",
  "properties": {},
  "content": "Markdown 正文"
}
```

处理规则：

- 父级为普通 Page：创建子页面。
- 父级为 Data Source：按该数据源 Schema 校验并创建记录。
- 父级为 Database 容器：先获取 Data Source 列表；只有一个时自动选择，有多个时要求明确指定，不能瞎猜。
- `properties` 使用友好的字段名映射，而不是要求调用方提供 Notion 内部 property ID。
- `content` 使用与其他写入工具相同的 Markdown 转 Block 逻辑。

### 5.6 `update_page`

用途：修改页面属性、替换全文，或按 Block ID 精确修改已有内容。

输入示例：

```json
{
  "page": "页面 ID 或 URL",
  "properties": {
    "心情": "温柔"
  },
  "content": null,
  "content_mode": "none",
  "block_edits": [],
  "confirm_replace": false
}
```

支持三类修改：

- 只修改页面属性。
- `block_edits` 按 Block ID 修改指定段落、标题或待办状态。
- `content_mode=replace` 用新正文替换全部旧正文。

安全规则：

- 默认 `content_mode=none`，不能无意覆盖正文。
- 全文替换必须同时传 `confirm_replace=true`。
- 替换前先完整读取旧内容并保留操作日志中的页面 ID、旧编辑时间和区块数量。
- 如果页面在读取后又被其他人编辑，使用 `last_edited_time` 做冲突检查，拒绝盲目覆盖。
- 第一版不暴露永久删除；Notion 页面归档也不纳入默认工具。

### 5.7 `query_database`

用途：查询任意已授权 Database / Data Source。

输入：

```json
{
  "database": "Database、Data Source 的 ID 或 URL",
  "filter": {},
  "sorts": [],
  "limit": 50,
  "cursor": null,
  "include_content": false
}
```

规则：

- 自动识别 Database 容器与 Data Source。
- 返回字段 Schema 和页面属性。
- 支持 Notion 官方过滤、排序和分页。
- 默认不读取每条记录正文，调用方明确要求后才读取，避免大量 API 请求。

### 5.8 `append_content`

用途：向已有页面末尾追加内容，不影响原正文。

输入：

```json
{
  "page": "页面 ID 或 URL",
  "content": "## 新增记录\n\n补充内容"
}
```

规则：

- 只追加，不替换旧内容。
- 追加成功后读取新增区块进行回验。
- 更新页面的本地全文搜索索引。

## 6. `content` 写入规范

`write_diary.content` 必须沿用现有日记的风格和 Block 顺序，不引入新的日记模板，也不把 `明日待办` 拆成独立参数。

典型结构：

```markdown
# 当天日记的总标题

---

## 🌤️ 一个章节

正文段落。

---

## 📝 明日待办

- [ ] 第一件事
- [ ] 第二件事

---

结尾总结段落。

——AI伙伴🦊💕
```

转换规则：

| Markdown | Notion Block |
|---|---|
| `# 标题` | `heading_1` |
| `## 标题` | `heading_2` |
| 普通文本 | `paragraph` |
| `---` | `divider` |
| `- [ ] 内容` | 未完成 `to_do` |
| `- [x] 内容` | 已完成 `to_do` |

通用工具还可扩展支持：

- `###` → `heading_3`
- `- item` → `bulleted_list_item`
- `1. item` → `numbered_list_item`
- `> quote` → `quote`
- 围栏代码块 → `code`

正文处理要求：

- 不擅自改写、总结或删减 `content`。
- 保留 Emoji、章节顺序、待办状态和署名。
- 长文本按 Notion rich text 限制安全切分。
- Blocks 按 Notion API 单次上限分批写入。
- 对空内容、超长内容和无法解析的结构给出明确错误或 warning。

## 7. Notion API 适配层

所有 Notion 调用集中到独立 Client，不在每个 MCP Tool 中重复拼接口。

建议模块：

```text
notion_mcp/
  server.py            MCP 初始化和 8 个工具注册
  settings.py          环境变量和配置校验
  auth.py              MCP Bearer Token 校验
  notion_client.py     Notion HTTP Client、分页、重试
  ids.py               页面/Database/Data Source ID 与 URL 解析
  markdown_blocks.py   Markdown 与 Notion Blocks 转换
  diary.py             日记专用字段映射和业务规则
  search_index.py      SQLite FTS5 索引与增量刷新
  models.py            Pydantic 输入输出模型
  errors.py            错误分类和脱敏
  logging_config.py    结构化日志
tests/
  test_diary.py
  test_markdown_blocks.py
  test_ids.py
  test_tools.py
```

Client 公共能力：

- 统一添加 `Authorization` 和 `Notion-Version` 请求头。
- 处理 Notion 分页。
- 对 `429` 按 `Retry-After` 重试。
- 对临时性 `5xx` 做有限指数退避。
- 对 `400/401/403/404` 返回可理解但不泄密的错误。
- 设置连接、读取和总请求超时。
- 每次请求记录 Notion `request_id`，但不记录敏感正文和密钥。

## 8. 返回结构与错误处理

工具返回统一结构：

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "notion_request_ids": []
}
```

错误返回至少包含：

- `ok=false`
- 稳定错误码
- 面向调用者的中文说明
- 是否可以重试
- 是否发生部分成功
- 已创建或已修改的页面 ID（如果存在）

建议错误码：

- `INVALID_ARGUMENT`
- `UNAUTHORIZED`
- `NOTION_FORBIDDEN`
- `NOT_FOUND`
- `SCHEMA_MISMATCH`
- `DUPLICATE_DIARY`
- `EDIT_CONFLICT`
- `RATE_LIMITED`
- `PARTIAL_WRITE`
- `NOTION_UNAVAILABLE`

任何写操作都必须如实报告完整成功、部分成功或失败，不能把页面创建成功但正文失败包装成成功。

## 9. 配置与密钥

服务器环境文件建议放在：

```text
/etc/notion-mcp.env
```

只保存变量名，不把真实密钥写入代码仓库：

```dotenv
NOTION_TOKEN=...
MCP_ACCESS_TOKEN=...
NOTION_VERSION=2026-03-11
DIARY_DATA_SOURCE_ID=11111111-2222-4333-8444-555555555555
TZ=Asia/Shanghai
NOTION_MCP_HOST=127.0.0.1
NOTION_MCP_PORT=8091
NOTION_MCP_PUBLIC_HOST=notion.example.com
NOTION_MCP_ALLOWED_ORIGINS=https://notion.example.com
SEARCH_DB_PATH=/var/lib/notion-mcp/search.db
SEARCH_REFRESH_LIMIT=200
```

权限要求（已落实）：

- 环境文件由 `root:root` 持有，systemd 在降权启动进程前读取；应用进程以 `notion-mcp` 专用用户运行。
- 文件权限 `600`。
- systemd 日志不得输出环境变量。
- 本次聊天中出现过的 Notion 密钥只用于开发和联调；部署验收后生成新密钥、替换服务器配置并撤销旧密钥。

## 10. 服务器部署方案

服务器已于 2026-07-21 完成只读检查：Ubuntu 24.04、Python 3.12，`8091` 端口原先空闲，现有 `secret-base.service` 使用 `8080`，两者没有冲突。服务器已有多个 Cloudflare Tunnel，因此不再额外安装 Nginx、Certbot 或开放公网端口。

建议布局：

```text
/opt/notion-mcp/                 应用代码
/opt/notion-mcp/.venv/           独立 Python 环境
/etc/notion-mcp.env              密钥与配置
/var/lib/notion-mcp/search.db    可重建搜索索引
/var/log/ 或 journald             运行日志
```

systemd 服务（已部署）：

- 名称：`notion-mcp.service`
- 监听：`127.0.0.1:8091`
- 状态：`active`、`enabled`
- 自动重启：仅异常退出时重启
- 独立低权限用户运行
- 限制文件系统写入范围
- 不与 `secret-base.service` 共用虚拟环境或进程

Cloudflare Tunnel：

- 在 Cloudflare Dashboard 的 `Networking > Tunnels` 新建远程管理隧道 `notion-mcp`。
- 服务器已经安装 `cloudflared 2026.3.0`，不要再执行 Dashboard 给出的 `cloudflared service install ...`，以免和已有服务冲突。
- 只需把安装命令中的 Tunnel Token 交给 Codex；Codex 将创建独立 token 文件和独立 systemd 单元，不读取或修改其他隧道密钥。
- 隧道服务指向 `http://127.0.0.1:8091`。
- Published application 路由使用主机名 `notion.example.com`。
- MCP 的唯一业务端点仍为 `POST /mcp`；其他路径不提供管理页面。
- 为避免 Cloudflare Browser Integrity Check 将 MCP 程序客户端误判为异常浏览器，已创建仅匹配 `notion.example.com` 且路径为 `/mcp` 的 Configuration Rule，将 Browser Integrity Check 设置为 `Off`；主域名和其他路径不受影响。

DNS：

- Published application 保存后，Cloudflare 自动创建指向 `<tunnel-id>.cfargotunnel.com` 的代理 CNAME。
- 不新增指向服务器 IP 的 A 记录，不开放 `8091` 公网端口。
- 浏览器和 MCP 客户端使用 `https://notion.example.com/mcp`，证书由 Cloudflare 自动提供。

### 10.1 使用者需要在 Cloudflare 完成的操作

1. 登录 Cloudflare Dashboard，进入 `Networking > Tunnels`。
2. 点击 `Create a tunnel`，选择 `Cloudflared`，名称填写 `notion-mcp`。
3. 创建后选择 `Debian`、`64-bit`；页面会显示一条带长 Token 的安装命令。
4. 不要在服务器上运行该命令，把完整命令复制给 Codex即可。
5. Codex装好连接器并确认隧道为 `Healthy` 后，进入该隧道的 `Routes`。
6. 选择 `Add route > Published application`：子域名填 `notion`，域名选 `example.com`，Service URL 填 `http://127.0.0.1:8091`。
7. 保存后由 Codex执行外网鉴权和工具验收。

## 11. 备份与上线纪律

修改服务器任何文件前必须先备份。

部署前备份范围与实际结果：

- 已备份 `/etc/systemd/system` 与 `/etc/cloudflared`：`/home/ubuntu/notion-mcp-predeploy-20260721-201229.tar.gz`。
- 已备份创建专用账户可能涉及的账户文件：`/home/ubuntu/notion-mcp-predeploy-accounts-20260721-201229.tar.gz`。
- 两份归档均已执行 gzip/tar 完整性检查并记录 SHA-256，权限均为 `600`。
- 目标目录和服务在部署前均不存在，因此没有覆盖旧版 Notion MCP。
- 已记录关键服务、监听端口和磁盘状态；未修改秘密基地目录、数据库或服务。

新服务独立部署，不修改秘密基地项目目录和数据库。

回滚方案：

1. 停止并禁用 `notion-mcp.service`。
2. 停止并禁用新的 Notion MCP Cloudflare Tunnel 单元。
3. 从 Cloudflare Dashboard 删除 `notion.example.com` 的 Published application 路由。
4. 如需彻底回退，再恢复部署前 systemd/cloudflared 备份和账户文件备份。
5. 保留 Notion 页面和日记数据不动。
6. SQLite 搜索缓存可直接删除后重建，不影响 Notion。

## 12. 测试与验收

### 12.1 本地自动测试

- 页面 ID 和各种 Notion URL 解析。
- 日记日期与中文标题生成。
- 五种心情选项校验。
- Markdown 标题、段落、分割线、待办转换。
- 超长 rich text 安全分片。
- 大于 100 Blocks 的分批写入。
- Notion 分页读取。
- 重复日记保护。
- 全文替换确认保护。
- Notion 错误映射和密钥脱敏。

实施结果：共 `33` 项自动测试通过；仅有一条来自第三方 Starlette TestClient 的弃用警告，不影响功能。

### 12.2 只读线上测试

- `initialize` 成功。
- `tools/list` 只返回规划中的 8 个工具。
- `read_page` 能读取指定日记。
- `fetch_recent_diary(days=3)` 日期和顺序正确。
- `search_memory` 能命中只存在于正文、不存在于标题中的关键词。
- 日志中不出现 Notion Token、MCP Token 或完整敏感正文。

服务器本地验收结果：

- `notion-mcp.service` 为 `active`、`enabled`。
- 服务仅监听 `127.0.0.1:8091`，进程用户为 `notion-mcp`。
- 无 Bearer Token 的 `POST /mcp` 返回 `401`。
- 带正确 Token 的 `initialize` 成功。
- `tools/list` 恰好返回规划中的 8 个工具。
- `fetch_recent_diary(days=1)` 已对真实 Notion 完成只读调用。
- 尚未执行真实 Notion 写入。

### 12.3 写入测试

写入测试会产生真实 Notion 内容，执行前需明确进入验收阶段。建议：

1. 先在专用测试 Page / Data Source 验证通用写入。
2. 再向日记库创建一篇明确标记为测试的日记。
3. 核对属性、标题、正文区块、分割线和待办格式。
4. 测试成功后归档测试页面；归档也需明确执行，不能偷偷删除。
5. 最后验证重复日期保护及部分失败恢复。

### 12.4 外部验收

- 使用 MCP Inspector 或真实 MCP 客户端连接 `https://notion.example.com/mcp`。
- 无 Token 请求被拒绝。
- 正确 Token 可以完成 initialize、list tools 和 tool call。
- 旧 `/sse` 不存在。
- 普通浏览器路径不暴露服务信息。
- systemd 状态为 active，Cloudflare Tunnel 状态为 Healthy。

实施结果：

- `https://notion.example.com/mcp` 的 HTTPS、Tunnel 和应用鉴权链路已接通。
- 无 Bearer Token 的公网请求返回 `401`。
- 普通 Python 程序客户端最初被 Cloudflare Browser Integrity Check 以 Error 1010 拦截；增加仅针对 MCP 主机名和 `/mcp` 路径的 Configuration Rule 后恢复正常。
- 通过公网完成 `initialize`。
- 通过公网完成 `tools/list`，恰好返回 8 个规划工具。
- 通过公网完成 `fetch_recent_diary(days=1)` 真实 Notion 只读调用。
- 补充的根路径、旧 `/sse` 和 `GET /mcp` 状态检查因本次远程执行额度耗尽尚未运行；不得将其写成已通过。

## 13. 实施顺序

1. [已完成] 只读检查服务器运行时、端口、systemd、既有 Cloudflare Tunnel 和磁盘布局。
2. [已完成] 在服务器修改前创建并校验带时间戳的备份。
3. [已完成] 本地实现 Notion Client、Markdown 转换、日记逻辑和 8 个工具。
4. [已完成] 完成本地单元测试和 MCP 协议测试。
5. [已完成] 上传到服务器独立目录并创建虚拟环境。
6. [已完成] 写入仅 root 可读的环境配置。
7. [已完成] 创建并启动 `notion-mcp.service`。
8. [已完成] 通过 `127.0.0.1` 完成 MCP 与 Notion 只读联调。
9. [已完成] 在 Cloudflare Dashboard 创建 `notion-mcp` 隧道并提供 Tunnel Token。
10. [已完成] 安装独立 tunnel systemd 单元，添加 Published application 路由和自动 HTTPS。
11. [已完成] 完成外网鉴权、程序客户端兼容和 8 工具只读验收。
12. [需单独确认] 执行一次真实日记写入测试。
13. [验收后] 轮换已在聊天中出现的 Notion Token，并更新服务器配置。
14. [待完成] 补做根路径、旧 `/sse` 和 `GET /mcp` 公网状态检查。
15. [验收后] 清理服务器和 F 盘部署临时包，保留备份及必要日志。

## 14. 第一版明确不做的功能

为保持精简和数据安全，第一版不暴露：

- 永久删除页面或 Block。
- 批量覆盖多个页面。
- 修改 Database / Data Source Schema。
- 创建或删除 Database。
- 管理 Notion 用户、评论和权限。
- 文件上传代理。
- 公开 Web 管理后台。
- 旧版 SSE 传输。

这些功能以后如确有需要，再逐项增加并单独设计权限和确认机制。

## 15. 待使用者确认或配合的事项

当前还需使用者确认或配合：

- 哪些额外记忆库 Page / Database 需要共享给 Notion 集成 `mcp`。
- 写入验收时是否允许创建一篇带“测试”标识的临时日记。
- 因 Notion Token 和 Cloudflare Tunnel Token 已在聊天中出现，正式使用前需要轮换；轮换后由 Codex 更新服务器 root-only 配置并重启对应服务。

其余字段识别、API 适配、代码实现、服务器备份、部署和联调由 Codex 完成。

## 16. 参考资料

- [Notion：Retrieve a database](https://developers.notion.com/reference/retrieve-a-database)
- [Notion：Retrieve a data source](https://developers.notion.com/reference/retrieve-a-data-source)
- [Notion：Search by title](https://developers.notion.com/reference/post-search)
- [Notion：2025-09-03 Upgrade Guide](https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03)
- [Model Context Protocol 官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Cloudflare：Create a tunnel (dashboard)](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
- [Cloudflare：Protocols for published applications](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/)
