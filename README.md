<p align="center">
  <img src="assets/noaff-logo.svg" width="112" alt="NOAFF Logo">
</p>

<h1 align="center">NOAFF Restock Monitor</h1>

<p align="center">
  公益 NOAFF IDC 补货监控应用：公开页面采集、页面解析、Telegram 状态机推送。
</p>

<p align="center">
  Python 3 · Flask · SQLite · DrissionPage · Telegram · Docker
</p>

## 项目定位

NOAFF Restock Monitor 用来监控 IDC、VPS、独服、WHMCS 商店等公开商品页面的补货状态，并把状态变化推送到 Telegram。

很多 IDC 商品页没有官方库存 API，所以项目的主路线是：

```text
公开页面采集 -> 页面适配器解析 -> 库存状态机 -> Telegram send/edit/sold-out 推送
```

项目边界很明确：

- 只监控公开可访问页面。
- 不绕过 Cloudflare / Turnstile / CAPTCHA。
- 不接入打码服务。
- 不模拟真人过验证。
- 遇到 Cloudflare challenge 会标记为受保护来源，进入冷却，不会反复重试或重建浏览器。
- 对无法稳定公开访问的页面，建议使用 `manual`、`webhook` 或替代公开页面。

这个项目坚持 NOAFF / 无推广返利。它适合做公开、透明、低打扰的补货提醒，而不是灰色绕过工具。

## 功能概览

- 多采集策略：`browser`、`static_http`、`generic_pricing_table`、`whmcs`、`firecrawl`、fallback pipeline、`manual`、`webhook`。
- IDC 页面解析：围绕目标关键词查找附近 card / table / section，识别库存数字、购买入口和售罄标记。
- WHMCS 解析：支持常见商店页、`pid`、`cart.php?gid=xx`、`configureproduct`、`Order Now`、`Out of Stock`。
- 可选 Firecrawl 后端：用于人工触发的商品入库 Map/Scrape 更合适，实时监控默认关闭。
- Firecrawl 连接诊断：后台可用当前表单配置测试 API URL / Key / proxy / ZDR，不保存、不泄露 Key。
- 商品入库工作台：入口 URL -> URL 发现 -> 批量抓取 -> 解析预览 -> 批量创建任务。
- 商品入库降噪：语言切换、导航、页脚、步骤标题、无价格/无规格候选会降级到人工确认。
- 受保护来源处理：Cloudflare challenge 统一分类为 `cloudflare_challenge`，并按 1 / 3 / 10 分钟递进冷却。
- Telegram 状态机：补货发新消息，库存变化编辑原消息，售罄覆盖原消息并清空 `message_id`。
- Manual / Webhook 数据源：没有可抓页面时，也能用后台手动标记或外部系统推送库存。
- 商家页面导入：从公开商品列表页发现商品，生成任务并按分组管理。
- 管理后台：任务管理、系统设置、商家导入、活动日志、备份恢复、升级入口、管理员改密。
- 安全基础：浏览器 UA 校验、同源校验、CSRF、AJAX 头校验、登录限流、敏感 token 脱敏。

## 快速安装

普通用户直接运行：

```bash
curl -H 'Cache-Control: no-cache' -fsSL https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh -o install.sh && bash install.sh
```

安装脚本会进入中文交互向导，覆盖：

- 部署方式：Docker 隔离或原生安装。
- 访问方式：IP + 端口、域名直连、Cloudflare 小黄云。
- 端口、域名、HTTPS 证书、Telegram、管理员账号。
- 安装摘要确认和运行状态检查。

推荐选择：

| 场景 | 建议 |
| --- | --- |
| 机器已有网站或已有 Nginx | Docker 隔离 |
| 干净服务器并希望脚本托管服务 | 原生安装 |
| 没有域名或临时测试 | IP + 端口 |
| 有域名且能直连源站 | 域名直连 |
| 域名走 Cloudflare 代理 | Cloudflare 小黄云 |

原生 Nginx 模式只写入 NOAFF 独立站点配置：

