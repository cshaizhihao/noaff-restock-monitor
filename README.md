<p align="center">
  <img src="assets/noaff-logo.svg" width="112" alt="NOAFF Logo">
</p>

<h1 align="center">NOAFF Restock Monitor</h1>

<p align="center">
  公益 NOAFF IDC 补货监控应用：公开页面采集、规则解析、Telegram 状态机推送。
</p>

<p align="center">
  Python 3 · Flask · SQLite · Scrapling · Telegram · Docker
</p>

## 项目定位

NOAFF Restock Monitor 用来监控 IDC、VPS、独服、WHMCS 商店等公开商品页面的补货状态，并把状态变化推送到 Telegram。

很多 IDC 商品页没有官方库存 API，所以项目主路线是：

```text
公开页面采集 -> 页面/规则解析 -> 库存状态机 -> Telegram send/edit/sold-out 推送
```

当前版本采用 **Data Collector + Multi-engine-first** 采集架构：

- `multi_engine` 是默认采集策略：先用 `curl_cffi` 做低成本浏览器指纹 HTTP 抓取，失败后再升级到本地浏览器增强链路。
- Scrapling 仍是本地浏览器增强层，用于标准、增强、高兼容模式。
- Data Collector 层统一封装 `direct`、`curl_cffi`、`external_solver`、`webhook`、`manual`，后续增加采集后端不再直接污染监控状态机。
- 外部增强采集服务可以通过 `ENHANCED_COLLECTOR_API_URL` 接入，用于个人自建的增强采集服务；默认不启用，不作为内置挑战绕过。
- Firecrawl 保留为外部兜底/诊断能力，不再作为定时监控首选。
- 旧 `browser`、`static_http`、Firecrawl pipeline 任务会在升级时平滑迁移到多引擎或本地增强策略。
- `manual` / `webhook` 仍是完全受保护页面的可靠兜底方案。

项目边界：

- 只监控公开可访问页面。
- 不实现 Cloudflare / Turnstile / CAPTCHA 绕过。
- 不接入打码服务。
- 不模拟真人过验证。
- 遇到 challenge 页面时，标记为 `cloudflare_challenge` / protected source，进入冷却，不反复打站点。
- 对无法稳定公开访问的页面，建议使用 `manual`、`webhook` 或替代公开页面。

这个项目坚持 NOAFF / 无推广返利。它适合做公开、透明、低打扰的补货提醒，而不是绕过工具。

## 功能概览

- Multi-engine-first 采集：智能多引擎、TLS 指纹 HTTP、标准、增强、高兼容。
- 可配置解析规则：自动卡片、CSS selector、XPath、正则、关键词附近文本、JSON path。
- IDC 页面解析：围绕目标关键词查找附近 card / table / section，识别库存数字、购买入口和售罄标记。
- WHMCS 解析：支持常见商店页、`pid`、`cart.php?gid=xx`、`configureproduct`、`Order Now`、`Out of Stock`。
- 域名级调度：同域/同 URL 在同一轮内复用抓取结果，减少重复请求和高级模式消耗。
- 受保护来源冷却：Cloudflare challenge 按 1 / 3 / 10 分钟递进冷却。
- 外部增强采集：支持配置通用 solver endpoint，作为可选采集后端和健康检查入口。
- Firecrawl 外部兜底：保留连接诊断、商品入库辅助和个别复杂页面手动兜底。
- 商品入库工作台：填页面 -> 自动发现 -> 预览确认 -> 创建任务。
- 商品入库降噪：语言切换、导航、页脚、步骤标题、无价格/无规格候选会降级到人工确认。
- 分组管理：主分组、多级子分组、重命名、删除、拖拽排序、批量移动、批量删除。
- Telegram 状态机：补货发新消息，库存变化编辑原消息，售罄覆盖原消息并清空 `message_id`。
- Manual / Webhook 数据源：没有可抓页面时，也能用后台手动标记或外部系统推送库存。
- 管理后台：任务管理、商品入库、系统设置、活动日志、备份恢复、管理员改密。
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
- Python 依赖、Scrapling runtime、应用健康检查。

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

## 采集模式

后台面向普通用户展示的是易懂模式，不需要理解底层 fetcher 名称：

