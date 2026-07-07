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

- 多采集策略：`browser`、`static_http`、`generic_pricing_table`、`whmcs`、`manual`、`webhook`。
- IDC 页面解析：围绕目标关键词查找附近 card / table / section，识别库存数字、购买入口和售罄标记。
- WHMCS 解析：支持常见商店页、`pid`、`cart.php?gid=xx`、`configureproduct`、`Order Now`、`Out of Stock`。
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
| `manual` | 没有稳定公开来源 | 后台手动标记有货 / 售罄，复用 Telegram 状态机 |
| `webhook` | 外部系统知道库存 | 外部 POST 库存状态，复用 Telegram 状态机 |

默认策略是 `browser`，旧任务无需手动迁移。

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
- 分组管理和分组重命名。
- 采集策略选择。
- 受保护来源提示和冷却时间展示。
- Manual 快捷标记。
- Webhook endpoint、token hint 和 token 重置。
- 商家页面导入、来源同步、来源启停、商品生成任务。
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

后台“升级”按钮默认会先判断当前 Web 进程是否有启动 systemd 服务的权限。没有权限时会显示手动命令，避免出现 `Interactive authentication required` 这类 systemd 认证错误。需要从面板直接触发 systemd 升级时，可在确认授权方案后设置 `PANEL_UPGRADE_ENABLED=true`。

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
bash -n install.sh
```

当前测试覆盖：

- 登录、CSRF、同源、AJAX 头、登录限流。
- 任务创建、编辑、分组、快照字段。
- 数据库迁移和备份恢复。
- `static_http`、`browser`、`generic_pricing_table`、`whmcs`。
- Cloudflare challenge 分类、受保护来源冷却、浏览器不误 rebuild。
- Manual / Webhook 库存写入和 Telegram 状态机。
- 商家页面导入和商品提升为任务。
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
- `manual` / `webhook` 能触发 Telegram send/edit/sold-out 行为。
- 快照、日志和数据库不泄露 webhook 明文 token。
- 不添加依赖实时公网商家页面的自动化测试。
- 本地验证三条命令全部通过。

## 贡献约定

- 新增商家解析逻辑时，请使用离线 HTML fixture 写测试。
- 不要提交绕过 Cloudflare / Turnstile / CAPTCHA 的实现。
- 不要把 live merchant 页面作为测试依赖。
- 不要在日志、快照、API 响应里暴露 token、secret 或 webhook 明文凭据。
- 优先保持 Flask + SQLite + DrissionPage + Telegram 的现有架构，避免不必要的大重写。