```text
/etc/nginx/sites-available/noaff-monitor.conf
/etc/nginx/sites-enabled/noaff-monitor.conf
```

不会删除默认站点，也不会主动杀已有 nginx 进程。如果 80/443 已被占用，脚本会打印占用详情并退出。

## 采集策略

| 策略 | 适合场景 | 行为 |
| --- | --- | --- |
| `browser` | 需要前端渲染的公开页面 | 使用 DrissionPage / Chromium 获取 HTML，再按关键词解析 |
| `static_http` | 普通静态 HTML 页面 | 使用 `requests` 和浏览器 UA 抓取，分类记录超时、403、429、5xx |
| `generic_pricing_table` | IDC 套餐卡片、价格页、表格 | 在 `target_keyword` 附近判断库存数字、购买按钮、售罄按钮 |
| `whmcs` | WHMCS 商店页 | 识别产品块、`pid`、购买链接、售罄标记 |
| `firecrawl` | 已显式配置 Firecrawl 的页面 | 调用外部 Firecrawl `/v2/scrape`，成功返回 HTML 后继续走本项目解析器 |
| `static_then_firecrawl` | 静态页面优先，失败后外部补充 | `static_http` 失败后尝试 Firecrawl |
| `firecrawl_then_static` | 外部抓取优先，失败后本地兜底 | Firecrawl 失败后尝试 `static_http` |
| `firecrawl_then_browser` | 外部抓取优先，限流等错误后浏览器兜底 | Firecrawl 失败后尝试本地 Chromium |
| `adaptive` | 不确定页面 | 静态优先，必要时浏览器或已启用的 Firecrawl；不会无限 fallback |
| `manual` | 没有稳定公开来源 | 后台手动标记有货 / 售罄，复用 Telegram 状态机 |
| `webhook` | 外部系统知道库存 | 外部 POST 库存状态，复用 Telegram 状态机 |

默认策略是 `browser`，旧任务无需手动迁移。

## Firecrawl 集成

Firecrawl 是可选外部采集后端，不是项目硬依赖。不开启 Firecrawl 时，本项目仍可使用 `static_http`、`browser`、`generic_pricing_table`、`whmcs`、`manual` 和 `webhook`。

推荐用法：

- 商品入库优先：用 Firecrawl `/v2/map` 发现候选 URL，再用 `/v2/scrape` 抓取候选页，最后由本项目解析器判断库存。
- 实时监控谨慎开启：默认 `FIRECRAWL_USE_FOR_MONITOR=false`，避免每轮监控产生外部调用成本。
- 库存监控必须使用 `FIRECRAWL_MAX_AGE_MS=0` 和 `FIRECRAWL_STORE_IN_CACHE=false`，避免缓存旧库存。
- API Key 只保存在后端，snapshot、备份、日志和前端响应不会返回明文。
- 后台 Firecrawl 集成页提供“测试 Firecrawl 连接”，会使用当前表单里的 API URL、API Key、proxy、zeroDataRetention 做一次最小 scrape 诊断；测试不会保存 Key，响应也不会返回明文 Key。
- 诊断会把常见错误翻译成操作建议：认证失败、额度不足、限流、ZDR 未开通、proxy 权限、返回 challenge、API URL 不正确等。

Hosted Firecrawl 可能提升复杂页面成功率，但页面内容会发送给外部服务，且 enhanced / auto proxy 可能产生额外费用。Self-host Firecrawl 不包含 hosted 版 Fire-engine 等高级 IP block / robot detection 能力，不能把它当成 Cloudflare 绕过能力。

边界保持一致：如果 Firecrawl 返回的是正常页面内容，本项目会继续解析；如果返回 Cloudflare / Turnstile / CAPTCHA challenge，仍会分类为 `cloudflare_challenge` 并进入受保护来源冷却。

最小配置：

```env
FIRECRAWL_ENABLED=true
FIRECRAWL_API_URL=https://api.firecrawl.dev
FIRECRAWL_API_KEY=fc-...
FIRECRAWL_MAX_AGE_MS=0
FIRECRAWL_STORE_IN_CACHE=false
FIRECRAWL_USE_FOR_MONITOR=false
FIRECRAWL_USE_FOR_CATALOG=true
```

