# NOAFF补货监控助手

面向 IDC / WHMCS 多商品列表页的补货监控 SaaS 面板。项目坚持 NOAFF 公益属性，重点解决 Cloudflare 场景抓取、目标商品精准识别、Telegram 状态机推送，以及生产环境下的安全部署。

仓库地址：

- [GitHub 仓库](https://github.com/cshaizhihao/noaff-restock-monitor)
- [一键安装脚本 `install.sh`](https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh)

## 功能概览

- 隐蔽控制台入口：默认使用高熵 `PORTAL_PATH`，不暴露 `/login`、`/admin`
- 登录限流：`Flask-Limiter` 默认 `5 per minute`
- 请求头校验：写操作要求浏览器 UA、同源 `Origin`、`X-Requested-With`、CSRF Token
- 深色 SaaS 面板：Tailwind CDN + Vanilla JS，AJAX 无刷轮询，登录页和后台已替换为新版 UI
- SQLite 管理员凭据：首次启动自动引导，面板内可安全修改账号密码
- 任务 CRUD：商品名称、监控链接、精准关键词、补货文案、售罄文案、2 组 Telegram 底部按钮
- DrissionPage 反爬：主监控与测试推送分离调试端口，避免互相拖垮
- 精准切片：命中关键词后只截取前 50 字符和后 1200 字符
- 库存正则嗅探：允许库存词和数字之间夹杂最多 40 个 HTML 标签或不可见片段
- 崩溃自愈：浏览器 `disconnected` / `Timeout` 自动重建
- Telegram 状态机：
  - 刚补货：发送新消息
  - 库存变动：静默 `editMessageText`
  - 已售罄：覆盖原消息为售罄文案，并清空 `message_id`

## 项目结构

```text
.
├── app.py
├── install.sh
├── requirements.txt
├── .env.example
├── templates/
│   └── portal.html
└── static/
    ├── app.css
    └── app.js
```

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

首次启动后访问：

```text
http://127.0.0.1:7777/<你的 PORTAL_PATH>
```

注意：

- `http://127.0.0.1:7777/` 返回 `404` 是设计行为，不是故障
- `.env.example` 默认保留 `SESSION_COOKIE_SECURE=false`，方便本地 HTTP 调试；生产安装脚本会默认写成 `true`
- 如果没有手动设置 `ADMIN_PASSWORD`，系统会把一次性初始凭据写到 `data/bootstrap_admin.txt`
- 首次登录后请立刻在面板里修改密码，并删除 `data/bootstrap_admin.txt`

## 文案占位符

```text
{name}        商品名称
{stock}       当前库存
{url}         监控链接
{keyword}     精准狙击关键词
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

## 自动化验证

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py tests/test_app.py
bash -n install.sh
bash install.sh --help
```

测试覆盖隐藏入口、浏览器 UA 校验、CSRF / AJAX 写操作拦截、登录限流、任务创建、端口隔离校验、管理员重名处理、精准切片、库存解析，以及安装脚本的 Cloudflare JSON 解析、代理端口校验和预检模式。

## 生产部署说明

推荐部署形态：

1. Cloudflare 小黄云代理域名
2. Nginx 暴露公网端口并反代到本机 `127.0.0.1:APP_PORT`
3. Waitress 仅监听本机高位端口
4. `certbot-dns-cloudflare` 通过 DNS-01 申请证书
5. `redis-server` 作为 Flask-Limiter 存储
6. `systemd` 守护 Flask 应用与证书续期

安装脚本会自动完成：

- 安装 `nginx`、`redis-server`、`xvfb`、`chromium`、Python 运行时
- 拉取或更新 GitHub 仓库
- 创建虚拟环境并安装依赖
- 自动写入或保留现有 `.env`
- 域名直连模式下通过 HTTP-01 自动申请 / 续签证书
- Cloudflare Token 模式下自动创建 / 更新 `FQDN` 与 `TLS_DOMAINS` 的 A/AAAA 记录
- 小黄云模式下可写入 Cloudflare Real IP 与源站锁定规则
- 自动注册 `systemd` 服务、升级服务与证书续期任务

## 一键安装

在 Linux VDS 上以 `root` 运行：

交互安装版，推荐普通用户使用：

```bash
curl -fsSL "https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh?$(date +%s)" | bash
```

脚本会进入全中文向导，依次选择：

- 应用本机端口
- `IP + 端口`、`域名直连` 或 `Cloudflare 小黄云`
- 是否自动申请 HTTPS 证书
- 是否提供 Cloudflare Token 开启 DNS-01 全自动模式
- 是否现在填写 Telegram 配置

静默安装版，适合已经准备好域名和参数的用户：

```bash
curl -fsSL "https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh?$(date +%s)" | ACCESS_MODE=domain-direct FQDN=monitor.example.com CERTBOT_EMAIL=ops@example.com bash
```

Cloudflare 小黄云 + Token 全自动版：

```bash
curl -fsSL "https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh?$(date +%s)" | ACCESS_MODE=domain-cf FQDN=monitor.example.com CF_ZONE_NAME=example.com CF_API_TOKEN=cf_xxx CERTBOT_EMAIL=ops@example.com bash
```

一行预检版，不会安装依赖或写系统服务：

```bash
curl -fsSL "https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh?$(date +%s)" | ACCESS_MODE=domain-direct FQDN=monitor.example.com CERTBOT_EMAIL=ops@example.com bash -s -- --validate-only
```

如果你想先保存脚本再运行：

```bash
curl -fsSL https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh -o install.sh
chmod +x install.sh
```

也可以使用复制粘贴版引导脚本。它会用 `cat << 'EOF'` 在当前目录生成 `noaff-install.sh`，再从公开仓库拉取最新 `install.sh` 并执行：

```bash
cat > noaff-install.sh << 'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_URL="${INSTALL_URL:-https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh}"
curl -fsSL "$INSTALL_URL" -o install.sh
chmod +x install.sh
exec bash install.sh "$@"
EOF

chmod +x noaff-install.sh
```

最小示例：

```bash
ACCESS_MODE=domain-direct \
FQDN=monitor.example.com \
CERTBOT_EMAIL=ops@example.com \
bash install.sh
```

使用引导脚本时，把最后一行换成：

```bash
./noaff-install.sh
```

正式安装前可以先跑预检模式。它只校验必要变量、TLS 域名和 Cloudflare 小黄云可代理端口，不会安装 apt 依赖、写入 Nginx 或注册 systemd：

```bash
ACCESS_MODE=domain-direct \
FQDN=monitor.example.com \
CERTBOT_EMAIL=ops@example.com \
bash install.sh --validate-only
```

常用自定义示例：

```bash
ACCESS_MODE=domain-cf \
FQDN=monitor.example.com \
TLS_DOMAINS=monitor.example.com,www.monitor.example.com \
CF_ZONE_NAME=example.com \
CF_API_TOKEN=cf_xxx \
CERTBOT_EMAIL=ops@example.com \
APP_PORT=7777 \
PUBLIC_HTTP_PORT=80 \
PUBLIC_HTTPS_PORT=443 \
MONITOR_DEBUG_PORT=9223 \
TEST_DEBUG_PORT=9334 \
ADMIN_USERNAME=operator \
TELEGRAM_BOT_TOKEN=123456:ABCDEF \
TELEGRAM_CHAT_ID=-1001234567890 \
bash install.sh
```

安装完成后，脚本会输出：

- 面板完整地址
- 隐蔽入口 `PORTAL_PATH`
- 当前管理员用户名
- 首次引导密码或“沿用现有密码”的说明
- 后台“系统升级”入口会调用 `noaff-monitor-upgrade.service` 完成后续版本升级

## 关键变量

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `ACCESS_MODE` | 安装模式：`ip` / `domain-direct` / `domain-cf` | 交互选择 |
| `FQDN` | 面板主域名，域名模式必填 | 无 |
| `TLS_DOMAINS` | 逗号分隔的附加证书域名 | `FQDN` |
| `CERT_MODE` | 证书模式：`http` / `dns` / `none` / `auto` | `auto` |
| `CF_ZONE_NAME` | Cloudflare Zone 名称，DNS-01 自动模式需要 | 无 |
| `CF_ZONE_ID` | Cloudflare Zone ID，可替代 `CF_ZONE_NAME` | 无 |
| `CF_API_TOKEN` | Cloudflare API Token，仅 DNS-01 全自动模式需要 | 无 |
| `CERTBOT_EMAIL` | Let's Encrypt 邮箱，启用 HTTPS 时需要 | 无 |
| `APP_PORT` | Flask / Waitress 本机监听端口 | `7777` |
| `APP_HOST` | Flask / Waitress 监听地址 | `127.0.0.1` |
| `PUBLIC_HTTP_PORT` | Nginx 暴露的 HTTP 端口 | `80` |
| `PUBLIC_HTTPS_PORT` | Nginx 暴露的 HTTPS 端口 | `443` |
| `MONITOR_DEBUG_PORT` | 主监控浏览器调试端口 | `9223` |
| `TEST_DEBUG_PORT` | 测试推送浏览器调试端口 | `9334` |
| `CF_RECORD_PROXIED` | Cloudflare 是否开启代理 | `true` |
| `CF_SSL_MODE` | Cloudflare SSL 模式 | `strict` |
| `ORIGIN_LOCKDOWN_TO_CLOUDFLARE` | 是否只允许 Cloudflare 回源 | `true` |
| `LETSENCRYPT_STAGING` | 证书调试模式 | `false` |
| `REPO_URL` | 仓库地址 | 当前 GitHub 仓库 |
| `REPO_REF` | 部署分支 | `master` |

## Cloudflare Token 权限

Cloudflare Token 不是普通安装必填项。只有你选择 `ACCESS_MODE=domain-cf` 并使用 `CERT_MODE=dns` 时，脚本才会访问 Zone、DNS 和 SSL 设置接口。建议令牌最少具备：

- `Zone / Zone / Read`
- `Zone / DNS / Edit`
- `Zone / Settings / Edit`

如果你不想让脚本自动切换 Cloudflare SSL 模式，可以删掉 `Zone / Settings / Edit`，然后手动把 SSL/TLS 模式改为 `Full (strict)`。

## 端口建议

Cloudflare 小黄云最稳妥的公网端口仍然是 `80 / 443`。脚本支持自定义 `PUBLIC_HTTP_PORT` 和 `PUBLIC_HTTPS_PORT`，但当 `CF_RECORD_PROXIED=true` 时，只能使用 Cloudflare 支持的代理端口：

- HTTP：`80 8080 8880 2052 2082 2086 2095`
- HTTPS：`443 2053 2083 2087 2096 8443`

建议理解为两层端口：

- `APP_PORT`：应用本机监听端口，推荐继续使用高位端口 `7777`
- `PUBLIC_HTTP_PORT` / `PUBLIC_HTTPS_PORT`：公网入口端口，推荐保持 `80 / 443`

## 安装后文件与服务

- 应用目录：`/opt/noaff-monitor`
- 环境文件：`/opt/noaff-monitor/.env`
- 数据目录：`/opt/noaff-monitor/data`
- Flask 服务：`noaff-monitor.service`
- 证书续期服务：`noaff-monitor-cert-renew.service`
- 证书续期定时器：`noaff-monitor-cert-renew.timer`
- Nginx 站点：`/etc/nginx/sites-available/noaff-monitor.conf`

## 常用运维命令

```bash
systemctl status noaff-monitor --no-pager
journalctl -u noaff-monitor -f
systemctl restart noaff-monitor
systemctl restart nginx
systemctl status redis-server --no-pager
systemctl list-timers | grep noaff-monitor
```

查看当前配置：

```bash
cat /opt/noaff-monitor/.env
```

查看首次引导凭据：

```bash
cat /opt/noaff-monitor/data/bootstrap_admin.txt
```

首次改密后删除：

```bash
rm -f /opt/noaff-monitor/data/bootstrap_admin.txt
```

## 安全建议

- 不要把 `.env`、`data/`、SQLite 数据库提交到 GitHub
- `PORTAL_PATH` 保持随机高熵，不要改成 `/login`、`/admin`
- 面板实际写操作依赖浏览器请求头与 CSRF，脚本直打接口会被拒绝
- `MONITOR_DEBUG_PORT` 与 `TEST_DEBUG_PORT` 必须不同
- 默认源站仅允许 Cloudflare 回源；如果你关闭 `ORIGIN_LOCKDOWN_TO_CLOUDFLARE`，请自行补防火墙
- 生产环境建议保持 `SESSION_COOKIE_SECURE=true`

## 仓库重新设为私有时

当前仓库已经是公开仓库，可以直接使用上面的 `curl` 命令。如果以后重新切回私有仓库，安装脚本仍然支持：

```bash
GH_TOKEN=github_pat_xxx \
REPO_URL=https://github.com/cshaizhihao/noaff-restock-monitor.git \
bash install.sh
```

## 故障排查

- 访问域名返回 522/523：先检查 Cloudflare DNS 是否回源到正确 IP，再看防火墙与 Nginx
- 面板打不开但服务运行：确认访问的是脚本输出的隐藏 `PORTAL_PATH`
- 直接访问根路径得到 404：这是正常行为
- 证书申请失败：确认域名已托管到 Cloudflare，Token 权限完整，邮箱有效
- 登录频繁失败：默认每 IP 每分钟最多 5 次
- Telegram 推送失败：确认 Bot Token、Chat ID、群组权限和 Bot 入群状态
- 库存识别不准：优先优化精准关键词，再检查目标 HTML 片段
