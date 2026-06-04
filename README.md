<p align="center">
  <img src="assets/noaff-logo.svg" width="112" alt="NOAFF Logo">
</p>

<h1 align="center">NOAFF 补货监控助手</h1>

<p align="center">
  <strong>IDC / WHMCS 补货监控 + Telegram 状态机推送 + 安全 SaaS 面板</strong>
</p>

<p align="center">🐍 Python 3.x · ⚗️ Flask · 🗄️ SQLite · 🐳 Docker · 📬 Telegram</p>

> 🛰️ 面向公益无 AFF 补货提醒场景，专注精准切片、库存识别、Telegram 静默更新和高防护后台。

<p align="center">
  <img src="ui-check/login-fresh-desktop.png" width="47%" alt="NOAFF 登录页预览">
  <img src="ui-check/dashboard-fresh-desktop.png" width="47%" alt="NOAFF 后台预览">
</p>

## 🚀 一键安装

普通用户只需要执行下面这一条命令：

```bash
curl -H 'Cache-Control: no-cache' -fsSL https://raw.githubusercontent.com/cshaizhihao/noaff-restock-monitor/master/install.sh -o install.sh && bash install.sh
```

脚本会自动进入 **全中文交互向导**，一步一步完成：

- 部署方式选择：`Docker 隔离` 或 `原生安装`
- 端口设置（IP / Docker 模式可用高位端口；域名模式固定使用标准 80/443）
- `IP + 端口`、`域名直连`、`Cloudflare 小黄云`
- HTTPS 证书方式
- Telegram 配置
- 安装摘要确认

默认推荐思路：

- 机器已经有网站 / 已经装了 Nginx：优先选 **Docker 隔离模式**
- 干净机器：可选 **原生安装**
- 没有域名：直接走 **IP + 端口**

安装器会根据机器环境和你的输入自动完成 Docker / 原生 / 域名 / Cloudflare 分流；如果系统尚未安装 Python 3，也会先自动补齐基础运行时。平时只保留上面的主命令即可，想改成无人值守时再用下方环境变量表覆盖默认值。

如果 Docker 模式填写域名，安装器会把公网地址输出为 `https://域名`，容器回源仍然是 `http://127.0.0.1:PUBLIC_APP_PORT`。

## ✨ 核心能力

- 🧭 **精准切片**：命中商品关键词后只截取前 50 字符和后 1200 字符，隔离同页其他商品干扰。
- 🔎 **库存嗅探**：正则允许库存词与数字之间夹杂最多 40 个 HTML 标签或不可见片段。
- 📣 **Telegram 状态机**：刚补货发新消息，库存变化静默编辑，售罄覆盖原消息并清空 `message_id`。
- 🛡️ **后台防护**：浏览器 UA 校验、同源校验、CSRF、AJAX 头校验和登录限流。
- 🧯 **浏览器自愈**：捕获 disconnected / timeout 后自动重建 Chromium。
- 🧪 **测试推送隔离**：主监控浏览器和测试推送浏览器使用不同调试端口。
- 🧰 **面板升级**：后台内置“系统升级”入口，原生安装会注册升级 service。

## 🧱 部署模式

| 模式 | 适合场景 | 是否接管 Nginx |
| --- | --- | --- |
| `Docker 隔离` | 机器已有网站、已有 Nginx、只想暴露高位端口 | 否 |
| `IP + 端口` | 临时测试，直接访问服务器 IP | 否 |
| `域名直连` | 域名灰云直连源站，自动 HTTP-01 证书 | 写入独立 noaff 站点 |
| `Cloudflare 小黄云` | 走 Cloudflare 代理，可选 Token 自动化 | 写入独立 noaff 站点 |

⚠️ 原生 Nginx 模式只写入：

```text
/etc/nginx/sites-available/noaff-monitor.conf
/etc/nginx/sites-enabled/noaff-monitor.conf
```

不会删除默认站点，不会杀已有 nginx 进程。如果 80/443 已被占用，脚本会打印占用详情并退出。

## 🖥️ 面板功能

- 🎛️ 监控任务 CRUD
- 🧩 商品名称、监控链接、精准关键词、补货文案、售罄文案
- 🏪 商家页面一键导入、来源同步与启停管理
- 🔗 两组 Telegram 底部透明按钮
- 🔐 管理员账号密码后台修改
- 📊 AJAX 无刷新轮询，骨架屏加载
- 🌑 深色 SaaS 风格 UI
- ⬆️ 后台系统升级入口

## 🔐 安全设计

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
| `CATALOG_DEBUG_PORT` | 商家导入浏览器端口 | `9445` |

域名模式会自动清理用户输入中的协议、端口和路径，例如 `https://monitor.example.com:20443/xxx` 会归一化为 `monitor.example.com`，最终面板地址固定输出为 `https://monitor.example.com`。

使用 `CERT_MODE=http` 时，Let's Encrypt 需要公网能访问域名的 `80/TCP`。如果验证失败，安装器会打印中文诊断，并可先关闭 HTTPS 继续完成 HTTP 安装；修复解析、防火墙或 Cloudflare 回源后重新运行脚本即可再次申请证书。

## 🛠️ 运维命令

快捷菜单：

```bash
noaff
```

菜单中包含状态、日志、重启、升级、重置后台密码，以及 **清理/卸载 NOAFF**。卸载会二次确认，默认保留 `/opt/noaff-monitor` 数据。

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
bash install.sh --docker-upgrade
```

忘记后台密码时：

```bash
cd /opt/noaff-monitor
bash install.sh --reset-password
```

如果安装中途失败导致 `noaff` 快捷命令还不可用，也可以直接用安装脚本清理：

```bash
bash install.sh --uninstall
```

也可以静默重置：

```bash
cd /opt/noaff-monitor
RESET_ADMIN_USERNAME=operator RESET_ADMIN_PASSWORD='NewStrongPass123' bash install.sh --reset-password
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

当前测试覆盖：根路径面板、UA/CSRF/AJAX 校验、登录限流、任务创建、端口隔离、精准切片、库存解析、Telegram 状态机、Docker 预检和非破坏式 Nginx 处理。

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