`FIRECRAWL_PROXY_MODE=enhanced` 或 `auto` 只有在对应 feature flag 显式开启时才会生效：

```env
FIRECRAWL_PROXY_MODE=auto
FIRECRAWL_ALLOW_AUTO_PROXY=true
```

## 商品入库

商品入库适合 IDC 商家没有公开 API、但有公开价格页 / WHMCS 商店页 / sitemap / 商品列表页的场景。当前工作流是：

```text
来源 -> 采集 -> 规则 -> 执行 -> 发现结果 -> 商品预览 -> 创建任务
```

工作台会先发现候选 URL，再让你抓取选中 URL，最后在商品预览里确认可入库商品。默认不会把语言切换、导航、页脚、分类/步骤标题、无价格/无规格候选直接写入任务；这些内容会进入“需要人工确认 / 已过滤候选”。

工作台字段：

| 字段 | 说明 |
| --- | --- |
| 商家 URL | 入口页，例如 pricing、store、cart.php?gid=xx |
| discovery strategy | `local` / `firecrawl_map` / `hybrid` |
| scrape strategy | `browser` / `static_http` / `firecrawl` / `adaptive` |
| extractor | `generic_pricing_table` / `whmcs` / `firecrawl_product_hint` / `fallback_keyword_parser` |
| search keyword | Firecrawl Map 搜索词，例如 `vps`、`hk`、`pricing` |
| target keyword | 目标商品关键词，建议用完整产品名 |
| dedupe policy | `by_url` / `by_title_url` / `by_pid` |
| include sold out | 是否把售罄商品也放进入库预览 |
| auto create tasks | 是否导入后直接生成监控任务 |

发现结果和商品预览会展示 URL、来源、状态、解析器、`backend_used`、置信度、命中信号和是否可创建任务。批量创建任务会按 `source_item_id` 去重；重复执行只会同步已有任务，不会重复创建。

## IDC / WHMCS 配置示例

DMIT 类价格页：

```text
monitor_url: https://www.dmit.io/pages/pricing
target_keyword: 目标套餐的完整名称或唯一关键词
fetch_strategy: generic_pricing_table
```

WHMCS 商店页：

```text
monitor_url: https://my.rfchost.com/index.php?rp=/store/hk-tier-1-international-optimization-network
target_keyword: 页面里对应产品的完整标题
fetch_strategy: whmcs
source_config: {"pid": 123}
```

常见有货信号：

```text
Order Now, Buy Now, Configure, Available, Add to Cart, 下单, 购买
```

常见售罄信号：

```text
Out of Stock, Sold Out, Unavailable, 缺货, 售罄, 无货
```

如果同一页面有多个产品，尽量把 `target_keyword` 写成目标产品独有的完整标题，避免误判到相邻产品。

## Cloudflare / CAPTCHA 处理

当页面返回 Cloudflare / Turnstile / CAPTCHA challenge 时，任务会被记录为受保护来源：

```text
error_kind: cloudflare_challenge
blocked_count: 自动递增
last_blocked_at: 最近拦截时间
cooldown_until: 冷却截止时间
```

冷却时间：

| 命中次数 | 冷却 |
| --- | --- |
| 第 1 次 | 1 分钟 |
| 第 2 次 | 3 分钟 |
| 第 3 次及以后 | 10 分钟 |

冷却期内：

- 不启动 Chromium。
- 不请求目标站。
- 不改变库存状态。
- 不发送 Telegram。

这不是绕过失败，而是项目的设计边界。对这类站点，建议改用：

- 商家公开 RSS / 状态页 / 静态价格页。
- `manual` 后台手动维护。
- `webhook` 接入你自己的合法库存来源。
- 已启用 Firecrawl 时可尝试外部抓取一次；如果仍返回 challenge，同样进入冷却。

## Manual / Webhook

`manual` 任务会在任务卡片显示“有货”和“售罄”按钮。点击后直接进入同一套 Telegram 状态机。

