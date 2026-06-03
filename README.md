# NOAFF 补货监控助手

一个面向 IDC / WHMCS 多商品列表页的私有补货监控面板。项目坚持 NOAFF 公益属性，核心目标是稳定绕过 Cloudflare 场景抓取、精准识别指定商品库存，并通过 Telegram 状态机推送补货、库存变化和售罄状态。

## 核心能力

- 隐蔽控制台入口：默认生成高熵 `PORTAL_PATH`，避免 `/login`、`/admin` 这类扫描热点。
- 严格登录限流：`Flask-Limiter` 默认 `5 per minute`，降低字典爆破风险。
- 请求头与 CSRF 防护：所有写操作必须带浏览器 UA、同源 Origin、`X-Requested-With` 和内部 CSRF Token。
- 高位端口绑定：默认 `7777`，支持 `.env` 自定义。
- SQLite 管理员凭据：首次启动自动生成初始账号，面板内可改用户名和密码。
- 任务 CRUD：商品名称、监控链接、精准关键词、TG 补货文案、售罄文案、2 个 Telegram 底部透明按钮。
- DrissionPage 反爬引擎：主监控和测试推送使用不同远程调试端口，测试不会拖垮后台轮询。
- 精准切片算法：命中关键词后，仅截取关键词前 50 字符和后 1200 字符，隔离同页其他商品干扰。
- 库存正则嗅探：支持中文 / English 库存词，并容忍最多 40 个 HTML 标签或不可见片段。
- 崩溃自愈：`disconnected`、`Timeout` 等异常会重建 Chromium 控制链路。
- Telegram 状态机：刚补货发新消息，库存变动静默编辑，售罄覆盖原消息并清空 `message_id`。

## 项目结构

```text
.
├── app.py                 # Flask 后端、数据库、监控引擎、TG 状态机
├── requirements.txt       # Python 依赖
├── install.sh             # Linux VDS 一键安装脚本
├── .env.example           # 环境变量模板
├── templates/
│   └── portal.html        # 深色 SaaS 面板模板
└── static/
    ├── app.css            # 面板样式
    └── app.js             # AJAX 轮询与 CRUD 交互
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
http://127.0.0.1:7777/你在 .env 中配置的 PORTAL_PATH
```

如果未设置 `ADMIN_PASSWORD`，系统会在 `data/bootstrap_admin.txt` 写入一次性初始凭据。首次登录后请立刻修改密码。

## 文案占位符

Telegram 文案支持以下占位符：

```text
{name}        商品名称
{stock}       当前库存数字
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

## 生产部署

在 VDS 上使用 root 执行。脚本会自动安装 apt 依赖、Chromium、Xvfb、Python venv、pip 依赖，写入 `.env`，注册并启动 systemd 服务。

> 把 `REPO_URL` 替换为你的 GitHub 仓库地址。

```bash
cat > install.sh << 'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="${APP_NAME:-noaff-monitor}"
SERVICE_USER="${SERVICE_USER:-noaffmon}"
APP_DIR="${APP_DIR:-/opt/noaff-monitor}"
REPO_URL="${REPO_URL:-}"
APP_PORT="${APP_PORT:-7777}"
MONITOR_DEBUG_PORT="${MONITOR_DEBUG_PORT:-9223}"
TEST_DEBUG_PORT="${TEST_DEBUG_PORT:-9334}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-45}"
REQUEST_TIMEOUT_SECONDS="${REQUEST_TIMEOUT_SECONDS:-25}"
ADMIN_USERNAME="${ADMIN_USERNAME:-operator}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

if [[ "$(id -u)" != "0" ]]; then
  echo "Please run as root."
  exit 1
fi

if [[ -z "$REPO_URL" && ! -f "$APP_DIR/app.py" ]]; then
  echo "REPO_URL is required unless $APP_DIR already contains the app."
  echo "Example: REPO_URL=https://github.com/yourname/noaff-monitor.git bash install.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip git curl ca-certificates xvfb procps
apt-get install -y fonts-noto-cjk fonts-noto-color-emoji || true

if ! command -v chromium >/dev/null 2>&1; then
  apt-get install -y chromium || apt-get install -y chromium-browser || true
fi

