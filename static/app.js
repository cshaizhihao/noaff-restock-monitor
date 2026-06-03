(() => {
    const context = window.APP_CONTEXT || {};
    const root = document.getElementById("app-root");
    let csrfToken = context.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || "";
    let snapshotTimer = null;
    let currentTasks = new Map();
    let currentSystem = null;
    let currentView = "tasks";

    const els = {
        loginShell: document.getElementById("login-shell"),
        dashboardShell: document.getElementById("dashboard-shell"),
        loadingSkeleton: document.getElementById("loading-skeleton"),
        dashboardContent: document.getElementById("dashboard-content"),
        loginForm: document.getElementById("login-form"),
        loginUsername: document.getElementById("login-username"),
        loginPassword: document.getElementById("login-password"),
        logoutButton: document.getElementById("logout-button"),
        mobileLogoutButton: document.getElementById("mobile-logout-button"),
        refreshButton: document.getElementById("refresh-button"),
        restartEngineButton: document.getElementById("restart-engine-button"),
        taskResetButton: document.getElementById("task-reset-button"),
        navTasks: document.getElementById("nav-tasks"),
        navSettings: document.getElementById("nav-settings"),
        mobileNavTasks: document.getElementById("mobile-nav-tasks"),
        mobileNavSettings: document.getElementById("mobile-nav-settings"),
        viewTitle: document.getElementById("view-title"),
        lastCycle: document.getElementById("last-cycle"),
        engineChip: document.getElementById("engine-chip"),
        metricTotal: document.getElementById("metric-total"),
        metricStock: document.getElementById("metric-stock"),
        metricSoldout: document.getElementById("metric-soldout"),
        metricUnknown: document.getElementById("metric-unknown"),
        tasksView: document.getElementById("tasks-view"),
        settingsView: document.getElementById("settings-view"),
        tasksGrid: document.getElementById("tasks-grid"),
        toastStack: document.getElementById("toast-stack"),
        logStream: document.getElementById("log-stream"),
        adminIdentity: document.getElementById("admin-identity"),
        settingsForm: document.getElementById("settings-form"),
        settingsBotToken: document.getElementById("settings-bot-token"),
        settingsBotTokenMask: document.getElementById("settings-bot-token-mask"),
        settingsChatId: document.getElementById("settings-chat-id"),
        settingsMonitorPort: document.getElementById("settings-monitor-port"),
        settingsTestPort: document.getElementById("settings-test-port"),
        settingsPollInterval: document.getElementById("settings-poll-interval"),
        settingsTimeout: document.getElementById("settings-timeout"),
        systemVersion: document.getElementById("system-version"),
        systemBranch: document.getElementById("system-branch"),
        upgradeServiceState: document.getElementById("upgrade-service-state"),
        upgradeButtonLabel: document.getElementById("upgrade-button-label"),
        upgradeButton: document.getElementById("upgrade-button"),
        upgradeHelp: document.getElementById("upgrade-help"),
        upgradeLog: document.getElementById("upgrade-log"),
        profileForm: document.getElementById("profile-form"),
        profileUsername: document.getElementById("profile-username"),
        profileCurrentPassword: document.getElementById("profile-current-password"),
        profileNewPassword: document.getElementById("profile-new-password"),
        profileConfirmPassword: document.getElementById("profile-confirm-password"),
        taskModal: document.getElementById("task-modal"),
        taskModalTitle: document.getElementById("task-modal-title"),
        taskModalClose: document.getElementById("task-modal-close"),
        taskForm: document.getElementById("task-form"),
        taskId: document.getElementById("task-id"),
        taskName: document.getElementById("task-name"),
        taskUrl: document.getElementById("task-url"),
        taskKeyword: document.getElementById("task-keyword"),
        taskRestock: document.getElementById("task-restock"),
        taskSoldout: document.getElementById("task-soldout"),
        taskButton1Text: document.getElementById("task-button-1-text"),
        taskButton1Url: document.getElementById("task-button-1-url"),
        taskButton2Text: document.getElementById("task-button-2-text"),
        taskButton2Url: document.getElementById("task-button-2-url"),
        taskEnabled: document.getElementById("task-enabled"),
        taskCancelButton: document.getElementById("task-cancel-button"),
        taskSubmitButton: document.getElementById("task-submit-button")
    };

    const defaultTemplates = {
        restock: "<b>{name}</b>\n库存：{stock}\n链接：{url}\n检测时间：{checked_at}",
        soldout: "<b>{name}</b>\n已售罄\n最后库存：{stock}\n检测时间：{checked_at}"
    };

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function formatTime(value) {
        if (!value) return "尚未检查";
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return value;
        return parsed.toLocaleString("zh-CN", { hour12: false });
    }

    function showToast(message, type = "success") {
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        toast.textContent = message;
        els.toastStack.appendChild(toast);
        window.setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateY(-0.35rem)";
            window.setTimeout(() => toast.remove(), 220);
        }, 3200);
    }

    async function copyText(value) {
        const text = String(value ?? "");
        if (!text) {
            return false;
        }
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
            return true;
        }
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "true");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const ok = document.execCommand("copy");
        textarea.remove();
        return ok;
    }

    function syncInputValue(input, value) {
        if (!input) return;
        const nextValue = String(value ?? "");
        const syncedValue = input.dataset.syncedValue;
        const hasLocalEdit = syncedValue !== undefined && input.value !== syncedValue;

        if (input.value === nextValue) {
            input.dataset.syncedValue = nextValue;
            return;
        }
        if (document.activeElement === input || hasLocalEdit) {
            return;
        }
        input.value = nextValue;
        input.dataset.syncedValue = nextValue;
    }

    async function apiFetch(path, options = {}) {
        const headers = {
            Accept: "application/json",
            "X-Requested-With": "XMLHttpRequest",
            ...(options.headers || {})
        };
        if (options.body !== undefined) {
            headers["Content-Type"] = "application/json";
            headers["X-CSRF-Token"] = csrfToken;
        }
        const response = await fetch(path, {
            cache: "no-store",
            credentials: "same-origin",
            ...options,
            headers
        });
        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = { ok: false, message: response.statusText || "请求失败。" };
        }
        if (data.csrf_token) {
            csrfToken = data.csrf_token;
            document.querySelector('meta[name="csrf-token"]')?.setAttribute("content", csrfToken);
        }
        if (!response.ok || data.ok === false) {
            const err = new Error(data.message || "请求失败。");
            err.status = response.status;
            throw err;
        }
        return data;
    }

    function startPolling() {
        stopPolling();
        snapshotTimer = window.setInterval(() => loadSnapshot(false), 8000);
    }

    function stopPolling() {
        if (snapshotTimer) {
            window.clearInterval(snapshotTimer);
            snapshotTimer = null;
        }
    }

    function setView(loggedIn) {
        els.loginShell.classList.toggle("hidden", loggedIn);
        els.dashboardShell.classList.toggle("hidden", !loggedIn);
        if (loggedIn) {
            loadSnapshot(true);
            startPolling();
        } else {
            stopPolling();
        }
    }

    function setNav(view) {
        currentView = view;
        const tasks = view === "tasks";
        els.tasksView.classList.toggle("hidden", !tasks);
        els.settingsView.classList.toggle("hidden", tasks);
        els.navTasks.classList.toggle("nav-item-active", tasks);
        els.navSettings.classList.toggle("nav-item-active", !tasks);
        els.mobileNavTasks?.classList.toggle("nav-item-active", tasks);
        els.mobileNavSettings?.classList.toggle("nav-item-active", !tasks);
        els.viewTitle.textContent = tasks ? "监控任务池" : "全局配置";
    }

    function openTaskModal(task = null) {
        if (task) {
            els.taskModalTitle.textContent = "编辑监控节点";
            els.taskId.value = task.id;
            els.taskName.value = task.name || "";
            els.taskUrl.value = task.monitor_url || "";
            els.taskKeyword.value = task.target_keyword || "";
            els.taskRestock.value = task.restock_template || defaultTemplates.restock;
            els.taskSoldout.value = task.soldout_template || defaultTemplates.soldout;
            els.taskButton1Text.value = task.button_1_text || "";
            els.taskButton1Url.value = task.button_1_url || "";
            els.taskButton2Text.value = task.button_2_text || "";
            els.taskButton2Url.value = task.button_2_url || "";
            els.taskEnabled.checked = Boolean(task.enabled);
            els.taskSubmitButton.textContent = "更新节点";
        } else {
            resetTaskForm();
            els.taskModalTitle.textContent = "新增监控节点";
            els.taskSubmitButton.textContent = "保存节点";
        }
        els.taskModal.classList.remove("hidden");
        document.body.style.overflow = "hidden";
        window.setTimeout(() => els.taskName.focus(), 40);
    }

    function closeTaskModal() {
        els.taskModal.classList.add("hidden");
        document.body.style.overflow = "";
    }

    function resetTaskForm() {
        els.taskForm.reset();
        els.taskId.value = "";
        els.taskRestock.value = defaultTemplates.restock;
        els.taskSoldout.value = defaultTemplates.soldout;
        els.taskEnabled.checked = true;
    }

    function renderMetrics(metrics) {
        els.metricTotal.textContent = metrics.total ?? 0;
        els.metricStock.textContent = metrics.in_stock ?? 0;
        els.metricSoldout.textContent = metrics.sold_out ?? 0;
        els.metricUnknown.textContent = metrics.unknown ?? 0;
    }

    function renderEngine(engine) {
        els.engineChip.textContent = engine.cycle_running ? "System Syncing" : "System Online";
        const finished = engine.last_cycle_finished ? formatTime(engine.last_cycle_finished) : "尚未完成轮询";
        els.lastCycle.textContent = engine.last_exception
            ? `最近异常：${engine.last_exception}`
            : `上次完成：${finished}`;
    }

    function renderSettings(settings) {
        els.settingsBotTokenMask.textContent = settings.telegram_bot_token_masked
            ? `当前 Token：${settings.telegram_bot_token_masked}`
            : "当前未配置 Bot Token";
        syncInputValue(els.settingsChatId, settings.telegram_chat_id || "");
        syncInputValue(els.settingsMonitorPort, settings.monitor_debug_port || 9223);
        syncInputValue(els.settingsTestPort, settings.test_debug_port || 9334);
        syncInputValue(els.settingsPollInterval, settings.poll_interval_seconds || 45);
        syncInputValue(els.settingsTimeout, settings.request_timeout_seconds || 25);
    }

    function renderSystem(system) {
        currentSystem = system || null;
        const lineBreak = String.fromCharCode(10);
        els.systemVersion.textContent = system.version || "-";
        els.systemBranch.textContent = system.branch || "-";
        els.upgradeServiceState.textContent = system.upgrade_state || (system.upgrade_supported ? "\u53ef\u7528" : "\u672a\u5b89\u88c5");
        const mode = system.upgrade_mode || (system.upgrade_supported ? "panel" : "unsupported");
        if (mode === "panel") {
            els.upgradeButton.disabled = false;
            els.upgradeButtonLabel.textContent = "\u6267\u884c\u5347\u7ea7";
            els.upgradeHelp.textContent = system.upgrade_hint || "\u70b9\u51fb\u540e\u4f1a\u5728\u540e\u53f0\u62c9\u53d6\u6700\u65b0\u4ee3\u7801\u5e76\u91cd\u542f\u670d\u52a1\u3002";
            const logLines = system.upgrade_log || [];
            els.upgradeLog.textContent = logLines.length ? logLines.join(lineBreak) : "\u6682\u65e0\u5347\u7ea7\u65e5\u5fd7\u3002";
            return;
        }
        if (mode === "manual") {
            els.upgradeButton.disabled = false;
            els.upgradeButtonLabel.textContent = "\u590d\u5236\u5347\u7ea7\u547d\u4ee4";
            els.upgradeHelp.textContent = system.upgrade_hint || "\u8bf7\u590d\u5236\u4e0b\u65b9\u547d\u4ee4\u5728\u670d\u52a1\u5668\u6267\u884c\u3002";
            els.upgradeLog.textContent = system.upgrade_command || "\u6682\u65e0\u5347\u7ea7\u547d\u4ee4\u3002";
            return;
        }
        els.upgradeButton.disabled = true;
        els.upgradeButtonLabel.textContent = "\u5f53\u524d\u73af\u5883\u4e0d\u652f\u6301";
        els.upgradeHelp.textContent = system.upgrade_hint || "\u672a\u68c0\u6d4b\u5230\u53ef\u7528\u7684\u5347\u7ea7\u670d\u52a1\u3002";
        const logLines = system.upgrade_log || [];
        els.upgradeLog.textContent = logLines.length ? logLines.join(lineBreak) : "\u6682\u65e0\u5347\u7ea7\u65e5\u5fd7\u3002";
    }

    function renderAdmin(admin) {
        els.adminIdentity.textContent = admin.username ? `管理员：${admin.username}` : "管理员";
        syncInputValue(els.profileUsername, admin.username || "");
    }

    function renderLogs(logs) {
        if (!logs.length) {
            els.logStream.innerHTML = '<p class="text-sm text-slate-500">暂无活动日志。</p>';
            return;
        }
        els.logStream.innerHTML = logs.map((log) => {
            const levelColor = log.level === "error"
                ? "text-rose-300"
                : log.level === "warning"
                    ? "text-amber-200"
                    : "text-emerald-300";
            return `
                <article class="border-b border-slate-900/80 pb-4 last:border-b-0 last:pb-0">
                    <div class="mb-2 flex items-center justify-between gap-3">
                        <span class="font-mono text-[11px] uppercase tracking-[0.14em] ${levelColor}">${escapeHtml(log.level)}</span>
                        <span class="font-mono text-[11px] text-slate-600">${escapeHtml(formatTime(log.created_at))}</span>
                    </div>
                    <p class="text-sm leading-6 text-slate-300">${escapeHtml(log.message)}</p>
                    <p class="mt-1 font-mono text-[11px] text-slate-600">${escapeHtml(log.scope)}</p>
                </article>
            `;
        }).join("");
    }

    function statusMeta(task) {
        if (!task.enabled) return ["status-disabled", "● DISABLED", "停用中"];
        if (task.last_state === "in_stock") return ["status-in-stock", "● IN STOCK", "补货监控命中"];
        if (task.last_state === "sold_out") return ["status-sold-out", "○ OUT OF STOCK", "持续缺货中"];
        return ["status-unknown", "◌ UNKNOWN", "等待首次识别"];
    }

    function renderTasks(tasks) {
        currentTasks = new Map(tasks.map((task) => [String(task.id), task]));
        const taskCards = tasks.map((task, index) => {
            const [statusClass, statusText, logHint] = statusMeta(task);
            const stockText = task.last_stock === null || task.last_stock === undefined ? "Hidden" : String(task.last_stock);
            const logMessage = task.last_error
                ? `> ${escapeHtml(task.last_error)}`
                : `> ${escapeHtml(logHint)} ${escapeHtml(formatTime(task.last_checked_at))}`;
            const lastChecked = task.last_checked_at ? escapeHtml(formatTime(task.last_checked_at)) : "尚未检查";
            const actionLabel = task.enabled ? "停用节点" : "启用节点";
            return `
                <article class="task-card reveal" style="animation-delay: ${index * 80}ms;" data-task-id="${task.id}">
                    <div class="absolute right-6 top-6">
                        <span class="status-badge ${statusClass}">${statusText}</span>
                    </div>

                    <div class="mb-5 pr-28">
                        <h3 class="mb-2 truncate text-xl font-bold text-white" title="${escapeHtml(task.name)}">${escapeHtml(task.name)}</h3>
                        <p class="truncate font-mono text-[13px] text-slate-500" title="${escapeHtml(task.monitor_url)}">${escapeHtml(task.monitor_url)}</p>
                    </div>

                    <div class="keyword-chip mb-4">
                        <svg class="mr-1.5 h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                        </svg>
                        切片狙击: ${escapeHtml(task.target_keyword)}
                    </div>

                    <div class="terminal-box mb-5 flex flex-1 flex-col justify-center p-4 ${task.last_error ? "" : "opacity-95"}">
                        <div class="mb-3 flex items-center justify-between border-b border-slate-800/80 pb-2">
                            <span class="text-[10px] font-bold uppercase tracking-widest text-slate-500">Engine Log</span>
                            <span class="rounded border border-slate-700 bg-slate-800/80 px-2 py-0.5 font-mono text-[10px] text-slate-400">
                                库存嗅探: <span class="${task.last_stock > 0 ? "text-emerald-400" : "text-slate-300"} font-bold">${escapeHtml(stockText)}</span>
                            </span>
                        </div>
                        <p class="truncate-two font-mono text-sm leading-relaxed ${task.last_error ? "text-rose-300" : "animate-pulse-soft text-emerald-400"}">${logMessage}</p>
                        <div class="mt-3 font-mono text-[11px] text-slate-600">
                            message_id: ${task.message_id ?? "-"} · checked: ${lastChecked}
                        </div>
                    </div>

                    <div class="mt-auto flex items-center justify-between border-t border-slate-700/60 pt-4">
                        <button type="button" class="ghost-button !min-h-[2.4rem] !rounded-lg !px-4 !py-2 text-[13px] font-bold text-indigo-300" data-action="test">
                            <svg class="mr-1.5 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                            </svg>
                            探针测试
                        </button>
                        <div class="flex space-x-1">
                            <button type="button" class="icon-button !h-9 !w-9" title="${escapeHtml(actionLabel)}" data-action="toggle">
                                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                                </svg>
                            </button>
                            <button type="button" class="icon-button !h-9 !w-9" title="编辑配置" data-action="edit">
                                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                                </svg>
                            </button>
                            <button type="button" class="icon-button !h-9 !w-9" title="删除" data-action="delete">
                                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                </article>
            `;
        }).join("");

        const addCard = `
            <button type="button" id="tasks-add-card" class="add-card reveal" style="animation-delay: ${tasks.length * 80}ms;">
                <div class="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-slate-800/80 transition-transform group-hover:scale-110">
                    <svg class="h-8 w-8 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                    </svg>
                </div>
                <p class="mb-1 font-bold text-slate-300">新增监控节点</p>
                <p class="px-4 text-center text-[13px] text-slate-500">填入商品链接与解析参数，立即开启 24H 自动化嗅探。</p>
            </button>
        `;

        els.tasksGrid.innerHTML = tasks.length ? `${taskCards}${addCard}` : addCard;
    }

    function renderSnapshot(data) {
        renderMetrics(data.metrics || {});
        renderEngine(data.engine || {});
        renderSettings(data.settings || {});
        renderSystem(data.system || {});
        renderAdmin(data.admin || {});
        renderLogs(data.logs || []);
        renderTasks(data.tasks || []);
    }

    async function loadSnapshot(initial = false) {
        try {
            const data = await apiFetch("/api/snapshot");
            renderSnapshot(data);
            els.loadingSkeleton.classList.add("hidden");
            els.dashboardContent.classList.remove("hidden");
        } catch (error) {
            if (error.status === 401) {
                setView(false);
                showToast("会话已过期，请重新登录。", "error");
                return;
            }
            if (initial) {
                els.loadingSkeleton.classList.add("hidden");
                els.dashboardContent.classList.remove("hidden");
            }
            showToast(error.message || "加载仪表盘失败。", "error");
        }
    }

    function collectTaskPayload() {
        return {
            name: els.taskName.value.trim(),
            monitor_url: els.taskUrl.value.trim(),
            target_keyword: els.taskKeyword.value.trim(),
            restock_template: els.taskRestock.value.trim(),
            soldout_template: els.taskSoldout.value.trim(),
            button_1_text: els.taskButton1Text.value.trim(),
            button_1_url: els.taskButton1Url.value.trim(),
            button_2_text: els.taskButton2Text.value.trim(),
            button_2_url: els.taskButton2Url.value.trim(),
            enabled: els.taskEnabled.checked
        };
    }

    async function handleTaskAction(button) {
        const card = button.closest("[data-task-id]");
        const taskId = card?.dataset.taskId;
        const task = currentTasks.get(String(taskId));
        if (!task) return;
        const action = button.dataset.action;

        if (action === "edit") {
            openTaskModal(task);
            return;
        }
        if (action === "delete" && !window.confirm(`确认删除任务「${task.name}」？`)) {
            return;
        }

        button.disabled = true;
        try {
            if (action === "test") {
                const data = await apiFetch(`/api/test-push/${taskId}`, {
                    method: "POST",
                    body: JSON.stringify({})
                });
                showToast(`测试消息已发送，库存识别：${data.result?.stock ?? "未知"}`);
            } else if (action === "toggle") {
                await apiFetch(`/api/tasks/${taskId}/toggle`, {
                    method: "POST",
                    body: JSON.stringify({ enabled: !task.enabled })
                });
                showToast(task.enabled ? "任务已停用。" : "任务已启用。");
            } else if (action === "delete") {
                await apiFetch(`/api/tasks/${taskId}`, {
                    method: "DELETE",
                    body: JSON.stringify({})
                });
                showToast("任务已删除。");
            }
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    async function logout() {
        try {
            await apiFetch("/logout", { method: "POST", body: JSON.stringify({}) });
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            setView(false);
        }
    }

    els.loginForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = event.submitter;
        submit.disabled = true;
        try {
            const data = await apiFetch("/gate", {
                method: "POST",
                body: JSON.stringify({
                    username: els.loginUsername.value.trim(),
                    password: els.loginPassword.value
                })
            });
            csrfToken = data.csrf_token || csrfToken;
            els.loginPassword.value = "";
            showToast("登录成功。");
            setView(true);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });

    els.logoutButton?.addEventListener("click", logout);
    els.mobileLogoutButton?.addEventListener("click", logout);

    els.refreshButton?.addEventListener("click", () => loadSnapshot(false));
    els.restartEngineButton?.addEventListener("click", async () => {
        els.restartEngineButton.disabled = true;
        try {
            await apiFetch("/api/engine/restart", {
                method: "POST",
                body: JSON.stringify({})
            });
            showToast("浏览器引擎已重启。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            els.restartEngineButton.disabled = false;
        }
    });

    els.upgradeButton?.addEventListener("click", async () => {
        const system = currentSystem || {};
        if (system.upgrade_mode === "manual") {
            try {
                const copied = await copyText(system.upgrade_command || "");
                showToast(copied ? "\u5347\u7ea7\u547d\u4ee4\u5df2\u590d\u5236\u3002" : "\u6ca1\u6709\u53ef\u590d\u5236\u7684\u5347\u7ea7\u547d\u4ee4\u3002", copied ? "success" : "error");
            } catch (error) {
                showToast(error.message, "error");
            }
            return;
        }
        if (!window.confirm("\u786e\u8ba4\u542f\u52a8\u7cfb\u7edf\u5347\u7ea7\uff1f\u5347\u7ea7\u5b8c\u6210\u540e\u670d\u52a1\u4f1a\u81ea\u52a8\u91cd\u542f\u3002")) {
            return;
        }
        els.upgradeButton.disabled = true;
        try {
            const data = await apiFetch("/api/system/upgrade", {
                method: "POST",
                body: JSON.stringify({})
            });
            showToast(data.message || "\u5347\u7ea7\u4efb\u52a1\u5df2\u542f\u52a8\u3002", "success");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            els.upgradeButton.disabled = false;
        }
    });

    els.navTasks?.addEventListener("click", () => setNav("tasks"));
    els.navSettings?.addEventListener("click", () => setNav("settings"));
    els.mobileNavTasks?.addEventListener("click", () => setNav("tasks"));
    els.mobileNavSettings?.addEventListener("click", () => setNav("settings"));

    els.taskResetButton?.addEventListener("click", () => openTaskModal());
    els.taskCancelButton?.addEventListener("click", closeTaskModal);
    els.taskModalClose?.addEventListener("click", closeTaskModal);
    els.taskModal?.addEventListener("click", (event) => {
        if (event.target === els.taskModal) {
            closeTaskModal();
        }
    });

    els.tasksGrid?.addEventListener("click", (event) => {
        const addCard = event.target.closest("#tasks-add-card");
        if (addCard) {
            openTaskModal();
            return;
        }
        const actionButton = event.target.closest("[data-action]");
        if (actionButton) {
            handleTaskAction(actionButton);
        }
    });

    els.taskForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = els.taskSubmitButton;
        const taskId = els.taskId.value;
        submit.disabled = true;
        try {
            await apiFetch(taskId ? `/api/tasks/${taskId}` : "/api/tasks", {
                method: taskId ? "PUT" : "POST",
                body: JSON.stringify(collectTaskPayload())
            });
            showToast(taskId ? "任务已更新。" : "任务已创建。");
            closeTaskModal();
            resetTaskForm();
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });

    els.settingsForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = event.submitter;
        submit.disabled = true;
        const payload = {
            telegram_chat_id: els.settingsChatId.value.trim(),
            monitor_debug_port: Number(els.settingsMonitorPort.value),
            test_debug_port: Number(els.settingsTestPort.value),
            poll_interval_seconds: Number(els.settingsPollInterval.value),
            request_timeout_seconds: Number(els.settingsTimeout.value)
        };
        if (els.settingsBotToken.value.trim()) {
            payload.telegram_bot_token = els.settingsBotToken.value.trim();
        }
        try {
            await apiFetch("/api/settings/telegram", {
                method: "POST",
                body: JSON.stringify(payload)
            });
            els.settingsBotToken.value = "";
            showToast("设置已保存。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });

    els.profileForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = event.submitter;
        submit.disabled = true;
        try {
            const data = await apiFetch("/api/settings/profile", {
                method: "POST",
                body: JSON.stringify({
                    new_username: els.profileUsername.value.trim(),
                    current_password: els.profileCurrentPassword.value,
                    new_password: els.profileNewPassword.value,
                    confirm_password: els.profileConfirmPassword.value
                })
            });
            csrfToken = data.csrf_token || csrfToken;
            els.profileCurrentPassword.value = "";
            els.profileNewPassword.value = "";
            els.profileConfirmPassword.value = "";
            showToast("管理员凭据已更新。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });

    window.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !els.taskModal.classList.contains("hidden")) {
            closeTaskModal();
        }
    });

    resetTaskForm();
    setNav("tasks");
    setView(context.loggedIn === true || root?.dataset.loggedIn === "true");
})();