| UI 模式 | 内部策略 | 适合场景 | 成本/资源 |
| --- | --- | --- | --- |
| 智能多引擎 | `multi_engine` | 默认推荐，curl_cffi -> standard -> dynamic -> stealth | 先低成本，按需升级 |
| TLS 指纹 HTTP | `curl_cffi` | 普通公开页面、轻度反爬、无需 JS | 最低，不启动浏览器 |
| 标准采集 | `scrapling_standard` | 普通公开 HTML、WHMCS、轻量 IDC 页面 | 低 |
| 增强渲染 | `scrapling_dynamic` | JS 渲染页面、按钮/内容由前端生成 | 中 |
| 高兼容浏览器 | `scrapling_stealth` | 复杂页面、轻度反爬、需要更高兼容性 | 高，低并发 |
| 手动 | `manual` | 没有稳定公开页面 | 不抓取 |
| Webhook | `webhook` | 外部系统知道库存 | 不抓取 |
| 外部兜底 | `firecrawl` | 个别页面诊断或人工触发兜底 | 消耗 Firecrawl credits |

新任务默认使用 `multi_engine`。旧任务升级时会自动迁移：

| 旧策略 | 迁移后 |
| --- | --- |
| `browser` | `scrapling_dynamic` |
| `static_http` | `curl_cffi` |
| `adaptive` | `multi_engine` |
| `firecrawl` / Firecrawl pipeline | `scrapling_stealth` |
| `generic_pricing_table` / `whmcs` | `multi_engine`，并保留原解析器到 `source_config.extractor` |
| `manual` / `webhook` | 保持不变 |

迁移只执行一次。迁移后如果你手动选择旧兼容策略，系统不会在下次启动时再次覆盖。

## 解析规则

解析优先级：

1. 用户显式规则
2. Scrapling selector / 自适应选择器
3. 商品卡片附近解析
4. WHMCS 规则
5. 通用关键词规则
6. unknown

支持的 `source_config` 字段：

| 字段 | 用途 |
| --- | --- |
| `stock_rule_type` | `auto_card` / `css_selector` / `xpath` / `regex` / `text_near_keyword` / `json_path` |
| `target_scope_selector` | 限定目标商品卡片范围 |
| `stock_selector` | 指向库存数字或有货文本 |
| `soldout_selector` | 指向售罄文本或禁用按钮 |
| `button_selector` | 指向购买/下单按钮 |
| `disabled_selector` | 指向 disabled / sold-out 状态 |
| `in_stock_keywords` | 自定义有货关键词 |
| `soldout_keywords` | 自定义售罄关键词 |
| `regex_pattern` | 正则提取库存数字 |
| `json_path` | 从页面 JSON 数据中提取库存 |

常见有货信号：

```text
Order Now, Buy Now, Configure, Available, Add to Cart, Continue, 下单, 购买, 继续
```

常见售罄信号：

```text
Out of Stock, Sold Out, Unavailable, disabled, 缺货, 售罄, 无货
```

如果同一页面有多个产品，尽量把 `target_keyword` 写成目标产品独有的完整标题，避免误判到相邻产品。

## Data Collector 层

采集层已经从“任务直接调用某个 fetcher”收敛成 Data Collector：

| Collector | 内部策略 | 用途 |
| --- | --- | --- |
| `direct` | `static_http` / legacy direct | 兼容旧任务 |
| `curl_cffi` | browser-fingerprint HTTP | 低成本公开页面采集 |
| `external_solver` | 外部增强采集服务 | 可选自建服务，不默认参与定时 |
| `webhook` | 外部系统写入库存 | 完全不抓目标站 |
| `manual` | 后台手动标记库存 | 完全不抓目标站 |

`external_solver` 只接入用户自己配置的外部服务地址。NOAFF 不内置挑战求解，也不会在没有显式配置时自动调用外部服务。

最小配置：

```env
ENHANCED_COLLECTOR_ENABLED=false
ENHANCED_COLLECTOR_API_URL=
ENHANCED_COLLECTOR_USE_FOR_MONITOR=false
ENHANCED_COLLECTOR_USE_FOR_CATALOG=true
```

后台“外部兜底”页可以做一次连接检测；检测不会把密钥或敏感配置写入日志/snapshot。

## 商品入库

商品入库适合 IDC 商家没有公开 API、但有公开价格页 / WHMCS 商店页 / sitemap / 商品列表页的场景。当前工作流是：

```text
填页面 -> 自动发现 -> 预览确认 -> 创建任务
```