CHROMIUM_BINARY="${CHROMIUM_BINARY:-$(command -v chromium || command -v chromium-browser || command -v google-chrome || true)}"
if [[ -z "$CHROMIUM_BINARY" ]]; then
  echo "Chromium was not found. Install chromium manually and rerun this script."
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if [[ -n "$REPO_URL" ]]; then
  if [[ -d "$APP_DIR/.git" ]]; then
    git -C "$APP_DIR" fetch --all --prune
    git -C "$APP_DIR" pull --ff-only
  elif [[ -e "$APP_DIR" && "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)" -gt 0 ]]; then
    echo "$APP_DIR exists and is not an empty git checkout. Move it away or set APP_DIR."
    exit 1
  else
    mkdir -p "$(dirname "$APP_DIR")"
    git clone "$REPO_URL" "$APP_DIR"
  fi
fi

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements.txt

SECRET_KEY="${SECRET_KEY:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)}"

PORTAL_PATH="${PORTAL_PATH:-$(python3 - <<'PY'
import secrets
print('/portal_' + secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24])
PY
)}"

ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)}"

if [[ ! -f .env ]]; then
  cat > .env <<EOF_ENV
APP_PORT=$APP_PORT
PORTAL_PATH=$PORTAL_PATH
SECRET_KEY=$SECRET_KEY
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD=$ADMIN_PASSWORD
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID
MONITOR_DEBUG_PORT=$MONITOR_DEBUG_PORT
TEST_DEBUG_PORT=$TEST_DEBUG_PORT
POLL_INTERVAL_SECONDS=$POLL_INTERVAL_SECONDS
REQUEST_TIMEOUT_SECONDS=$REQUEST_TIMEOUT_SECONDS
CHROMIUM_HEADLESS=true
CHROMIUM_BINARY=$CHROMIUM_BINARY
SESSION_COOKIE_SECURE=false
LOGIN_RATE_LIMIT=5 per minute
GENERAL_MUTATION_LIMIT=40 per minute
LIMITER_STORAGE_URI=memory://
EOF_ENV
fi

mkdir -p data
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

cat > "/etc/systemd/system/$APP_NAME.service" <<EOF_SERVICE
[Unit]
Description=NOAFF Restock Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=/usr/bin/xvfb-run -a --server-args="-screen 0 1920x1080x24" $APP_DIR/.venv/bin/python $APP_DIR/app.py
Restart=always
RestartSec=6
KillSignal=SIGTERM
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF_SERVICE

systemctl daemon-reload
systemctl enable "$APP_NAME"
systemctl restart "$APP_NAME"

if command -v ufw >/dev/null 2>&1 && ufw status | grep -qi active; then
  ufw allow "$APP_PORT/tcp" || true
fi

echo
echo "NOAFF monitor is installed."
echo "Service: systemctl status $APP_NAME --no-pager"
echo "Logs:    journalctl -u $APP_NAME -f"
echo "URL:     http://YOUR_SERVER_IP:$APP_PORT$PORTAL_PATH"
echo "Admin:   $ADMIN_USERNAME"
if [[ -n "${ADMIN_PASSWORD:-}" ]]; then
  echo "Password: $ADMIN_PASSWORD"
fi
echo "Change the password immediately after first login."
EOF

chmod +x install.sh
REPO_URL=https://github.com/your-name/noaff-monitor.git bash install.sh
```

## 常用运维命令

```bash
systemctl status noaff-monitor --no-pager
journalctl -u noaff-monitor -f
systemctl restart noaff-monitor
systemctl stop noaff-monitor
```

查看生产配置：

```bash
cat /opt/noaff-monitor/.env
```

查看首次启动凭据文件：

```bash
cat /opt/noaff-monitor/data/bootstrap_admin.txt
```

首次登录并修改密码后，应删除该文件：

```bash
rm -f /opt/noaff-monitor/data/bootstrap_admin.txt
```

## 安全建议

- 不要把 `.env`、`data/`、SQLite 数据库和 bootstrap 凭据提交到 GitHub。
- 生产环境建议用防火墙只允许可信 IP 访问 `APP_PORT`。
- 若反向代理并启用 HTTPS，可把 `SESSION_COOKIE_SECURE=true`。
- `PORTAL_PATH` 建议保持随机高熵，不要使用 `/login`、`/admin`。
- 测试推送端口和后台监控端口必须保持不同，默认 `9223` / `9334`。

## 故障排查

- 面板无法访问：检查 `systemctl status noaff-monitor --no-pager` 和防火墙端口。
- Chromium 启动失败：检查 `CHROMIUM_BINARY` 是否指向有效浏览器。
- Telegram 推送失败：确认 Bot Token、Chat ID、群组权限和 Bot 是否已加入频道/群组。
- 库存识别失败：确认精准关键词能在源码中命中目标商品，并适当调整关键词。
- 登录频繁失败：默认每 IP 每分钟 5 次，等待限流窗口结束或调整 `LOGIN_RATE_LIMIT`。