`webhook` 任务需要先在后台重置 token。明文 token 只在重置时返回一次；数据库、快照和日志不会暴露明文 token。

有货推送示例：

```bash
curl -X POST 'https://your-panel.example.com/api/webhooks/restock/123' \
  -H 'Authorization: Bearer <ingest_token>' \
  -H 'Content-Type: application/json' \
  -d '{"stock": 3, "detail": "provider push", "checked_at": "2026-07-07T12:00:00+08:00"}'
```

售罄推送示例：

```bash
curl -X POST 'https://your-panel.example.com/api/webhooks/restock/123' \
  -H 'X-NOAFF-Token: <ingest_token>' \
  -H 'Content-Type: application/json' \
  -d '{"status": "sold_out", "detail": "provider reports sold out"}'
```

支持字段：

| 字段 | 说明 |
| --- | --- |
| `stock` | 数字库存，`> 0` 表示有货，`0` 表示售罄 |
| `status` | `in_stock` / `sold_out` / `unknown` |
| `detail` | 本次来源说明 |
| `checked_at` | 外部系统检测时间，ISO 8601 |

## Telegram 推送状态机

同一个任务只维护一个 Telegram 状态：

| 状态变化 | 行为 |
| --- | --- |
| 首次补货 | 发送新消息，保存 `message_id` |
| 库存数字变化 | 编辑原消息 |
| 仍然有货且库存不变 | 不重复刷屏 |
| 售罄 | 编辑原消息为售罄文案，清空 `message_id` |
| 采集失败或受保护来源 | 只记录错误，不改变库存状态，不发送消息 |

文案模板支持：

```text
{name}        商品名称
{stock}       当前库存
{url}         监控链接
{keyword}     目标关键词
{checked_at}  检测时间
{status}      in_stock / sold_out / test
```

示例：

```html
<b>{name}</b>
库存：{stock}
链接：{url}
检测时间：{checked_at}
```

## 管理后台

后台包含：

- 监控任务创建、编辑、启停、删除。
- 主分组 / 多级子分组卡片浏览，进入后再看下一级或商品列表，避免一页瀑布流。
- 分组重命名、删除分组、批量删除子分组、批量删除任务。
- 采集策略选择。
- 受保护来源提示和冷却时间展示。
- Manual 快捷标记。
- Webhook endpoint、token hint 和 token 重置。
- 商家页面导入、来源同步、来源启停、商品生成任务。
- TG 文案变量说明和当前编辑模板测试推送。
- Telegram Bot Token 和 Chat ID 配置。
- 数据备份 / 恢复。
- 系统升级入口。
- 管理员账号密码修改。
- 活动日志和运行状态。

## 常用环境变量

