(() => {
    const root = document.getElementById("app-root");
    let csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
    let snapshotTimer = null;
    let currentTasks = new Map();
    let currentTaskGroups = [];
    let currentTaskGroupNodes = [];
    let currentMerchant = { sources: [], items: [], metrics: {} };
    let merchantPreview = { candidateUrls: [], items: [], rejectedItems: [], failures: [] };
    let currentSettings = {};
    let currentSystem = null;
    let currentView = "tasks";
    let tasksRendered = false;
    let taskIdsSignature = "";
    let taskStateSignature = "";
    let logsSignature = null;
    let merchantSignature = null;
    let merchantActiveStep = "source";
    let firecrawlGuideIndex = 0;
    let taskBrowserPath = { groupName: "", subgroupName: "", view: "children" };
    let taskDragState = null;
    let taskDragSuppressClickUntil = 0;

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
        navMerchant: document.getElementById("nav-merchant"),
        navSettings: document.getElementById("nav-settings"),
        mobileNavTasks: document.getElementById("mobile-nav-tasks"),
        mobileNavMerchant: document.getElementById("mobile-nav-merchant"),
        mobileNavSettings: document.getElementById("mobile-nav-settings"),
        viewTitle: document.getElementById("view-title"),
        lastCycle: document.getElementById("last-cycle"),
        engineChip: document.getElementById("engine-chip"),
        metricTotal: document.getElementById("metric-total"),
        metricStock: document.getElementById("metric-stock"),
        metricSoldout: document.getElementById("metric-soldout"),
        metricUnknown: document.getElementById("metric-unknown"),
        tasksView: document.getElementById("tasks-view"),
        merchantView: document.getElementById("merchant-view"),
        settingsView: document.getElementById("settings-view"),
        settingsHome: document.getElementById("settings-home"),
        settingsPages: document.getElementById("settings-pages"),
        firecrawlGuideModal: document.getElementById("firecrawl-guide-modal"),
        firecrawlGuideClose: document.getElementById("firecrawl-guide-close"),
        firecrawlGuideTrack: document.getElementById("firecrawl-guide-track"),
        firecrawlGuideDots: document.getElementById("firecrawl-guide-dots"),
        firecrawlGuidePrev: document.getElementById("firecrawl-guide-prev"),
        firecrawlGuideNext: document.getElementById("firecrawl-guide-next"),
        tasksGrid: document.getElementById("tasks-grid"),
        toastStack: document.getElementById("toast-stack"),
        logStream: document.getElementById("log-stream"),
        adminIdentity: document.getElementById("admin-identity"),
        settingsForm: document.getElementById("settings-form"),
        settingsBotToken: document.getElementById("settings-bot-token"),
        settingsBotTokenMask: document.getElementById("settings-bot-token-mask"),
        settingsChatIds: document.getElementById("settings-chat-ids"),
        settingsChatIdsHint: document.getElementById("settings-chat-ids-hint"),
        settingsChatIdsCount: document.getElementById("settings-chat-ids-count"),
        settingsMonitorPort: document.getElementById("settings-monitor-port"),
        settingsTestPort: document.getElementById("settings-test-port"),
        settingsCatalogPort: document.getElementById("settings-catalog-port"),
        settingsPollInterval: document.getElementById("settings-poll-interval"),
        settingsTimeout: document.getElementById("settings-timeout"),
        settingsFirecrawlEnabled: document.getElementById("settings-firecrawl-enabled"),
        settingsFirecrawlApiUrl: document.getElementById("settings-firecrawl-api-url"),
        settingsFirecrawlApiKey: document.getElementById("settings-firecrawl-api-key"),
        settingsFirecrawlApiKeyMask: document.getElementById("settings-firecrawl-api-key-mask"),
        settingsFirecrawlTimeout: document.getElementById("settings-firecrawl-timeout"),
        settingsFirecrawlMaxAge: document.getElementById("settings-firecrawl-max-age"),
        settingsFirecrawlStoreInCache: document.getElementById("settings-firecrawl-store-in-cache"),
        settingsFirecrawlProxyMode: document.getElementById("settings-firecrawl-proxy-mode"),
        settingsFirecrawlAllowAutoProxy: document.getElementById("settings-firecrawl-allow-auto-proxy"),
        settingsFirecrawlAllowEnhancedProxy: document.getElementById("settings-firecrawl-allow-enhanced-proxy"),
        settingsFirecrawlZeroDataRetention: document.getElementById("settings-firecrawl-zero-data-retention"),
        settingsFirecrawlUseForMonitor: document.getElementById("settings-firecrawl-use-for-monitor"),
        settingsFirecrawlUseForCatalog: document.getElementById("settings-firecrawl-use-for-catalog"),
        settingsFirecrawlCatalogLimit: document.getElementById("settings-firecrawl-catalog-limit"),
        settingsFirecrawlTestButton: document.getElementById("settings-firecrawl-test-button"),
        settingsFirecrawlTestResult: document.getElementById("settings-firecrawl-test-result"),
        settingsScraplingStatus: document.getElementById("settings-scrapling-status"),
        settingsScraplingStatusPill: document.getElementById("settings-scrapling-status-pill"),
        settingsScraplingTestButton: document.getElementById("settings-scrapling-test-button"),
        settingsScraplingEnabled: document.getElementById("settings-scrapling-enabled"),
        settingsScraplingDefaultMode: document.getElementById("settings-scrapling-default-mode"),
        settingsScraplingUseForMonitor: document.getElementById("settings-scrapling-use-for-monitor"),
        settingsScraplingUseForCatalog: document.getElementById("settings-scrapling-use-for-catalog"),
        settingsScraplingSessionReuse: document.getElementById("settings-scrapling-session-reuse"),
        settingsScraplingAdaptiveSelector: document.getElementById("settings-scrapling-adaptive-selector"),
        settingsScraplingTimeoutStandard: document.getElementById("settings-scrapling-timeout-standard"),
        settingsScraplingTimeoutDynamic: document.getElementById("settings-scrapling-timeout-dynamic"),
        settingsScraplingTimeoutStealth: document.getElementById("settings-scrapling-timeout-stealth"),
        settingsScraplingCooldownStandard: document.getElementById("settings-scrapling-cooldown-standard"),
        settingsScraplingCooldownDynamic: document.getElementById("settings-scrapling-cooldown-dynamic"),
        settingsScraplingCooldownStealth: document.getElementById("settings-scrapling-cooldown-stealth"),
        settingsScraplingConcurrencyStandard: document.getElementById("settings-scrapling-concurrency-standard"),
        settingsScraplingConcurrencyDynamic: document.getElementById("settings-scrapling-concurrency-dynamic"),
        settingsScraplingConcurrencyStealth: document.getElementById("settings-scrapling-concurrency-stealth"),
        merchantForm: document.getElementById("merchant-form"),
        merchantSourceUrl: document.getElementById("merchant-source-url"),
        merchantSourceName: document.getElementById("merchant-source-name"),
        merchantGroup: document.getElementById("merchant-group"),
        merchantGroupCustomWrap: document.getElementById("merchant-group-custom-wrap"),
        merchantGroupCustom: document.getElementById("merchant-group-custom"),
        merchantDiscoveryStrategy: document.getElementById("merchant-discovery-strategy"),
        merchantScrapeStrategy: document.getElementById("merchant-scrape-strategy"),
        merchantDefaultFetchStrategy: document.getElementById("merchant-default-fetch-strategy"),
        merchantDefaultExtractor: document.getElementById("merchant-default-extractor"),
        merchantSearchKeyword: document.getElementById("merchant-search-keyword"),
        merchantTargetKeyword: document.getElementById("merchant-target-keyword"),
        merchantTargetKeywordMode: document.getElementById("merchant-target-keyword-mode"),
        merchantDedupePolicy: document.getElementById("merchant-dedupe-policy"),
        merchantMaxDiscoveredUrls: document.getElementById("merchant-max-discovered-urls"),
        merchantMaxImportItems: document.getElementById("merchant-max-import-items"),
        merchantTimeoutSeconds: document.getElementById("merchant-timeout-seconds"),
        merchantIncludeSoldOut: document.getElementById("merchant-include-sold-out"),
        merchantAutoPromote: document.getElementById("merchant-auto-promote"),
        merchantFirecrawlState: document.getElementById("merchant-firecrawl-state"),
        merchantStepper: document.getElementById("merchant-stepper"),
        merchantReviewSummary: document.getElementById("merchant-review-summary"),
        merchantImportButton: document.getElementById("merchant-import-button"),
        merchantImportButtonLabel: document.getElementById("merchant-import-button-label"),
        merchantBulkPromoteButton: document.getElementById("merchant-bulk-promote-button"),
        merchantBulkPromoteCount: document.getElementById("merchant-bulk-promote-count"),
        merchantMetricSources: document.getElementById("merchant-metric-sources"),
        merchantMetricItems: document.getElementById("merchant-metric-items"),
        merchantMetricLinked: document.getElementById("merchant-metric-linked"),
        merchantStepSourceCount: document.getElementById("merchant-step-source-count"),
        merchantStepItemCount: document.getElementById("merchant-step-item-count"),
        merchantItemFilter: document.getElementById("merchant-item-filter"),
        merchantSourceList: document.getElementById("merchant-source-list"),
        merchantItemList: document.getElementById("merchant-item-list"),
        merchantPreviewScrapeButton: document.getElementById("merchant-preview-scrape-button"),
        merchantPreviewCommitButton: document.getElementById("merchant-preview-commit-button"),
        merchantPreviewUrlCount: document.getElementById("merchant-preview-url-count"),
        systemVersion: document.getElementById("system-version"),
        systemBranch: document.getElementById("system-branch"),
        upgradeServiceState: document.getElementById("upgrade-service-state"),
        upgradeButtonLabel: document.getElementById("upgrade-button-label"),
        upgradeButton: document.getElementById("upgrade-button"),
        upgradeHelp: document.getElementById("upgrade-help"),
        upgradeLog: document.getElementById("upgrade-log"),
        backupExportButton: document.getElementById("backup-export-button"),
        backupRestoreButton: document.getElementById("backup-restore-button"),
        backupFileInput: document.getElementById("backup-file-input"),
        backupFileName: document.getElementById("backup-file-name"),
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
        taskGroup: document.getElementById("task-group"),
        taskGroupCustomWrap: document.getElementById("task-group-custom-wrap"),
        taskGroupCustom: document.getElementById("task-group-custom"),
        taskSubgroup: document.getElementById("task-subgroup"),
        taskSubgroupCustomWrap: document.getElementById("task-subgroup-custom-wrap"),
        taskSubgroupCustom: document.getElementById("task-subgroup-custom"),
        taskUrl: document.getElementById("task-url"),
        taskKeyword: document.getElementById("task-keyword"),
        taskFetchStrategy: document.getElementById("task-fetch-strategy"),
        taskStrategyCards: document.getElementById("task-strategy-cards"),
        taskStrategySummary: document.getElementById("task-strategy-summary"),
        taskWebhookHint: document.getElementById("task-webhook-hint"),
        taskRuleDetails: document.getElementById("task-rule-details"),
        taskStockRuleType: document.getElementById("task-stock-rule-type"),
        taskTargetScopeSelector: document.getElementById("task-target-scope-selector"),
        taskStockSelector: document.getElementById("task-stock-selector"),
        taskSoldoutSelector: document.getElementById("task-soldout-selector"),
        taskRegexPattern: document.getElementById("task-regex-pattern"),
        taskJsonPath: document.getElementById("task-json-path"),
        taskInStockKeywords: document.getElementById("task-in-stock-keywords"),
        taskSoldoutKeywords: document.getElementById("task-soldout-keywords"),
        taskRestock: document.getElementById("task-restock"),
        taskSoldout: document.getElementById("task-soldout"),
        taskTemplateHelpButton: document.getElementById("task-template-help-button"),
        taskTemplateTestKind: document.getElementById("task-template-test-kind"),
        taskTemplateTestChatIds: document.getElementById("task-template-test-chat-ids"),
        taskTemplateTestButton: document.getElementById("task-template-test-button"),
        taskButton1Text: document.getElementById("task-button-1-text"),
        taskButton1Url: document.getElementById("task-button-1-url"),
        taskButton2Text: document.getElementById("task-button-2-text"),
        taskButton2Url: document.getElementById("task-button-2-url"),
        taskEnabled: document.getElementById("task-enabled"),
        taskCancelButton: document.getElementById("task-cancel-button"),
        taskSubmitButton: document.getElementById("task-submit-button"),
        taskSaveCheckButton: document.getElementById("task-save-check-button"),
        templateHelpModal: document.getElementById("template-help-modal"),
        templateHelpClose: document.getElementById("template-help-close"),
        groupRenameModal: document.getElementById("group-rename-modal"),
        groupRenameTitle: document.getElementById("group-rename-title"),
        groupRenameClose: document.getElementById("group-rename-close"),
        groupRenameForm: document.getElementById("group-rename-form"),
        groupRenameInput: document.getElementById("group-rename-input"),
        groupRenameCancel: document.getElementById("group-rename-cancel"),
        groupRenameSubmit: document.getElementById("group-rename-submit"),
        taskMoveModal: document.getElementById("task-move-modal"),
        taskMoveTitle: document.getElementById("task-move-title"),
        taskMoveCount: document.getElementById("task-move-count"),
        taskMoveClose: document.getElementById("task-move-close"),
        taskMoveForm: document.getElementById("task-move-form"),
        taskMoveGroup: document.getElementById("task-move-group"),
        taskMoveGroupCustomWrap: document.getElementById("task-move-group-custom-wrap"),
        taskMoveGroupCustom: document.getElementById("task-move-group-custom"),
        taskMoveSubgroup: document.getElementById("task-move-subgroup"),
        taskMoveSubgroupCustomWrap: document.getElementById("task-move-subgroup-custom-wrap"),
        taskMoveSubgroupCustom: document.getElementById("task-move-subgroup-custom"),
        taskMoveCancel: document.getElementById("task-move-cancel"),
        taskMoveSubmit: document.getElementById("task-move-submit")
    };

    const defaultTemplates = {
        restock: "【补货提醒】\n<b>{name}</b>\n状态：有货\n库存：{stock}\n关键词：{keyword}\n链接：{url}\n时间：{checked_at}",
        soldout: "【售罄提醒】\n<b>{name}</b>\n状态：已售罄\n最后库存：{stock}\n关键词：{keyword}\n链接：{url}\n时间：{checked_at}"
    };
    const stockRuleConfigKeys = [
        "stock_rule_type",
        "target_scope_selector",
        "stock_selector",
        "soldout_selector",
        "regex_pattern",
        "json_path",
        "in_stock_keywords",
        "soldout_keywords"
    ];

    function normalizeFetchStrategy(value) {
        const strategy = String(value || "").trim().toLowerCase().replaceAll("-", "_");
        return strategy || "browser";
    }

    function fetchStrategyLabel(value) {
        switch (normalizeFetchStrategy(value)) {
            case "scrapling_standard":
                return "Scrapling 标准";
            case "scrapling_dynamic":
                return "Scrapling 增强";
            case "scrapling_stealth":
                return "Scrapling 高兼容";
            case "scrapling_adaptive":
                return "Scrapling 自适应";
            case "static_http":
                return "静态 HTTP";
            case "generic_pricing_table":
                return "通用价格页";
            case "whmcs":
                return "WHMCS";
            case "firecrawl":
                return "Firecrawl 外部兜底";
            case "firecrawl_then_static":
                return "外部兜底 → 静态";
            case "static_then_firecrawl":
                return "静态 → 外部兜底";
            case "firecrawl_then_browser":
                return "外部兜底 → 浏览器";
            case "adaptive":
                return "自适应低成本";
            case "manual":
                return "手动录入";
            case "webhook":
                return "Webhook";
            default:
                return "浏览器渲染";
        }
    }

    function fetchStrategyHelp(value) {
        switch (normalizeFetchStrategy(value)) {
            case "scrapling_standard":
                return "Scrapling 标准模式：适合普通公开 IDC / WHMCS 页面，成本最低，作为后续主采集方向。";
            case "scrapling_dynamic":
                return "Scrapling 增强模式：适合 JS 渲染页面，会启动浏览器，资源消耗高于标准模式。";
            case "scrapling_stealth":
                return "Scrapling 高兼容模式：适合复杂页面，低并发、长超时；仍不会处理验证码或 Turnstile。";
            case "scrapling_adaptive":
                return "Scrapling 自适应：按标准、增强、高兼容逐步尝试，失败后进入受保护来源处理。";
            case "firecrawl":
                return "外部付费兜底服务，会消耗 Firecrawl credits；默认不用于定时监控，只建议手动检测、商品入库或诊断时使用。";
            case "firecrawl_then_static":
                return "先尝试外部 Firecrawl，再回退静态 HTTP。定时监控默认会跳过 Firecrawl，除非系统设置显式允许。";
            case "firecrawl_then_browser":
                return "先尝试外部 Firecrawl，再回退本地浏览器。定时监控默认会跳过 Firecrawl，避免持续消耗 credits。";
            case "static_then_firecrawl":
                return "先用本地静态 HTTP，失败后才调用外部 Firecrawl；定时监控需显式允许 Firecrawl 才会触发。";
            case "adaptive":
                return "默认低成本方案：先用静态 HTTP，再用本地浏览器做有限 fallback；不会默认消耗 Firecrawl credits。";
            case "generic_pricing_table":
                return "通用 IDC 价格卡片/表格解析器。会围绕目标关键词判断购买入口、售罄标记和库存数字。";
            case "whmcs":
                return "WHMCS 商城页面专用解析器，适合 cart.php、store、configureproduct 等常见 IDC 购物车页面。";
            case "browser":
                return "本地 Chromium 渲染后解析。适合必须执行 JS 的公开页面；Cloudflare challenge 不会触发反复重建。";
            case "static_http":
                return "本地 requests 抓取 HTML。速度快、成本低，适合无需 JS 渲染的公开页面。";
            case "manual":
                return "手动维护库存状态，不访问目标页面；适合受保护页面或暂时需要人工确认的商品。";
            case "webhook":
                return "由外部系统通过 Webhook 推送库存状态。只有 Webhook 任务才会显示 Token 重置操作。";
            default:
                return "选择一种采集方式后，系统会按该策略抓取并交给解析器判断库存。";
        }
    }

    function parseTaskSourceConfig(value) {
        if (!value) return {};
        if (typeof value === "object") return { ...value };
        try {
            const parsed = JSON.parse(String(value));
            return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
        } catch (error) {
            return {};
        }
    }

    function setTaskStrategy(value) {
        const strategy = normalizeFetchStrategy(value || preferredTaskFetchStrategy());
        if (els.taskFetchStrategy) {
            els.taskFetchStrategy.value = strategy;
        }
        updateTaskStrategyUi();
    }

    function updateTaskStrategyUi() {
        const strategy = normalizeFetchStrategy(els.taskFetchStrategy?.value);
        if (els.taskStrategySummary) {
            els.taskStrategySummary.textContent = fetchStrategyHelp(strategy);
        }
        if (els.taskWebhookHint) {
            els.taskWebhookHint.classList.toggle("hidden", strategy !== "webhook");
        }
        document.querySelectorAll("[data-task-strategy-card]").forEach((card) => {
            const active = normalizeFetchStrategy(card.dataset.taskStrategyCard) === strategy;
            card.classList.toggle("is-active", active);
            card.setAttribute("aria-checked", active ? "true" : "false");
        });
    }

    function setTaskRuleFields(config) {
        const sourceConfig = parseTaskSourceConfig(config);
        if (els.taskStockRuleType) els.taskStockRuleType.value = sourceConfig.stock_rule_type || "";
        if (els.taskTargetScopeSelector) els.taskTargetScopeSelector.value = sourceConfig.target_scope_selector || "";
        if (els.taskStockSelector) els.taskStockSelector.value = sourceConfig.stock_selector || "";
        if (els.taskSoldoutSelector) els.taskSoldoutSelector.value = sourceConfig.soldout_selector || "";
        if (els.taskRegexPattern) els.taskRegexPattern.value = sourceConfig.regex_pattern || "";
        if (els.taskJsonPath) els.taskJsonPath.value = sourceConfig.json_path || "";
        if (els.taskInStockKeywords) {
            els.taskInStockKeywords.value = Array.isArray(sourceConfig.in_stock_keywords)
                ? sourceConfig.in_stock_keywords.join(", ")
                : sourceConfig.in_stock_keywords || "";
        }
        if (els.taskSoldoutKeywords) {
            els.taskSoldoutKeywords.value = Array.isArray(sourceConfig.soldout_keywords)
                ? sourceConfig.soldout_keywords.join(", ")
                : sourceConfig.soldout_keywords || "";
        }
        if (els.taskRuleDetails) {
            els.taskRuleDetails.open = stockRuleConfigKeys.some((key) => Boolean(sourceConfig[key]));
        }
    }

    function splitRuleKeywords(value) {
        return String(value || "")
            .split(/[\n,，]+/)
            .map((item) => item.trim())
            .filter(Boolean);
    }

    function collectTaskSourceConfig() {
        const sourceConfig = parseTaskSourceConfig(els.taskForm?.dataset.sourceConfig || "{}");
        stockRuleConfigKeys.forEach((key) => delete sourceConfig[key]);
        const ruleType = els.taskStockRuleType?.value || "";
        if (ruleType) {
            sourceConfig.stock_rule_type = ruleType;
        }
        const textFields = {
            target_scope_selector: els.taskTargetScopeSelector?.value,
            stock_selector: els.taskStockSelector?.value,
            soldout_selector: els.taskSoldoutSelector?.value,
            regex_pattern: els.taskRegexPattern?.value,
            json_path: els.taskJsonPath?.value
        };
        Object.entries(textFields).forEach(([key, value]) => {
            const text = String(value || "").trim();
            if (text) sourceConfig[key] = text;
        });
        const inStockKeywords = splitRuleKeywords(els.taskInStockKeywords?.value);
        const soldoutKeywords = splitRuleKeywords(els.taskSoldoutKeywords?.value);
        if (inStockKeywords.length) sourceConfig.in_stock_keywords = inStockKeywords;
        if (soldoutKeywords.length) sourceConfig.soldout_keywords = soldoutKeywords;
        return sourceConfig;
    }

    function preferredTaskFetchStrategy() {
        return "scrapling_adaptive";
    }

    function stockResultLabel(stock, state = "") {
        if (stock === null || stock === undefined || state === "unknown") return "未知";
        const value = Number(stock);
        if (Number.isFinite(value) && value > 0) return `有货（库存 ${value}）`;
        if (Number.isFinite(value) && value <= 0) return "售罄";
        return "未知";
    }

    function extractorLabel(value) {
        const extractor = String(value || "").trim().toLowerCase();
        switch (extractor) {
            case "whmcs":
                return "WHMCS";
            case "firecrawl_product_hint":
                return "Firecrawl Product";
            case "fallback_keyword_parser":
                return "关键词 fallback";
            case "generic_pricing_table":
                return "通用价格页";
            default:
                return extractor || "-";
        }
    }

    function catalogErrorAdvice(value) {
        const text = String(value || "").toLowerCase();
        if (!text) return "";
        if (text.includes("catalog_browser_port_busy")) return "修改商品入库浏览器端口后重试。";
        if (text.includes("firecrawl_zdr_not_enabled") || text.includes("zero data retention") || text.includes("zdr")) return "关闭 Firecrawl zeroDataRetention 后重试，或联系 Firecrawl 开通 ZDR。";
        if (text.includes("firecrawl_permission_error")) return "检查 Firecrawl 账号权限、proxy 模式或 zeroDataRetention 配置。";
        if (text.includes("firecrawl_auth_error") || text.includes("认证失败")) return "检查 Firecrawl API Key。";
        if (text.includes("firecrawl_credit_required") || text.includes("额度")) return "Firecrawl 额度不足，建议切回 Scrapling 自适应；Firecrawl 仅作为外部兜底。";
        if (text.includes("firecrawl_rate_limited") || text.includes("频率")) return "降低频率或稍后重试。";
        if (text.includes("cloudflare") || text.includes("turnstile") || text.includes("验证页")) return "受保护站点，建议 Webhook、手动录入或替代公开页面。";
        if (text.includes("parse_unknown") || text.includes("无法判断")) return "设置目标关键词或更换解析器。";
        return "检查来源 URL、抓取策略和解析器后重试。";
    }

    function merchantStockStatusMeta(item) {
        const text = String(`${item.stock_hint || ""} ${item.restock_hint || ""}`).toLowerCase();
        if (text.includes("out of stock") || text.includes("sold out") || text.includes("售罄") || text.includes("缺货") || text.trim() === "0") {
            return ["border-slate-700 bg-slate-900/70 text-slate-400", "售罄"];
        }
        if (text.includes("order") || text.includes("available") || text.includes("库存") || /^[1-9]\d*$/.test(String(item.stock_hint || "").trim())) {
            return ["border-emerald-500/20 bg-emerald-500/10 text-emerald-200", "可入库"];
        }
        return ["border-amber-500/20 bg-amber-500/10 text-amber-200", "无法判断"];
    }

    function catalogDiscoveryLabel(value) {
        switch (String(value || "").trim().toLowerCase()) {
            case "local_sitemap":
                return "sitemap";
            case "local_page_links":
                return "page_links";
            case "local":
                return "Scrapling 页面链接";
            case "hybrid":
                return "Scrapling + 外部 Map";
            case "firecrawl_map":
                return "Firecrawl Map 外部兜底";
            case "entry_page":
                return "入口页面";
            default:
                return value || "-";
        }
    }

    function merchantSourceStatusMeta(source) {
        const lastError = String(source.last_error || "");
        if (lastError) {
            if (catalogErrorAdvice(lastError).includes("受保护站点")) {
                return ["border-amber-500/20 bg-amber-500/10 text-amber-200", "受保护"];
            }
            return ["border-rose-500/20 bg-rose-500/10 text-rose-200", "异常"];
        }
        if (source.last_sync_at) {
            return ["border-sky-500/20 bg-sky-500/10 text-sky-200", "已抓取"];
        }
        return ["border-slate-700 bg-slate-900/70 text-slate-400", "待抓取"];
    }

    function setOptionAvailability(select, values, enabled) {
        if (!select) return;
        const controlledValues = new Set(values);
        Array.from(select.options || []).forEach((option) => {
            if (controlledValues.has(option.value)) {
                option.disabled = !enabled;
            }
        });
    }

    function resetSelectIfDisabled(select, fallbackValue) {
        if (!select) return;
        const selected = Array.from(select.options || []).find((option) => option.value === select.value);
        if (selected?.disabled) {
            select.value = fallbackValue;
        }
    }

    function updateMerchantFirecrawlOptions() {
        const enabled = Boolean(currentSettings.firecrawl_enabled) && currentSettings.firecrawl_use_for_catalog !== false;
        setOptionAvailability(els.merchantDiscoveryStrategy, ["firecrawl_map", "hybrid"], enabled);
        setOptionAvailability(els.merchantScrapeStrategy, ["firecrawl"], enabled);
        setOptionAvailability(els.merchantDefaultFetchStrategy, ["firecrawl"], enabled);
        setOptionAvailability(els.merchantDefaultExtractor, ["firecrawl_product_hint"], enabled);
        resetSelectIfDisabled(els.merchantDiscoveryStrategy, "local");
        resetSelectIfDisabled(els.merchantScrapeStrategy, "browser");
        resetSelectIfDisabled(els.merchantDefaultFetchStrategy, "browser");
        resetSelectIfDisabled(els.merchantDefaultExtractor, "generic_pricing_table");
        if (els.merchantFirecrawlState) {
            els.merchantFirecrawlState.textContent = enabled
                ? "Firecrawl 已启用，可用于 Map、Scrape 和商品提示解析。"
                : "Firecrawl 未启用，相关选项已锁定；可在系统设置 > Firecrawl 外部兜底中开启。";
        }
        renderMerchantReviewSummary();
    }

    const merchantStepOrder = ["source", "strategy", "rules", "review", "sources", "items", "recovery"];

    function merchantStepButtons() {
        return Array.from(document.querySelectorAll(".merchant-step-button[data-merchant-step-target]"));
    }

    function merchantStepPanels() {
        return Array.from(document.querySelectorAll("[data-merchant-step-panel]"));
    }

    function selectOptionLabel(select) {
        if (!select) return "-";
        const option = Array.from(select.options || []).find((item) => item.value === select.value);
        return option?.textContent?.trim() || select.value || "-";
    }

    function renderMerchantReviewSummary() {
        if (!els.merchantReviewSummary) return;
        let payload = {};
        try {
            payload = collectMerchantPayload();
        } catch {
            payload = {
                source_url: els.merchantSourceUrl?.value.trim() || "",
                source_name: els.merchantSourceName?.value.trim() || "",
                group_name: els.merchantGroupCustom?.value.trim() || els.merchantGroup?.value || defaultTaskGroup
            };
        }
        const rows = [
            ["来源 URL", payload.source_url || "未填写"],
            ["来源名称", payload.source_name || "自动识别"],
            ["默认分组", payload.group_name || defaultTaskGroup],
            ["发现方式", selectOptionLabel(els.merchantDiscoveryStrategy)],
            ["抓取方式", selectOptionLabel(els.merchantScrapeStrategy)],
            ["生成任务采集", selectOptionLabel(els.merchantDefaultFetchStrategy)],
            ["解析器", selectOptionLabel(els.merchantDefaultExtractor)],
            ["目标关键词", payload.target_keyword || "不限制"],
            ["单次上限", `${payload.max_discovered_urls || 50} URL / ${payload.max_import_items || 50} 商品`],
            ["自动创建任务", payload.auto_promote ? "开启" : "关闭，先进入商品预览"]
        ];
        els.merchantReviewSummary.innerHTML = rows
            .map(([label, value]) => `
                <div>
                    <span>${escapeHtml(label)}</span>
                    <strong>${escapeHtml(value)}</strong>
                </div>
            `)
            .join("");
    }

    function updateMerchantStepCounts(metrics = {}) {
        if (els.merchantStepSourceCount) {
            els.merchantStepSourceCount.textContent = metrics.total_sources ?? 0;
        }
        if (els.merchantStepItemCount) {
            els.merchantStepItemCount.textContent = metrics.total_items ?? 0;
        }
    }

    function setMerchantStep(step, focusPanel = false) {
        const normalizedStep = merchantStepOrder.includes(step) ? step : "source";
        merchantActiveStep = normalizedStep;
        merchantStepButtons().forEach((button) => {
            const active = button.dataset.merchantStepTarget === normalizedStep;
            button.classList.toggle("merchant-step-active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        merchantStepPanels().forEach((panel) => {
            panel.classList.toggle("hidden", panel.dataset.merchantStepPanel !== normalizedStep);
        });
        renderMerchantReviewSummary();
        if (focusPanel) {
            const panel = document.querySelector(`[data-merchant-step-panel="${normalizedStep}"]`);
            panel?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
    }

    function moveMerchantStep(delta) {
        const currentIndex = merchantStepOrder.indexOf(merchantActiveStep);
        const nextIndex = Math.max(0, Math.min(merchantStepOrder.length - 1, currentIndex + delta));
        setMerchantStep(merchantStepOrder[nextIndex], true);
    }

    function normalizePreviewResult(result = {}) {
        return {
            sourceUrl: result.source_url || "",
            sourceName: result.source_name || "",
            groupName: result.group_name || "",
            generatedAt: result.generated_at || "",
            candidateUrls: Array.isArray(result.candidate_urls) ? result.candidate_urls : [],
            items: Array.isArray(result.items) ? result.items : [],
            rejectedItems: Array.isArray(result.rejected_items) ? result.rejected_items : [],
            failures: Array.isArray(result.failures) ? result.failures : [],
            counts: result.counts || {}
        };
    }

    function hasMerchantPreviewSources() {
        return Boolean(merchantPreview.candidateUrls?.length || merchantPreview.failures?.length);
    }

    function hasMerchantPreviewItems() {
        return Boolean(merchantPreview.items?.length || merchantPreview.rejectedItems?.length || merchantPreview.failures?.length);
    }

    function merchantPreviewSignature() {
        return JSON.stringify({
            sourceUrl: merchantPreview.sourceUrl || "",
            generatedAt: merchantPreview.generatedAt || "",
            urls: (merchantPreview.candidateUrls || []).map((item) => [item.id, item.url, item.status, item.accepted_count, item.rejected_count, item.error_kind]),
            items: (merchantPreview.items || []).map((item) => [item.source_item_key, item.title, item.confidence, item.include_reason]),
            rejected: (merchantPreview.rejectedItems || []).map((item) => [item.source_item_key, item.title, item.reject_reason]),
            failures: (merchantPreview.failures || []).map((item) => [item.url, item.error_kind, item.detail])
        });
    }

    function previewStatusMeta(status, errorKind = "") {
        if (status === "scraped") return ["border-emerald-500/20 bg-emerald-500/10 text-emerald-200", "已抓取"];
        if (status === "failed" || errorKind) return ["border-rose-500/20 bg-rose-500/10 text-rose-200", "失败"];
        if (status === "no_items") return ["border-amber-500/20 bg-amber-500/10 text-amber-200", "无商品"];
        return ["border-slate-700 bg-slate-900/70 text-slate-300", "待抓取"];
    }

    function selectedPreviewUrls() {
        const selectedIds = new Set(Array.from(document.querySelectorAll("[data-preview-url-select]:checked")).map((item) => item.value));
        return (merchantPreview.candidateUrls || []).filter((item) => selectedIds.has(String(item.id)));
    }

    function selectedPreviewItems() {
        const selectedKeys = new Set(Array.from(document.querySelectorAll("[data-preview-item-select]:checked")).map((item) => item.value));
        return (merchantPreview.items || []).filter((item) => selectedKeys.has(String(item.source_item_key)));
    }

    function updateMerchantPreviewActions() {
        const selectedUrls = selectedPreviewUrls();
        const selectedItems = selectedPreviewItems();
        if (els.merchantPreviewUrlCount) {
            els.merchantPreviewUrlCount.textContent = `${selectedUrls.length} 已选`;
        }
        if (els.merchantPreviewScrapeButton) {
            els.merchantPreviewScrapeButton.disabled = !selectedUrls.length;
        }
        if (els.merchantPreviewCommitButton) {
            els.merchantPreviewCommitButton.disabled = !selectedItems.length;
        }
        if (els.merchantBulkPromoteButton && hasMerchantPreviewItems()) {
            els.merchantBulkPromoteButton.disabled = true;
        }
        if (els.merchantBulkPromoteCount && hasMerchantPreviewItems()) {
            els.merchantBulkPromoteCount.textContent = `${selectedItems.length} 待写入`;
        }
    }

    function previewItemSignalHtml(item) {
        const signals = Array.isArray(item.signals) ? item.signals.slice(0, 4) : [];
        if (!signals.length) return '<span>暂无信号</span>';
        return signals.map((signal) => `
            <span title="${escapeHtml(signal.text || "")}">
                ${escapeHtml(signal.type || "signal")} ${escapeHtml(signal.weight ?? "")}
            </span>
        `).join("");
    }

    function renderMerchantPreviewSources() {
        const urls = merchantPreview.candidateUrls || [];
        if (!urls.length) {
            return '<p class="text-sm text-slate-500">暂无候选 URL，请先在执行步骤点击“发现候选 URL”。</p>';
        }
        return urls.map((candidate) => {
            const [statusClass, statusText] = previewStatusMeta(candidate.status, candidate.error_kind);
            const detail = candidate.detail || catalogErrorAdvice(candidate.error_kind || "");
            return `
                <article class="merchant-card rounded-xl border border-slate-800/80 bg-slate-950/50 p-4">
                    <div class="flex flex-wrap items-start justify-between gap-3">
                        <label class="flex min-w-0 flex-1 items-start gap-3">
                            <input type="checkbox" class="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500" data-preview-url-select value="${escapeHtml(candidate.id)}" ${candidate.selected === false ? "" : "checked"}>
                            <span class="min-w-0">
                                <strong class="block truncate text-sm font-bold text-white">${escapeHtml(candidate.url)}</strong>
                                <span class="mt-1 block font-mono text-[11px] text-slate-500">${escapeHtml(catalogDiscoveryLabel(candidate.source))}</span>
                            </span>
                        </label>
                        <span class="rounded-full border px-2.5 py-1 font-mono text-[11px] ${statusClass}">${statusText}</span>
                    </div>
                    <div class="mt-3 flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
                        <span class="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">可入库 ${escapeHtml(candidate.accepted_count ?? 0)}</span>
                        <span class="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">过滤 ${escapeHtml(candidate.rejected_count ?? 0)}</span>
                        <span class="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">后端 ${escapeHtml(fetchStrategyLabel(candidate.backend_used || ""))}</span>
                    </div>
                    ${detail ? `<p class="mt-3 text-xs leading-5 text-slate-500">${escapeHtml(detail)}</p>` : ""}
                </article>
            `;
        }).join("");
    }

    function renderMerchantPreviewItems() {
        const items = merchantPreview.items || [];
        const rejected = merchantPreview.rejectedItems || [];
        const failures = merchantPreview.failures || [];
        if (!items.length && !rejected.length && !failures.length) {
            return '<p class="text-sm text-slate-500">暂无商品预览，请先在发现结果中抓取选中 URL。</p>';
        }
        const summaryHtml = `
            <div class="merchant-preview-summary">
                <div>
                    <span>可入库</span>
                    <strong>${items.length}</strong>
                    <p>高置信商品会默认勾选，确认后可写入商品库。</p>
                </div>
                <div>
                    <span>需要人工确认</span>
                    <strong>${rejected.length}</strong>
                    <p>低置信、关键词不匹配、语言/导航/步骤标题会留在这里。</p>
                </div>
                <div>
                    <span>抓取失败</span>
                    <strong>${failures.length}</strong>
                    <p>失败项会给出恢复建议，不会自动创建任务。</p>
                </div>
            </div>
        `;
        const acceptedHtml = items.map((item) => {
            const [stockClass, stockText] = merchantStockStatusMeta(item);
            const confidence = Number(item.confidence || 0);
            const reasonText = item.include_reason || "暂无识别依据";
            return `
                <article class="merchant-card rounded-xl border border-slate-800/80 bg-slate-950/50 p-4">
                    <div class="flex flex-wrap items-start justify-between gap-3">
                        <label class="flex min-w-0 flex-1 items-start gap-3">
                            <input type="checkbox" class="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-950 text-indigo-500" data-preview-item-select value="${escapeHtml(item.source_item_key)}" checked>
                            <span class="min-w-0">
                                <strong class="block truncate text-sm font-bold text-white">${escapeHtml(item.title)}</strong>
                                <span class="mt-1 block truncate font-mono text-[11px] text-slate-500">${escapeHtml(item.item_url || item.monitor_url || "")}</span>
                            </span>
                        </label>
                        <span class="rounded-full border px-2.5 py-1 font-mono text-[11px] ${stockClass}">${stockText}</span>
                    </div>
                    <div class="mt-3 grid gap-2 text-[11px] font-mono text-slate-400 sm:grid-cols-2">
                        <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">关键词：${escapeHtml(item.keyword)}</span>
                        <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">价格：${escapeHtml(item.price_hint || "-")}</span>
                        <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">后端：${escapeHtml(fetchStrategyLabel(item.backend_used || ""))}</span>
                        <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">解析器：${escapeHtml(extractorLabel(item.extractor))}</span>
                    </div>
                    <div class="merchant-signal-box">
                        <div>
                            <span>置信度</span>
                            <strong>${confidence > 0 ? `${confidence}%` : "-"}</strong>
                        </div>
                        <p>${escapeHtml(reasonText)}</p>
                        <div class="merchant-signal-chips">${previewItemSignalHtml(item)}</div>
                    </div>
                </article>
            `;
        }).join("");
        const rejectedHtml = rejected.length ? `
            <div class="merchant-preview-section-title">需要人工确认 / 已过滤候选</div>
            <p class="merchant-preview-help">这些候选不会写入商品库。常见原因是目标关键词不匹配、置信度过低、语言切换、导航、页脚或步骤标题。</p>
            ${rejected.slice(0, 20).map((item) => `
                <article class="merchant-card rounded-xl border border-amber-500/15 bg-amber-500/5 p-4">
                    <div class="flex flex-wrap items-start justify-between gap-3">
                        <div class="min-w-0">
                            <h4 class="truncate text-sm font-bold text-amber-100">${escapeHtml(item.title || "未命名候选")}</h4>
                            <p class="mt-1 text-xs leading-5 text-amber-100/70">${escapeHtml(item.reject_reason || "已过滤")}</p>
                        </div>
                        <span class="rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-1 font-mono text-[11px] text-amber-200">${escapeHtml(item.confidence || 0)}%</span>
                    </div>
                </article>
            `).join("")}
        ` : "";
        const failureHtml = failures.length ? `
            <div class="merchant-preview-section-title">抓取失败项</div>
            <p class="merchant-preview-help">失败项不会进入商品库。按错误提示调整抓取方式、Firecrawl 配置、目标关键词或替代公开页面后再重试。</p>
            ${failures.slice(0, 20).map((failure) => `
                <article class="merchant-card rounded-xl border border-rose-500/15 bg-rose-500/5 p-4">
                    <h4 class="truncate text-sm font-bold text-rose-100">${escapeHtml(failure.url || failure.error_kind || "抓取失败")}</h4>
                    <p class="mt-1 text-xs leading-5 text-rose-100/75">${escapeHtml(failure.detail || catalogErrorAdvice(failure.error_kind))}</p>
                </article>
            `).join("")}
        ` : "";
        return `${summaryHtml}${acceptedHtml}${rejectedHtml}${failureHtml}`;
    }

    function fetchAttemptMeta(task) {
        const backendText = task.last_fetch_backend ? ` · 采集: ${fetchStrategyLabel(task.last_fetch_backend)}` : "";
        const attempts = Array.isArray(task.last_fetch_attempts) ? task.last_fetch_attempts : [];
        const attemptsText = attempts.length > 1 ? ` · ${attempts.length} 次尝试` : "";
        return `${backendText}${attemptsText}`;
    }

    function errorKindLabel(kind) {
        switch (kind) {
            case "cloudflare_challenge":
                return "受保护页面 / Cloudflare 验证";
            case "telegram_error":
                return "通知失败，不影响库存识别";
            case "firecrawl_zdr_not_enabled":
                return "Firecrawl ZDR 未开通";
            case "firecrawl_permission_error":
                return "Firecrawl 权限不足";
            case "firecrawl_bad_request":
                return "Firecrawl 参数错误";
            case "firecrawl_auth_error":
                return "Firecrawl 认证失败";
            case "firecrawl_monitor_disabled":
                return "Firecrawl 定时监控未启用";
            case "firecrawl_credit_required":
                return "Firecrawl 额度不足";
            case "firecrawl_rate_limited":
                return "Firecrawl 频率受限";
            case "firecrawl_upstream_error":
                return "Firecrawl 服务异常";
            case "firecrawl_bad_response":
                return "Firecrawl 响应异常";
            case "firecrawl_disabled":
                return "Firecrawl 未启用";
            case "empty_response":
                return "页面没有可解析内容";
            case "parse_unknown":
                return "解析器无法判断库存";
            case "catalog_browser_port_busy":
                return "商品入库浏览器端口被占用";
            case "catalog_browser_connection_failed":
                return "商品入库浏览器连接失败";
            case "timeout":
                return "请求超时";
            case "browser_connection":
                return "浏览器连接异常";
            default:
                return "";
        }
    }

    function errorKindTone(kind) {
        switch (kind) {
            case "cloudflare_challenge":
                return "text-amber-300";
            case "browser_connection":
                return "text-orange-300";
            case "telegram_error":
                return "text-sky-300";
            case "timeout":
                return "text-rose-300";
            default:
                return "text-rose-300";
        }
    }

    function formatTaskLogLine(task, logHint) {
        if (task.last_error) {
            const protectedNotice = protectedSourceNoticeText(task);
            if (protectedNotice) {
                return `> ${protectedNotice}`;
            }
            const label = errorKindLabel(task.last_error_kind);
            const detail = task.last_error_detail || task.last_error;
            return label ? `> ${label}${detail ? `：${detail}` : ""}` : `> ${detail}`;
        }
        return `> ${logHint} ${formatTime(task.last_checked_at)}`;
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    const defaultTaskGroup = "默认分组";
    const defaultTaskSubgroup = "默认子分组";
    let pendingGroupRename = "";
    let pendingTaskMoveIds = [];

    function normalizeTaskGroup(value) {
        const group = String(value ?? "").trim().replace(/\s+/g, " ");
        return group || defaultTaskGroup;
    }

    function normalizeTaskSubgroup(value) {
        const raw = String(value ?? "").trim().replace(/\s+/g, " ");
        const parts = raw.split(/\s*\/\s*/).map((part) => part.trim()).filter(Boolean);
        return parts.length ? parts.join(" / ") : defaultTaskSubgroup;
    }

    function splitTaskSubgroupPath(value) {
        const normalized = normalizeTaskSubgroup(value);
        if (normalized === defaultTaskSubgroup) {
            return [];
        }
        return normalized.split(" / ").map((part) => part.trim()).filter(Boolean);
    }

    function joinTaskSubgroupPath(parts) {
        const cleaned = (parts || []).map((part) => String(part || "").trim()).filter(Boolean);
        return cleaned.length ? normalizeTaskSubgroup(cleaned.join(" / ")) : defaultTaskSubgroup;
    }

    function taskSubgroupPath(task) {
        return joinTaskSubgroupPath(splitTaskSubgroupPath(task?.subgroup_name));
    }

    function isSameSubgroupPath(left, right) {
        return joinTaskSubgroupPath(splitTaskSubgroupPath(left)) === joinTaskSubgroupPath(splitTaskSubgroupPath(right));
    }

    function isSubgroupDescendant(path, parentPath) {
        const pathParts = splitTaskSubgroupPath(path);
        const parentParts = splitTaskSubgroupPath(parentPath);
        if (pathParts.length <= parentParts.length) {
            return false;
        }
        return parentParts.every((part, index) => pathParts[index] === part);
    }

    function directChildSubgroupPath(path, parentPath) {
        const pathParts = splitTaskSubgroupPath(path);
        const parentParts = splitTaskSubgroupPath(parentPath);
        if (pathParts.length <= parentParts.length) {
            return "";
        }
        if (!parentParts.every((part, index) => pathParts[index] === part)) {
            return "";
        }
        return joinTaskSubgroupPath(pathParts.slice(0, parentParts.length + 1));
    }

    function groupSortOrder(groupName) {
        const normalized = normalizeTaskGroup(groupName);
        const row = currentTaskGroups.find((group) => normalizeTaskGroup(group.group_name) === normalized);
        return Number(row?.sort_order || 0);
    }

    function subgroupSortOrder(groupName, subgroupName) {
        const normalizedGroup = normalizeTaskGroup(groupName);
        const normalizedSubgroup = normalizeTaskSubgroup(subgroupName);
        const row = currentTaskGroupNodes.find((node) => (
            normalizeTaskGroup(node.group_name) === normalizedGroup
            && normalizeTaskSubgroup(node.subgroup_name) === normalizedSubgroup
        ));
        return Number(row?.sort_order || 0);
    }

    function compareCardsByOrderName(left, right) {
        const orderDelta = Number(left.sort_order || 0) - Number(right.sort_order || 0);
        if (orderDelta) return orderDelta;
        return String(left.name || "").localeCompare(String(right.name || ""), "zh-Hans-CN");
    }

    function compareTasksByOrder(left, right) {
        const orderDelta = Number(left.sort_order || 0) - Number(right.sort_order || 0);
        if (orderDelta) return orderDelta;
        return Number(right.id || 0) - Number(left.id || 0);
    }

    function collectGroupNames(tasks, extraGroupNames = []) {
        const groups = new Set([defaultTaskGroup]);
        tasks.forEach((task) => {
            groups.add(normalizeTaskGroup(task.group_name));
        });
        extraGroupNames.forEach((groupName) => {
            const normalized = normalizeTaskGroup(groupName);
            if (normalized) {
                groups.add(normalized);
            }
        });
        return Array.from(groups);
    }

    function collectSubgroupNames(tasks, groupName, extraSubgroupNames = []) {
        const targetGroup = normalizeTaskGroup(groupName);
        const subgroups = new Set([defaultTaskSubgroup]);
        tasks.forEach((task) => {
            if (normalizeTaskGroup(task.group_name) === targetGroup) {
                subgroups.add(normalizeTaskSubgroup(task.subgroup_name));
            }
        });
        currentTaskGroupNodes.forEach((node) => {
            if (normalizeTaskGroup(node.group_name) === targetGroup) {
                subgroups.add(normalizeTaskSubgroup(node.subgroup_name));
            }
        });
        extraSubgroupNames.forEach((subgroupName) => {
            const normalized = normalizeTaskSubgroup(subgroupName);
            if (normalized) {
                subgroups.add(normalized);
            }
        });
        return Array.from(subgroups);
    }

    function updateGroupVisibility(selectEl, customWrapEl, customInputEl) {
        if (!selectEl || !customWrapEl || !customInputEl) {
            return;
        }
        const customMode = selectEl.value === "__custom__";
        customWrapEl.classList.toggle("hidden", !customMode);
        if (customMode) {
            wireDirtyTracking(customInputEl);
        }
    }

    function renderGroupOptions(selectEl, customWrapEl, customInputEl, tasks, extraGroupNames = []) {
        if (!selectEl) {
            return;
        }
        const currentSelectValue = selectEl.value || defaultTaskGroup;
        const currentCustomValue = customInputEl?.value || "";
        const groupNames = collectGroupNames(tasks, extraGroupNames);
        if (currentSelectValue !== "__custom__" && !groupNames.includes(currentSelectValue)) {
            groupNames.push(currentSelectValue);
        }
        const nextSignature = groupNames.join("\u0000");
        if (selectEl.dataset.groupOptionsSignature === nextSignature && selectEl.dataset.groupOptionsReady === "1") {
            updateGroupVisibility(selectEl, customWrapEl, customInputEl);
            return;
        }
        selectEl.dataset.groupOptionsSignature = nextSignature;
        selectEl.innerHTML = `${groupNames
            .map((groupName) => `<option value="${escapeHtml(groupName)}">${escapeHtml(groupName)}</option>`)
            .join("")}<option value="__custom__">新建分组…</option>`;
        selectEl.dataset.groupOptionsReady = "1";
        if (currentSelectValue === "__custom__") {
            selectEl.value = "__custom__";
            syncInputValue(customInputEl, currentCustomValue);
        } else {
            selectEl.value = groupNames.includes(currentSelectValue) ? currentSelectValue : defaultTaskGroup;
            syncInputValue(customInputEl, "");
        }
        updateGroupVisibility(selectEl, customWrapEl, customInputEl);
    }

    function setGroupSelection(selectEl, customWrapEl, customInputEl, groupName, tasks, extraGroupNames = []) {
        if (!selectEl) {
            return;
        }
        renderGroupOptions(selectEl, customWrapEl, customInputEl, tasks, extraGroupNames);
        const normalized = normalizeTaskGroup(groupName);
        const groupNames = collectGroupNames(tasks, extraGroupNames);
        if (groupNames.includes(normalized)) {
            selectEl.value = normalized;
            syncInputValue(customInputEl, "");
        } else {
            selectEl.value = "__custom__";
            syncInputValue(customInputEl, normalized);
        }
        updateGroupVisibility(selectEl, customWrapEl, customInputEl);
    }

    function readGroupValue(selectEl, customInputEl) {
        if (!selectEl) {
            return defaultTaskGroup;
        }
        if (selectEl.value === "__custom__") {
            const customGroup = String(customInputEl?.value || "").trim();
            return customGroup ? normalizeTaskGroup(customGroup) : "";
        }
        return normalizeTaskGroup(selectEl.value);
    }

    function renderTaskGroupOptions(tasks, extraGroupNames = []) {
        renderGroupOptions(els.taskGroup, els.taskGroupCustomWrap, els.taskGroupCustom, tasks, extraGroupNames);
    }

    function renderMerchantGroupOptions(tasks, extraGroupNames = []) {
        renderGroupOptions(els.merchantGroup, els.merchantGroupCustomWrap, els.merchantGroupCustom, tasks, extraGroupNames);
    }

    function renderTaskMoveGroupOptions(extraGroupNames = []) {
        renderGroupOptions(els.taskMoveGroup, els.taskMoveGroupCustomWrap, els.taskMoveGroupCustom, Array.from(currentTasks.values()), extraGroupNames);
    }

    function setTaskGroupSelection(groupName, extraGroupNames = []) {
        setGroupSelection(els.taskGroup, els.taskGroupCustomWrap, els.taskGroupCustom, groupName, Array.from(currentTasks.values()), extraGroupNames);
    }

    function setTaskMoveGroupSelection(groupName, extraGroupNames = []) {
        setGroupSelection(els.taskMoveGroup, els.taskMoveGroupCustomWrap, els.taskMoveGroupCustom, groupName, Array.from(currentTasks.values()), extraGroupNames);
    }

    function readTaskGroupValue() {
        return readGroupValue(els.taskGroup, els.taskGroupCustom);
    }

    function readTaskMoveGroupValue() {
        return readGroupValue(els.taskMoveGroup, els.taskMoveGroupCustom);
    }

    function readMerchantGroupValue() {
        return readGroupValue(els.merchantGroup, els.merchantGroupCustom);
    }

    function renderTaskSubgroupOptions(groupName, extraSubgroupNames = []) {
        const selectEl = els.taskSubgroup;
        const customWrapEl = els.taskSubgroupCustomWrap;
        const customInputEl = els.taskSubgroupCustom;
        if (!selectEl) {
            return;
        }
        const currentSelectValue = selectEl.value || defaultTaskSubgroup;
        const currentCustomValue = customInputEl?.value || "";
        const subgroupNames = collectSubgroupNames(Array.from(currentTasks.values()), groupName, extraSubgroupNames);
        if (currentSelectValue !== "__custom__" && !subgroupNames.includes(currentSelectValue)) {
            subgroupNames.push(currentSelectValue);
        }
        const signature = `${normalizeTaskGroup(groupName)}\u0000${subgroupNames.join("\u0000")}`;
        if (selectEl.dataset.subgroupOptionsSignature === signature && selectEl.dataset.subgroupOptionsReady === "1") {
            updateGroupVisibility(selectEl, customWrapEl, customInputEl);
            return;
        }
        selectEl.dataset.subgroupOptionsSignature = signature;
        selectEl.innerHTML = `${subgroupNames
            .map((subgroupName) => `<option value="${escapeHtml(subgroupName)}">${escapeHtml(subgroupName)}</option>`)
            .join("")}<option value="__custom__">新建子分组…</option>`;
        selectEl.dataset.subgroupOptionsReady = "1";
        if (currentSelectValue === "__custom__") {
            selectEl.value = "__custom__";
            syncInputValue(customInputEl, currentCustomValue);
        } else {
            selectEl.value = subgroupNames.includes(currentSelectValue) ? currentSelectValue : defaultTaskSubgroup;
            syncInputValue(customInputEl, "");
        }
        updateGroupVisibility(selectEl, customWrapEl, customInputEl);
    }

    function setTaskSubgroupSelection(groupName, subgroupName, extraSubgroupNames = []) {
        if (!els.taskSubgroup) {
            return;
        }
        renderTaskSubgroupOptions(groupName, extraSubgroupNames);
        const normalized = normalizeTaskSubgroup(subgroupName);
        const subgroupNames = collectSubgroupNames(Array.from(currentTasks.values()), groupName, extraSubgroupNames);
        if (subgroupNames.includes(normalized)) {
            els.taskSubgroup.value = normalized;
            syncInputValue(els.taskSubgroupCustom, "");
        } else {
            els.taskSubgroup.value = "__custom__";
            syncInputValue(els.taskSubgroupCustom, normalized);
        }
        updateGroupVisibility(els.taskSubgroup, els.taskSubgroupCustomWrap, els.taskSubgroupCustom);
    }

    function readTaskSubgroupValue() {
        if (!els.taskSubgroup) {
            return defaultTaskSubgroup;
        }
        if (els.taskSubgroup.value === "__custom__") {
            const customSubgroup = String(els.taskSubgroupCustom?.value || "").trim();
            return customSubgroup ? normalizeTaskSubgroup(customSubgroup) : "";
        }
        return normalizeTaskSubgroup(els.taskSubgroup.value);
    }

    function renderTaskMoveSubgroupOptions(groupName, extraSubgroupNames = []) {
        const selectEl = els.taskMoveSubgroup;
        const customWrapEl = els.taskMoveSubgroupCustomWrap;
        const customInputEl = els.taskMoveSubgroupCustom;
        if (!selectEl) {
            return;
        }
        const currentSelectValue = selectEl.value || defaultTaskSubgroup;
        const currentCustomValue = customInputEl?.value || "";
        const subgroupNames = collectSubgroupNames(Array.from(currentTasks.values()), groupName, extraSubgroupNames);
        if (currentSelectValue !== "__custom__" && !subgroupNames.includes(currentSelectValue)) {
            subgroupNames.push(currentSelectValue);
        }
        const signature = `${normalizeTaskGroup(groupName)}\u0000${subgroupNames.join("\u0000")}`;
        if (selectEl.dataset.subgroupOptionsSignature === signature && selectEl.dataset.subgroupOptionsReady === "1") {
            updateGroupVisibility(selectEl, customWrapEl, customInputEl);
            return;
        }
        selectEl.dataset.subgroupOptionsSignature = signature;
        selectEl.innerHTML = `${subgroupNames
            .map((subgroupName) => `<option value="${escapeHtml(subgroupName)}">${escapeHtml(subgroupName)}</option>`)
            .join("")}<option value="__custom__">新建子分组…</option>`;
        selectEl.dataset.subgroupOptionsReady = "1";
        if (currentSelectValue === "__custom__") {
            selectEl.value = "__custom__";
            syncInputValue(customInputEl, currentCustomValue);
        } else {
            selectEl.value = subgroupNames.includes(currentSelectValue) ? currentSelectValue : defaultTaskSubgroup;
            syncInputValue(customInputEl, "");
        }
        updateGroupVisibility(selectEl, customWrapEl, customInputEl);
    }

    function setTaskMoveSubgroupSelection(groupName, subgroupName, extraSubgroupNames = []) {
        if (!els.taskMoveSubgroup) {
            return;
        }
        renderTaskMoveSubgroupOptions(groupName, extraSubgroupNames);
        const normalized = normalizeTaskSubgroup(subgroupName);
        const subgroupNames = collectSubgroupNames(Array.from(currentTasks.values()), groupName, extraSubgroupNames);
        if (subgroupNames.includes(normalized)) {
            els.taskMoveSubgroup.value = normalized;
            syncInputValue(els.taskMoveSubgroupCustom, "");
        } else {
            els.taskMoveSubgroup.value = "__custom__";
            syncInputValue(els.taskMoveSubgroupCustom, normalized);
        }
        updateGroupVisibility(els.taskMoveSubgroup, els.taskMoveSubgroupCustomWrap, els.taskMoveSubgroupCustom);
    }

    function readTaskMoveSubgroupValue() {
        if (!els.taskMoveSubgroup) {
            return defaultTaskSubgroup;
        }
        if (els.taskMoveSubgroup.value === "__custom__") {
            const customSubgroup = String(els.taskMoveSubgroupCustom?.value || "").trim();
            return customSubgroup ? normalizeTaskSubgroup(customSubgroup) : "";
        }
        return normalizeTaskSubgroup(els.taskMoveSubgroup.value);
    }

    function splitTelegramChatIds(value) {
        return String(value ?? "")
            .split(/\r?\n/)
            .map((chatId) => chatId.trim())
            .filter(Boolean);
    }

    function formatTime(value) {
        if (!value) return "尚未检查";
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) return value;
        return parsed.toLocaleString("zh-CN", { hour12: false });
    }

    function protectedSourceNoticeText(task) {
        if (task.last_error_kind !== "cloudflare_challenge" || !task.cooldown_until) {
            return "";
        }
        const backend = normalizeFetchStrategy(task.last_protected_source_backend || task.last_fetch_backend || "");
        if (backend === "firecrawl") {
            return `外部采集服务也返回受保护页面 · 冷却至 ${formatTime(task.cooldown_until)} · 建议改用 Webhook、手动录入或替代公开页面`;
        }
        return `本地抓取遇到受保护站点 · 冷却至 ${formatTime(task.cooldown_until)} · 建议改用 Webhook、手动录入或替代公开页面`;
    }

    function webhookMetaText(task) {
        if (normalizeFetchStrategy(task.fetch_strategy) !== "webhook") {
            return "";
        }
        const endpoint = task.webhook_endpoint || "";
        const hint = task.ingest_token_hint || "未生成";
        return `Webhook: ${endpoint || "-"} · token ${hint}`;
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
        wireDirtyTracking(input);
        const nextValue = String(value ?? "");
        const syncedValue = input.dataset.syncedValue;
        const hasLocalEdit = syncedValue !== undefined && input.value !== syncedValue;
        const hasDirtyFlag = input.dataset.inputDirty === "1";

        if (input.value === nextValue) {
            input.dataset.syncedValue = nextValue;
            input.dataset.inputDirty = "0";
            return;
        }
        if (document.activeElement === input || hasLocalEdit || hasDirtyFlag) {
            return;
        }
        input.value = nextValue;
        input.dataset.syncedValue = nextValue;
        input.dataset.inputDirty = "0";
    }

    function syncCheckboxValue(input, value) {
        if (!input) return;
        wireDirtyTracking(input);
        const nextValue = value ? "1" : "0";
        const currentValue = input.checked ? "1" : "0";
        const syncedValue = input.dataset.syncedChecked;
        const hasLocalEdit = syncedValue !== undefined && currentValue !== syncedValue;
        const hasDirtyFlag = input.dataset.inputDirty === "1";

        if (currentValue === nextValue) {
            input.dataset.syncedChecked = nextValue;
            input.dataset.inputDirty = "0";
            return;
        }
        if (document.activeElement === input || hasLocalEdit || hasDirtyFlag) {
            return;
        }
        input.checked = value;
        input.dataset.syncedChecked = nextValue;
        input.dataset.inputDirty = "0";
    }

    function wireDirtyTracking(input) {
        if (!input || input.dataset.dirtyTracking === "1") {
            return;
        }
        input.dataset.dirtyTracking = "1";
        const markDirty = () => {
            if (input.type === "checkbox") {
                const syncedChecked = input.dataset.syncedChecked ?? (input.checked ? "1" : "0");
                input.dataset.inputDirty = (input.checked ? "1" : "0") === syncedChecked ? "0" : "1";
                return;
            }
            const syncedValue = input.dataset.syncedValue ?? "";
            input.dataset.inputDirty = input.value === syncedValue ? "0" : "1";
        };
        input.addEventListener("input", markDirty);
        input.addEventListener("change", markDirty);
        input.addEventListener("blur", markDirty);
    }

    function updateTaskCard(task) {
        const card = els.tasksGrid?.querySelector?.(`[data-task-id="${task.id}"]`);
        if (!card) {
            return;
        }

        const [statusClass, statusText, logHint] = statusMeta(task);
        const stockText = task.last_stock === null || task.last_stock === undefined ? "-" : String(task.last_stock);
        const lastChecked = task.last_checked_at ? formatTime(task.last_checked_at) : "尚未检查";
        const actionLabel = task.enabled ? "停用任务" : "启用任务";
        const sourceLine = task.source_source_name
            ? `来源：${task.source_source_name}${task.source_item_url ? ` · ${task.source_item_url}` : ""}`
            : "";
        const fetchStrategyText = fetchStrategyLabel(task.fetch_strategy);
        const logLine = formatTaskLogLine(task, logHint);
        const protectedNotice = protectedSourceNoticeText(task);
        const webhookMeta = webhookMetaText(task);
        const attemptMeta = fetchAttemptMeta(task);

        const statusBadge = card.querySelector("[data-task-status]");
        if (statusBadge) {
            statusBadge.className = `status-badge ${statusClass}`;
            statusBadge.textContent = statusText;
        }

        const title = card.querySelector("[data-task-name]");
        if (title) {
            title.textContent = task.name || "";
            title.setAttribute("title", task.name || "");
        }

        const url = card.querySelector("[data-task-url]");
        if (url) {
            url.textContent = task.monitor_url || "";
            url.setAttribute("title", task.monitor_url || "");
        }

        const source = card.querySelector("[data-task-source]");
        if (source) {
            source.textContent = sourceLine;
            source.classList.toggle("hidden", !sourceLine);
        }

        const keyword = card.querySelector("[data-task-keyword-text]");
        if (keyword) {
            keyword.textContent = `关键词: ${task.target_keyword || ""}`;
        }
        const fetchStrategy = card.querySelector("[data-task-fetch-strategy]");
        if (fetchStrategy) {
            fetchStrategy.textContent = fetchStrategyText;
        }

        const terminal = card.querySelector("[data-task-terminal]");
        if (terminal) {
            terminal.classList.toggle("opacity-95", !task.last_error);
        }

        const stock = card.querySelector("[data-task-stock]");
        if (stock) {
            stock.textContent = stockText;
            stock.className = task.last_stock > 0 ? "text-emerald-400 font-bold" : "text-slate-300 font-bold";
        }

        const log = card.querySelector("[data-task-log]");
        if (log) {
            log.textContent = logLine;
            log.className = `task-log-text truncate-two font-mono ${task.last_error ? errorKindTone(task.last_error_kind) : "animate-pulse-soft text-emerald-400"}`;
        }
        const protectedNoticeEl = card.querySelector("[data-task-protected-notice]");
        if (protectedNoticeEl) {
            protectedNoticeEl.textContent = protectedNotice;
            protectedNoticeEl.classList.toggle("hidden", !protectedNotice);
        }
        const webhookMetaEl = card.querySelector("[data-task-webhook-meta]");
        if (webhookMetaEl) {
            webhookMetaEl.textContent = webhookMeta;
            webhookMetaEl.classList.toggle("hidden", !webhookMeta);
        }
        const manualActions = card.querySelector("[data-task-manual-actions]");
        if (manualActions) {
            manualActions.classList.toggle("hidden", normalizeFetchStrategy(task.fetch_strategy) !== "manual");
        }
        const webhookAction = card.querySelector("[data-task-webhook-action]");
        if (webhookAction) {
            webhookAction.classList.toggle("hidden", normalizeFetchStrategy(task.fetch_strategy) !== "webhook");
        }
        const checkAction = card.querySelector("[data-task-check-action]");
        if (checkAction) {
            checkAction.classList.toggle(
                "hidden",
                ["manual", "webhook"].includes(normalizeFetchStrategy(task.fetch_strategy))
            );
        }

        const meta = card.querySelector("[data-task-meta]");
        if (meta) {
            meta.textContent = `message_id: ${task.message_id ?? "-"} · checked: ${lastChecked}${attemptMeta}`;
        }

        const toggle = card.querySelector("[data-task-toggle]");
        if (toggle) {
            toggle.title = actionLabel;
            toggle.setAttribute("aria-label", actionLabel);
        }
    }

    function updateTaskGroupSummaries(tasks) {
        const summaryMap = new Map();
        const subgroupSummaryMap = new Map();
        tasks.forEach((task) => {
            const groupName = normalizeTaskGroup(task.group_name);
            if (!summaryMap.has(groupName)) {
                summaryMap.set(groupName, { count: 0, errorCount: 0 });
            }
            const summary = summaryMap.get(groupName);
            summary.count += 1;
            if (task.last_error) {
                summary.errorCount += 1;
            }
            const subgroupParts = splitTaskSubgroupPath(task.subgroup_name);
            subgroupParts.forEach((_, index) => {
                const subgroupName = joinTaskSubgroupPath(subgroupParts.slice(0, index + 1));
                const subgroupKey = `${groupName}\u0000${subgroupName}`;
                if (!subgroupSummaryMap.has(subgroupKey)) {
                    subgroupSummaryMap.set(subgroupKey, { count: 0, errorCount: 0 });
                }
                const subgroupSummary = subgroupSummaryMap.get(subgroupKey);
                subgroupSummary.count += 1;
                if (task.last_error) {
                    subgroupSummary.errorCount += 1;
                }
            });
        });

        els.tasksGrid?.querySelectorAll?.("[data-task-group-section]")?.forEach((section) => {
            const groupName = section.dataset.taskGroupName || defaultTaskGroup;
            const summary = summaryMap.get(groupName) || { count: 0, errorCount: 0 };
            const countBadge = section.querySelector("[data-task-group-count]");
            if (countBadge) {
                countBadge.textContent = `${summary.count} 个任务`;
            }
            const errorBadge = section.querySelector("[data-task-group-error]");
            if (errorBadge) {
                errorBadge.textContent = `${summary.errorCount} 错误`;
                errorBadge.classList.toggle("hidden", summary.errorCount === 0);
            }
        });

        els.tasksGrid?.querySelectorAll?.("[data-task-subgroup-section]")?.forEach((section) => {
            const groupName = section.dataset.taskGroupName || defaultTaskGroup;
            const subgroupName = section.dataset.taskSubgroupName || defaultTaskSubgroup;
            const summary = subgroupSummaryMap.get(`${groupName}\u0000${subgroupName}`) || { count: 0, errorCount: 0 };
            const countBadge = section.querySelector("[data-task-subgroup-count]");
            if (countBadge) {
                countBadge.textContent = `${summary.count} 个任务`;
            }
            const errorBadge = section.querySelector("[data-task-subgroup-error]");
            if (errorBadge) {
                errorBadge.textContent = `${summary.errorCount} 错误`;
                errorBadge.classList.toggle("hidden", summary.errorCount === 0);
            }
        });
    }

    async function apiFetch(path, options = {}) {
        const method = String(options.method || "GET").toUpperCase();
        const headers = {
            Accept: "application/json",
            "X-Requested-With": "XMLHttpRequest",
            ...(options.headers || {})
        };
        if (options.body !== undefined) {
            headers["Content-Type"] = "application/json";
        }
        if (method !== "GET") {
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
        const responseMessage = String(data.message || "").trim();
        const gateBlocked = method !== "GET" && response.status === 404
            && path.startsWith("/api/")
            && (!responseMessage || responseMessage.toUpperCase() === "NOT FOUND");
        if (gateBlocked) {
            window.setTimeout(() => window.location.reload(), 900);
            const err = new Error("页面会话已失效，正在刷新页面...");
            err.status = response.status;
            throw err;
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

    function openSettingsHome() {
        els.settingsHome?.classList.remove("hidden");
        els.settingsPages?.classList.add("hidden");
        els.settingsView?.querySelectorAll?.("[data-settings-panel]")?.forEach((panel) => {
            panel.classList.add("hidden");
        });
    }

    function openSettingsPage(panelId) {
        const panel = panelId ? document.getElementById(panelId) : null;
        if (!panel) {
            openSettingsHome();
            return;
        }
        els.settingsHome?.classList.add("hidden");
        els.settingsPages?.classList.remove("hidden");
        els.settingsView?.querySelectorAll?.("[data-settings-panel]")?.forEach((section) => {
            section.classList.toggle("hidden", section !== panel);
        });
        panel.scrollIntoView({ block: "start" });
    }

    function firecrawlGuideSlideCount() {
        return els.firecrawlGuideTrack?.children?.length || 0;
    }

    function renderFirecrawlGuide() {
        const total = firecrawlGuideSlideCount();
        firecrawlGuideIndex = Math.min(Math.max(firecrawlGuideIndex, 0), Math.max(total - 1, 0));
        if (els.firecrawlGuideTrack) {
            els.firecrawlGuideTrack.style.transform = `translateX(-${firecrawlGuideIndex * 100}%)`;
        }
        els.firecrawlGuideDots?.querySelectorAll("[data-firecrawl-step]").forEach((button) => {
            const isActive = Number(button.dataset.firecrawlStep) === firecrawlGuideIndex;
            button.classList.toggle("is-active", isActive);
            button.setAttribute("aria-current", isActive ? "step" : "false");
        });
        if (els.firecrawlGuidePrev) {
            els.firecrawlGuidePrev.disabled = firecrawlGuideIndex === 0;
        }
        if (els.firecrawlGuideNext) {
            els.firecrawlGuideNext.textContent = firecrawlGuideIndex >= total - 1 ? "看完了，关闭" : "下一步";
        }
    }

    function setFirecrawlGuideStep(index) {
        firecrawlGuideIndex = index;
        renderFirecrawlGuide();
    }

    function openFirecrawlGuideModal() {
        firecrawlGuideIndex = 0;
        renderFirecrawlGuide();
        els.firecrawlGuideModal?.classList.remove("hidden");
    }

    function closeFirecrawlGuideModal() {
        els.firecrawlGuideModal?.classList.add("hidden");
    }

    function setNav(view) {
        currentView = view;
        const tasks = view === "tasks";
        const merchant = view === "merchant";
        const settings = view === "settings";
        els.tasksView.classList.toggle("hidden", !tasks);
        els.merchantView?.classList.toggle("hidden", !merchant);
        els.settingsView.classList.toggle("hidden", !settings);
        els.navTasks.classList.toggle("nav-item-active", tasks);
        els.navMerchant?.classList.toggle("nav-item-active", merchant);
        els.navSettings.classList.toggle("nav-item-active", settings);
        els.mobileNavTasks?.classList.toggle("nav-item-active", tasks);
        els.mobileNavMerchant?.classList.toggle("nav-item-active", merchant);
        els.mobileNavSettings?.classList.toggle("nav-item-active", settings);
        els.viewTitle.textContent = tasks ? "监控任务" : merchant ? "商品入库" : "系统设置";
        if (settings) {
            openSettingsHome();
        }
    }

    function openTaskModal(task = null) {
        renderTaskGroupOptions(Array.from(currentTasks.values()), task ? [task.group_name] : []);
        if (task) {
            els.taskModalTitle.textContent = "编辑监控节点";
            els.taskId.value = task.id;
            els.taskName.value = task.name || "";
            setTaskGroupSelection(task.group_name, [task.group_name]);
            setTaskSubgroupSelection(task.group_name, task.subgroup_name, [task.subgroup_name]);
            els.taskUrl.value = task.monitor_url || "";
            els.taskKeyword.value = task.target_keyword || "";
            els.taskForm.dataset.sourceConfig = JSON.stringify(parseTaskSourceConfig(task.source_config));
            setTaskRuleFields(task.source_config);
            setTaskStrategy(task.fetch_strategy);
            els.taskRestock.value = task.restock_template || defaultTemplates.restock;
            els.taskSoldout.value = task.soldout_template || defaultTemplates.soldout;
            els.taskButton1Text.value = task.button_1_text || "";
            els.taskButton1Url.value = task.button_1_url || "";
            els.taskButton2Text.value = task.button_2_text || "";
            els.taskButton2Url.value = task.button_2_url || "";
            els.taskEnabled.checked = Boolean(task.enabled);
            els.taskSubmitButton.textContent = "更新节点";
            if (els.taskSaveCheckButton) {
                els.taskSaveCheckButton.textContent = "更新并立即检测";
            }
        } else {
            resetTaskForm();
            if (taskBrowserPath.groupName) {
                setTaskGroupSelection(taskBrowserPath.groupName, [taskBrowserPath.groupName]);
                setTaskSubgroupSelection(taskBrowserPath.groupName, taskBrowserPath.subgroupName || defaultTaskSubgroup, [taskBrowserPath.subgroupName || defaultTaskSubgroup]);
            }
            els.taskModalTitle.textContent = "新增任务";
            els.taskSubmitButton.textContent = "保存节点";
            if (els.taskSaveCheckButton) {
                els.taskSaveCheckButton.textContent = "保存并立即检测";
            }
        }
        updateTaskStrategyUi();
        els.taskModal.classList.remove("hidden");
        document.body.style.overflow = "hidden";
        window.setTimeout(() => els.taskName.focus(), 40);
    }

    function closeTaskModal() {
        els.taskModal.classList.add("hidden");
        els.templateHelpModal?.classList.add("hidden");
        document.body.style.overflow = "";
    }

    function openTemplateHelpModal() {
        els.templateHelpModal?.classList.remove("hidden");
        document.body.style.overflow = "hidden";
    }

    function closeTemplateHelpModal() {
        els.templateHelpModal?.classList.add("hidden");
        if (els.taskModal?.classList.contains("hidden")) {
            document.body.style.overflow = "";
        }
    }

    function resetTaskForm() {
        els.taskForm.reset();
        els.taskId.value = "";
        els.taskForm.dataset.sourceConfig = "{}";
        if (els.taskGroup) {
            els.taskGroup.value = defaultTaskGroup;
        }
        if (els.taskGroupCustom) {
            syncInputValue(els.taskGroupCustom, "");
        }
        renderTaskSubgroupOptions(defaultTaskGroup);
        if (els.taskSubgroup) {
            els.taskSubgroup.value = defaultTaskSubgroup;
        }
        if (els.taskSubgroupCustom) {
            syncInputValue(els.taskSubgroupCustom, "");
        }
        els.taskRestock.value = defaultTemplates.restock;
        els.taskSoldout.value = defaultTemplates.soldout;
        if (els.taskTemplateTestKind) {
            els.taskTemplateTestKind.value = "restock";
        }
        if (els.taskTemplateTestChatIds) {
            els.taskTemplateTestChatIds.value = "";
        }
        setTaskRuleFields({});
        setTaskStrategy(preferredTaskFetchStrategy());
        els.taskEnabled.checked = true;
        updateGroupVisibility(els.taskGroup, els.taskGroupCustomWrap, els.taskGroupCustom);
        updateGroupVisibility(els.taskSubgroup, els.taskSubgroupCustomWrap, els.taskSubgroupCustom);
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
        currentSettings = settings || {};
        els.settingsBotTokenMask.textContent = settings.telegram_bot_token_masked
            ? `当前 Token：${settings.telegram_bot_token_masked}`
            : "当前未配置 Bot Token";
        const chatIdsText = settings.telegram_chat_ids_text || settings.telegram_chat_id || "";
        const chatIds = splitTelegramChatIds(chatIdsText);
        syncInputValue(els.settingsChatIds, chatIdsText);
        if (els.settingsChatIdsHint) {
            els.settingsChatIdsHint.textContent = chatIds.length
                ? `已配置 ${chatIds.length} 个群聊。支持多群聊，一行一个 Chat ID。`
                : "支持多群聊，一行一个 Chat ID。";
        }
        if (els.settingsChatIdsCount) {
            els.settingsChatIdsCount.textContent = `${chatIds.length} 群聊`;
        }
        syncInputValue(els.settingsMonitorPort, settings.monitor_debug_port || 9223);
        syncInputValue(els.settingsTestPort, settings.test_debug_port || 9334);
        syncInputValue(els.settingsCatalogPort, settings.catalog_debug_port || 9445);
        syncInputValue(els.settingsPollInterval, settings.poll_interval_seconds || 45);
        syncInputValue(els.settingsTimeout, settings.request_timeout_seconds || 25);
        syncCheckboxValue(els.settingsFirecrawlEnabled, Boolean(settings.firecrawl_enabled));
        syncInputValue(els.settingsFirecrawlApiUrl, settings.firecrawl_api_url || "https://api.firecrawl.dev");
        if (els.settingsFirecrawlApiKeyMask) {
            els.settingsFirecrawlApiKeyMask.textContent = settings.firecrawl_api_key_masked
                ? `当前 Key：${settings.firecrawl_api_key_masked}`
                : "当前未配置 Firecrawl API Key";
        }
        syncInputValue(els.settingsFirecrawlTimeout, settings.firecrawl_timeout_seconds || 60);
        syncInputValue(els.settingsFirecrawlMaxAge, settings.firecrawl_max_age_ms ?? 0);
        syncCheckboxValue(els.settingsFirecrawlStoreInCache, Boolean(settings.firecrawl_store_in_cache));
        syncInputValue(els.settingsFirecrawlProxyMode, settings.firecrawl_proxy_mode || "basic");
        syncCheckboxValue(els.settingsFirecrawlAllowAutoProxy, Boolean(settings.firecrawl_allow_auto_proxy));
        syncCheckboxValue(els.settingsFirecrawlAllowEnhancedProxy, Boolean(settings.firecrawl_allow_enhanced_proxy));
        syncCheckboxValue(els.settingsFirecrawlZeroDataRetention, Boolean(settings.firecrawl_zero_data_retention));
        syncCheckboxValue(els.settingsFirecrawlUseForMonitor, Boolean(settings.firecrawl_use_for_monitor));
        syncCheckboxValue(els.settingsFirecrawlUseForCatalog, settings.firecrawl_use_for_catalog !== false);
        syncInputValue(els.settingsFirecrawlCatalogLimit, settings.firecrawl_catalog_limit || 50);
        renderScraplingRuntimeStatus(settings.scrapling_status || {});
        syncCheckboxValue(els.settingsScraplingEnabled, settings.scrapling_enabled !== false);
        syncInputValue(els.settingsScraplingDefaultMode, settings.scrapling_default_mode || "standard");
        syncCheckboxValue(els.settingsScraplingUseForMonitor, settings.scrapling_use_for_monitor !== false);
        syncCheckboxValue(els.settingsScraplingUseForCatalog, settings.scrapling_use_for_catalog !== false);
        syncCheckboxValue(els.settingsScraplingSessionReuse, settings.scrapling_session_reuse !== false);
        syncCheckboxValue(els.settingsScraplingAdaptiveSelector, settings.scrapling_adaptive_selector !== false);
        syncInputValue(els.settingsScraplingTimeoutStandard, settings.scrapling_timeout_standard || 25);
        syncInputValue(els.settingsScraplingTimeoutDynamic, settings.scrapling_timeout_dynamic || 45);
        syncInputValue(els.settingsScraplingTimeoutStealth, settings.scrapling_timeout_stealth || 75);
        syncInputValue(els.settingsScraplingCooldownStandard, settings.scrapling_domain_cooldown_standard ?? 0);
        syncInputValue(els.settingsScraplingCooldownDynamic, settings.scrapling_domain_cooldown_dynamic || 60);
        syncInputValue(els.settingsScraplingCooldownStealth, settings.scrapling_domain_cooldown_stealth || 300);
        syncInputValue(els.settingsScraplingConcurrencyStandard, settings.scrapling_max_concurrency_standard || 3);
        syncInputValue(els.settingsScraplingConcurrencyDynamic, settings.scrapling_max_concurrency_dynamic || 2);
        syncInputValue(els.settingsScraplingConcurrencyStealth, settings.scrapling_max_concurrency_stealth || 1);
        updateMerchantFirecrawlOptions();
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

    function merchantStateMeta(itemState) {
        if (itemState === "new") return ["border-emerald-500/20 bg-emerald-500/10 text-emerald-200", "新发现"];
        if (itemState === "updated") return ["border-sky-500/20 bg-sky-500/10 text-sky-200", "已更新"];
        if (itemState === "archived") return ["border-slate-700 bg-slate-900/70 text-slate-400", "已归档"];
        return ["border-slate-700 bg-slate-900/70 text-slate-400", "未知"];
    }

    function merchantItemFilterCounts(items) {
        const counts = {
            all: items.length,
            linked: 0,
            unlinked: 0,
            new: 0,
            updated: 0,
            archived: 0
        };
        items.forEach((item) => {
            if (item.task_id) {
                counts.linked += 1;
            } else {
                counts.unlinked += 1;
            }
            if (item.item_state === "new") counts.new += 1;
            if (item.item_state === "updated") counts.updated += 1;
            if (item.item_state === "archived") counts.archived += 1;
        });
        return counts;
    }

    function merchantItemFilterLabel(value, counts) {
        switch (value) {
            case "linked":
                return `已关联任务 (${counts.linked})`;
            case "unlinked":
                return `未关联任务 (${counts.unlinked})`;
            case "new":
                return `仅新发现 (${counts.new})`;
            case "updated":
                return `仅已更新 (${counts.updated})`;
            case "archived":
                return `仅已归档 (${counts.archived})`;
            default:
                return `全部商品 (${counts.all})`;
        }
    }

    function renderMerchantItemFilterOptions(items) {
        if (!els.merchantItemFilter) {
            return "all";
        }
        const counts = merchantItemFilterCounts(items);
        const current = els.merchantItemFilter.value || "all";
        const options = ["all", "linked", "unlinked", "new", "updated", "archived"];
        els.merchantItemFilter.innerHTML = options
            .map((value) => `<option value="${value}">${escapeHtml(merchantItemFilterLabel(value, counts))}</option>`)
            .join("");
        els.merchantItemFilter.value = options.includes(current) ? current : "all";
        return els.merchantItemFilter.value;
    }

    function filterMerchantItems(items, filterValue) {
        switch (filterValue) {
            case "linked":
                return items.filter((item) => Boolean(item.task_id));
            case "unlinked":
                return items.filter((item) => !item.task_id);
            case "new":
            case "updated":
            case "archived":
                return items.filter((item) => item.item_state === filterValue);
            default:
                return items;
        }
    }

    function renderMerchant(merchant) {
        currentMerchant = merchant || { sources: [], items: [], metrics: {} };
        const sources = Array.isArray(currentMerchant.sources) ? currentMerchant.sources : [];
        const items = Array.isArray(currentMerchant.items) ? currentMerchant.items : [];
        const metrics = currentMerchant.metrics || {};
        const filterValue = renderMerchantItemFilterOptions(items);
        const filteredItems = filterMerchantItems(items, filterValue);
        const nextMerchantSignature = [
            taskIdsSignature,
            filterValue,
            merchantPreviewSignature(),
            sources.map((source) => [
                source.id ?? "",
                source.active ? "1" : "0",
                source.source_name || "",
                source.source_url || "",
                source.group_name || "",
                source.item_count ?? 0,
                source.linked_count ?? 0,
                source.last_sync_at || "",
                source.last_error || ""
            ].join(":")).join("|"),
            filteredItems.map((item) => [
                item.id ?? "",
                item.source_id ?? "",
                item.item_state || "",
                item.task_id ?? "",
                item.title || "",
                item.keyword || "",
                item.monitor_url || "",
                item.item_url || "",
                item.stock_hint || "",
                item.backend_used || "",
                item.discovery_source || "",
                item.extractor || "",
                item.fetch_strategy || "",
                item.confidence ?? "",
                item.include_reason || "",
                item.reject_reason || ""
            ].join(":")).join("|"),
            [
                metrics.total_sources ?? 0,
                metrics.total_items ?? 0,
                metrics.linked_tasks ?? 0,
                metrics.new_items ?? 0,
                metrics.updated_items ?? 0,
                metrics.archived_items ?? 0
            ].join(":")
        ].join("||");
        if (merchantSignature !== null && nextMerchantSignature === merchantSignature) {
            return;
        }
        merchantSignature = nextMerchantSignature;

        if (els.merchantMetricSources) els.merchantMetricSources.textContent = metrics.total_sources ?? 0;
        if (els.merchantMetricItems) els.merchantMetricItems.textContent = metrics.total_items ?? 0;
        if (els.merchantMetricLinked) els.merchantMetricLinked.textContent = metrics.linked_tasks ?? 0;
        updateMerchantStepCounts(metrics);
        renderMerchantReviewSummary();

        if (els.merchantSourceList) {
            if (hasMerchantPreviewSources()) {
                els.merchantSourceList.innerHTML = renderMerchantPreviewSources();
            } else if (!sources.length) {
                els.merchantSourceList.innerHTML = '<p class="text-sm text-slate-500">暂无导入来源，先填一个商家商品页试试。</p>';
            } else {
                els.merchantSourceList.innerHTML = sources.map((source) => {
                    const [sourceStatusClass, sourceStatusText] = merchantSourceStatusMeta(source);
                    const activeClass = source.active ? "text-emerald-300" : "text-slate-500";
                    const activeText = source.active ? "ACTIVE" : "PAUSED";
                    const lastSync = source.last_sync_at ? formatTime(source.last_sync_at) : "尚未同步";
                    const errorAdvice = source.last_error ? catalogErrorAdvice(source.last_error) : "";
                    const lastError = source.last_error ? `
                        <div class="mt-3 rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2">
                            <p class="truncate-two text-sm text-rose-200">${escapeHtml(source.last_error)}</p>
                            <p class="mt-1 text-xs text-rose-100/80">${escapeHtml(errorAdvice)}</p>
                        </div>
                    ` : "";
                    return `
                        <article class="merchant-card rounded-xl border border-slate-800/80 bg-slate-950/50 p-4">
                            <div class="flex flex-wrap items-start justify-between gap-3">
                                <div class="min-w-0">
                                    <h4 class="truncate text-sm font-bold text-white">${escapeHtml(source.source_name || source.source_url)}</h4>
                                    <p class="mt-1 truncate font-mono text-[11px] text-slate-500">${escapeHtml(source.source_url)}</p>
                                </div>
                                <div class="flex flex-wrap justify-end gap-2">
                                    <span class="rounded-full border px-2.5 py-1 font-mono text-[11px] ${sourceStatusClass}">${sourceStatusText}</span>
                                    <span class="font-mono text-[11px] ${activeClass}">${activeText}</span>
                                </div>
                            </div>
                            <div class="mt-3 flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
                                <span class="rounded-full border border-indigo-900/60 bg-indigo-500/10 px-2.5 py-1">分组 ${escapeHtml(source.group_name || defaultTaskGroup)}</span>
                                <span class="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">商品 ${escapeHtml(source.item_count ?? 0)}</span>
                                <span class="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">关联 ${escapeHtml(source.linked_count ?? 0)}</span>
                                <span class="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">最后同步 ${escapeHtml(lastSync)}</span>
                            </div>
                            ${lastError}
                            <div class="mt-3 flex justify-end">
                                <div class="flex flex-wrap gap-2">
                                    <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-merchant-action="sync-source" data-source-id="${source.id}">
                                        同步
                                    </button>
                                    <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-merchant-action="toggle-source" data-source-id="${source.id}" data-active="${source.active ? 'true' : 'false'}">
                                        ${source.active ? "停用" : "启用"}
                                    </button>
                                </div>
                            </div>
                        </article>
                    `;
                }).join("");
            }
        }

        if (els.merchantItemList) {
            if (hasMerchantPreviewItems()) {
                els.merchantItemList.innerHTML = renderMerchantPreviewItems();
            } else if (!filteredItems.length) {
                els.merchantItemList.innerHTML = '<p class="text-sm text-slate-500">当前筛选条件下没有商品记录。</p>';
            } else {
                els.merchantItemList.innerHTML = filteredItems.map((item) => {
                    const [badgeClass, badgeText] = merchantStateMeta(item.item_state);
                    const [stockClass, stockText] = merchantStockStatusMeta(item);
                    const linkedTask = item.task_id && currentTasks.get(String(item.task_id));
                    const sourceLabel = item.source_name || item.source_url || "未知来源";
                    const actionLabel = linkedTask ? "编辑任务" : "生成任务";
                    const actionName = linkedTask ? "open-task" : "promote-item";
                    const backendLabel = item.backend_used ? fetchStrategyLabel(item.backend_used) : "-";
                    const discoveryLabel = catalogDiscoveryLabel(item.discovery_source);
                    const extractor = extractorLabel(item.extractor);
                    const fetchStrategy = fetchStrategyLabel(item.fetch_strategy);
                    const confidence = Number(item.confidence || 0);
                    const confidenceText = confidence > 0 ? `${confidence}%` : "-";
                    const reasonText = item.reject_reason || item.include_reason || "暂无识别依据";
                    const signals = Array.isArray(item.signals) ? item.signals.slice(0, 4) : [];
                    const signalChips = signals.length
                        ? signals.map((signal) => `
                            <span title="${escapeHtml(signal.text || "")}">
                                ${escapeHtml(signal.type || "signal")} ${escapeHtml(signal.weight ?? "")}
                            </span>
                        `).join("")
                        : '<span>暂无信号</span>';
                    return `
                        <article class="merchant-card rounded-xl border border-slate-800/80 bg-slate-950/50 p-4">
                            <div class="flex flex-wrap items-start justify-between gap-3">
                                <div class="min-w-0">
                                    <h4 class="truncate text-sm font-bold text-white">${escapeHtml(item.title)}</h4>
                                    <p class="mt-1 truncate font-mono text-[11px] text-slate-500">${escapeHtml(sourceLabel)}</p>
                                </div>
                                <div class="flex flex-wrap justify-end gap-2">
                                    <span class="rounded-full border px-2.5 py-1 font-mono text-[11px] ${stockClass}">${stockText}</span>
                                    <span class="rounded-full border px-2.5 py-1 font-mono text-[11px] ${badgeClass}">${badgeText}</span>
                                </div>
                            </div>
                            <div class="mt-3 grid gap-2 text-[11px] font-mono text-slate-400 sm:grid-cols-2">
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">关键词：${escapeHtml(item.keyword)}</span>
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">价格：${escapeHtml(item.price_hint || "-")}</span>
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">库存：${escapeHtml(item.stock_hint || "-")}</span>
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">补货：${escapeHtml(item.restock_hint || "-")}</span>
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">后端：${escapeHtml(backendLabel)}</span>
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">发现：${escapeHtml(discoveryLabel)}</span>
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">解析器：${escapeHtml(extractor)}</span>
                                <span class="truncate rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1">任务采集：${escapeHtml(fetchStrategy)}</span>
                            </div>
                            <div class="merchant-signal-box">
                                <div>
                                    <span>置信度</span>
                                    <strong>${escapeHtml(confidenceText)}</strong>
                                </div>
                                <p>${escapeHtml(reasonText)}</p>
                                <div class="merchant-signal-chips">${signalChips}</div>
                            </div>
                            <div class="mt-3 flex flex-wrap items-center justify-between gap-3">
                                <p class="truncate font-mono text-[11px] text-slate-500">${escapeHtml(item.item_url || item.monitor_url || "")}</p>
                                <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-merchant-action="${actionName}" data-task-id="${item.task_id || ""}" data-item-id="${item.id}">
                                    ${actionLabel}
                                </button>
                            </div>
                        </article>
                    `;
                }).join("");
            }
        }
        if (els.merchantBulkPromoteButton) {
            const promotableItems = filteredItems.filter((item) => !item.task_id && item.item_state !== "archived");
            els.merchantBulkPromoteButton.disabled = hasMerchantPreviewItems() || promotableItems.length === 0;
            els.merchantBulkPromoteButton.dataset.itemIds = promotableItems.map((item) => item.id).join(",");
            if (els.merchantBulkPromoteCount) {
                els.merchantBulkPromoteCount.textContent = `${promotableItems.length} 可创建`;
            }
        }
        updateMerchantPreviewActions();
    }

    function renderLogs(logs) {
        const nextLogsSignature = Array.isArray(logs)
            ? logs.map((log) => [
                log.level || "",
                log.scope || "",
                log.message || "",
                log.created_at || ""
            ].join(":")).join("|")
            : "";
        if (logsSignature !== null && nextLogsSignature === logsSignature) {
            return;
        }
        logsSignature = nextLogsSignature;
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
        if (!task.enabled) return ["status-disabled", "已停用", "任务已停用"];
        if (task.last_state === "in_stock") return ["status-in-stock", "有货", "库存识别：有货"];
        if (task.last_state === "sold_out") return ["status-sold-out", "售罄", "库存识别：售罄"];
        return ["status-unknown", "未知", "等待首次检测"];
    }

    function taskErrorCount(tasks) {
        return tasks.filter((task) => task.last_error).length;
    }

    function collectTaskBrowserGroups(tasks) {
        const groups = new Map();
        groups.set(defaultTaskGroup, { name: defaultTaskGroup, tasks: [] });
        tasks.forEach((task) => {
            const groupName = normalizeTaskGroup(task.group_name);
            if (!groups.has(groupName)) {
                groups.set(groupName, { name: groupName, tasks: [] });
            }
            groups.get(groupName).tasks.push(task);
        });
        currentTaskGroupNodes.forEach((node) => {
            const groupName = normalizeTaskGroup(node.group_name);
            if (!groups.has(groupName)) {
                groups.set(groupName, { name: groupName, tasks: [] });
            }
        });
        return Array.from(groups.values())
            .filter((group) => group.name !== defaultTaskGroup || group.tasks.length)
            .map((group) => ({
                ...group,
                sort_order: groupSortOrder(group.name),
                tasks: group.tasks.slice().sort(compareTasksByOrder)
            }))
            .sort(compareCardsByOrderName);
    }

    function collectChildSubgroups(tasks, groupName, parentPath) {
        const children = new Map();
        const normalizedGroup = normalizeTaskGroup(groupName);
        const addChild = (path, task = null) => {
            const childPath = directChildSubgroupPath(path, parentPath);
            if (!childPath) return;
            if (!children.has(childPath)) {
                const parts = splitTaskSubgroupPath(childPath);
                children.set(childPath, {
                    name: parts[parts.length - 1] || childPath,
                    path: childPath,
                    sort_order: subgroupSortOrder(normalizedGroup, childPath),
                    tasks: []
                });
            }
            if (task) {
                children.get(childPath).tasks.push(task);
            }
        };
        tasks.forEach((task) => {
            if (normalizeTaskGroup(task.group_name) !== normalizedGroup) return;
            addChild(taskSubgroupPath(task), task);
        });
        currentTaskGroupNodes.forEach((node) => {
            if (normalizeTaskGroup(node.group_name) !== normalizedGroup) return;
            addChild(normalizeTaskSubgroup(node.subgroup_name), null);
        });
        return Array.from(children.values())
            .map((child) => ({
                ...child,
                tasks: child.tasks.slice().sort(compareTasksByOrder)
            }))
            .sort(compareCardsByOrderName);
    }

    function tasksAtBrowserPath(tasks, groupName, subgroupPath) {
        const normalizedGroup = normalizeTaskGroup(groupName);
        const normalizedPath = joinTaskSubgroupPath(splitTaskSubgroupPath(subgroupPath));
        return tasks.filter((task) => (
            normalizeTaskGroup(task.group_name) === normalizedGroup
            && isSameSubgroupPath(taskSubgroupPath(task), normalizedPath)
        )).sort(compareTasksByOrder);
    }

    function taskBrowserView() {
        return taskBrowserPath.view === "products" ? "products" : "children";
    }

    function setTaskBrowserPath(groupName = "", subgroupName = "", view = "children") {
        const hasGroup = String(groupName || "").trim() !== "";
        const normalizedSubgroup = String(subgroupName || "").trim()
            ? normalizeTaskSubgroup(subgroupName)
            : "";
        taskBrowserPath = {
            groupName: hasGroup ? normalizeTaskGroup(groupName) : "",
            subgroupName: normalizedSubgroup === defaultTaskSubgroup ? "" : normalizedSubgroup,
            view: hasGroup && view === "products" ? "products" : "children"
        };
    }

    function taskBrowserPathExists(tasks) {
        if (!taskBrowserPath.groupName) {
            return true;
        }
        const groupName = normalizeTaskGroup(taskBrowserPath.groupName);
        const groups = collectTaskBrowserGroups(tasks).map((group) => group.name);
        if (!groups.includes(groupName)) {
            return false;
        }
        const subgroupPath = joinTaskSubgroupPath(splitTaskSubgroupPath(taskBrowserPath.subgroupName));
        if (subgroupPath === defaultTaskSubgroup) {
            return true;
        }
        const hasTaskPath = tasks.some((task) => (
            normalizeTaskGroup(task.group_name) === groupName
            && (isSameSubgroupPath(taskSubgroupPath(task), subgroupPath) || isSubgroupDescendant(taskSubgroupPath(task), subgroupPath))
        ));
        const hasNodePath = currentTaskGroupNodes.some((node) => (
            normalizeTaskGroup(node.group_name) === groupName
            && (isSameSubgroupPath(node.subgroup_name, subgroupPath) || isSubgroupDescendant(node.subgroup_name, subgroupPath))
        ));
        return hasTaskPath || hasNodePath;
    }

    function taskBrowserCrumbs() {
        const crumbs = [{ label: "全部分组", groupName: "", subgroupName: "" }];
        if (!taskBrowserPath.groupName) {
            return crumbs;
        }
        const groupName = normalizeTaskGroup(taskBrowserPath.groupName);
        crumbs.push({ label: groupName, groupName, subgroupName: "" });
        const parts = splitTaskSubgroupPath(taskBrowserPath.subgroupName);
        parts.forEach((part, index) => {
            crumbs.push({
                label: part,
                groupName,
                subgroupName: joinTaskSubgroupPath(parts.slice(0, index + 1))
            });
        });
        return crumbs;
    }

    function renderTaskBrowserBreadcrumbs() {
        return taskBrowserCrumbs().map((crumb, index, list) => {
            const current = index === list.length - 1;
            return `
                <button type="button" class="task-crumb ${current ? "is-current" : ""}" data-task-crumb-group="${escapeHtml(crumb.groupName)}" data-task-crumb-subgroup="${escapeHtml(crumb.subgroupName)}" ${current ? "disabled" : ""}>
                    ${escapeHtml(crumb.label)}
                </button>
            `;
        }).join('<span class="text-slate-700">/</span>');
    }
    function renderTaskCards(tasks, animateCards) {
        return tasks.map((task) => {
            const [statusClass, statusText, logHint] = statusMeta(task);
            const stockText = task.last_stock === null || task.last_stock === undefined ? "-" : String(task.last_stock);
            const logMessage = task.last_error
                ? escapeHtml(formatTaskLogLine(task, logHint))
                : `> ${escapeHtml(logHint)} ${escapeHtml(formatTime(task.last_checked_at))}`;
            const lastChecked = task.last_checked_at ? escapeHtml(formatTime(task.last_checked_at)) : "尚未检查";
            const actionLabel = task.enabled ? "停用任务" : "启用任务";
            const protectedNotice = protectedSourceNoticeText(task);
            const webhookMeta = webhookMetaText(task);
            const normalizedStrategy = normalizeFetchStrategy(task.fetch_strategy);
            const attemptMeta = fetchAttemptMeta(task);
            const rowClass = animateCards ? "task-row reveal" : "task-row";
            return `
                <article class="${rowClass}" data-task-id="${task.id}" data-drag-kind="task" data-drag-id="${task.id}" draggable="true">
                    <span class="task-drag-handle" aria-hidden="true" title="拖动排序">
                        <svg viewBox="0 0 20 20" fill="currentColor">
                            <path d="M7 4a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm9-12a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z"/>
                        </svg>
                    </span>
                    <div class="task-row-product">
                        <label class="task-select-pill" title="选择任务">
                            <input type="checkbox" value="${task.id}" data-task-select aria-label="选择任务 ${escapeHtml(task.name)}">
                            <span></span>
                        </label>
                        <span class="status-badge ${statusClass}" data-task-status>${statusText}</span>
                        <div class="min-w-0">
                            <h3 class="task-row-title" title="${escapeHtml(task.name)}" data-task-name>${escapeHtml(task.name)}</h3>
                            <p class="task-row-url font-mono" title="${escapeHtml(task.monitor_url)}" data-task-url>${escapeHtml(task.monitor_url)}</p>
                            ${task.source_source_name ? `<p class="task-row-source font-mono" data-task-source>来源：${escapeHtml(task.source_source_name)}${task.source_item_url ? ` · ${escapeHtml(task.source_item_url)}` : ""}</p>` : '<p class="task-row-source hidden font-mono" data-task-source></p>'}
                        </div>
                    </div>

                    <div class="task-row-signal">
                        <div class="keyword-chip" data-task-keyword>
                            <svg class="mr-1.5 h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                            </svg>
                            <span data-task-keyword-text>关键词: ${escapeHtml(task.target_keyword)}</span>
                            <span class="ml-2 rounded border border-slate-700/70 bg-slate-950/70 px-2 py-0.5 text-[10px] text-slate-400" data-task-fetch-strategy>${escapeHtml(fetchStrategyLabel(task.fetch_strategy))}</span>
                        </div>
                        <div class="task-row-stock font-mono">
                            <span>库存</span>
                            <strong class="${task.last_stock > 0 ? "text-emerald-400" : "text-slate-300"} font-bold" data-task-stock>${escapeHtml(stockText)}</strong>
                        </div>
                    </div>

                    <div class="task-row-log terminal-box ${task.last_error ? "" : "opacity-95"}" data-task-terminal>
                        <p class="task-log-text truncate-two font-mono ${task.last_error ? errorKindTone(task.last_error_kind) : "animate-pulse-soft text-emerald-400"}" data-task-log>${logMessage}</p>
                        <details class="task-row-details" data-task-log-details>
                            <summary>详情</summary>
                            <p class="rounded border border-amber-500/20 bg-amber-500/10 px-2.5 py-1.5 text-xs leading-5 text-amber-200 ${protectedNotice ? "" : "hidden"}" data-task-protected-notice>${escapeHtml(protectedNotice)}</p>
                            <p class="mt-2 rounded border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-1.5 font-mono text-[11px] leading-5 text-cyan-200 ${webhookMeta ? "" : "hidden"}" data-task-webhook-meta>${escapeHtml(webhookMeta)}</p>
                            <div class="task-row-checked font-mono" data-task-meta>
                                message_id: ${task.message_id ?? "-"} · checked: ${lastChecked}${escapeHtml(attemptMeta)}
                            </div>
                        </details>
                    </div>

                    <div class="task-actions flex flex-col gap-2">
                        <div class="flex flex-wrap items-center gap-2">
                            <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px] font-bold text-indigo-300 ${["manual", "webhook"].includes(normalizedStrategy) ? "hidden" : ""}" data-action="check" data-task-check-action>
                                <svg class="mr-1.5 h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                                </svg>
                                检测
                            </button>
                            <div class="flex gap-1 ${normalizedStrategy === "manual" ? "" : "hidden"}" data-task-manual-actions>
                                <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px] text-emerald-300" data-action="manual-in-stock">有货</button>
                                <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px] text-rose-300" data-action="manual-sold-out">售罄</button>
                            </div>
                            <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px] text-cyan-300 ${normalizedStrategy === "webhook" ? "" : "hidden"}" data-action="webhook-token" data-task-webhook-action>重置 Token</button>
                        </div>
                        <div class="flex space-x-1">
                            <button type="button" class="icon-button !h-9 !w-9" title="${escapeHtml(actionLabel)}" aria-label="${escapeHtml(actionLabel)}" data-action="toggle" data-task-toggle>
                                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                                </svg>
                            </button>
                            <button type="button" class="icon-button !h-9 !w-9" title="编辑配置" data-action="edit">
                                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                                </svg>
                            </button>
                            <button type="button" class="icon-button !h-9 !w-9" title="移动到其他分组" data-action="move" data-task-move-action>
                                <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4M16 17H4m0 0l4 4m-4-4l4-4"/>
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
    }

    function renderAddTaskCard(animateCards) {
        const addRowClass = animateCards ? "add-row reveal" : "add-row";
        return `
            <button type="button" id="tasks-add-row" class="${addRowClass}">
                <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-800/80">
                    <svg class="h-5 w-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                    </svg>
                </div>
                <div class="min-w-0 text-left">
                    <p class="font-bold text-slate-200">新增任务</p>
                    <p class="text-[13px] text-slate-500">填写商品链接、关键词与采集方式。</p>
                </div>
            </button>
        `;
    }

    function renderTaskGroupCards(tasks, animateCards) {
        const groupCards = collectTaskBrowserGroups(tasks).map((group) => {
            const errorCount = taskErrorCount(group.tasks);
            const stockCount = group.tasks.filter((task) => task.last_state === "in_stock").length;
            const canManageGroup = group.name !== defaultTaskGroup;
            const cardClass = animateCards ? "task-browser-card reveal" : "task-browser-card";
            return `
                <article class="${cardClass}" data-task-group-section data-task-group-name="${escapeHtml(group.name)}" data-drag-kind="group" data-drag-id="${escapeHtml(group.name)}" draggable="true">
                    <span class="task-drag-handle" aria-hidden="true" title="拖动排序">
                        <svg viewBox="0 0 20 20" fill="currentColor">
                            <path d="M7 4a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm9-12a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z"/>
                        </svg>
                    </span>
                    <button type="button" class="task-browser-card-main" data-group-open="${escapeHtml(group.name)}">
                        <span class="task-browser-kicker">IDC GROUP</span>
                        <strong>${escapeHtml(group.name)}</strong>
                        <span class="task-browser-meta">
                            <span data-task-group-count>${group.tasks.length} 个任务</span>
                            <span>${stockCount} 有货</span>
                            <span class="${errorCount ? "" : "hidden"}" data-task-group-error>${errorCount} 错误</span>
                        </span>
                    </button>
                    <div class="task-browser-card-actions">
                        <button type="button" class="icon-button !h-9 !w-9 ${canManageGroup ? "" : "opacity-40"}" title="${canManageGroup ? "重命名分组" : "默认分组不可重命名"}" data-group-action="rename" data-group-name="${escapeHtml(group.name)}" ${canManageGroup ? "" : "disabled"}>
                            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                            </svg>
                        </button>
                        <button type="button" class="icon-button !h-9 !w-9 text-rose-300 ${canManageGroup ? "" : "opacity-40"}" title="${canManageGroup ? "删除分组" : "默认分组不可整体删除"}" data-group-action="delete" data-group-name="${escapeHtml(group.name)}" ${canManageGroup ? "" : "disabled"}>
                            <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                            </svg>
                        </button>
                    </div>
                </article>
            `;
        }).join("");
        const empty = `
            <div class="task-empty-state">
                <p class="font-bold text-slate-200">还没有监控分组</p>
                <p class="text-sm text-slate-500">新增任务后会自动形成主分组。</p>
            </div>
        `;
        return `<div class="task-browser-grid" data-drag-scope="group">${groupCards || empty}</div>`;
    }

    function renderCurrentLayerProductsCard(directTasks, animateCards) {
        if (!directTasks.length) {
            return "";
        }
        const errorCount = taskErrorCount(directTasks);
        const stockCount = directTasks.filter((task) => task.last_state === "in_stock").length;
        const cardClass = animateCards ? "task-browser-card task-browser-card-products reveal" : "task-browser-card task-browser-card-products";
        return `
            <article class="${cardClass}" data-task-products-section>
                <button type="button" class="task-browser-card-main" data-task-products-open>
                    <span class="task-browser-kicker">PRODUCTS</span>
                    <strong>当前层商品</strong>
                    <span class="task-browser-meta">
                        <span>${directTasks.length} 个任务</span>
                        <span>${stockCount} 有货</span>
                        <span class="${errorCount ? "" : "hidden"}">${errorCount} 错误</span>
                    </span>
                    <span class="task-browser-card-note">直属于当前层级，单独进入后可多选删除和拖拽排序。</span>
                </button>
            </article>
        `;
    }

    function renderTaskSubgroupCards(children, animateCards, directTasks = []) {
        if (!children.length) {
            return "";
        }
        return `
            <section class="task-browser-section">
                <div class="task-browser-section-head">
                    <div>
                        <p class="task-browser-kicker">SUBGROUPS</p>
                        <h3>子分组</h3>
                    </div>
                    <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-subgroup-action="bulk-delete" disabled>删除选中子分组</button>
                </div>
                <div class="task-browser-grid" data-drag-scope="subgroup">
                    ${renderCurrentLayerProductsCard(directTasks, animateCards)}
                    ${children.map((child) => {
                        const errorCount = taskErrorCount(child.tasks);
                        const cardClass = animateCards ? "task-browser-card reveal" : "task-browser-card";
                        return `
                            <article class="${cardClass}" data-task-subgroup-section data-task-group-name="${escapeHtml(taskBrowserPath.groupName)}" data-task-subgroup-name="${escapeHtml(child.path)}" data-drag-kind="subgroup" data-drag-id="${escapeHtml(child.path)}" draggable="true">
                                <span class="task-drag-handle" aria-hidden="true" title="拖动排序">
                                    <svg viewBox="0 0 20 20" fill="currentColor">
                                        <path d="M7 4a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm9-12a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zm0 6a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z"/>
                                    </svg>
                                </span>
                                <label class="task-select-pill task-subgroup-select" title="选择子分组">
                                    <input type="checkbox" value="${escapeHtml(child.path)}" data-subgroup-select aria-label="选择子分组 ${escapeHtml(child.name)}">
                                    <span></span>
                                </label>
                                <button type="button" class="task-browser-card-main" data-subgroup-open="${escapeHtml(child.path)}">
                                    <span class="task-browser-kicker">SUBGROUP</span>
                                    <strong>${escapeHtml(child.name)}</strong>
                                    <span class="task-browser-meta">
                                        <span data-task-subgroup-count>${child.tasks.length} 个任务</span>
                                        <span class="${errorCount ? "" : "hidden"}" data-task-subgroup-error>${errorCount} 错误</span>
                                    </span>
                                </button>
                                <div class="task-browser-card-actions">
                                    <button type="button" class="icon-button !h-9 !w-9" title="重命名子分组" data-subgroup-action="rename" data-subgroup-name="${escapeHtml(child.path)}">
                                        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                                        </svg>
                                    </button>
                                    <button type="button" class="icon-button !h-9 !w-9 text-rose-300" title="删除子分组" data-subgroup-action="delete" data-subgroup-name="${escapeHtml(child.path)}">
                                        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                        </svg>
                                    </button>
                                </div>
                            </article>
                        `;
                    }).join("")}
                </div>
            </section>
        `;
    }

    function renderTaskProductList(directTasks, animateCards, hasChildren) {
        const title = taskBrowserPath.subgroupName ? "当前子分组商品" : "默认层级商品";
        const empty = `
            <div class="task-empty-state">
                <p class="font-bold text-slate-200">当前层级还没有商品</p>
                <p class="text-sm text-slate-500">可以新增任务并归入这里，或返回继续创建子分组。</p>
            </div>
        `;
        return `
            <section class="task-browser-section task-products-panel">
                <div class="task-browser-section-head">
                    <div>
                        <p class="task-browser-kicker">PRODUCTS</p>
                        <h3>${escapeHtml(title)}</h3>
                    </div>
                    <div class="task-browser-head-actions">
                        ${hasChildren ? '<button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-task-products-back>返回子分组</button>' : ""}
                        <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-group-action="bulk-move" disabled>移动选中商品</button>
                        <button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-group-action="bulk-delete" disabled>删除选中商品</button>
                    </div>
                </div>
                ${directTasks.length ? `<div class="task-list-stack mt-3" data-drag-scope="task">${renderTaskCards(directTasks, animateCards)}</div>` : empty}
            </section>
        `;
    }

    function renderTaskBrowserToolbar() {
        const inGroup = Boolean(taskBrowserPath.groupName);
        const inProducts = taskBrowserView() === "products";
        return `
            <div class="task-browser-toolbar">
                <div class="task-breadcrumbs">${renderTaskBrowserBreadcrumbs()}</div>
                <div class="flex flex-wrap justify-end gap-2">
                    ${inGroup ? `<button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-task-browser-back>${inProducts ? "返回子分组" : "返回上级"}</button>` : ""}
                    ${inGroup && !inProducts ? '<button type="button" class="ghost-button !min-h-9 !rounded-lg !px-3 !py-2 text-[12px]" data-subgroup-action="create">创建子分组</button>' : ""}
                </div>
            </div>
        `;
    }

    function renderTasks(tasks, initial = false, force = false) {
        currentTasks = new Map(tasks.map((task) => [String(task.id), task]));
        const groupSignature = currentTaskGroups
            .map((group) => `${normalizeTaskGroup(group.group_name)}:${Number(group.sort_order || 0)}`)
            .join("|");
        const nodeSignature = currentTaskGroupNodes
            .map((node) => `${normalizeTaskGroup(node.group_name)}:${normalizeTaskSubgroup(node.subgroup_name)}:${Number(node.sort_order || 0)}`)
            .join("|");
        const nextTaskIdsSignature = tasks
            .map((task) => [
                String(task.id),
                normalizeTaskGroup(task.group_name),
                normalizeTaskSubgroup(task.subgroup_name),
                Number(task.sort_order || 0),
                task.enabled ? "1" : "0",
                task.name || "",
                task.monitor_url || "",
                task.target_keyword || "",
                task.fetch_strategy || "",
                task.source_config || "",
                task.restock_template || "",
                task.soldout_template || "",
                task.button_1_text || "",
                task.button_1_url || "",
                task.button_2_text || "",
                task.button_2_url || "",
                task.source_source_name || "",
                task.source_item_url || "",
                task.source_source_url || "",
                task.webhook_endpoint || "",
                task.ingest_token_hint || ""
            ].join(":"))
            .join("|") + `::groups:${groupSignature}::nodes:${nodeSignature}::path:${taskBrowserPath.groupName}:${taskBrowserPath.subgroupName}::view:${taskBrowserView()}`;
        const nextTaskStateSignature = tasks
            .map((task) => [
                String(task.id),
                task.last_state || "",
                task.last_stock ?? "",
                task.last_error || "",
                task.last_error_kind || "",
                task.message_id ?? "",
                task.last_checked_at || "",
                task.blocked_count ?? "",
                task.last_blocked_at || "",
                task.cooldown_until || ""
            ].join(":"))
            .join("|");
        const animateCards = initial || !tasksRendered || taskIdsSignature !== nextTaskIdsSignature;
        const stateChanged = taskStateSignature !== nextTaskStateSignature;
        tasksRendered = true;
        taskIdsSignature = nextTaskIdsSignature;
        taskStateSignature = nextTaskStateSignature;
        if (!force && !animateCards) {
            if (stateChanged) {
                tasks.forEach(updateTaskCard);
                updateTaskGroupSummaries(tasks);
            }
            return;
        }

        if (!taskBrowserPathExists(tasks)) {
            setTaskBrowserPath();
        }

        const toolbar = renderTaskBrowserToolbar();
        const addRow = `<div class="task-add-stack">${renderAddTaskCard(animateCards)}</div>`;
        if (!taskBrowserPath.groupName) {
            els.tasksGrid.innerHTML = `
                <section class="task-browser-shell">
                    ${toolbar}
                    ${renderTaskGroupCards(tasks, animateCards)}
                </section>
                ${addRow}
            `;
            return;
        }

        const children = collectChildSubgroups(tasks, taskBrowserPath.groupName, taskBrowserPath.subgroupName);
        const directTasks = tasksAtBrowserPath(tasks, taskBrowserPath.groupName, taskBrowserPath.subgroupName);
        const showProductList = taskBrowserView() === "products" || !children.length;
        const productList = showProductList ? renderTaskProductList(directTasks, animateCards, children.length > 0) : "";
        const empty = !children.length && !directTasks.length ? `
            <div class="task-empty-state">
                <p class="font-bold text-slate-200">当前层级还没有子分组或商品</p>
                <p class="text-sm text-slate-500">可以创建子分组，或新增任务并归入当前层级。</p>
            </div>
        ` : "";
        els.tasksGrid.innerHTML = `
            <section class="task-browser-shell">
                ${toolbar}
                ${showProductList ? productList : renderTaskSubgroupCards(children, animateCards, directTasks)}
                ${showProductList ? "" : empty}
            </section>
            ${addRow}
        `;
    }

    function renderSnapshot(data, initial = false) {
        renderMetrics(data.metrics || {});
        renderEngine(data.engine || {});
        renderSettings(data.settings || {});
        renderSystem(data.system || {});
        renderAdmin(data.admin || {});
        renderLogs(data.logs || []);
        currentTaskGroups = Array.isArray(data.task_groups) ? data.task_groups : [];
        currentTaskGroupNodes = Array.isArray(data.task_group_nodes) ? data.task_group_nodes : [];
        renderTasks(data.tasks || [], initial);
        renderMerchant(data.merchant || {});
        const merchantSources = Array.isArray(data.merchant?.sources) ? data.merchant.sources : [];
        const extraGroupNames = merchantSources.map((source) => source.group_name || defaultTaskGroup);
        renderTaskGroupOptions(data.tasks || [], extraGroupNames);
        renderTaskSubgroupOptions(readTaskGroupValue());
        renderMerchantGroupOptions(data.tasks || [], extraGroupNames);
    }

    async function loadSnapshot(initial = false) {
        try {
            const data = await apiFetch("/api/snapshot");
            renderSnapshot(data, initial);
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
        const groupName = readTaskGroupValue();
        if (!groupName) {
            throw new Error("请输入新的分组名称。");
        }
        const subgroupName = readTaskSubgroupValue();
        if (!subgroupName) {
            throw new Error("请输入新的子分组名称。");
        }
        return {
            name: els.taskName.value.trim(),
            group_name: groupName,
            subgroup_name: subgroupName,
            monitor_url: els.taskUrl.value.trim(),
            target_keyword: els.taskKeyword.value.trim(),
            fetch_strategy: normalizeFetchStrategy(els.taskFetchStrategy.value),
            source_config: collectTaskSourceConfig(),
            restock_template: els.taskRestock.value.trim(),
            soldout_template: els.taskSoldout.value.trim(),
            button_1_text: els.taskButton1Text.value.trim(),
            button_1_url: els.taskButton1Url.value.trim(),
            button_2_text: els.taskButton2Text.value.trim(),
            button_2_url: els.taskButton2Url.value.trim(),
            enabled: els.taskEnabled.checked
        };
    }

    function collectTemplateTestPayload() {
        return {
            name: els.taskName.value.trim() || "NOAFF 模板测试商品",
            monitor_url: els.taskUrl.value.trim() || "https://example.com/product",
            target_keyword: els.taskKeyword.value.trim() || "NOAFF",
            template_kind: els.taskTemplateTestKind?.value || "restock",
            test_chat_ids: els.taskTemplateTestChatIds?.value.trim() || "",
            restock_template: els.taskRestock.value.trim(),
            soldout_template: els.taskSoldout.value.trim(),
            button_1_text: els.taskButton1Text.value.trim(),
            button_1_url: els.taskButton1Url.value.trim(),
            button_2_text: els.taskButton2Text.value.trim(),
            button_2_url: els.taskButton2Url.value.trim()
        };
    }

    function collectFirecrawlDiagnosticPayload() {
        return {
            firecrawl_enabled: Boolean(els.settingsFirecrawlEnabled?.checked),
            firecrawl_api_url: els.settingsFirecrawlApiUrl?.value.trim() || "https://api.firecrawl.dev",
            firecrawl_api_key: els.settingsFirecrawlApiKey?.value.trim() || "",
            firecrawl_timeout_seconds: Number(els.settingsFirecrawlTimeout?.value || 60),
            firecrawl_max_age_ms: Number(els.settingsFirecrawlMaxAge?.value || 0),
            firecrawl_store_in_cache: Boolean(els.settingsFirecrawlStoreInCache?.checked),
            firecrawl_proxy_mode: els.settingsFirecrawlProxyMode?.value || "basic",
            firecrawl_allow_auto_proxy: Boolean(els.settingsFirecrawlAllowAutoProxy?.checked),
            firecrawl_allow_enhanced_proxy: Boolean(els.settingsFirecrawlAllowEnhancedProxy?.checked),
            firecrawl_zero_data_retention: Boolean(els.settingsFirecrawlZeroDataRetention?.checked)
        };
    }

    async function testFirecrawlConnection() {
        const button = els.settingsFirecrawlTestButton;
        const resultBox = els.settingsFirecrawlTestResult;
        if (!button) return;
        button.disabled = true;
        if (resultBox) {
            resultBox.textContent = "正在测试 Firecrawl 连接...";
            resultBox.className = "firecrawl-test-result is-pending";
        }
        try {
            const data = await apiFetch("/api/settings/firecrawl-test", {
                method: "POST",
                body: JSON.stringify(collectFirecrawlDiagnosticPayload())
            });
            const result = data.result || {};
            const ok = result.status === "ok";
            const detail = ok
                ? `${result.detail || "Firecrawl API 可用。"}${result.status_code ? ` HTTP ${result.status_code}` : ""}`
                : `${result.detail || data.message || "测试失败。"}${result.advice ? ` 建议：${result.advice}` : ""}`;
            if (resultBox) {
                resultBox.textContent = detail;
                resultBox.className = `firecrawl-test-result ${ok ? "is-ok" : "is-error"}`;
            }
            showToast(ok ? "Firecrawl 连接测试成功。" : "Firecrawl 连接测试失败，请查看诊断建议。", ok ? "success" : "error");
        } catch (error) {
            if (resultBox) {
                resultBox.textContent = error.message || "Firecrawl 连接测试失败。";
                resultBox.className = "firecrawl-test-result is-error";
            }
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    function renderScraplingRuntimeStatus(status) {
        const payload = status || {};
        const available = Boolean(payload.available);
        if (els.settingsScraplingStatus) {
            els.settingsScraplingStatus.textContent = payload.detail || "Scrapling 状态等待检测。";
        }
        if (els.settingsScraplingStatusPill) {
            els.settingsScraplingStatusPill.textContent = available
                ? "可用"
                : (payload.status === "missing_fetchers" ? "依赖缺失" : "未安装");
            els.settingsScraplingStatusPill.className = available
                ? "rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-bold text-emerald-200"
                : "rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-bold text-amber-200";
        }
    }

    async function testScraplingRuntime() {
        const button = els.settingsScraplingTestButton;
        if (!button) return;
        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = "检测中...";
        try {
            const data = await apiFetch("/api/settings/scrapling-test", { method: "POST" });
            const result = data.result || {};
            renderScraplingRuntimeStatus(result);
            showToast(
                result.available ? "Scrapling 检测通过。" : "Scrapling 检测未通过，请查看状态说明。",
                result.available ? "success" : "error"
            );
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
            button.textContent = originalText || "检测 Scrapling";
        }
    }

    async function sendTemplateTestPush() {
        const submit = els.taskTemplateTestButton;
        if (!submit) return;
        submit.disabled = true;
        try {
            const data = await apiFetch("/api/template-test-push", {
                method: "POST",
                body: JSON.stringify(collectTemplateTestPayload())
            });
            const count = data.result?.chat_count ?? 0;
            showToast(count ? `模板测试消息已发送到 ${count} 个对话。` : "模板测试消息已发送。");
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    }

    function collectMerchantPayload() {
        const groupName = readMerchantGroupValue();
        if (!groupName) {
            throw new Error("请输入新的分组名称。");
        }
        return {
            source_url: els.merchantSourceUrl.value.trim(),
            source_name: els.merchantSourceName.value.trim(),
            group_name: groupName,
            catalog_discovery_strategy: els.merchantDiscoveryStrategy?.value || "local",
            catalog_scrape_strategy: els.merchantScrapeStrategy?.value || "scrapling_adaptive",
            default_fetch_strategy: els.merchantDefaultFetchStrategy?.value || "scrapling_adaptive",
            default_extractor: els.merchantDefaultExtractor?.value || "generic_pricing_table",
            search_keyword: els.merchantSearchKeyword?.value.trim() || "",
            target_keyword: els.merchantTargetKeyword?.value.trim() || "",
            target_keyword_mode: els.merchantTargetKeywordMode?.value || "contains",
            dedupe_policy: els.merchantDedupePolicy?.value || "by_url",
            max_discovered_urls: Number(els.merchantMaxDiscoveredUrls?.value || 50),
            max_import_items: Number(els.merchantMaxImportItems?.value || 50),
            timeout_seconds: Number(els.merchantTimeoutSeconds?.value || 25),
            include_sold_out: Boolean(els.merchantIncludeSoldOut?.checked),
            auto_promote: Boolean(els.merchantAutoPromote?.checked)
        };
    }

    function setMerchantPreviewFromResult(result) {
        merchantPreview = normalizePreviewResult(result || {});
        merchantSignature = null;
        renderMerchant(currentMerchant);
        updateMerchantPreviewActions();
    }

    async function discoverMerchantCandidateUrls(submit) {
        if (submit) submit.disabled = true;
        const originalLabel = els.merchantImportButtonLabel?.textContent || "";
        if (els.merchantImportButtonLabel) {
            els.merchantImportButtonLabel.textContent = "发现中...";
        }
        try {
            const data = await apiFetch("/api/merchant/discover", {
                method: "POST",
                body: JSON.stringify(collectMerchantPayload())
            });
            setMerchantPreviewFromResult(data.result || {});
            const count = data.result?.counts?.candidate_urls ?? data.result?.candidate_urls?.length ?? 0;
            showToast(`已发现 ${count} 个候选 URL。`);
            setMerchantStep("sources", true);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            if (submit) submit.disabled = false;
            if (els.merchantImportButtonLabel) {
                els.merchantImportButtonLabel.textContent = originalLabel || "发现候选 URL";
            }
        }
    }

    async function scrapeMerchantPreviewUrls() {
        const selectedUrls = selectedPreviewUrls();
        if (!selectedUrls.length) {
            showToast("请先选择要抓取的候选 URL。", "error");
            return;
        }
        const button = els.merchantPreviewScrapeButton;
        if (button) button.disabled = true;
        try {
            const payload = collectMerchantPayload();
            payload.source_name = merchantPreview.sourceName || payload.source_name;
            payload.candidate_urls = selectedUrls;
            const data = await apiFetch("/api/merchant/preview", {
                method: "POST",
                body: JSON.stringify(payload)
            });
            setMerchantPreviewFromResult(data.result || {});
            const count = data.result?.counts?.items ?? data.result?.items?.length ?? 0;
            showToast(`商品预览已生成：${count} 个可入库商品。`);
            setMerchantStep("items", true);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            updateMerchantPreviewActions();
        }
    }

    async function commitMerchantPreviewItems() {
        const selectedItems = selectedPreviewItems();
        if (!selectedItems.length) {
            showToast("请先选择要写入的商品。", "error");
            return;
        }
        const button = els.merchantPreviewCommitButton;
        if (button) button.disabled = true;
        try {
            const payload = collectMerchantPayload();
            const data = await apiFetch("/api/merchant/commit", {
                method: "POST",
                body: JSON.stringify({
                    source_url: merchantPreview.sourceUrl || payload.source_url,
                    source_name: merchantPreview.sourceName || payload.source_name,
                    group_name: merchantPreview.groupName || payload.group_name,
                    auto_promote: Boolean(els.merchantAutoPromote?.checked),
                    items: selectedItems
                })
            });
            const promoted = data.result?.promoted_count ?? 0;
            showToast(`已写入 ${data.result?.upserted_count ?? selectedItems.length} 个商品，生成 ${promoted} 个任务。`);
            merchantPreview = { candidateUrls: [], items: [], rejectedItems: [], failures: [] };
            merchantSignature = null;
            await loadSnapshot(false);
            setMerchantStep("items", true);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            updateMerchantPreviewActions();
        }
    }

    async function handleMerchantAction(button) {
        const action = button.dataset.merchantAction;
        if (action === "open-task") {
            const taskId = button.dataset.taskId;
            const task = currentTasks.get(String(taskId));
            if (task) {
                openTaskModal(task);
            }
            return;
        }
        if (action === "promote-item") {
            const itemId = button.dataset.itemId;
            if (!itemId) return;
            button.disabled = true;
            try {
                const data = await apiFetch(`/api/merchant/items/${itemId}/promote`, {
                    method: "POST",
                    body: JSON.stringify({})
                });
                showToast(data.message || "商家商品已生成任务。");
                await loadSnapshot(false);
                const createdTaskId = data.result?.task_id;
                const createdTask = createdTaskId ? currentTasks.get(String(createdTaskId)) : null;
                if (createdTask) {
                    openTaskModal(createdTask);
                }
            } catch (error) {
                showToast(error.message, "error");
            } finally {
                button.disabled = false;
            }
            return;
        }
        if (action === "bulk-promote") {
            const itemIds = String(button.dataset.itemIds || "")
                .split(",")
                .map((value) => Number(value))
                .filter((value) => Number.isInteger(value) && value > 0);
            if (!itemIds.length) {
                showToast("当前筛选条件下没有可创建任务的商品。", "error");
                return;
            }
            button.disabled = true;
            try {
                const data = await apiFetch("/api/merchant/items/bulk-promote", {
                    method: "POST",
                    body: JSON.stringify({ item_ids: itemIds })
                });
                showToast(data.message || `批量创建完成：${itemIds.length} 个商品已处理。`);
                await loadSnapshot(false);
            } catch (error) {
                showToast(error.message, "error");
            } finally {
                button.disabled = !String(button.dataset.itemIds || "").trim();
            }
            return;
        }
        if (action !== "sync-source" && action !== "toggle-source") return;
        const sourceId = button.dataset.sourceId;
        if (!sourceId) return;

        button.disabled = true;
        try {
            if (action === "sync-source") {
                await apiFetch(`/api/merchant/sources/${sourceId}/sync`, {
                    method: "POST",
                    body: JSON.stringify({ auto_promote: true })
                });
                showToast("商家来源已同步。");
            } else {
                const nextActive = button.dataset.active !== "true";
                await apiFetch(`/api/merchant/sources/${sourceId}/toggle`, {
                    method: "POST",
                    body: JSON.stringify({ active: nextActive })
                });
                showToast(nextActive ? "商家来源已启用。" : "商家来源已停用。");
            }
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    function openTaskGroupRenameModal(groupName) {
        const normalizedGroup = normalizeTaskGroup(groupName);
        if (!normalizedGroup || normalizedGroup === defaultTaskGroup) {
            showToast("默认分组暂不支持重命名。", "error");
            return;
        }
        pendingGroupRename = normalizedGroup;
        if (els.groupRenameTitle) {
            els.groupRenameTitle.textContent = `重命名分组：${normalizedGroup}`;
        }
        syncInputValue(els.groupRenameInput, normalizedGroup);
        els.groupRenameModal?.classList.remove("hidden");
        document.body.style.overflow = "hidden";
        window.setTimeout(() => els.groupRenameInput?.focus(), 40);
    }

    function closeTaskGroupRenameModal() {
        pendingGroupRename = "";
        els.groupRenameModal?.classList.add("hidden");
        document.body.style.overflow = "";
    }

    async function submitTaskGroupRename(event) {
        event.preventDefault();
        const oldName = pendingGroupRename || normalizeTaskGroup(els.groupRenameInput?.value);
        const nextName = normalizeTaskGroup(els.groupRenameInput?.value);
        if (!oldName || oldName === defaultTaskGroup) {
            showToast("默认分组暂不支持重命名。", "error");
            return;
        }
        if (!nextName) {
            showToast("新的分组名称不能为空。", "error");
            return;
        }
        if (nextName === oldName) {
            closeTaskGroupRenameModal();
            return;
        }
        const submitButton = els.groupRenameSubmit;
        submitButton.disabled = true;
        try {
            const data = await apiFetch("/api/task-groups/rename", {
                method: "POST",
                body: JSON.stringify({
                    old_name: oldName,
                    new_name: nextName
                })
            });
            showToast(data.message || "分组已重命名。");
            closeTaskGroupRenameModal();
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submitButton.disabled = false;
        }
    }

    function openTaskMoveModal(taskIds) {
        pendingTaskMoveIds = Array.from(new Set((taskIds || [])
            .map((taskId) => Number(taskId))
            .filter((taskId) => Number.isInteger(taskId) && taskId > 0)));
        if (!pendingTaskMoveIds.length) {
            showToast("请先选择要移动的商品。", "error");
            return;
        }
        const firstTask = currentTasks.get(String(pendingTaskMoveIds[0]));
        const defaultGroup = taskBrowserPath.groupName || firstTask?.group_name || defaultTaskGroup;
        const defaultSubgroup = taskBrowserPath.subgroupName || firstTask?.subgroup_name || defaultTaskSubgroup;
        if (els.taskMoveTitle) {
            els.taskMoveTitle.textContent = pendingTaskMoveIds.length > 1 ? "批量移动商品" : "移动商品";
        }
        if (els.taskMoveCount) {
            els.taskMoveCount.textContent = `将移动 ${pendingTaskMoveIds.length} 个商品，状态、消息记录和来源信息都会保留。`;
        }
        renderTaskMoveGroupOptions([defaultGroup]);
        setTaskMoveGroupSelection(defaultGroup, [defaultGroup]);
        renderTaskMoveSubgroupOptions(defaultGroup, [defaultSubgroup]);
        setTaskMoveSubgroupSelection(defaultGroup, defaultSubgroup, [defaultSubgroup]);
        els.taskMoveModal?.classList.remove("hidden");
        document.body.style.overflow = "hidden";
        window.setTimeout(() => els.taskMoveGroup?.focus(), 40);
    }

    function closeTaskMoveModal() {
        pendingTaskMoveIds = [];
        els.taskMoveModal?.classList.add("hidden");
        document.body.style.overflow = "";
    }

    async function submitTaskMove(event) {
        event.preventDefault();
        const targetGroup = readTaskMoveGroupValue();
        const targetSubgroup = readTaskMoveSubgroupValue();
        if (!pendingTaskMoveIds.length) {
            showToast("请先选择要移动的商品。", "error");
            return;
        }
        if (!targetGroup) {
            showToast("请选择或输入目标主分组。", "error");
            return;
        }
        if (!targetSubgroup) {
            showToast("请选择或输入目标子分组。", "error");
            return;
        }
        const submitButton = els.taskMoveSubmit;
        if (submitButton) submitButton.disabled = true;
        try {
            const data = await apiFetch("/api/tasks/move", {
                method: "POST",
                body: JSON.stringify({
                    task_ids: pendingTaskMoveIds,
                    target_group_name: targetGroup,
                    target_subgroup_name: targetSubgroup
                })
            });
            showToast(data.message || `已移动 ${pendingTaskMoveIds.length} 个商品。`);
            closeTaskMoveModal();
            setTaskBrowserPath(targetGroup, targetSubgroup === defaultTaskSubgroup ? "" : targetSubgroup, "products");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            if (submitButton) submitButton.disabled = false;
            updateBulkDeleteButtons();
        }
    }

    function selectedTaskIdsIn(scope) {
        return Array.from(scope?.querySelectorAll?.("[data-task-select]:checked") || [])
            .map((input) => Number(input.value))
            .filter((taskId) => Number.isInteger(taskId) && taskId > 0);
    }

    function selectedSubgroupPathsIn(scope) {
        return Array.from(scope?.querySelectorAll?.("[data-subgroup-select]:checked") || [])
            .map((input) => normalizeTaskSubgroup(input.value))
            .filter((path) => path && path !== defaultTaskSubgroup);
    }

    function updateBulkDeleteButtons(scope = els.tasksGrid) {
        scope?.querySelectorAll?.("[data-group-action=\"bulk-move\"]")?.forEach((button) => {
            const container = button.closest(".task-browser-section") || button.closest("[data-task-subgroup-section]") || button.closest("[data-task-group-section]") || els.tasksGrid;
            const selectedCount = selectedTaskIdsIn(container).length;
            button.disabled = selectedCount === 0;
            button.textContent = selectedCount ? `移动选中 (${selectedCount})` : "移动选中商品";
        });
        scope?.querySelectorAll?.("[data-group-action=\"bulk-delete\"]")?.forEach((button) => {
            const container = button.closest(".task-browser-section") || button.closest("[data-task-subgroup-section]") || button.closest("[data-task-group-section]") || els.tasksGrid;
            const selectedCount = selectedTaskIdsIn(container).length;
            button.disabled = selectedCount === 0;
            button.textContent = selectedCount ? `删除选中 (${selectedCount})` : "删除选中";
        });
        scope?.querySelectorAll?.("[data-subgroup-action=\"bulk-delete\"]")?.forEach((button) => {
            const container = button.closest(".task-browser-section") || els.tasksGrid;
            const selectedCount = selectedSubgroupPathsIn(container).length;
            button.disabled = selectedCount === 0;
            button.textContent = selectedCount ? `删除选中子分组 (${selectedCount})` : "删除选中子分组";
        });
    }

    function bulkMoveSelectedTasks(button) {
        const scope = button.closest(".task-browser-section") || button.closest("[data-task-subgroup-section]") || button.closest("[data-task-group-section]") || els.tasksGrid;
        openTaskMoveModal(selectedTaskIdsIn(scope));
    }

    async function bulkDeleteSelectedTasks(button) {
        const scope = button.closest(".task-browser-section") || button.closest("[data-task-subgroup-section]") || button.closest("[data-task-group-section]") || els.tasksGrid;
        const taskIds = selectedTaskIdsIn(scope);
        if (!taskIds.length) {
            showToast("请先选择要删除的任务。", "error");
            return;
        }
        if (!window.confirm(`确认删除选中的 ${taskIds.length} 个任务？`)) {
            return;
        }
        button.disabled = true;
        try {
            const data = await apiFetch("/api/tasks/bulk-delete", {
                method: "POST",
                body: JSON.stringify({ task_ids: taskIds })
            });
            showToast(data.message || `已删除 ${taskIds.length} 个任务。`);
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
            updateBulkDeleteButtons();
        }
    }

    async function deleteTaskGroup(groupName, button) {
        const normalizedGroup = normalizeTaskGroup(groupName);
        if (!normalizedGroup || normalizedGroup === defaultTaskGroup) {
            showToast("默认分组暂不支持整体删除。", "error");
            return;
        }
        if (!window.confirm(`确认删除分组「${normalizedGroup}」以及其中所有任务？`)) {
            return;
        }
        button.disabled = true;
        try {
            const data = await apiFetch("/api/task-groups/delete", {
                method: "POST",
                body: JSON.stringify({ group_name: normalizedGroup })
            });
            showToast(data.message || "分组已删除。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    async function deleteTaskSubgroup(groupName, subgroupName, button) {
        const normalizedGroup = normalizeTaskGroup(groupName);
        const normalizedSubgroup = normalizeTaskSubgroup(subgroupName);
        if (!window.confirm(`确认删除子分组「${normalizedGroup} / ${normalizedSubgroup}」以及其中所有任务？`)) {
            return;
        }
        button.disabled = true;
        try {
            const data = await apiFetch("/api/task-subgroups/delete", {
                method: "POST",
                body: JSON.stringify({
                    group_name: normalizedGroup,
                    subgroup_name: normalizedSubgroup
                })
            });
            showToast(data.message || "子分组已删除。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    async function createTaskSubgroup(button) {
        const groupName = normalizeTaskGroup(taskBrowserPath.groupName);
        if (!groupName) {
            showToast("请先进入一个主分组。", "error");
            return;
        }
        const name = window.prompt("新子分组名称");
        if (!name || !name.trim()) {
            return;
        }
        button.disabled = true;
        try {
            const data = await apiFetch("/api/task-subgroups", {
                method: "POST",
                body: JSON.stringify({
                    group_name: groupName,
                    parent_subgroup_name: taskBrowserPath.subgroupName || defaultTaskSubgroup,
                    name: name.trim()
                })
            });
            showToast(data.message || "子分组已创建。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    async function renameTaskSubgroup(subgroupName, button) {
        const groupName = normalizeTaskGroup(taskBrowserPath.groupName);
        const currentPath = normalizeTaskSubgroup(subgroupName);
        const parts = splitTaskSubgroupPath(currentPath);
        const currentName = parts[parts.length - 1] || currentPath;
        const nextName = window.prompt("新的子分组名称", currentName);
        if (!nextName || !nextName.trim() || nextName.trim() === currentName) {
            return;
        }
        button.disabled = true;
        try {
            const data = await apiFetch("/api/task-subgroups/rename", {
                method: "POST",
                body: JSON.stringify({
                    group_name: groupName,
                    old_subgroup_name: currentPath,
                    new_name: nextName.trim()
                })
            });
            const renamedPath = data.result?.new_subgroup_name || currentPath;
            if (isSameSubgroupPath(taskBrowserPath.subgroupName, currentPath) || isSubgroupDescendant(taskBrowserPath.subgroupName, currentPath)) {
                setTaskBrowserPath(groupName, renamedPath, taskBrowserView());
            }
            showToast(data.message || "子分组已重命名。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
        }
    }

    async function bulkDeleteSelectedSubgroups(button) {
        const scope = button.closest(".task-browser-section") || els.tasksGrid;
        const subgroupNames = selectedSubgroupPathsIn(scope);
        if (!subgroupNames.length) {
            showToast("请先选择要删除的子分组。", "error");
            return;
        }
        if (!window.confirm(`确认删除选中的 ${subgroupNames.length} 个子分组及其商品？`)) {
            return;
        }
        button.disabled = true;
        try {
            const data = await apiFetch("/api/task-subgroups/bulk-delete", {
                method: "POST",
                body: JSON.stringify({
                    group_name: normalizeTaskGroup(taskBrowserPath.groupName),
                    subgroup_names: subgroupNames
                })
            });
            showToast(data.message || "子分组已删除。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            button.disabled = false;
            updateBulkDeleteButtons();
        }
    }

    function cleanupTaskDragClasses() {
        els.tasksGrid?.querySelectorAll(".is-dragging, .is-drop-target, .is-drag-active").forEach((element) => {
            element.classList.remove("is-dragging", "is-drop-target", "is-drag-active");
        });
    }

    function draggableCardFromEvent(event) {
        return event.target.closest("[data-drag-kind][data-drag-id]");
    }

    function handleTaskDragStart(event) {
        const card = draggableCardFromEvent(event);
        if (!card) return;
        const interactive = event.target.closest("button, a, input, textarea, select, label");
        if (interactive && !event.target.closest(".task-drag-handle")) {
            event.preventDefault();
            return;
        }
        const kind = card.dataset.dragKind;
        const container = card.closest(`[data-drag-scope="${kind}"]`);
        if (!kind || !container) {
            event.preventDefault();
            return;
        }
        taskDragState = {
            kind,
            id: card.dataset.dragId,
            container,
            moved: false
        };
        card.classList.add("is-dragging");
        container.classList.add("is-drag-active");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", `${kind}:${card.dataset.dragId}`);
    }

    function shouldPlaceAfter(target, event) {
        const rect = target.getBoundingClientRect();
        const midY = rect.top + rect.height / 2;
        const midX = rect.left + rect.width / 2;
        const sameRowBias = Math.abs(event.clientY - midY) < Math.max(16, rect.height * 0.35);
        return event.clientY > midY || (sameRowBias && event.clientX > midX);
    }

    function handleTaskDragOver(event) {
        if (!taskDragState) return;
        const container = event.target.closest(`[data-drag-scope="${taskDragState.kind}"]`);
        if (!container || container !== taskDragState.container) return;
        const dragging = container.querySelector(`[data-drag-kind="${taskDragState.kind}"].is-dragging`);
        const target = draggableCardFromEvent(event);
        if (!dragging || !target || target === dragging || target.dataset.dragKind !== taskDragState.kind) {
            event.preventDefault();
            return;
        }
        event.preventDefault();
        container.querySelectorAll(".is-drop-target").forEach((element) => element.classList.remove("is-drop-target"));
        target.classList.add("is-drop-target");
        const after = shouldPlaceAfter(target, event);
        container.insertBefore(dragging, after ? target.nextElementSibling : target);
        taskDragState.moved = true;
    }

    function currentDragOrder(kind, container) {
        return Array.from(container.querySelectorAll(`[data-drag-kind="${kind}"][data-drag-id]`))
            .map((element) => element.dataset.dragId)
            .filter(Boolean);
    }

    async function persistTaskDragOrder(kind, order) {
        if (!order.length) return;
        let endpoint = "";
        let body = {};
        if (kind === "group") {
            endpoint = "/api/task-groups/reorder";
            body = { group_names: order };
        } else if (kind === "subgroup") {
            endpoint = "/api/task-subgroups/reorder";
            body = {
                group_name: normalizeTaskGroup(taskBrowserPath.groupName),
                parent_subgroup_name: taskBrowserPath.subgroupName || defaultTaskSubgroup,
                subgroup_names: order
            };
        } else if (kind === "task") {
            endpoint = "/api/tasks/reorder";
            body = { task_ids: order.map((value) => Number(value)).filter((value) => Number.isInteger(value) && value > 0) };
        }
        if (!endpoint) return;
        try {
            await apiFetch(endpoint, {
                method: "POST",
                body: JSON.stringify(body)
            });
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message || "排序保存失败。", "error");
            await loadSnapshot(false);
        }
    }

    async function handleTaskDragDrop(event) {
        if (!taskDragState) return;
        const state = taskDragState;
        const container = event.target.closest(`[data-drag-scope="${state.kind}"]`) || state.container;
        if (!container || container !== state.container) {
            cleanupTaskDragClasses();
            taskDragState = null;
            return;
        }
        event.preventDefault();
        const order = currentDragOrder(state.kind, container);
        taskDragSuppressClickUntil = Date.now() + 300;
        cleanupTaskDragClasses();
        taskDragState = null;
        if (state.moved) {
            await persistTaskDragOrder(state.kind, order);
        }
    }

    function handleTaskDragEnd() {
        cleanupTaskDragClasses();
        taskDragState = null;
    }

    async function runTaskStockCheck(taskId, options = {}) {
        const data = await apiFetch(`/api/tasks/${taskId}/check`, {
            method: "POST",
            body: JSON.stringify({})
        });
        const result = data.result || {};
        const backend = result.backend_used ? ` · ${fetchStrategyLabel(result.backend_used)}` : "";
        if (options.showToast !== false) {
            showToast(`库存检测完成：${stockResultLabel(result.stock, result.state)}${backend}`);
        }
        return result;
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
        if (action === "move") {
            openTaskMoveModal([taskId]);
            return;
        }
        if (action === "delete" && !window.confirm(`确认删除任务「${task.name}」？`)) {
            return;
        }

        button.disabled = true;
        try {
            if (action === "check") {
                await runTaskStockCheck(taskId);
            } else if (action === "manual-in-stock" || action === "manual-sold-out") {
                const stock = action === "manual-in-stock" ? 1 : 0;
                await apiFetch(`/api/tasks/${taskId}/manual-stock`, {
                    method: "POST",
                    body: JSON.stringify({
                        stock,
                        detail: action === "manual-in-stock" ? "后台手动标记有货" : "后台手动标记售罄"
                    })
                });
                showToast(stock > 0 ? "已手动标记有货。" : "已手动标记售罄。");
            } else if (action === "webhook-token") {
                const data = await apiFetch(`/api/tasks/${taskId}/webhook-token`, {
                    method: "POST",
                    body: JSON.stringify({})
                });
                const token = data.result?.ingest_token || "";
                const copied = await copyText(token);
                if (!copied && token) {
                    window.prompt("Webhook token", token);
                }
                showToast(copied ? "Webhook token 已重置并复制。" : "Webhook token 已重置。");
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

    function updateBackupFileName() {
        if (!els.backupFileName || !els.backupFileInput) return;
        const file = els.backupFileInput.files?.[0];
        els.backupFileName.textContent = file ? file.name : "选择备份文件";
    }

    async function exportBackup() {
        const anchor = document.createElement("a");
        anchor.href = "/api/system/backup";
        anchor.download = "";
        anchor.rel = "noopener";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        showToast("备份下载已开始。");
    }

    async function restoreBackup() {
        const file = els.backupFileInput?.files?.[0];
        if (!file) {
            showToast("请先选择要恢复的备份文件。", "error");
            return;
        }
        if (!window.confirm("确认恢复这份备份？当前数据库内容将被覆盖。")) {
            return;
        }
        const formData = new FormData();
        formData.append("backup_file", file, file.name || "noaff-backup.json");
        els.backupRestoreButton.disabled = true;
        try {
            const response = await fetch("/api/system/backup", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRF-Token": csrfToken
                },
                body: formData
            });
            const data = await response.json().catch(() => ({}));
            if (data.csrf_token) {
                csrfToken = data.csrf_token;
                document.querySelector('meta[name="csrf-token"]')?.setAttribute("content", csrfToken);
            }
            if (!response.ok || data.ok === false) {
                throw new Error(data.message || "恢复失败。");
            }
            showToast(data.message || "备份已恢复。");
            els.backupFileInput.value = "";
            updateBackupFileName();
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            els.backupRestoreButton.disabled = false;
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

    els.backupExportButton?.addEventListener("click", exportBackup);
    els.backupRestoreButton?.addEventListener("click", restoreBackup);
    els.backupFileInput?.addEventListener("change", updateBackupFileName);

    els.navTasks?.addEventListener("click", () => setNav("tasks"));
    els.navMerchant?.addEventListener("click", () => setNav("merchant"));
    els.navSettings?.addEventListener("click", () => setNav("settings"));
    els.mobileNavTasks?.addEventListener("click", () => setNav("tasks"));
    els.mobileNavMerchant?.addEventListener("click", () => setNav("merchant"));
    els.mobileNavSettings?.addEventListener("click", () => setNav("settings"));
    els.settingsView?.addEventListener("click", (event) => {
        const entry = event.target.closest("[data-settings-target]");
        if (entry) {
            openSettingsPage(entry.dataset.settingsTarget);
            if (entry.dataset.settingsTarget === "settings-firecrawl") {
                openFirecrawlGuideModal();
            }
            return;
        }
        const back = event.target.closest("[data-settings-back]");
        if (back) {
            openSettingsHome();
        }
    });

    els.taskResetButton?.addEventListener("click", () => openTaskModal());
    els.taskCancelButton?.addEventListener("click", closeTaskModal);
    els.taskModalClose?.addEventListener("click", closeTaskModal);
    els.taskTemplateHelpButton?.addEventListener("click", openTemplateHelpModal);
    els.templateHelpClose?.addEventListener("click", closeTemplateHelpModal);
    els.firecrawlGuideClose?.addEventListener("click", closeFirecrawlGuideModal);
    els.firecrawlGuidePrev?.addEventListener("click", () => {
        setFirecrawlGuideStep(firecrawlGuideIndex - 1);
    });
    els.firecrawlGuideNext?.addEventListener("click", () => {
        const total = firecrawlGuideSlideCount();
        if (firecrawlGuideIndex >= total - 1) {
            closeFirecrawlGuideModal();
            return;
        }
        setFirecrawlGuideStep(firecrawlGuideIndex + 1);
    });
    els.firecrawlGuideDots?.addEventListener("click", (event) => {
        const dot = event.target.closest("[data-firecrawl-step]");
        if (!dot) return;
        setFirecrawlGuideStep(Number(dot.dataset.firecrawlStep || 0));
    });
    els.firecrawlGuideModal?.addEventListener("click", (event) => {
        if (event.target === els.firecrawlGuideModal) {
            closeFirecrawlGuideModal();
        }
    });
    els.taskTemplateTestButton?.addEventListener("click", sendTemplateTestPush);
    els.taskModal?.addEventListener("click", (event) => {
        if (event.target === els.taskModal) {
            closeTaskModal();
        }
    });
    els.taskMoveModal?.addEventListener("click", (event) => {
        if (event.target === els.taskMoveModal) {
            closeTaskMoveModal();
        }
    });
    els.templateHelpModal?.addEventListener("click", (event) => {
        if (event.target === els.templateHelpModal) {
            closeTemplateHelpModal();
        }
    });
    els.taskGroup?.addEventListener("change", () => {
        updateGroupVisibility(els.taskGroup, els.taskGroupCustomWrap, els.taskGroupCustom);
        const selectedGroup = readTaskGroupValue() || defaultTaskGroup;
        renderTaskSubgroupOptions(selectedGroup);
        if (els.taskGroup?.value === "__custom__") {
            window.setTimeout(() => els.taskGroupCustom?.focus(), 0);
        }
    });
    els.taskSubgroup?.addEventListener("change", () => {
        updateGroupVisibility(els.taskSubgroup, els.taskSubgroupCustomWrap, els.taskSubgroupCustom);
        if (els.taskSubgroup?.value === "__custom__") {
            window.setTimeout(() => els.taskSubgroupCustom?.focus(), 0);
        }
    });
    els.taskMoveGroup?.addEventListener("change", () => {
        updateGroupVisibility(els.taskMoveGroup, els.taskMoveGroupCustomWrap, els.taskMoveGroupCustom);
        const selectedGroup = readTaskMoveGroupValue() || defaultTaskGroup;
        renderTaskMoveSubgroupOptions(selectedGroup);
        if (els.taskMoveGroup?.value === "__custom__") {
            window.setTimeout(() => els.taskMoveGroupCustom?.focus(), 0);
        }
    });
    els.taskMoveSubgroup?.addEventListener("change", () => {
        updateGroupVisibility(els.taskMoveSubgroup, els.taskMoveSubgroupCustomWrap, els.taskMoveSubgroupCustom);
        if (els.taskMoveSubgroup?.value === "__custom__") {
            window.setTimeout(() => els.taskMoveSubgroupCustom?.focus(), 0);
        }
    });
    els.merchantGroup?.addEventListener("change", () => {
        updateGroupVisibility(els.merchantGroup, els.merchantGroupCustomWrap, els.merchantGroupCustom);
        if (els.merchantGroup?.value === "__custom__") {
            window.setTimeout(() => els.merchantGroupCustom?.focus(), 0);
        }
    });

    els.tasksGrid?.addEventListener("click", (event) => {
        if (Date.now() < taskDragSuppressClickUntil) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        const groupAction = event.target.closest("[data-group-action]");
        if (groupAction) {
            const groupName = groupAction.dataset.groupName || defaultTaskGroup;
            if (groupAction.dataset.groupAction === "rename") {
                openTaskGroupRenameModal(groupName);
            } else if (groupAction.dataset.groupAction === "delete") {
                deleteTaskGroup(groupName, groupAction);
            } else if (groupAction.dataset.groupAction === "bulk-move") {
                bulkMoveSelectedTasks(groupAction);
            } else if (groupAction.dataset.groupAction === "bulk-delete") {
                bulkDeleteSelectedTasks(groupAction);
            }
            return;
        }
        const subgroupAction = event.target.closest("[data-subgroup-action]");
        if (subgroupAction) {
            const action = subgroupAction.dataset.subgroupAction;
            const subgroupName = subgroupAction.dataset.subgroupName || defaultTaskSubgroup;
            if (action === "create") {
                createTaskSubgroup(subgroupAction);
            } else if (action === "rename") {
                renameTaskSubgroup(subgroupName, subgroupAction);
            } else if (action === "delete") {
                deleteTaskSubgroup(taskBrowserPath.groupName, subgroupName, subgroupAction);
            } else if (action === "bulk-delete") {
                bulkDeleteSelectedSubgroups(subgroupAction);
            }
            return;
        }
        const crumb = event.target.closest("[data-task-crumb-group]");
        if (crumb) {
            setTaskBrowserPath(crumb.dataset.taskCrumbGroup || "", crumb.dataset.taskCrumbSubgroup || "", "children");
            renderTasks(Array.from(currentTasks.values()), false, true);
            return;
        }
        const back = event.target.closest("[data-task-browser-back]");
        if (back) {
            const tasks = Array.from(currentTasks.values());
            const hasChildren = collectChildSubgroups(tasks, taskBrowserPath.groupName, taskBrowserPath.subgroupName).length > 0;
            if (taskBrowserView() === "products" && hasChildren) {
                setTaskBrowserPath(taskBrowserPath.groupName, taskBrowserPath.subgroupName, "children");
            } else if (taskBrowserPath.subgroupName) {
                const parts = splitTaskSubgroupPath(taskBrowserPath.subgroupName);
                setTaskBrowserPath(taskBrowserPath.groupName, joinTaskSubgroupPath(parts.slice(0, -1)), "children");
            } else {
                setTaskBrowserPath();
            }
            renderTasks(tasks, false, true);
            return;
        }
        const groupOpen = event.target.closest("[data-group-open]");
        if (groupOpen) {
            setTaskBrowserPath(groupOpen.dataset.groupOpen, "", "children");
            renderTasks(Array.from(currentTasks.values()), false, true);
            return;
        }
        const subgroupOpen = event.target.closest("[data-subgroup-open]");
        if (subgroupOpen) {
            setTaskBrowserPath(taskBrowserPath.groupName, subgroupOpen.dataset.subgroupOpen, "children");
            renderTasks(Array.from(currentTasks.values()), false, true);
            return;
        }
        const productsOpen = event.target.closest("[data-task-products-open]");
        if (productsOpen) {
            setTaskBrowserPath(taskBrowserPath.groupName, taskBrowserPath.subgroupName, "products");
            renderTasks(Array.from(currentTasks.values()), false, true);
            return;
        }
        const productsBack = event.target.closest("[data-task-products-back]");
        if (productsBack) {
            setTaskBrowserPath(taskBrowserPath.groupName, taskBrowserPath.subgroupName, "children");
            renderTasks(Array.from(currentTasks.values()), false, true);
            return;
        }
        const addRow = event.target.closest("#tasks-add-row");
        if (addRow) {
            openTaskModal();
            return;
        }
        const actionButton = event.target.closest("[data-action]");
        if (actionButton) {
            handleTaskAction(actionButton);
        }
    });
    els.tasksGrid?.addEventListener("dragstart", handleTaskDragStart);
    els.tasksGrid?.addEventListener("dragover", handleTaskDragOver);
    els.tasksGrid?.addEventListener("drop", handleTaskDragDrop);
    els.tasksGrid?.addEventListener("dragend", handleTaskDragEnd);
    els.tasksGrid?.addEventListener("change", (event) => {
        if (event.target.closest("[data-task-select]") || event.target.closest("[data-subgroup-select]")) {
            updateBulkDeleteButtons();
        }
    });

    els.merchantSourceList?.addEventListener("click", (event) => {
        const actionButton = event.target.closest("[data-merchant-action]");
        if (actionButton) {
            handleMerchantAction(actionButton);
        }
    });

    els.merchantItemList?.addEventListener("click", (event) => {
        const actionButton = event.target.closest("[data-merchant-action]");
        if (actionButton) {
            handleMerchantAction(actionButton);
        }
    });

    els.merchantSourceList?.addEventListener("change", (event) => {
        if (event.target.closest("[data-preview-url-select]")) {
            updateMerchantPreviewActions();
        }
    });

    els.merchantItemList?.addEventListener("change", (event) => {
        if (event.target.closest("[data-preview-item-select]")) {
            updateMerchantPreviewActions();
        }
    });

    els.merchantItemFilter?.addEventListener("change", () => {
        renderMerchant(currentMerchant);
    });

    els.merchantBulkPromoteButton?.addEventListener("click", () => {
        handleMerchantAction(els.merchantBulkPromoteButton);
    });

    els.merchantPreviewScrapeButton?.addEventListener("click", scrapeMerchantPreviewUrls);
    els.merchantPreviewCommitButton?.addEventListener("click", commitMerchantPreviewItems);

    els.merchantView?.addEventListener("click", (event) => {
        const stepTarget = event.target.closest("[data-merchant-step-target]");
        if (stepTarget && els.merchantView.contains(stepTarget)) {
            setMerchantStep(stepTarget.dataset.merchantStepTarget, true);
            return;
        }
        if (event.target.closest("[data-merchant-step-next]")) {
            moveMerchantStep(1);
            return;
        }
        if (event.target.closest("[data-merchant-step-prev]")) {
            moveMerchantStep(-1);
        }
    });

    els.merchantForm?.addEventListener("input", renderMerchantReviewSummary);
    els.merchantForm?.addEventListener("change", renderMerchantReviewSummary);

    els.groupRenameForm?.addEventListener("submit", submitTaskGroupRename);
    els.groupRenameCancel?.addEventListener("click", closeTaskGroupRenameModal);
    els.groupRenameClose?.addEventListener("click", closeTaskGroupRenameModal);
    els.taskMoveForm?.addEventListener("submit", submitTaskMove);
    els.taskMoveCancel?.addEventListener("click", closeTaskMoveModal);
    els.taskMoveClose?.addEventListener("click", closeTaskMoveModal);

    els.taskForm?.addEventListener("click", (event) => {
        const strategyCard = event.target.closest("[data-task-strategy-card]");
        if (strategyCard && els.taskForm.contains(strategyCard)) {
            setTaskStrategy(strategyCard.dataset.taskStrategyCard);
        }
    });

    els.taskForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = event.submitter || els.taskSubmitButton;
        const taskId = els.taskId.value;
        const runCheckAfterSave = submit?.dataset?.afterSave === "check";
        submit.disabled = true;
        try {
            const data = await apiFetch(taskId ? `/api/tasks/${taskId}` : "/api/tasks", {
                method: taskId ? "PUT" : "POST",
                body: JSON.stringify(collectTaskPayload())
            });
            const savedTaskId = data.task_id || taskId;
            if (runCheckAfterSave && savedTaskId) {
                const result = await runTaskStockCheck(savedTaskId, { showToast: false });
                const backend = result.backend_used ? ` · ${fetchStrategyLabel(result.backend_used)}` : "";
                showToast(`${taskId ? "节点已更新" : "节点已创建"}，检测结果：${stockResultLabel(result.stock, result.state)}${backend}`);
            } else {
                showToast(taskId ? "任务已更新。" : "任务已创建。");
            }
            closeTaskModal();
            resetTaskForm();
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });

    els.taskFetchStrategy?.addEventListener("change", updateTaskStrategyUi);
    els.settingsFirecrawlTestButton?.addEventListener("click", testFirecrawlConnection);
    els.settingsScraplingTestButton?.addEventListener("click", testScraplingRuntime);

    els.settingsForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = event.submitter;
        submit.disabled = true;
        const payload = {
            telegram_chat_ids: els.settingsChatIds.value.trim(),
            monitor_debug_port: Number(els.settingsMonitorPort.value),
            test_debug_port: Number(els.settingsTestPort.value),
            catalog_debug_port: Number(els.settingsCatalogPort.value),
            poll_interval_seconds: Number(els.settingsPollInterval.value),
            request_timeout_seconds: Number(els.settingsTimeout.value),
            firecrawl_enabled: Boolean(els.settingsFirecrawlEnabled?.checked),
            firecrawl_api_url: els.settingsFirecrawlApiUrl?.value.trim() || "https://api.firecrawl.dev",
            firecrawl_timeout_seconds: Number(els.settingsFirecrawlTimeout?.value || 60),
            firecrawl_max_age_ms: Number(els.settingsFirecrawlMaxAge?.value || 0),
            firecrawl_store_in_cache: Boolean(els.settingsFirecrawlStoreInCache?.checked),
            firecrawl_proxy_mode: els.settingsFirecrawlProxyMode?.value || "basic",
            firecrawl_allow_auto_proxy: Boolean(els.settingsFirecrawlAllowAutoProxy?.checked),
            firecrawl_allow_enhanced_proxy: Boolean(els.settingsFirecrawlAllowEnhancedProxy?.checked),
            firecrawl_zero_data_retention: Boolean(els.settingsFirecrawlZeroDataRetention?.checked),
            firecrawl_use_for_monitor: Boolean(els.settingsFirecrawlUseForMonitor?.checked),
            firecrawl_use_for_catalog: Boolean(els.settingsFirecrawlUseForCatalog?.checked),
            firecrawl_catalog_limit: Number(els.settingsFirecrawlCatalogLimit?.value || 50),
            scrapling_enabled: Boolean(els.settingsScraplingEnabled?.checked),
            scrapling_default_mode: els.settingsScraplingDefaultMode?.value || "standard",
            scrapling_use_for_monitor: Boolean(els.settingsScraplingUseForMonitor?.checked),
            scrapling_use_for_catalog: Boolean(els.settingsScraplingUseForCatalog?.checked),
            scrapling_session_reuse: Boolean(els.settingsScraplingSessionReuse?.checked),
            scrapling_adaptive_selector: Boolean(els.settingsScraplingAdaptiveSelector?.checked),
            scrapling_timeout_standard: Number(els.settingsScraplingTimeoutStandard?.value || 25),
            scrapling_timeout_dynamic: Number(els.settingsScraplingTimeoutDynamic?.value || 45),
            scrapling_timeout_stealth: Number(els.settingsScraplingTimeoutStealth?.value || 75),
            scrapling_domain_cooldown_standard: Number(els.settingsScraplingCooldownStandard?.value || 0),
            scrapling_domain_cooldown_dynamic: Number(els.settingsScraplingCooldownDynamic?.value || 60),
            scrapling_domain_cooldown_stealth: Number(els.settingsScraplingCooldownStealth?.value || 300),
            scrapling_max_concurrency_standard: Number(els.settingsScraplingConcurrencyStandard?.value || 3),
            scrapling_max_concurrency_dynamic: Number(els.settingsScraplingConcurrencyDynamic?.value || 2),
            scrapling_max_concurrency_stealth: Number(els.settingsScraplingConcurrencyStealth?.value || 1)
        };
        if (els.settingsBotToken.value.trim()) {
            payload.telegram_bot_token = els.settingsBotToken.value.trim();
        }
        if (els.settingsFirecrawlApiKey?.value.trim()) {
            payload.firecrawl_api_key = els.settingsFirecrawlApiKey.value.trim();
        }
        try {
            await apiFetch("/api/settings/telegram", {
                method: "POST",
                body: JSON.stringify(payload)
            });
            els.settingsBotToken.value = "";
            if (els.settingsFirecrawlApiKey) {
                els.settingsFirecrawlApiKey.value = "";
            }
            showToast("设置已保存。");
            await loadSnapshot(false);
        } catch (error) {
            showToast(error.message, "error");
        } finally {
            submit.disabled = false;
        }
    });

    els.merchantForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const submit = event.submitter || els.merchantImportButton;
        await discoverMerchantCandidateUrls(submit);
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
        if (event.key === "Escape" && !els.templateHelpModal?.classList.contains("hidden")) {
            closeTemplateHelpModal();
        } else if (event.key === "Escape" && !els.taskModal.classList.contains("hidden")) {
            closeTaskModal();
        } else if (event.key === "Escape" && !els.groupRenameModal.classList.contains("hidden")) {
            closeTaskGroupRenameModal();
        } else if (event.key === "Escape" && !els.taskMoveModal?.classList.contains("hidden")) {
            closeTaskMoveModal();
        }
    });

    wireDirtyTracking(els.taskGroup);
    wireDirtyTracking(els.taskGroupCustom);
    wireDirtyTracking(els.taskSubgroup);
    wireDirtyTracking(els.taskSubgroupCustom);
    wireDirtyTracking(els.taskMoveGroup);
    wireDirtyTracking(els.taskMoveGroupCustom);
    wireDirtyTracking(els.taskMoveSubgroup);
    wireDirtyTracking(els.taskMoveSubgroupCustom);
    wireDirtyTracking(els.merchantGroup);
    wireDirtyTracking(els.merchantGroupCustom);
    [
        els.merchantDiscoveryStrategy,
        els.merchantScrapeStrategy,
        els.merchantDefaultFetchStrategy,
        els.merchantDefaultExtractor,
        els.merchantSearchKeyword,
        els.merchantTargetKeyword,
        els.merchantTargetKeywordMode,
        els.merchantDedupePolicy,
        els.merchantMaxDiscoveredUrls,
        els.merchantMaxImportItems,
        els.merchantTimeoutSeconds,
        els.merchantIncludeSoldOut,
        els.merchantAutoPromote,
        els.settingsChatIds,
        els.settingsMonitorPort,
        els.settingsTestPort,
        els.settingsCatalogPort,
        els.settingsPollInterval,
        els.settingsTimeout,
        els.settingsFirecrawlEnabled,
        els.settingsFirecrawlApiUrl,
        els.settingsFirecrawlApiKey,
        els.settingsFirecrawlTimeout,
        els.settingsFirecrawlMaxAge,
        els.settingsFirecrawlStoreInCache,
        els.settingsFirecrawlProxyMode,
        els.settingsFirecrawlAllowAutoProxy,
        els.settingsFirecrawlAllowEnhancedProxy,
        els.settingsFirecrawlZeroDataRetention,
        els.settingsFirecrawlUseForMonitor,
        els.settingsFirecrawlUseForCatalog,
        els.settingsFirecrawlCatalogLimit
    ].forEach(wireDirtyTracking);
    updateGroupVisibility(els.taskGroup, els.taskGroupCustomWrap, els.taskGroupCustom);
    updateGroupVisibility(els.taskSubgroup, els.taskSubgroupCustomWrap, els.taskSubgroupCustom);
    updateGroupVisibility(els.taskMoveGroup, els.taskMoveGroupCustomWrap, els.taskMoveGroupCustom);
    updateGroupVisibility(els.taskMoveSubgroup, els.taskMoveSubgroupCustomWrap, els.taskMoveSubgroupCustom);
    updateGroupVisibility(els.merchantGroup, els.merchantGroupCustomWrap, els.merchantGroupCustom);
    resetTaskForm();
    setMerchantStep("source");
    setNav("tasks");
    setView(root?.dataset.loggedIn === "true");
})();
