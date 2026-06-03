<p align="center">
  <img src="assets/noaff-logo.svg" width="112" alt="NOAFF Logo">
</p>

<h1 align="center">NOAFF 补货监控助手</h1>

<p align="center">
  <strong>IDC / WHMCS 补货监控 + Telegram 状态机推送 + 安全 SaaS 面板</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-SaaS%20Panel-111827?style=for-the-badge&logo=flask&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white">
  <img alt="NOAFF" src="https://img.shields.io/badge/NOAFF-Public%20Good-10B981?style=for-the-badge">
</p>

> 🛰️ 面向公益无 AFF 补货提醒场景，专注精准切片、库存识别、Telegram 静默更新和高防护后台。

## 🚀 一键安装

推荐已有网站 / 已安装 Nginx 的机器使用 Docker 隔离模式，不接管宿主机 Nginx：

```bash
curl -fsSL https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/v1.0.6/install.sh -o install.sh && DEPLOY_MODE=docker PUBLIC_APP_PORT=7777 bash install.sh
```

想使用中文交互向导：

```bash
curl -fsSL "https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh?$(date +%s)" -o install.sh && bash install.sh
```

域名直连原生安装：

```bash
curl -fsSL "https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh?$(date +%s)" | ACCESS_MODE=domain-direct FQDN=monitor.example.com CERTBOT_EMAIL=ops@example.com bash
```

Cloudflare 小黄云 + Token 全自动安装：

```bash
curl -fsSL "https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh?$(date +%s)" | ACCESS_MODE=domain-cf FQDN=monitor.example.com CF_ZONE_NAME=example.com CF_API_TOKEN=cf_xxx CERTBOT_EMAIL=ops@example.com bash
```

预检模式，不安装依赖、不写系统服务：

```bash
ACCESS_MODE=domain-direct FQDN=monitor.example.com CERTBOT_EMAIL=ops@example.com bash install.sh --validate-only
```

## ✨ 核心能力

- 🧭 **精准切片**：命中商品关键词后只截取前 50 字符和后 1200 字符，隔离同页其他商品干扰。
- 🔎 **库存嗅探**：正则允许库存词与数字之间夹杂最多 40 个 HTML 标签或不可见片段。
- 📣 **Telegram 状态机**：刚补货发新消息，库存变化静默编辑，售罄覆盖原消息并清空 `message_id`。
- 🛡️ **后台防护**：隐藏入口、浏览器 UA 校验、同源校验、CSRF、AJAX 头校验和登录限流。
- 🧯 **浏览器自愈**：捕获 disconnected / timeout 后自动重建 Chromium。
- 🧪 **测试推送隔离**：主监控浏览器和测试推送浏览器使用不同调试端口。
- 🧰 **面板升级**：后台内置“系统升级”入口，原生安装会注册升级 service。

## 🧱 部署模式

| 模式 | 适合场景 | 是否接管 Nginx |
| --- | --- | --- |
| `DEPLOY_MODE=docker` | 机器已有网站、已有 Nginx、只想暴露高位端口 | 否 |
| `ACCESS_MODE=ip` | 临时测试，直接 IP + 端口访问 | 否 |
| `ACCESS_MODE=domain-direct` | 域名灰云直连源站，自动 HTTP-01 证书 | 写入独立 noaff 站点 |
| `ACCESS_MODE=domain-cf` | Cloudflare 小黄云，Token 可选，高级模式支持 DNS-01 | 写入独立 noaff 站点 |

⚠️ 原生 Nginx 模式只写入：

```text
/etc/nginx/sites-available/noaff-monitor.conf
/etc/nginx/sites-enabled/noaff-monitor.conf
```

不会删除默认站点，不会杀已有 nginx 进程。如果 80/443 已被占用，脚本会打印占用详情并退出。

## 🖥️ 面板功能

- 🎛️ 监控任务 CRUD
- 🧩 商品名称、监控链接、精准关键词、补货文案、售罄文案
- 🔗 两组 Telegram 底部透明按钮
- 🔐 管理员账号密码后台修改
- 📊 AJAX 无刷新轮询，骨架屏加载
- 🌑 深色 SaaS 风格 UI
- ⬆️ 后台系统升级入口

## 🔐 安全设计

- 隐藏控制台路径：默认生成高熵 `PORTAL_PATH`
- 禁止暴露 `/login`、`/admin`
- 登录接口默认 `5 per minute`
- 写操作必须携带浏览器 UA、同源 `Origin`、`X-Requested-With` 和 CSRF Token
- 生产模式建议开启 HTTPS 和 `SESSION_COOKIE_SECURE=true`
- `MONITOR_DEBUG_PORT` 与 `TEST_DEBUG_PORT` 必须不同

## 🧩 文案占位符

```text
{name}        商品名称
{stock}       当前库存
{url}         监控链接
{keyword}     精准关键词
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

## ⚙️ 常用变量

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `DEPLOY_MODE` | `native` / `docker` | `native` |
| `ACCESS_MODE` | `ip` / `domain-direct` / `domain-cf` | 交互选择 |
| `APP_PORT` | 应用监听端口 | `7777` |
| `PUBLIC_APP_PORT` | Docker 对外端口 | `APP_PORT` |
| `DOCKER_BIND_HOST` | Docker 绑定地址 | `0.0.0.0` |
| `FQDN` | 面板域名 | 空 |
| `CERT_MODE` | `http` / `dns` / `none` / `auto` | `auto` |
| `CF_API_TOKEN` | Cloudflare DNS-01 自动化时需要 | 空 |
| `CERTBOT_EMAIL` | 启用 HTTPS 时需要 | 空 |
| `MONITOR_DEBUG_PORT` | 主监控浏览器端口 | `9223` |
| `TEST_DEBUG_PORT` | 测试推送浏览器端口 | `9334` |

## 🛠️ 运维命令

原生模式：

```bash
systemctl status noaff-monitor --no-pager
journalctl -u noaff-monitor -f
systemctl restart noaff-monitor
systemctl start noaff-monitor-upgrade.service
```

Docker 模式：

```bash
cd /opt/noaff-monitor
docker compose ps
docker compose logs -f noaff
docker compose up -d --build
```

首次引导凭据：

```bash
cat /opt/noaff-monitor/data/bootstrap_admin.txt
```

首次改密后建议删除：

```bash
rm -f /opt/noaff-monitor/data/bootstrap_admin.txt
```

## 🧪 本地验证

```bash
python -m unittest discover -s tests -v
python -m py_compile app.py tests/test_app.py tests/test_install_script.py
bash -n install.sh
```

当前测试覆盖：隐藏入口、UA/CSRF/AJAX 校验、登录限流、任务创建、端口隔离、精准切片、库存解析、Telegram 状态机、Docker 预检和非破坏式 Nginx 处理。

## 📦 项目结构

```text
.
├── app.py
├── install.sh
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── assets/
│   └── noaff-logo.svg
├── templates/
│   └── portal.html
└── static/
    ├── app.css
    └── app.js
```

## 🧡 NOAFF

这个项目坚持 **NOAFF / 无推广返利**。
如果它帮你少蹲一次库存、少踩一次假补货，那它就完成了自己的工作。
