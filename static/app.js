(() => {
    const context = window.APP_CONTEXT || {};
    let csrfToken = context.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || '';
    let snapshotTimer = null;
    let currentTasks = new Map();

    const root = document.getElementById('app-root');
    const loginShell = document.getElementById('login-shell');
    const dashboardShell = document.getElementById('dashboard-shell');
    const loadingSkeleton = document.getElementById('loading-skeleton');
    const dashboardContent = document.getElementById('dashboard-content');
    const toastStack = document.getElementById('toast-stack');
    const portalPath = root?.dataset.portalPath || context.portalPath || '';

    const els = {
        loginForm: document.getElementById('login-form'),
        loginUsername: document.getElementById('login-username'),
        loginPassword: document.getElementById('login-password'),
        logoutButton: document.getElementById('logout-button'),
        refreshButton: document.getElementById('refresh-button'),
        restartEngineButton: document.getElementById('restart-engine-button'),
        engineChip: document.getElementById('engine-chip'),
        adminIdentity: document.getElementById('admin-identity'),
        portalChip: document.getElementById('portal-chip'),
        lastCycle: document.getElementById('last-cycle'),
        metricTotal: document.getElementById('metric-total'),
        metricStock: document.getElementById('metric-stock'),
        metricSoldout: document.getElementById('metric-soldout'),
        metricUnknown: document.getElementById('metric-unknown'),
        tasksTable: document.getElementById('tasks-table'),
        taskForm: document.getElementById('task-form'),
        taskResetButton: document.getElementById('task-reset-button'),
        taskCancelButton: document.getElementById('task-cancel-button'),
        taskSubmitButton: document.getElementById('task-submit-button'),
        taskId: document.getElementById('task-id'),
        taskName: document.getElementById('task-name'),
        taskUrl: document.getElementById('task-url'),
        taskKeyword: document.getElementById('task-keyword'),
        taskRestock: document.getElementById('task-restock'),
        taskSoldout: document.getElementById('task-soldout'),
        taskButton1Text: document.getElementById('task-button-1-text'),
        taskButton1Url: document.getElementById('task-button-1-url'),
        taskButton2Text: document.getElementById('task-button-2-text'),
        taskButton2Url: document.getElementById('task-button-2-url'),
        taskEnabled: document.getElementById('task-enabled'),
        settingsForm: document.getElementById('settings-form'),
        settingsBotToken: document.getElementById('settings-bot-token'),
        settingsBotTokenMask: document.getElementById('settings-bot-token-mask'),
        settingsChatId: document.getElementById('settings-chat-id'),
        settingsMonitorPort: document.getElementById('settings-monitor-port'),
        settingsTestPort: document.getElementById('settings-test-port'),
        settingsPollInterval: document.getElementById('settings-poll-interval'),
        settingsTimeout: document.getElementById('settings-timeout'),
        profileForm: document.getElementById('profile-form'),
        profileUsername: document.getElementById('profile-username'),
        profileCurrentPassword: document.getElementById('profile-current-password'),
        profileNewPassword: document.getElementById('profile-new-password'),
        profileConfirmPassword: document.getElementById('profile-confirm-password'),
        logStream: document.getElementById('log-stream')
    };

    const defaultTemplates = {
        restock: '<b>{name}</b>\n库存：{stock}\n链接：{url}\n检测时间：{checked_at}',
        soldout: '<b>{name}</b>\n已售罄\n最后库存：{stock}\n检测时间：{checked_at}'
    };

    function setView(loggedIn) {
        loginShell.classList.toggle('hidden', loggedIn);
        dashboardShell.classList.toggle('hidden', !loggedIn);
        if (loggedIn) {
            loadSnapshot(true);
            startPolling();
        } else {
            stopPolling();
        }
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

    function showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        toastStack.appendChild(toast);
        window.setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-0.35rem)';
            window.setTimeout(() => toast.remove(), 220);
        }, 3600);
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    function formatTime(value) {
        if (!value) return '尚未检查';
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return value;
        return parsed.toLocaleString('zh-CN', { hour12: false });
    }

    async function apiFetch(path, options = {}) {
        const headers = {
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            ...options.headers
        };
        if (options.body !== undefined) {
            headers['Content-Type'] = 'application/json';
            headers['X-CSRF-Token'] = csrfToken;
        }

        const response = await fetch(`${portalPath}${path}`, {
            cache: 'no-store',
            credentials: 'same-origin',
            ...options,
            headers
        });

        let data = {};
        try {
            data = await response.json();
        } catch (error) {
            data = { ok: false, message: response.statusText || '请求失败。' };
        }

        if (data.csrf_token) {
            csrfToken = data.csrf_token;
            document.querySelector('meta[name="csrf-token"]')?.setAttribute('content', csrfToken);
        }

        if (!response.ok || data.ok === false) {
            const error = new Error(data.message || '请求失败。');
            error.status = response.status;
            throw error;
        }
        return data;
    }

    async function loadSnapshot(initial = false) {
        try {
            const data = await apiFetch('/api/snapshot');
            renderSnapshot(data);
            loadingSkeleton.classList.add('hidden');
            dashboardContent.classList.remove('hidden');
        } catch (error) {
            if (error.status === 401) {
                setView(false);
                showToast('会话已过期，请重新登录。', 'error');
                return;
            }
            if (initial) {
                loadingSkeleton.classList.add('hidden');
                dashboardContent.classList.remove('hidden');
            }
            showToast(error.message || '加载仪表盘失败。', 'error');
        }
    }

    function renderSnapshot(data) {
        currentTasks = new Map((data.tasks || []).map((task) => [String(task.id), task]));
        renderMetrics(data.metrics || {});
        renderEngine(data.engine || {});
        renderSettings(data.settings || {});
        renderAdmin(data.admin || {});
        renderTasks(data.tasks || []);
        renderLogs(data.logs || []);
    }

    function renderMetrics(metrics) {
        els.metricTotal.textContent = metrics.total ?? 0;
        els.metricStock.textContent = metrics.in_stock ?? 0;
        els.metricSoldout.textContent = metrics.sold_out ?? 0;
        els.metricUnknown.textContent = metrics.unknown ?? 0;
    }

    function renderEngine(engine) {
        const running = Boolean(engine.cycle_running);
        els.engineChip.textContent = running ? '引擎轮询中' : '引擎待机';
        els.engineChip.className = `status-chip ${running ? 'status-chip-active' : 'status-chip-idle'}`;
        const finished = engine.last_cycle_finished ? formatTime(engine.last_cycle_finished) : '尚未完成轮询';
        const extra = engine.last_exception ? ` · ${engine.last_exception}` : '';
        els.lastCycle.textContent = `上次完成：${finished}${extra}`;
    }

    function renderSettings(settings) {
        els.settingsBotTokenMask.textContent = settings.telegram_bot_token_masked
            ? `当前 Token：${settings.telegram_bot_token_masked}`
            : '当前未配置 Bot Token';
        els.settingsChatId.value = settings.telegram_chat_id || '';
        els.settingsMonitorPort.value = settings.monitor_debug_port || 9223;
        els.settingsTestPort.value = settings.test_debug_port || 9334;
        els.settingsPollInterval.value = settings.poll_interval_seconds || 45;
        els.settingsTimeout.value = settings.request_timeout_seconds || 25;
    }

    function renderAdmin(admin) {
        els.adminIdentity.textContent = admin.username ? `管理员：${admin.username}` : '管理员';
        els.portalChip.textContent = admin.portal_path || portalPath;
        els.profileUsername.value = admin.username || '';
    }

    function stateMeta(task) {
        if (!task.enabled) return ['state-disabled', '停用'];
        if (task.last_state === 'in_stock') return ['state-in-stock', '有货'];
        if (task.last_state === 'sold_out') return ['state-sold-out', '售罄'];
        return ['state-unknown', '未知'];
    }

    function renderTasks(tasks) {
        if (!tasks.length) {
            els.tasksTable.innerHTML = `
                <tr>
                    <td colspan="6" class="px-4 py-10 text-center text-sm text-slate-500">
                        暂无任务。添加第一个监控目标后，后台引擎会自动纳入轮询。
                    </td>
                </tr>
            `;
            return;
        }

        els.tasksTable.innerHTML = tasks.map((task) => {
            const [stateClass, stateLabel] = stateMeta(task);
            const stock = task.last_stock === null || task.last_stock === undefined ? '未知' : task.last_stock;
            const errorHtml = task.last_error ? `<p class="mt-1 truncate-two text-xs text-rose-300">${escapeHtml(task.last_error)}</p>` : '';
            return `
                <tr data-task-id="${task.id}">
                    <td class="px-4 py-4 align-top">
                        <div class="max-w-[23rem]">
                            <p class="font-medium text-slate-100">${escapeHtml(task.name)}</p>
                            <p class="mt-1 truncate-two text-xs text-slate-500">${escapeHtml(task.monitor_url)}</p>
                            <p class="mt-1 text-xs text-indigo-200">${escapeHtml(task.target_keyword)}</p>
                            ${errorHtml}
                        </div>
                    </td>
                    <td class="px-4 py-4 align-top">
                        <span class="state-badge ${stateClass}">${stateLabel}</span>
                    </td>
                    <td class="px-4 py-4 align-top text-sm text-slate-300">${escapeHtml(stock)}</td>
                    <td class="px-4 py-4 align-top text-sm text-slate-400">${task.message_id ? escapeHtml(task.message_id) : '-'}</td>
                    <td class="px-4 py-4 align-top text-sm text-slate-400">${escapeHtml(formatTime(task.last_checked_at))}</td>
                    <td class="px-4 py-4 align-top">
                        <div class="flex flex-wrap gap-2">
                            <button type="button" class="table-action" data-action="edit">编辑</button>
                            <button type="button" class="table-action" data-action="test">测试</button>
                            <button type="button" class="table-action" data-action="toggle">${task.enabled ? '停用' : '启用'}</button>
                            <button type="button" class="table-action danger" data-action="delete">删除</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');
    }

    function renderLogs(logs) {
        if (!logs.length) {
            els.logStream.innerHTML = '<p class="text-sm text-slate-500">暂无活动日志。</p>';
            return;
        }
        els.logStream.innerHTML = logs.map((log) => {
            const color = log.level === 'error'
                ? 'text-rose-300'
                : log.level === 'warning'
                    ? 'text-amber-200'
                    : 'text-emerald-200';
            return `
                <article class="rounded-2xl border border-slate-800 bg-slate-950/40 px-4 py-3">
                    <div class="flex items-center justify-between gap-3">
                        <p class="text-xs font-semibold uppercase tracking-[0.14em] ${color}">${escapeHtml(log.level)}</p>
                        <p class="text-xs text-slate-500">${escapeHtml(formatTime(log.created_at))}</p>
                    </div>
                    <p class="mt-2 text-sm leading-6 text-slate-300">${escapeHtml(log.message)}</p>
                    <p class="mt-1 text-xs text-slate-600">${escapeHtml(log.scope)}</p>
                </article>
            `;
        }).join('');
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

    function resetTaskForm() {
        els.taskId.value = '';
        els.taskForm.reset();
        els.taskRestock.value = defaultTemplates.restock;
        els.taskSoldout.value = defaultTemplates.soldout;
        els.taskEnabled.checked = true;
        els.taskSubmitButton.textContent = '保存任务';
    }

    function editTask(task) {
        els.taskId.value = task.id;
        els.taskName.value = task.name || '';
        els.taskUrl.value = task.monitor_url || '';
        els.taskKeyword.value = task.target_keyword || '';
        els.taskRestock.value = task.restock_template || defaultTemplates.restock;
        els.taskSoldout.value = task.soldout_template || defaultTemplates.soldout;
        els.taskButton1Text.value = task.button_1_text || '';
        els.taskButton1Url.value = task.button_1_url || '';
        els.taskButton2Text.value = task.button_2_text || '';
        els.taskButton2Url.value = task.button_2_url || '';
        els.taskEnabled.checked = Boolean(task.enabled);
        els.taskSubmitButton.textContent = '更新任务';
        els.taskName.focus();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    async function handleTaskAction(event) {
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const row = button.closest('tr[data-task-id]');
        const taskId = row?.dataset.taskId;
        const task = currentTasks.get(String(taskId));
        if (!task) return;

        const action = button.dataset.action;
        if (action === 'edit') {
            editTask(task);
            return;
        }

        if (action === 'delete' && !window.confirm(`确认删除任务「${task.name}」？`)) {
            return;
        }

        button.disabled = true;
        try {
            if (action === 'test') {
                const data = await apiFetch(`/api/test-push/${taskId}`, { method: 'POST', body: JSON.stringify({}) });
                showToast(`测试消息已发送，库存识别：${data.result?.stock ?? '未知'}`);
            } else if (action === 'toggle') {
                await apiFetch(`/api/tasks/${taskId}/toggle`, {
                    method: 'POST',
                    body: JSON.stringify({ enabled: !task.enabled })
                });
                showToast(task.enabled ? '任务已停用。' : '任务已启用。');
            } else if (action === 'delete') {
                await apiFetch(`/api/tasks/${taskId}`, { method: 'DELETE', body: JSON.stringify({}) });
                showToast('任务已删除。');
            }
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            button.disabled = false;
        }
    }

    els.loginForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const submitButton = event.submitter;
        submitButton.disabled = true;
        try {
            const data = await apiFetch('/gate', {
                method: 'POST',
                body: JSON.stringify({
                    username: els.loginUsername.value.trim(),
                    password: els.loginPassword.value
                })
            });
            csrfToken = data.csrf_token || csrfToken;
            els.loginPassword.value = '';
            showToast('登录成功。');
            setView(true);
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            submitButton.disabled = false;
        }
    });

    els.logoutButton?.addEventListener('click', async () => {
        try {
            await apiFetch('/logout', { method: 'POST', body: JSON.stringify({}) });
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            setView(false);
        }
    });

    els.refreshButton?.addEventListener('click', () => loadSnapshot(false));

    els.restartEngineButton?.addEventListener('click', async () => {
        els.restartEngineButton.disabled = true;
        try {
            await apiFetch('/api/engine/restart', { method: 'POST', body: JSON.stringify({}) });
            showToast('浏览器引擎已重启。');
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            els.restartEngineButton.disabled = false;
        }
    });

    els.taskForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        els.taskSubmitButton.disabled = true;
        const taskId = els.taskId.value;
        try {
            const path = taskId ? `/api/tasks/${taskId}` : '/api/tasks';
            const method = taskId ? 'PUT' : 'POST';
            await apiFetch(path, { method, body: JSON.stringify(collectTaskPayload()) });
            showToast(taskId ? '任务已更新。' : '任务已创建。');
            resetTaskForm();
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            els.taskSubmitButton.disabled = false;
        }
    });

    els.taskResetButton?.addEventListener('click', resetTaskForm);
    els.taskCancelButton?.addEventListener('click', resetTaskForm);
    els.tasksTable?.addEventListener('click', handleTaskAction);

    els.settingsForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const submitButton = event.submitter;
        submitButton.disabled = true;
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
            await apiFetch('/api/settings/telegram', { method: 'POST', body: JSON.stringify(payload) });
            els.settingsBotToken.value = '';
            showToast('设置已保存。');
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            submitButton.disabled = false;
        }
    });

    els.profileForm?.addEventListener('submit', async (event) => {
        event.preventDefault();
        const submitButton = event.submitter;
        submitButton.disabled = true;
        try {
            const data = await apiFetch('/api/settings/profile', {
                method: 'POST',
                body: JSON.stringify({
                    new_username: els.profileUsername.value.trim(),
                    current_password: els.profileCurrentPassword.value,
                    new_password: els.profileNewPassword.value,
                    confirm_password: els.profileConfirmPassword.value
                })
            });
            csrfToken = data.csrf_token || csrfToken;
            els.profileCurrentPassword.value = '';
            els.profileNewPassword.value = '';
            els.profileConfirmPassword.value = '';
            showToast('管理员凭据已更新。');
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, 'error');
        } finally {
            submitButton.disabled = false;
        }
    });

    resetTaskForm();
    setView(context.loggedIn === true || root?.dataset.loggedIn === 'true');
})();