运行时变量：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `APP_PORT` | 应用监听端口 | `7777` |
| `APP_HOST` | 应用绑定地址 | `127.0.0.1` |
| `SECRET_KEY` | Flask session 密钥 | 自动生成或手动配置 |
| `ADMIN_USERNAME` | 首次初始化管理员 | `operator` |
| `ADMIN_PASSWORD` | 首次初始化密码 | 随机生成或手动配置 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 空 |
| `TELEGRAM_CHAT_ID` | 单个 Telegram Chat ID | 空 |
| `TELEGRAM_CHAT_IDS` | 多个 Chat ID，逗号或换行分隔 | 空 |
| `MONITOR_DEBUG_PORT` | 主监控浏览器调试端口 | `9223` |
| `TEST_DEBUG_PORT` | 测试推送浏览器调试端口 | `9334` |
| `CATALOG_DEBUG_PORT` | 商家导入浏览器调试端口 | `9445` |
| `POLL_INTERVAL_SECONDS` | 任务轮询间隔 | `45` |
| `REQUEST_TIMEOUT_SECONDS` | 页面抓取超时 | `25` |
| `FIRECRAWL_ENABLED` | 是否启用 Firecrawl 集成 | `false` |
| `FIRECRAWL_API_URL` | Firecrawl API 地址，hosted 或 self-host | `https://api.firecrawl.dev` |
| `FIRECRAWL_API_KEY` | Firecrawl API Key，永不通过 snapshot 明文返回 | 空 |
| `FIRECRAWL_TIMEOUT_SECONDS` | Firecrawl 请求超时 | `60` |
| `FIRECRAWL_MAX_AGE_MS` | Firecrawl 缓存年龄；库存监控必须为 `0` | `0` |
| `FIRECRAWL_STORE_IN_CACHE` | 是否允许 Firecrawl 缓存结果 | `false` |
| `FIRECRAWL_PROXY_MODE` | `basic` / `enhanced` / `auto` | `basic` |
| `FIRECRAWL_ALLOW_AUTO_PROXY` | 是否允许 auto proxy | `false` |
| `FIRECRAWL_ALLOW_ENHANCED_PROXY` | 是否允许 enhanced proxy | `false` |
| `FIRECRAWL_ZERO_DATA_RETENTION` | 请求 Firecrawl 零数据保留；hosted 账号需开通 ZDR | `false` |
| `FIRECRAWL_USE_FOR_MONITOR` | 是否允许监控任务默认使用 Firecrawl | `false` |
| `FIRECRAWL_USE_FOR_CATALOG` | 是否允许商品入库使用 Firecrawl | `true` |
| `FIRECRAWL_CATALOG_LIMIT` | Firecrawl Map 单次候选 URL 上限 | `50` |
| `CATALOG_DISCOVERY_STRATEGY` | 商品入库默认发现策略 | `local` |
| `CATALOG_SCRAPE_STRATEGY` | 商品入库默认抓取策略 | `browser` |
| `CATALOG_DEFAULT_FETCH_STRATEGY` | 入库后生成任务的默认采集策略 | `browser` |
| `CATALOG_DEFAULT_EXTRACTOR` | 商品入库默认解析器 | `generic_pricing_table` |
| `CATALOG_DEDUPE_POLICY` | 商品入库默认去重策略 | `by_url` |
| `CATALOG_MAX_DISCOVERED_URLS` | 商品入库默认发现 URL 上限 | `50` |
| `CATALOG_MAX_IMPORT_ITEMS` | 商品入库默认入库上限 | `50` |
| `CATALOG_TIMEOUT_SECONDS` | 商品入库抓取超时 | `25` |
| `CHROMIUM_HEADLESS` | Chromium 是否无头 | `true` |
| `CHROMIUM_BINARY` | Chromium 可执行文件路径 | 自动探测 |
| `CHROMIUM_USER_AGENT` | 覆盖浏览器和 `static_http` UA | 空 |
| `SESSION_COOKIE_SECURE` | Cookie 是否仅 HTTPS | HTTPS 部署建议 true |
| `LOGIN_RATE_LIMIT` | 登录限流 | `5 per minute` |
| `GENERAL_MUTATION_LIMIT` | 写操作限流 | `40 per minute` |
| `LIMITER_STORAGE_URI` | Flask-Limiter 存储 | 内存或 Redis |

安装脚本也支持 `DEPLOY_MODE`、`ACCESS_MODE`、`FQDN`、`CERT_MODE`、`CF_API_TOKEN`、`CERTBOT_EMAIL`、`PUBLIC_APP_PORT` 等变量做无人值守安装。

## 运维命令

快捷菜单：

```bash
noaff
```

原生 systemd：

```bash
systemctl status noaff-monitor --no-pager
journalctl -u noaff-monitor -f
systemctl restart noaff-monitor
sudo systemctl start noaff-monitor-upgrade.service
```

后台“升级”按钮默认会先判断当前 Web 进程是否有启动 systemd 服务的权限。没有权限时会显示手动命令，避免出现 `Interactive authentication required` 这类 systemd 认证错误。

如果需要在 Web 后台直接触发一键升级，原生安装时可显式开启：

```bash
ENABLE_PANEL_UPGRADE=true bash install.sh
```