默认路径是多引擎优先：

- discovery 默认 `local`，从入口页和链接关系发现候选 URL。
- scrape 默认 `multi_engine`。
- 创建任务默认 `multi_engine`。
- 普通用户只需要填商家页面、分组和可选目标关键词。
- 自动 / JS 页面 / 高兼容三个预设会同步底层发现、抓取、任务采集和解析器配置。
- 高级采集参数、去重策略、URL 上限、超时等折叠在高级区，默认不打扰用户。
- Firecrawl Map/Scrape 只作为外部兜底选项，不默认消耗 credits。

工作台会先发现候选 URL，再让你抓取选中 URL，最后在商品预览里确认可入库商品。默认不会把语言切换、导航、页脚、分类/步骤标题、无价格/无规格候选直接写入任务；这些内容会进入“需要人工确认 / 已过滤候选”。

工作台字段：

| 字段 | 说明 |
| --- | --- |
| 商家 URL | 入口页，例如 pricing、store、cart.php?gid=xx |
| 采集预设 | 自动推荐 / JS 页面 / 高兼容 |
| discovery strategy | 默认 `local`，高级区可调 |
| scrape strategy | 默认 `multi_engine`，高级区可调 |
| extractor | `generic_pricing_table` / `whmcs` / `fallback_keyword_parser` / `firecrawl_product_hint` |
| target keyword | 可选目标商品关键词，建议用完整产品名 |
| dedupe policy | 高级区：`by_url` / `by_title_url` / `by_pid` |
| include sold out | 是否把售罄商品也放进入库预览 |
| auto create tasks | 是否导入后直接生成监控任务 |

批量创建任务会按 `source_item_id` 去重；重复执行只会同步已有任务，不会重复创建。

## 分组和移动

任务页采用分层工作台：

```text
主分组 -> 子分组 -> 多级子分组 -> 当前层商品
```

支持：

- 创建主分组和子分组。
- 子分组重命名、删除、进入。
- 当前层卡片拖拽排序。
- 商品多选删除。
- 商品单个或批量移动到任意主分组 / 子分组。
- 移动到不存在的目标分组时自动创建。
- 移动后保留库存状态、Telegram `message_id`、source metadata 和排序信息。

跨层移动请使用“移动到...”弹窗；拖拽只负责当前层排序。

## Firecrawl 外部兜底

Firecrawl 是可选外部采集后端，不是项目硬依赖。当前项目不建议把 Firecrawl 用于高频定时监控，因为它会消耗 credits。

推荐用法：

- 商品入库或人工诊断时使用。
- 个别复杂页面可以手动选择 Firecrawl 外部兜底。
- 实时监控默认 `FIRECRAWL_USE_FOR_MONITOR=false`。
- 库存监控必须使用 `FIRECRAWL_MAX_AGE_MS=0` 和 `FIRECRAWL_STORE_IN_CACHE=false`，避免缓存旧库存。

API Key 只保存在后端，snapshot、备份、日志和前端响应不会返回明文。后台 Firecrawl 页面提供连接诊断，使用当前表单配置做一次最小 scrape 测试；测试不会保存 Key。

Hosted Firecrawl 可能提升复杂页面成功率，但页面内容会发送给外部服务，且 enhanced / auto proxy 可能产生额外费用。Self-host Firecrawl 不包含 hosted 版 Fire-engine 等高级 IP block / robot detection 能力，不能把它当成 Cloudflare 绕过能力。

如果 Firecrawl 返回正常页面内容，本项目会继续解析；如果返回 Cloudflare / Turnstile / CAPTCHA challenge，仍会分类为 `cloudflare_challenge` 并进入受保护来源冷却。

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
- 不请求 Firecrawl。
- 不改变库存状态。
- 不发送 Telegram。

这不是绕过失败，而是项目边界。对这类站点，建议改用：

- 商家公开 RSS / 状态页 / 静态价格页。
- `manual` 后台手动维护。
- `webhook` 接入你自己的合法库存来源。
- 替代公开页面。

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

## 环境变量

核心配置：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `APP_PORT` | 面板监听端口 | `7777` |
| `APP_HOST` | 面板监听地址 | `127.0.0.1` |
| `POLL_INTERVAL_SECONDS` | 定时轮询间隔 | `45` |
| `REQUEST_TIMEOUT_SECONDS` | 通用请求超时 | `25` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 空 |
| `TELEGRAM_CHAT_IDS` | 多个 Chat ID，一行或逗号分隔 | 空 |
| `LIMITER_STORAGE_URI` | 限流存储 | `redis://127.0.0.1:6379/0` |

Scrapling：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `SCRAPLING_ENABLED` | 启用 Scrapling | `true` |
| `SCRAPLING_DEFAULT_MODE` | 默认模式：`standard` / `dynamic` / `stealth` | `standard` |
| `SCRAPLING_USE_FOR_MONITOR` | 用于定时监控 | `true` |
| `SCRAPLING_USE_FOR_CATALOG` | 用于商品入库 | `true` |
| `SCRAPLING_TIMEOUT_STANDARD` | 标准模式超时 | `25` |
| `SCRAPLING_TIMEOUT_DYNAMIC` | 增强模式超时 | `45` |
| `SCRAPLING_TIMEOUT_STEALTH` | 高兼容模式超时 | `75` |
| `SCRAPLING_MAX_CONCURRENCY_STEALTH` | 高兼容并发 | `1` |
| `SCRAPLING_SESSION_REUSE` | 复用站点会话 | `true` |
| `SCRAPLING_ADAPTIVE_SELECTOR` | 启用自适应选择器 | `true` |

Firecrawl：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `FIRECRAWL_ENABLED` | 启用外部兜底 | `false` |
| `FIRECRAWL_API_URL` | API 地址 | `https://api.firecrawl.dev` |
| `FIRECRAWL_API_KEY` | API Key | 空 |
| `FIRECRAWL_MAX_AGE_MS` | 缓存年龄，库存监控必须为 0 | `0` |
| `FIRECRAWL_STORE_IN_CACHE` | 是否存入 Firecrawl 缓存 | `false` |
| `FIRECRAWL_USE_FOR_MONITOR` | 是否允许定时监控使用 | `false` |
| `FIRECRAWL_USE_FOR_CATALOG` | 是否允许商品入库使用 | `true` |

商品入库：

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `CATALOG_DISCOVERY_STRATEGY` | 默认发现策略 | `local` |
| `CATALOG_SCRAPE_STRATEGY` | 默认抓取策略 | `multi_engine` |
| `CATALOG_DEFAULT_FETCH_STRATEGY` | 创建任务默认策略 | `multi_engine` |
| `CATALOG_DEFAULT_EXTRACTOR` | 默认解析器 | `generic_pricing_table` |
| `CATALOG_DEDUPE_POLICY` | 默认去重策略 | `by_url` |

完整配置见 `.env.example`。

## 运维和升级

原生安装：

```bash
sudo systemctl status noaff-monitor
sudo systemctl restart noaff-monitor
sudo journalctl -u noaff-monitor -n 100 --no-pager
```

如果启用了面板一键升级，后台可以直接触发 systemd upgrade service；否则后台会显示手动升级命令。

升级脚本会：

- `git pull --ff-only`
- 安装 `requirements.txt`
- 检测 Scrapling runtime
- 重启服务

如果遇到 Git `dubious ownership`，新版安装/升级脚本会自动配置 safe.directory。老版本可手动执行：

```bash
git config --global --add safe.directory /opt/noaff-monitor
```

## 验证

开发验证：

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile app.py tests/test_app.py tests/test_install_script.py
node --check static/app.js
bash -n install.sh
git diff --check
```

当前基线：

- 177 tests passing
- Python compile check passing
- `static/app.js` syntax check passing
- `install.sh` bash syntax check passing

## 发布检查

- 新建智能多引擎任务，确认普通 IDC 页面可识别有货/售罄。
- 用 CSS selector / XPath / 正则各创建一个规则任务，确认状态机正常。
- 商品入库跑一次 local discovery -> Scrapling preview -> 批量创建。
- 分组、子分组、移动、批量删除、拖拽排序各 smoke test 一次。
- Firecrawl 设置页用有效/无效 key 各跑一次诊断，确认不泄露 key。
- 手动任务点击有货/售罄，确认 Telegram send/edit/sold-out。
- Webhook 任务 reset token 后 POST `stock` 和 `status=sold_out`。
- 用 Cloudflare challenge fixture 或受保护页面确认进入 cooldown，且冷却期不请求目标站。
- 确认 snapshot、日志、备份不包含 Firecrawl API key 或 webhook plaintext token。