开启后安装脚本会写入最小 polkit 授权规则：仅允许 NOAFF 服务用户启动 `noaff-monitor-upgrade.service`，不会授予重启其他服务或执行任意 systemd 操作的权限。已有安装也可以重新运行安装脚本并设置 `ENABLE_PANEL_UPGRADE=true` 来补齐授权；仅手工把 `.env` 里的 `PANEL_UPGRADE_ENABLED=true` 改开不会自动创建系统授权规则。

Docker：

```bash
cd /opt/noaff-monitor
docker compose ps
docker compose logs -f noaff
bash install.sh --docker-upgrade
```

重置后台密码：

```bash
cd /opt/noaff-monitor
bash install.sh --reset-password
```

静默重置：

```bash
cd /opt/noaff-monitor
RESET_ADMIN_USERNAME=operator RESET_ADMIN_PASSWORD='NewStrongPass123' bash install.sh --reset-password
```

查看首次引导凭据：

```bash
cat /opt/noaff-monitor/data/bootstrap_admin.txt
```

首次改密后建议删除：

```bash
rm -f /opt/noaff-monitor/data/bootstrap_admin.txt
```

卸载：

```bash
bash install.sh --uninstall
```

卸载会二次确认，默认保留数据目录。

## 本地开发

准备环境：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

启动 Flask 开发服务：

```bash
ADMIN_USERNAME=operator ADMIN_PASSWORD=operator-test flask --app app:app run --host 127.0.0.1 --port 7777
```

运行完整验证：

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py tests/test_app.py tests/test_install_script.py
node --check static/app.js
bash -n install.sh
```

当前完整回归基线：

- 152 tests passing
- Python compile check passing
- `static/app.js` syntax check passing
- `install.sh` bash syntax check passing

当前测试覆盖：

- 登录、CSRF、同源、AJAX 头、登录限流。
- 任务创建、编辑、分组、快照字段。
- 数据库迁移和备份恢复。
- `static_http`、`browser`、`generic_pricing_table`、`whmcs`。
- Firecrawl scrape/map/fallback pipeline 和连接诊断，全部使用 mock，不依赖实时 Firecrawl。
- Cloudflare challenge 分类、受保护来源冷却、浏览器不误 rebuild。
- Manual / Webhook 库存写入和 Telegram 状态机。
- 商品入库 URL 发现、Firecrawl Map、噪音过滤、商品预览、批量创建任务去重。
- 安装脚本、Docker、Nginx、升级、卸载。
- 前端轮询、任务卡片局部更新、UI 静态约束。

## 项目结构

```text
.
├── app.py
├── install.sh
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── assets/
│   └── noaff-logo.svg
├── docs/
│   ├── HANDOFF.md
│   ├── PR_DRAFT.md
│   └── RELEASE_NOTES.md
├── templates/
│   └── portal.html
├── static/
│   ├── app.css
│   └── app.js
└── tests/
    ├── test_app.py
    └── test_install_script.py
```

## 发布检查清单

- 普通 IDC / WHMCS 页面能通过合适策略监控。
- 页面正常可访问时能识别购买入口、售罄标记和库存数字。
- Cloudflare challenge 被识别为受保护来源，不触发浏览器 rebuild。
- 冷却期不会持续请求目标站。
- Firecrawl 使用 `maxAge=0`、默认不缓存，API Key 不出现在 snapshot / 日志 / 备份里。
- `manual` / `webhook` 能触发 Telegram send/edit/sold-out 行为。
- 快照、日志和数据库不泄露 webhook 明文 token。
- 不添加依赖实时公网商家页面的自动化测试。
- 本地验证命令全部通过：单元测试、Python 编译检查、`static/app.js` 语法检查、`install.sh` 语法检查。

## 贡献约定

- 新增商家解析逻辑时，请使用离线 HTML fixture 写测试。
- 不要提交绕过 Cloudflare / Turnstile / CAPTCHA 的实现。
- 不要把 live merchant 页面作为测试依赖。
- 不要在日志、快照、API 响应里暴露 token、secret 或 webhook 明文凭据。
- 优先保持 Flask + SQLite + DrissionPage + Telegram 的现有架构，避免不必要的大重写。
