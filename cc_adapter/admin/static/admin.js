// I18n
const i18n = {
  zh: {
    title: "CC Adapter 管理面板",
    loginTitle: "管理员登录",
    loginBtn: "登录",
    loginError: "密码错误",
    loginPlaceholder: "请输入密码",
    dashboard: "状态面板",
    config: "配置编辑",
    playground: "测试面板",
    serverStatus: "服务状态",
    running: "运行中",
    stopped: "未运行",
    apiKey: "API Key",
    configured: "已配置",
    notConfigured: "未配置",
    verify: "验证",
    verifying: "验证中...",
    valid: "有效",
    invalid: "无效",
    save: "保存",
    cancel: "取消",
    saved: "保存成功",
    saveFailed: "保存失败",
    model: "模型",
    messages: "消息",
    stream: "流式输出",
    send: "发送",
    clear: "清空",
    thinking: "思考强度",
    thinkingOff: "关闭",
    logs: "日志",
    logLevel: "级别",
    logSearch: "搜索",
    logAutoRefresh: "自动刷新 (5s)",
    logRefresh: "刷新",
    logNoEntries: "暂无日志",
    logNoMatch: "无匹配日志",
    logLoading: "加载中...",
    logStatus: "显示 {shown} 条 (缓冲区共 {total} 条)",
    response: "响应",
    usage: "使用统计",
    usageRange1d: "近1天",
    usageRange7d: "近7天",
    usageRange30d: "近30天",
    usageStart: "开始",
    usageEnd: "结束",
    usageTotalCost: "总费用",
    usageTotalRequests: "总请求数",
    usageTotalModels: "模型数",
    usageDailyTrend: "每日费用趋势",
    usageByModel: "按模型分布",
    usageDate: "日期",
    usageCost: "费用",
    usageRequests: "请求数",
    usageModels: "模型",
    usageLoading: "加载中...",
    usageNoData: "暂无使用数据",
    pastYear: "过去一年",
    tokenLimit5h: "5h窗口",
    tokenLimitWeekly: "每周",
    tokenLimitReset: "重置",
    tokenLimitRestricted: "已限流",
    keys: "Key 管理",
    keysRefresh: "刷新",
    keysLoading: "加载中...",
    keysEmpty: "未配置上游 Key",
    keysLoadFailed: "加载失败",
    keysSwitchLabel: "Key 开关",
    keysSwitchOn: "启用",
    keysSwitchOff: "停用",
    keysEnabledToast: "{key} 已启用",
    keysDisabledToast: "{key} 已停用",
    keysAddTitle: "添加 Key",
    keysAddPlaceholder: "user_...",
    keysAddButton: "添加",
    keysAddHint: "Key 保存在挂载卷上的面板配置文件（.env）中，立即生效并在重启后保留。",
    keysAddEmpty: "请输入 Key",
    keysAddToast: "{key} 已添加",
    keysAddFailed: "添加失败",
    keysDelete: "删除",
    keysDeleteConfirm: "确定删除 {key} 吗？该 Key 将立即停止使用。",
    keysDeleteToast: "{key} 已删除",
    keysRemoveFailed: "删除失败",
    keysConfigured: "已配置 {n} 个 Key",
    keysManagedInTab: "在「Keys」页添加、删除、启停",
    keysManageButton: "去 Keys 页管理",
    tokenManagerEmpty: "请先添加至少一个 Key",
    tokenManagerResult: "新增 {added} 个，已存在 {existing} 个，失败 {failed} 个",
    tokenManagerHint: "此处只新增 Key（不会覆盖已有列表）；删除与启停在「Keys」页。",
    keyStateOk: "正常",
    keyStateCooling: "冷却",
    keyStateDisabled: "已停用",
    keyStateOff: "已关闭",
    keyStateUnmanaged: "未托管",
    keyCredits: "额度",
    keySessions: "会话",
    keyFailures: "失败",
    keyUnknown: "未知",
    keyUnmanagedHint: "仅在配置多个 Key 时可管理",
    keyReasonCredits: "额度用尽",
    keyReasonRateLimited: "限流",
    keyReasonInvalidKey: "密钥无效",
  },
  en: {
    title: "CC Adapter Admin",
    loginTitle: "Admin Login",
    loginBtn: "Login",
    loginError: "Invalid password",
    loginPlaceholder: "Enter password",
    dashboard: "Dashboard",
    config: "Configuration",
    playground: "Playground",
    serverStatus: "Server Status",
    running: "Running",
    stopped: "Stopped",
    apiKey: "API Key",
    configured: "Configured",
    notConfigured: "Not Configured",
    verify: "Verify",
    verifying: "Verifying...",
    valid: "Valid",
    invalid: "Invalid",
    save: "Save",
    cancel: "Cancel",
    saved: "Saved successfully",
    saveFailed: "Save failed",
    model: "Model",
    messages: "Messages",
    stream: "Stream",
    send: "Send",
    clear: "Clear",
    thinking: "Thinking",
    thinkingOff: "Off",
    logs: "Logs",
    logLevel: "Level",
    logSearch: "Search",
    logAutoRefresh: "Auto-refresh 5s",
    logRefresh: "Refresh",
    logNoEntries: "No log entries",
    logNoMatch: "No matching entries",
    logLoading: "Loading...",
    logStatus: "Showing {shown} entries (filtered from {total} in buffer)",
    response: "Response",
    usage: "Usage",
    usageRange1d: "1 Day",
    usageRange7d: "7 Days",
    usageRange30d: "30 Days",
    usageStart: "Start",
    usageEnd: "End",
    usageTotalCost: "Total Cost",
    usageTotalRequests: "Total Requests",
    usageTotalModels: "Models",
    usageDailyTrend: "Daily Cost Trend",
    usageByModel: "By Model",
    usageDate: "Date",
    usageCost: "Cost",
    usageRequests: "Requests",
    usageModels: "Models",
    usageLoading: "Loading...",
    usageNoData: "No usage data",
    pastYear: "Past Year",
    tokenLimit5h: "5h Window",
    tokenLimitWeekly: "Weekly",
    tokenLimitReset: "Resets in",
    tokenLimitRestricted: "Rate Limited",
    keys: "Keys",
    keysRefresh: "Refresh",
    keysLoading: "Loading...",
    keysEmpty: "No upstream keys configured",
    keysLoadFailed: "Load failed",
    keysSwitchLabel: "Key switch",
    keysSwitchOn: "Enable",
    keysSwitchOff: "Disable",
    keysEnabledToast: "{key} enabled",
    keysDisabledToast: "{key} disabled",
    keysAddTitle: "Add Key",
    keysAddPlaceholder: "user_...",
    keysAddButton: "Add",
    keysAddHint: "The key is written to the panel config file (.env) on the mounted volume: it takes effect immediately and survives a restart.",
    keysAddEmpty: "Enter a key",
    keysAddToast: "{key} added",
    keysAddFailed: "Add failed",
    keysDelete: "Delete",
    keysDeleteConfirm: "Delete {key}? It stops being used immediately.",
    keysDeleteToast: "{key} deleted",
    keysRemoveFailed: "Delete failed",
    keysConfigured: "{n} key(s) configured",
    keysManagedInTab: "Add, remove or switch keys in the Keys tab",
    keysManageButton: "Manage in the Keys tab",
    tokenManagerEmpty: "Add at least one key first",
    tokenManagerResult: "added {added}, already configured {existing}, failed {failed}",
    tokenManagerHint: "This dialog only adds keys (it never rewrites the pool); removal and the on/off switch live in the Keys tab.",
    keyStateOk: "OK",
    keyStateCooling: "Cooling",
    keyStateDisabled: "Disabled",
    keyStateOff: "Off",
    keyStateUnmanaged: "Unmanaged",
    keyCredits: "Credits",
    keySessions: "Sessions",
    keyFailures: "Failures",
    keyUnknown: "unknown",
    keyUnmanagedHint: "Manageable only with multiple keys",
    keyReasonCredits: "out of credits",
    keyReasonRateLimited: "rate limited",
    keyReasonInvalidKey: "invalid key",
  },
};

let lang = localStorage.getItem("cc-admin-lang") || "zh";
let theme = localStorage.getItem("cc-admin-theme") || "light";
let token = localStorage.getItem("cc-admin-token") || null;
let defaultModel = "deepseek/deepseek-v4-flash";
let pgMessages = [];
let pgStreaming = false;

function t(key) { return i18n[lang][key] || key; }

function fmtUptime(s) {
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  const w = Math.floor(d / 7);
  if (w > 0) return `${w}周${d % 7}天`;
  if (d > 0) return `${d}天${h % 24}小时`;
  if (h > 0) return h > 0 && m % 60 > 0 ? `${h}小时${m % 60}分钟` : `${h}小时`;
  return `${m}分钟`;
}

function fmtResetTime(resetAt) {
  if (!resetAt) return "";
  const now = Date.now();
  const diff = Math.floor((resetAt - now) / 1000);
  if (diff <= 0) return "resetting...";
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  if (h > 24) {
    const d = Math.floor(h / 24);
    return d + "d " + (h % 24) + "h";
  }
  if (h > 0) return h + "h " + m + "m";
  return m + "m";
}

function applyLang() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.title = t("title");
}

function applyTheme() {
  document.documentElement.dataset.theme = theme;
  document.getElementById("theme-toggle").textContent =
    theme === "dark" ? t("themeLight") : t("themeDark");
}

function toggleTheme() {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem("cc-admin-theme", theme);
  applyTheme();
}

function switchLang(newLang) {
  lang = newLang;
  localStorage.setItem("cc-admin-lang", lang);
  applyLang();
  renderAll();
}

// Toast
let toastTimer = null;
function showToast(msg, type) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
}

// API helpers
async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (resp.status === 401 && path !== "/admin/api/login") {
    showLogin();
    throw new Error("Unauthorized");
  }
  return resp;
}

// Auth
function showLogin(message) {
  token = null;
  localStorage.removeItem("cc-admin-token");
  document.getElementById("login-overlay").classList.remove("hidden");
  const errEl = document.getElementById("login-error");
  if (message) {
    errEl.textContent = message;
    errEl.classList.remove("hidden");
  } else {
    errEl.classList.add("hidden");
  }
}

async function doLogin() {
  const pw = document.getElementById("login-password").value;
  const resp = await api("POST", "/admin/api/login", { password: pw });
  if (resp.status === 401) {
    showLogin(t("loginError"));
    return;
  }
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    document.getElementById("login-error").textContent = data.detail || `Error ${resp.status}`;
    document.getElementById("login-error").classList.remove("hidden");
    return;
  }
  const data = await resp.json();
  token = data.token;
  localStorage.setItem("cc-admin-token", token);
  document.getElementById("login-overlay").classList.add("hidden");
  renderAll();
}

// Navigation
function switchTab(name) {
  destroyUsageCharts();
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
  document.querySelector(`.nav-item[data-tab="${name}"]`).classList.add("active");
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  renderTab(name);
}

// Render by tab
function renderAll() {
  applyLang();
  applyTheme();
  const active = document.querySelector(".nav-item.active");
  if (active) renderTab(active.dataset.tab);
}

function renderTab(name) {
  if (name === "dashboard") renderDashboard();
  else if (name === "config") renderConfig();
  else if (name === "playground") renderPlayground();
  else if (name === "usage") renderUsage();
  else if (name === "keys") renderKeys();
  else if (name === "logs") renderLogs();
}

// Dashboard
async function renderDashboard() {
  const el = document.getElementById("tab-dashboard");
  el.innerHTML = `
    <h2 data-i18n="dashboard">${t("dashboard")}</h2>
    <div class="card-grid" style="margin-top:16px">
      <div class="card">
        <div class="status-dot" id="health-dot"></div>
        <strong data-i18n="serverStatus">${t("serverStatus")}</strong>
        <p id="health-text" style="margin-top:8px;font-size:13px;color:var(--text-secondary)">Loading...</p>
      </div>
      <div class="card">
        <div class="status-dot" id="key-dot"></div>
        <strong data-i18n="apiKey">${t("apiKey")}</strong>
        <p id="key-text" style="margin-top:8px;font-size:13px;color:var(--text-secondary)">Loading...</p>
        <button class="btn btn-secondary" id="verify-key-btn" style="margin-top:12px">${t("verify")}</button>
      </div>
    </div>`;
  loadDashboard();
  document.getElementById("verify-key-btn").onclick = verifyKey;
  renderHeatmap();
  renderUsageSection();
}

function renderHeatmap() {
  const container = document.getElementById("tab-dashboard");
  const section = document.createElement("div");
  section.className = "token-heatmap";
  section.id = "heatmap-section";
  section.innerHTML = `
    <h3>Token Heatmap (${t("pastYear")})</h3>
    <div id="heatmap-content"><div class="heatmap-empty">Loading...</div></div>`;
  container.appendChild(section);
  loadHeatmap();
}

async function loadHeatmap() {
  const content = document.getElementById("heatmap-content");
  if (!content) return;
  try {
    const resp = await api("GET", "/admin/api/token-usage?days=365");
    const data = await resp.json();
    if (!data || Object.keys(data).length === 0) {
      content.innerHTML = '<div class="heatmap-empty">No token usage data yet</div>';
      return;
    }
    content.innerHTML = "";
    content.appendChild(buildHeatmap(data));
  } catch {
    content.innerHTML = '<div class="heatmap-empty">Failed to load</div>';
  }
}

function buildHeatmap(data) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const endDate = new Date(today);
  const startDate = new Date(today);
  startDate.setDate(startDate.getDate() - 365 + 1);

  // Normalize to start on Sunday
  const dayOfWeek = startDate.getDay();
  if (dayOfWeek !== 0) {
    startDate.setDate(startDate.getDate() - dayOfWeek);
  }

  const values = [];
  let maxTokens = 1;
  for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
    const key = d.toISOString().slice(0, 10);
    const entry = data[key];
    const tokens = entry ? entry.tokens : 0;
    values.push({date: key, tokens: tokens, requests: entry ? entry.requests : 0});
    if (tokens > maxTokens) maxTokens = tokens;
  }

  // Compute quantile thresholds for 5 levels
  const nonZero = values.filter(v => v.tokens > 0).map(v => v.tokens).sort((a, b) => a - b);
  let thresholds = [0, 0, 0, 0, 0];
  if (nonZero.length > 0) {
    const step = Math.max(1, Math.floor(nonZero.length / 5));
    for (let i = 0; i < 5; i++) {
      const idx = Math.min(nonZero.length - 1, i * step);
      thresholds[i] = nonZero[idx];
    }
  }

  function level(tokens) {
    if (tokens <= thresholds[0]) return 0;
    for (let i = 4; i >= 0; i--) {
      if (tokens >= thresholds[i]) return i;
    }
    return 1;
  }

  // Build columns: one per week
  const columns = [];
  for (let i = 0; i < values.length; i += 7) {
    columns.push(values.slice(i, i + 7));
  }

  // Month labels
  const months = [];
  let lastMonth = -1;
  for (let ci = 0; ci < columns.length; ci++) {
    const d = new Date(columns[ci][0].date + "T00:00:00");
    const m = d.getMonth();
    if (m !== lastMonth) {
      months.push({index: ci, label: d.toLocaleDateString("en", {month: "short"})});
      lastMonth = m;
    }
  }

  const weekDays = ["", "Mon", "", "Wed", "", "Fri", ""];

  const wrapper = document.createElement("div");

  // Month labels row
  const monthRow = document.createElement("div");
  monthRow.className = "heatmap-month-labels";
  const totalWidth = columns.length * 17; // 14px cell + 3px gap
  monthRow.style.width = totalWidth + "px";
  months.forEach((m, i) => {
    const label = document.createElement("span");
    label.className = "heatmap-month-label";
    const start = m.index * 17;
    label.style.position = "absolute";
    label.style.left = (start + 24) + "px";
    label.textContent = m.label;
    monthRow.appendChild(label);
  });
  monthRow.style.position = "relative";
  monthRow.style.height = "16px";
  wrapper.appendChild(monthRow);

  // Body: week labels + grid
  const body = document.createElement("div");
  body.className = "heatmap-body";

  // Week day labels
  const weekLabels = document.createElement("div");
  weekLabels.className = "heatmap-week-labels";
  weekDays.forEach(day => {
    const wl = document.createElement("span");
    wl.className = "heatmap-week-label";
    wl.textContent = day;
    weekLabels.appendChild(wl);
  });
  body.appendChild(weekLabels);

  // Grid
  const grid = document.createElement("div");
  grid.className = "heatmap-grid";

  // ponytail: sync month labels scroll with grid
  grid.onscroll = () => { monthRow.scrollLeft = grid.scrollLeft; };
  monthRow.onscroll = () => { grid.scrollLeft = monthRow.scrollLeft; };

  let tid = "heatmap-tooltip";
  let tooltipEl = document.getElementById(tid);
  if (!tooltipEl) {
    tooltipEl = document.createElement("div");
    tooltipEl.id = tid;
    tooltipEl.className = "heatmap-tooltip";
    tooltipEl.style.display = "none";
    document.body.appendChild(tooltipEl);
  }

  function showTooltip(e, date, tokens, requests) {
    tooltipEl.innerHTML = `<div class="date">${date}</div><div class="tokens">${tokens.toLocaleString()} tokens</div><div>${requests} requests</div>`;
    tooltipEl.style.display = "block";
    const rect = e.target.getBoundingClientRect();
    tooltipEl.style.position = "fixed";
    tooltipEl.style.left = Math.min(rect.left + 12, window.innerWidth - 160) + "px";
    tooltipEl.style.top = (rect.top - 44) + "px";
  }

  function onDocClick() { tooltipEl.style.display = "none"; }
  document.removeEventListener("click", onDocClick, true);
  document.addEventListener("click", onDocClick, true);

  columns.forEach((col, ci) => {
    const colDiv = document.createElement("div");
    colDiv.className = "heatmap-column";
    col.forEach(cell => {
      const cel = document.createElement("div");
      cel.className = "heatmap-cell l" + level(cell.tokens);
      cel.onmouseenter = (e) => showTooltip(e, cell.date, cell.tokens, cell.requests);
      cel.onmouseleave = () => { tooltipEl.style.display = "none"; };
      cel.onclick = () => {
        document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
        const usageTab = document.querySelector('.nav-item[data-tab="usage"]');
        if (usageTab) usageTab.click();
        const startInput = document.getElementById("usage-start");
        const endInput = document.getElementById("usage-end");
        if (startInput && endInput) {
          startInput.value = cell.date;
          endInput.value = cell.date;
          if (typeof loadUsageAnalyticsData === "function") loadUsageAnalyticsData();
        }
      };
      colDiv.appendChild(cel);
    });
    grid.appendChild(colDiv);
  });
  body.appendChild(grid);
  wrapper.appendChild(body);

  // Legend
  const legend = document.createElement("div");
  legend.className = "heatmap-legend";
  legend.innerHTML = '<span class="heatmap-legend-label">Less</span>';
  for (let l = 0; l <= 4; l++) {
    const legendCell = document.createElement("span");
    legendCell.className = "heatmap-legend-cell l" + l;
    legend.appendChild(legendCell);
  }
  legend.innerHTML += '<span class="heatmap-legend-label">More</span>';
  wrapper.appendChild(legend);

  return wrapper;
}

async function loadDashboard() {
  try {
    const resp = await api("GET", "/admin/api/health");
    const data = await resp.json();
    // ponytail: show version in topbar
    document.querySelector(".logo").textContent = "CC Adapter v" + data.version;
    document.getElementById("health-dot").className = "status-dot ok";
    document.getElementById("health-text").textContent =
      `${t("running")} | ${fmtUptime(data.uptime)}`;
    document.getElementById("key-dot").className =
      data.cc_api_key_configured ? "status-dot ok" : "status-dot err";
    document.getElementById("key-text").textContent =
      data.cc_api_key_configured ? t("configured") : t("notConfigured");
  } catch {
    document.getElementById("health-dot").className = "status-dot err";
    document.getElementById("health-text").textContent = t("stopped");
    document.querySelector(".logo").textContent = "CC Adapter";
  }
}

async function verifyKey() {
  const btn = document.getElementById("verify-key-btn");
  btn.textContent = t("verifying");
  btn.disabled = true;
  try {
    const resp = await api("POST", "/admin/api/verify-key");
    const data = await resp.json();
    showToast(data.valid ? `${t("apiKey")}: ${t("valid")}` : `${t("apiKey")}: ${t("invalid")} - ${data.message}`,
      data.valid ? "success" : "error");
    loadDashboard();
  } catch { showToast(t("saveFailed"), "error"); }
  btn.textContent = t("verify");
  btn.disabled = false;
}

// Token Usage
function renderUsageSection() {
  const container = document.getElementById("tab-dashboard");
  const section = document.createElement("div");
  section.className = "token-usage-section";
  section.innerHTML = `
    <div class="token-usage-header">
      <h3>${t("tokenUsage")}</h3>
      <div class="token-actions">
        <button class="btn btn-secondary" id="usage-manage-btn">${t("manage")}</button>
        <button class="btn btn-primary" id="usage-refresh-btn">${t("refresh")}</button>
      </div>
    </div>
    <div id="usage-cards-container">
      <div class="token-empty">Loading...</div>
    </div>`;
  container.appendChild(section);
  document.getElementById("usage-refresh-btn").onclick = loadTokenUsageData;
  document.getElementById("usage-manage-btn").onclick = showTokenManager;
  loadTokenUsageData();
}

async function loadTokenUsageData() {
  const container = document.getElementById("usage-cards-container");
  if (!container) return;
  container.innerHTML = '<div class="token-empty">Loading...</div>';
  try {
    const resp = await api("POST", "/admin/api/usage/query");
    const data = await resp.json();
    if (!data || data.length === 0) {
      container.innerHTML = `<div class="token-empty">${t("noTokens")}</div>`;
      return;
    }
    container.innerHTML = "";
    for (const item of data) {
      container.appendChild(renderTokenCard(item));
    }
  } catch {
    container.innerHTML = `<div class="token-empty">Error loading usage data</div>`;
  }
}

function renderTokenCard(item) {
  const card = document.createElement("div");
  card.className = "token-card" + (item.ok ? "" : " error");
  const labelKey = localStorage.getItem("cc-token-label-" + item.token) || item.label || "";

  if (item.ok) {
    const usage = item.usage || { total_cost: 0, total_count: 0, models: [] };
    const credits = item.credits || { total: 0, monthly: 0, purchased: 0, free: 0 };
    const sub = item.subscription || { plan_name: "", status: "", period_start: "", period_end: "" };
    const user = item.user || { name: "", email: "" };
    const totalLimit = usage.total_cost + credits.total;
    const pct = totalLimit > 0 ? Math.min(100, Math.round((usage.total_cost / totalLimit) * 100)) : 0;
    let barClass = "token-usage-bar-fill";
    if (pct >= 90) barClass += " danger";
    else if (pct >= 75) barClass += " warning";
    const periodStr = sub.period_start ? `${sub.period_start.slice(0, 10)} ~ ${sub.period_end.slice(0, 10)}` : "";
    card.innerHTML = `
      <div class="token-card-header">
        <div>
          <span class="status-dot ok"></span>
          <strong title="${item.token}">${item.token.slice(0, 10)}...${item.token.slice(-6)}</strong>
          ${labelKey ? `<span class="token-label-badge">${labelKey}</span>` : ""}
        </div>
        <span style="font-size:12px;color:var(--success)">${t("tokenNormal")}</span>
      </div>
      <div class="token-card-info">
        ${user.name ? `<div><div class="label">${t("tokenAccount")}</div><div class="value">${user.name}</div></div>` : ""}
        ${sub.plan_name ? `<div><div class="label">${t("tokenPlan")}</div><div class="value">${sub.plan_name} <span style="color:var(--text-muted);font-size:11px">(${sub.status})</span></div></div>` : ""}
        ${user.email ? `<div><div class="label">Email</div><div class="value">${user.email}</div></div>` : ""}
        ${periodStr ? `<div><div class="label">${t("tokenPeriod")}</div><div class="value">${periodStr}</div></div>` : ""}
      </div>
      <div class="token-usage-bar">
        <div class="token-usage-bar-header">
          <span>${t("tokenUsed")} / ${t("tokenTotal")}</span>
          <span><strong>$${usage.total_cost.toFixed(2)}</strong> / $${totalLimit.toFixed(2)}</span>
        </div>
        <div class="token-usage-bar-track">
          <div class="${barClass}" style="width:${pct}%"></div>
        </div>
      </div>
      `;
      if (usage.fiveHour || usage.weekly) {
        let limitHtml = '<div class="token-limits">';
        if (usage.limited) {
          limitHtml += `<div class="token-limit-alert">&#9888; ${t("tokenLimitRestricted")}</div>`;
        }
        if (usage.fiveHour?.cap) {
          const fiveHrUsed = Number(usage.fiveHour.used) || 0;
          const fiveHrCap = Number(usage.fiveHour.cap) || 0;
          const fiveHrPct = fiveHrCap > 0 ? Math.min(100, Math.round((fiveHrUsed / fiveHrCap) * 100)) : 0;
          const fiveHrReset = fmtResetTime(usage.fiveHour.resetAt);
          limitHtml += `<div class="token-limit-row">
            <span class="token-limit-label">${t("tokenLimit5h")}</span>
            <span class="token-limit-value">${fiveHrUsed}/${fiveHrCap}</span>
            ${fiveHrReset ? `<span class="token-limit-reset">${t("tokenLimitReset")} ${fiveHrReset}</span>` : ""}
            <div class="token-limit-bar-track"><div class="token-limit-bar-fill" style="width:${fiveHrPct}%"></div></div>
          </div>`;
        }
        if (usage.weekly?.cap) {
          const weeklyUsed = Number(usage.weekly.used) || 0;
          const weeklyCap = Number(usage.weekly.cap) || 0;
          const weeklyPct = weeklyCap > 0 ? Math.min(100, Math.round((weeklyUsed / weeklyCap) * 100)) : 0;
          const weeklyReset = fmtResetTime(usage.weekly.resetAt);
          limitHtml += `<div class="token-limit-row">
            <span class="token-limit-label">${t("tokenLimitWeekly")}</span>
            <span class="token-limit-value">${weeklyUsed}/${weeklyCap}</span>
            ${weeklyReset ? `<span class="token-limit-reset">${t("tokenLimitReset")} ${weeklyReset}</span>` : ""}
            <div class="token-limit-bar-track"><div class="token-limit-bar-fill" style="width:${weeklyPct}%"></div></div>
          </div>`;
        }
        limitHtml += '</div>';
        const usageBar = card.querySelector('.token-usage-bar');
        if (usageBar) {
          usageBar.insertAdjacentHTML('afterend', limitHtml);
        }
      }
  } else {
    const errMsg = item.error || "Unknown error";
    card.innerHTML = `
      <div class="token-card-header">
        <div>
          <span class="status-dot err"></span>
          <strong title="${item.token}">${item.token.slice(0, 10)}...${item.token.slice(-6)}</strong>
          ${labelKey ? `<span class="token-label-badge">${labelKey}</span>` : ""}
        </div>
        <span style="font-size:12px;color:var(--error)">${t("tokenInvalid")}</span>
      </div>
      <div class="token-error-text">${errMsg}</div>`;
  }
  return card;
}

function showTokenManager() {
  const overlay = document.createElement("div");
  overlay.id = "token-manager-overlay";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:300;";
  overlay.innerHTML = `
    <div class="card" style="width:520px;max-width:90vw;max-height:80vh;overflow-y:auto;">
      <h3 style="margin-bottom:16px">${t("tokenManageTitle")}</h3>
      <div style="margin-bottom:12px;display:flex;gap:8px;">
        <input id="tm-label" placeholder="${t("tokenLabel")}" style="width:100px;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);font-size:13px;">
        <input id="tm-key" placeholder="${t("tokenKey")}" style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);font-size:13px;font-family:monospace;">
        <button id="tm-add" class="btn btn-primary" style="padding:6px 14px;font-size:13px;">${t("addToken")}</button>
      </div>
      <div class="key-hint" style="margin-bottom:8px;">${t("tokenManagerHint")}</div>
      <div id="tm-list"></div>
      <div class="form-actions" style="margin-top:16px;">
        <button id="tm-save" class="btn btn-primary">${t("tokenSave")}</button>
        <button class="btn btn-secondary" onclick="this.closest('#token-manager-overlay').remove()">${t("tokenCancel")}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const listEl = overlay.querySelector("#tm-list");

  document.getElementById("tm-add").onclick = () => {
    const keyInput = document.getElementById("tm-key");
    const labelInput = document.getElementById("tm-label");
    const keyVal = keyInput.value.trim();
    if (!keyVal) return;
    const row = document.createElement("div");
    // Full key stays on the row; only the masked form is rendered (and it must never be read back)
    row.dataset.key = keyVal;
    row.style.cssText = "display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border);";
    row.innerHTML = `
      <input class="tm-item-label" placeholder="${t("tokenLabel")}" style="width:80px;padding:4px 6px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--text);font-size:12px;">
      <code style="flex:1;font-size:12px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${escapeHtml(keyVal.slice(0, 12) + "..." + keyVal.slice(-8))}</code>
      <button style="color:var(--error);background:none;border:none;cursor:pointer;font-size:16px;" onclick="this.parentElement.remove()">&times;</button>`;
    // Set the label via DOM property so operator input is never interpolated into markup
    row.querySelector(".tm-item-label").value = labelInput.value.trim();
    listEl.appendChild(row);
    keyInput.value = "";
    labelInput.value = "";
  };

  document.getElementById("tm-save").onclick = async () => {
    const tokens = [];
    // Build the token list from the stored full keys, never from the masked row text
    for (const row of listEl.children) {
      const keyVal = row.dataset.key;
      if (!keyVal) continue;
      tokens.push(keyVal);
      const labelInput = row.querySelector(".tm-item-label");
      if (labelInput && labelInput.value) {
        localStorage.setItem("cc-token-label-" + keyVal, labelInput.value);
      }
    }
    if (tokens.length === 0) {
      showToast(t("tokenManagerEmpty"), "error");
      return;
    }
    // Additive only: the dialog adds keys to the pool, it never rewrites the list, so
    // keys configured in the Keys tab (or removed from it) cannot be lost here.
    let added = 0;
    let existing = 0;
    let failed = 0;
    for (const token of tokens) {
      try {
        const resp = await api("POST", "/admin/api/keys", { key: token });
        if (resp.ok) added += 1;
        else if (resp.status === 409) existing += 1;
        else failed += 1;
      } catch {
        failed += 1;
      }
    }
    const message = t("tokenManagerResult")
      .replace("{added}", added)
      .replace("{existing}", existing)
      .replace("{failed}", failed);
    showToast(message, failed > 0 ? "error" : "success");
    overlay.remove();
    loadTokenUsageData();
  };
}

// Config
let configData = null;

async function renderConfig() {
  const el = document.getElementById("tab-config");
  el.innerHTML = `
    <h2 data-i18n="config">${t("config")}</h2>
    <div id="cfg-form-view">
      <div class="card">
        <div class="form-group">
          <label>CC_ADAPTER_CC_API_KEY</label>
          <div class="cfg-key-status">
            <span id="cfg-key-count">—</span>
            <span class="cfg-key-hint">${t("keysManagedInTab")}</span>
          </div>
          <button type="button" class="btn btn-secondary" id="cfg-manage-keys">${t("keysManageButton")}</button>
        </div>
        <div class="form-group">
          <label>CC_ADAPTER_CC_BASE_URL</label>
          <input type="text" id="cfg-base-url">
        </div>
        <div class="form-group">
          <label>CC_ADAPTER_HOST</label>
          <input type="text" id="cfg-host">
        </div>
        <div class="form-group">
          <label>CC_ADAPTER_PORT</label>
          <input type="number" id="cfg-port">
        </div>
        <div class="form-group">
          <label>CC_ADAPTER_LOG_LEVEL</label>
          <select id="cfg-log-level">
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
        </div>
        <div class="form-group">
          <label>CC_ADAPTER_DEFAULT_MODEL</label>
          <input type="text" id="cfg-default-model">
        </div>
        <div class="form-actions">
          <button class="btn btn-primary" id="cfg-save">${t("save")}</button>
          <button class="btn btn-secondary" id="cfg-cancel">${t("cancel")}</button>
        </div>
      </div>
    </div>`;
  loadConfig();
  document.getElementById("cfg-save").onclick = saveConfig;
  document.getElementById("cfg-cancel").onclick = loadConfig;
  // Upstream keys live in the Keys tab; the config form only reports how many are set.
  document.getElementById("cfg-manage-keys").onclick = () => switchTab("keys");

  // Append reasoning-effort info card
  try {
    const reResp = await api("GET", "/admin/api/reasoning-effort");
    const reData = await reResp.json();
    const reCard = document.createElement("div");
    reCard.className = "card";
    reCard.style.marginTop = "16px";
    reCard.innerHTML = `
      <details style="cursor:pointer;">
        <summary style="font-weight:600;font-size:14px;padding:12px 0;">
          Model Reasoning Efforts
        </summary>
        <div style="margin-top:8px;font-size:13px;color:var(--text-secondary);">
          <p>${escapeHtml(reData.description)}</p>
          <table style="margin-top:8px;width:100%;border-collapse:collapse;font-size:12px;">
            <thead><tr style="border-bottom:1px solid var(--border);">
              <th style="padding:4px 8px;text-align:left;">Model</th>
              <th style="padding:4px 8px;text-align:left;">Supported Efforts</th>
            </tr></thead>
            <tbody>${Object.entries(reData.model_reasoning_efforts).map(function(e) {
              return '<tr style="border-bottom:1px solid var(--border);"><td style="padding:4px 8px;"><code>' + escapeHtml(e[0]) + '</code></td><td style="padding:4px 8px;">' + escapeHtml(e[1].join(', ')) + '</td></tr>';
            }).join('')}</tbody>
          </table>
        </div>
      </details>`;
    el.appendChild(reCard);
  } catch (e) {
    console.error("Failed to load reasoning-effort config:", e);
  }
}

async function loadConfig() {
  try {
    const resp = await api("GET", "/admin/api/config");
    configData = await resp.json();
    // Keys are managed in the Keys tab: show the count instead of an editable field.
    const keyCount = typeof configData.cc_api_key_count === "number" ? configData.cc_api_key_count : 0;
    document.getElementById("cfg-key-count").textContent = t("keysConfigured").replace("{n}", keyCount);
    document.getElementById("cfg-base-url").value = configData.cc_base_url;
    document.getElementById("cfg-host").value = configData.host;
    document.getElementById("cfg-port").value = configData.port;
    document.getElementById("cfg-log-level").value = configData.log_level;
    document.getElementById("cfg-default-model").value = configData.default_model;
  } catch { showToast(t("saveFailed"), "error"); }
}

async function saveConfig() {
  const body = {};
  const baseUrl = document.getElementById("cfg-base-url").value;
  if (baseUrl !== configData.cc_base_url) body.cc_base_url = baseUrl;
  const host = document.getElementById("cfg-host").value;
  if (host !== configData.host) body.host = host;
  const port = parseInt(document.getElementById("cfg-port").value);
  if (port !== configData.port) body.port = port;
  const logLevel = document.getElementById("cfg-log-level").value;
  if (logLevel !== configData.log_level) body.log_level = logLevel;
  const defaultModelVal = document.getElementById("cfg-default-model").value;
  if (defaultModelVal !== configData.default_model) body.default_model = defaultModelVal;
  if (Object.keys(body).length === 0) { showToast("No changes", "success"); return; }
  try {
    const resp = await api("PUT", "/admin/api/config", body);
    if (!resp.ok) throw new Error(await resp.text());
    configData = await resp.json();
    showToast(t("saved"), "success");
  } catch { showToast(t("saveFailed"), "error"); }
}

// Playground — Chat UI
async function renderPlayground() {
  let defaultModelVal = defaultModel;
  try {
    const [uiResp, modelsResp] = await Promise.all([
      fetch("/admin/api/ui-config"),
      fetch("/admin/api/models"),
    ]);
    const uiCfg = await uiResp.json();
    if (uiCfg.default_model) defaultModelVal = uiCfg.default_model;
    const modelsData = await modelsResp.json();
    const modelOptions = modelsData.models
      .map(m => `<option value="${m.id}"${m.id === defaultModelVal ? " selected" : ""}>${m.name}</option>`)
      .join("");
    window._modelSelectHtml = modelOptions;
  } catch {}
  if (!window._modelSelectHtml) {
    window._modelSelectHtml = `<option value="${defaultModelVal}">${defaultModelVal}</option>`;
  }

  const el = document.getElementById("tab-playground");
  el.innerHTML = `
    <div class="chat-container">
      <div class="chat-model-bar">
        <select id="pg-model-select">${window._modelSelectHtml}</select>
        <select id="pg-reasoning-select" style="max-width:120px;padding:6px 10px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--text);font-size:13px">
          <option value="">${t("thinkingOff")}</option>
        </select>
        <button class="btn btn-secondary" id="pg-clear">${t("clear")}</button>
      </div>
      <div class="chat-messages" id="pg-chat"></div>
      <div class="chat-input-area">
        <textarea id="pg-input" placeholder="输入消息..." rows="1">你好，请介绍一下你自己</textarea>
        <button class="btn btn-primary" id="pg-send">${t("send")}</button>
      </div>
    </div>`;

  document.getElementById("pg-send").onclick = sendChatMessage;
  document.getElementById("pg-clear").onclick = clearChat;

  const modelSelect = document.getElementById("pg-model-select");
  const reasoningSelect = document.getElementById("pg-reasoning-select");
  modelSelect.onchange = async () => {
    await updateReasoningDropdown(modelSelect.value, reasoningSelect);
  };
  await updateReasoningDropdown(modelSelect.value, reasoningSelect);

  const textarea = document.getElementById("pg-input");
  textarea.oninput = () => {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + "px";
  };
  textarea.onkeydown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  };

  pgMessages = [];
}

function clearChat() {
  pgMessages = [];
  const chatEl = document.getElementById("pg-chat");
  if (chatEl) chatEl.innerHTML = "";
}

async function updateReasoningDropdown(modelId, selectEl) {
  selectEl.innerHTML = `<option value="">${t("thinkingOff")}</option>`;
  try {
    const resp = await fetch("/admin/api/reasoning-effort");
    if (resp.ok) {
      const data = await resp.json();
      const efforts = data.model_reasoning_efforts?.[modelId];
      if (efforts && efforts.length > 0) {
        for (const e of efforts) {
          selectEl.innerHTML += `<option value="${e}">${e}</option>`;
        }
      }
    }
  } catch {}
}

function appendBubble(role, text, streaming) {
  const chatEl = document.getElementById("pg-chat");
  if (!chatEl) return null;
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}` + (streaming ? " streaming" : "");
  if (text) {
    bubble.textContent = text;
  } else if (streaming) {
    bubble.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div>';
  }
  chatEl.appendChild(bubble);
  chatEl.scrollTop = chatEl.scrollHeight;
  return bubble;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

async function sendChatMessage() {
  if (pgStreaming) return;
  const input = document.getElementById("pg-input");
  const text = input.value.trim();
  if (!text) return;

  const model = document.getElementById("pg-model-select").value;
  const chatEl = document.getElementById("pg-chat");

  pgMessages.push({ role: "user", content: text });
  appendBubble("user", text);
  input.value = "";
  input.style.height = "auto";
  chatEl.scrollTop = chatEl.scrollHeight;

  pgStreaming = true;
  const sendBtn = document.getElementById("pg-send");
  sendBtn.disabled = true;
  sendBtn.textContent = "...";

  const assistantBubble = appendBubble("assistant", "", true);
  let accumulatedContent = "";
  let reasoningContent = "";
  let streamEndedWithError = null;
  let requestError = null;

  try {
    const reasoningValue = document.getElementById("pg-reasoning-select")?.value;
    const body = { model, messages: pgMessages, stream: true };
    if (reasoningValue) {
      body.reasoning_effort = reasoningValue;
    }

    const response = await fetch("/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { "Authorization": `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      requestError = (err.error && err.error.message) || `HTTP ${response.status}`;
    } else {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ") || line === "data: [DONE]") continue;
          try {
            const data = JSON.parse(line.slice(6));

            if (data.error) {
              streamEndedWithError = data.error;
              break;
            }

            const delta = data.choices?.[0]?.delta || {};
            const finishReason = data.choices?.[0]?.finish_reason;
            const contentDelta = delta.content || "";
            const reasoningDelta = delta.reasoning_content || "";

            if (contentDelta) accumulatedContent += contentDelta;
            if (reasoningDelta) reasoningContent += reasoningDelta;

            let html = "";
            if (reasoningContent) {
              html += `<div class="reasoning">${escapeHtml(reasoningContent)}</div>`;
            }
            if (accumulatedContent) {
              html += `<div>${escapeHtml(accumulatedContent)}</div>`;
            }
            if (!accumulatedContent && !reasoningContent && !finishReason) {
              html = '<div class="thinking-dots"><span></span><span></span><span></span></div>';
            }
            assistantBubble.innerHTML = html;
            chatEl.scrollTop = chatEl.scrollHeight;
          } catch {}
        }
        if (streamEndedWithError) break;
      }
    }
  } catch (e) {
    requestError = `Network error: ${e.message}`;
  } finally {
    if (requestError) {
      assistantBubble.innerHTML = `<div class="error">Error: ${escapeHtml(requestError)}</div>`;
      assistantBubble.classList.add("error");
    } else if (streamEndedWithError) {
      const errMsg = streamEndedWithError.message || "Upstream model returned an empty response";
      assistantBubble.innerHTML = `<div class="error">Error: ${escapeHtml(errMsg)}</div>`;
      assistantBubble.classList.add("error");
    } else if (!accumulatedContent && !reasoningContent) {
      assistantBubble.innerHTML = `<div class="error">Error: Upstream model returned an empty response</div>`;
      assistantBubble.classList.add("error");
    } else {
      pgMessages.push({ role: "assistant", content: accumulatedContent, reasoning_content: reasoningContent || undefined });
    }
    assistantBubble.classList.remove("streaming");
    pgStreaming = false;
    sendBtn.disabled = false;
    sendBtn.textContent = t("send");
  }
}

let usageCharts = {};

function destroyUsageCharts() {
  Object.values(usageCharts).forEach(c => { if (c) c.destroy(); });
  usageCharts = {};
}

async function renderUsage() {
  const el = document.getElementById("tab-usage");
  destroyUsageCharts();

  const today = new Date().toISOString().slice(0, 10);
  const sevenDaysAgo = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10);

  el.innerHTML = `
    <div class="usage-header">
      <h2>${t("usage")}</h2>
    </div>
    <div class="usage-range-selector" style="margin-bottom:16px">
      <button class="usage-range-btn" data-range="1">${t("usageRange1d")}</button>
      <button class="usage-range-btn active" data-range="7">${t("usageRange7d")}</button>
      <button class="usage-range-btn" data-range="30">${t("usageRange30d")}</button>
      <input type="date" id="usage-start" value="${sevenDaysAgo}" style="padding:5px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);font-size:13px;">
      <span style="color:var(--text-muted)">~</span>
      <input type="date" id="usage-end" value="${today}" style="padding:5px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg);color:var(--text);font-size:13px;">
    </div>
    <div id="usage-content">
      <div style="text-align:center;padding:48px;color:var(--text-muted)">${t("usageLoading")}</div>
    </div>`;

  document.querySelectorAll(".usage-range-btn").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".usage-range-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const days = parseInt(btn.dataset.range);
      const end = new Date();
      const start = new Date(end.getTime() - (days - 1) * 86400000);
      document.getElementById("usage-start").value = start.toISOString().slice(0, 10);
      document.getElementById("usage-end").value = end.toISOString().slice(0, 10);
      loadUsageAnalyticsData();
    };
  });

  document.getElementById("usage-start").onchange = loadUsageAnalyticsData;
  document.getElementById("usage-end").onchange = loadUsageAnalyticsData;

  loadUsageAnalyticsData();
}

async function loadUsageAnalyticsData() {
  const container = document.getElementById("usage-content");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:48px;color:var(--text-muted)">${t("usageLoading")}</div>`;

  const startDate = document.getElementById("usage-start").value;
  const endDate = document.getElementById("usage-end").value;

  try {
    const resp = await api("POST", "/admin/api/usage/daily", { start_date: startDate, end_date: endDate });
    const data = await resp.json();

    if (!data.daily || data.daily.length === 0) {
      container.innerHTML = `<div style="text-align:center;padding:48px;color:var(--text-muted)">${t("usageNoData")}</div>`;
      return;
    }

    const totals = data.totals;
    const activeModels = totals.models.filter(m => m.cost > 0);
    container.innerHTML = `
      <div class="usage-summary-grid">
        <div class="usage-summary-card">
          <div class="value">$${totals.total_cost.toFixed(2)}</div>
          <div class="label">${t("usageTotalCost")}</div>
        </div>
        <div class="usage-summary-card">
          <div class="value">${totals.total_count.toLocaleString()}</div>
          <div class="label">${t("usageTotalRequests")}</div>
        </div>
        <div class="usage-summary-card">
          <div class="value">${activeModels.length}</div>
          <div class="label">${t("usageTotalModels")}</div>
        </div>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px">
        <div class="usage-chart-container">
          <canvas id="chart-daily-trend"></canvas>
        </div>
        <div class="usage-chart-container">
          <canvas id="chart-by-model"></canvas>
        </div>
      </div>
      <div class="card">
        <table class="usage-daily-table">
          <thead><tr>
            <th>${t("usageDate")}</th>
            <th>${t("usageCost")}</th>
            <th>${t("usageRequests")}</th>
            <th>${t("usageModels")}</th>
          </tr></thead>
          <tbody>${[...data.daily].reverse().map(d => {
            const modelsHtml = (d.models || []).map(m => `<span class="usage-model-badge">${m.model_id.split("/").pop()} $${m.cost.toFixed(2)}</span>`).join("");
            return `<tr><td>${d.date.slice(5)}</td><td>$${d.total_cost.toFixed(2)}</td><td>${d.total_count}</td><td>${modelsHtml || "-"}</td></tr>`;
          }).join("")}</tbody>
        </table>
      </div>`;

    const ctx1 = document.getElementById("chart-daily-trend").getContext("2d");
    usageCharts.dailyTrend = new Chart(ctx1, {
      type: "line",
      data: {
        labels: data.daily.map(d => d.date.slice(5)),
        datasets: [{
          label: t("usageCost"),
          data: data.daily.map(d => d.total_cost),
          borderColor: "#3b82f6",
          backgroundColor: "rgba(59, 130, 246, 0.1)",
          fill: true,
          tension: 0.3,
          pointRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: { legend: { display: false }, title: { display: true, text: t("usageDailyTrend"), color: getComputedStyle(document.documentElement).getPropertyValue("--text").trim() } },
        scales: { x: { ticks: { color: getComputedStyle(document.documentElement).getPropertyValue("--text-muted").trim() } }, y: { ticks: { color: getComputedStyle(document.documentElement).getPropertyValue("--text-muted").trim() } } },
      },
    });

    const ctx2 = document.getElementById("chart-by-model").getContext("2d");
    const modelColors = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];
    usageCharts.byModel = new Chart(ctx2, {
      type: "bar",
      data: {
        labels: activeModels.map(m => m.model_id.split("/").pop()),
        datasets: [{
          label: t("usageCost"),
          data: activeModels.map(m => m.cost),
          backgroundColor: activeModels.map((_, i) => modelColors[i % modelColors.length]),
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        indexAxis: "y",
        plugins: { legend: { display: false }, title: { display: true, text: t("usageByModel"), color: getComputedStyle(document.documentElement).getPropertyValue("--text").trim() } },
        scales: { x: { ticks: { color: getComputedStyle(document.documentElement).getPropertyValue("--text-muted").trim() } }, y: { ticks: { color: getComputedStyle(document.documentElement).getPropertyValue("--text-muted").trim() } } },
      },
    });
  } catch (e) {
    container.innerHTML = `<div style="text-align:center;padding:48px;color:var(--error)">Error: ${escapeHtml(e.message)}</div>`;
  }
}

let logsTimer = null;

async function renderLogs() {
  if (logsTimer) { clearInterval(logsTimer); logsTimer = null; }

  const el = document.getElementById("tab-logs");
  el.innerHTML = `
    <div class="log-viewer">
      <div class="log-toolbar">
        <label class="log-toolbar-label">${t("logLevel")}:</label>
        <select id="log-level">
          <option value="DEBUG">DEBUG</option>
          <option value="INFO" selected>INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <label class="log-toolbar-label">${t("logSearch")}:</label>
        <input id="log-search" type="text" placeholder="keyword...">
        <label class="log-autorefresh-label">
          <input type="checkbox" id="log-autorefresh">
          <span>${t("logAutoRefresh")}</span>
        </label>
        <button class="btn btn-secondary" id="log-refresh-btn">${t("logRefresh")}</button>
      </div>
      <div class="log-entries" id="log-entries">
        <div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">
          ${t("logLoading")}
        </div>
      </div>
      <div class="log-status" id="log-status"></div>
    </div>`;

  const levelSelect = document.getElementById("log-level");
  const searchInput = document.getElementById("log-search");
  const autoRefreshCb = document.getElementById("log-autorefresh");
  const refreshBtn = document.getElementById("log-refresh-btn");

  const fetchLogs = async () => {
    const level = levelSelect.value;
    const search = searchInput.value;
    const url = `/admin/api/logs?level=${encodeURIComponent(level)}&search=${encodeURIComponent(search)}&limit=200`;
    try {
      const resp = await api("GET", url);
      const data = await resp.json();
      renderLogEntries(data.entries, data.total_in_buffer);
    } catch (e) {
      const entriesEl = document.getElementById("log-entries");
      entriesEl.innerHTML = `<div class="log-error">Error: ${e.message}</div>`;
    }
  };

  levelSelect.onchange = fetchLogs;
  let searchDebounce = null;
  searchInput.oninput = () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(fetchLogs, 300);
  };
  refreshBtn.onclick = fetchLogs;

  autoRefreshCb.onchange = () => {
    if (autoRefreshCb.checked) {
      logsTimer = setInterval(fetchLogs, 5000);
    } else {
      clearInterval(logsTimer);
      logsTimer = null;
    }
  };

  await fetchLogs();
}

function renderLogEntries(entries, totalInBuffer) {
  const container = document.getElementById("log-entries");
  const statusEl = document.getElementById("log-status");

  if (!entries || entries.length === 0) {
    container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted)">${t("logNoMatch")}</div>`;
    statusEl.textContent = "";
    return;
  }

  let html = "";
  for (const e of entries) {
    const level = (e.level || "info").toUpperCase();
    const levelLower = level.toLowerCase();
    const ts = (e.timestamp || "").slice(11, 19) || "";
    const event = e.event || "";
    let fields = "";
    const skipKeys = new Set(["timestamp", "level", "event", "logger", "request_id"]);
    for (const [k, v] of Object.entries(e)) {
      if (skipKeys.has(k)) continue;
      if (v === null || v === undefined) continue;
      fields += ` <span class="log-field">${k}=${escapeHtml(String(v))}</span>`;
    }
    if (e.request_id) {
      fields += ` <span class="log-field">req=${escapeHtml(e.request_id.slice(0, 8))}</span>`;
    }
    html += `<div class="log-entry">
      <span class="log-ts">${ts}</span>
      <span class="log-level ${levelLower}">${level}</span>
      <span class="log-event">${escapeHtml(event)}</span>${fields}
    </div>`;
  }

  container.innerHTML = html;
  const statusText = t("logStatus")
    .replace("{shown}", entries.length)
    .replace("{total}", totalInBuffer);
  statusEl.textContent = statusText;
}

// Keys (per-key auth switches)
let keysData = [];

// Server-state field `until` is a monotonic clock value, so remaining time always
// comes from `cooldown_seconds`.
function keySuffix(label) {
  return String(label || "").replace(/^\*+/, "");
}

function formatCooldown(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function formatKeyReason(reason) {
  if (reason === "insufficient_credits") return t("keyReasonCredits");
  if (reason === "rate_limited") return t("keyReasonRateLimited");
  if (reason === "http_401" || reason === "http_403") return t("keyReasonInvalidKey");
  return String(reason);
}

async function readErrorDetail(resp, fallback) {
  const data = await resp.json().catch(() => ({}));
  return data.detail || fallback || `Error ${resp.status}`;
}

async function renderKeys() {
  const el = document.getElementById("tab-keys");
  keysData = [];
  el.innerHTML = `
    <div class="keys-header">
      <h2>${t("keys")}</h2>
      <button class="btn btn-secondary" id="keys-refresh-btn">${t("keysRefresh")}</button>
    </div>
    <div class="card keys-add">
      <div class="keys-add-title">${t("keysAddTitle")}</div>
      <div class="keys-add-row">
        <input type="text" id="keys-add-input" class="keys-add-input" placeholder="${t("keysAddPlaceholder")}" aria-label="${t("keysAddTitle")}" autocomplete="off" spellcheck="false">
        <button class="btn btn-primary" id="keys-add-btn">${t("keysAddButton")}</button>
      </div>
      <div class="keys-add-hint">${t("keysAddHint")}</div>
    </div>
    <div id="keys-list">
      <div class="keys-empty">${t("keysLoading")}</div>
    </div>`;
  document.getElementById("keys-refresh-btn").onclick = loadKeys;
  document.getElementById("keys-add-btn").onclick = addKey;
  document.getElementById("keys-add-input").onkeydown = (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    addKey();
  };
  await loadKeys();
}

async function loadKeys() {
  const container = document.getElementById("keys-list");
  if (!container) return;
  container.innerHTML = `<div class="keys-empty">${t("keysLoading")}</div>`;
  try {
    const resp = await api("GET", "/admin/api/keys");
    if (!resp.ok) throw new Error(await readErrorDetail(resp));
    const data = await resp.json();
    keysData = data.keys || [];
    if (keysData.length === 0) {
      container.innerHTML = `<div class="keys-empty">${t("keysEmpty")}</div>`;
      return;
    }
    container.innerHTML = "";
    for (const item of keysData) container.appendChild(buildKeyRow(item));
  } catch (e) {
    container.innerHTML = `<div class="keys-empty">${escapeHtml(t("keysLoadFailed"))}: ${escapeHtml(e.message)}</div>`;
  }
}

async function addKey() {
  const input = document.getElementById("keys-add-input");
  const btn = document.getElementById("keys-add-btn");
  if (!input || !btn || btn.disabled) return; // in-flight guard
  const value = input.value.trim();
  if (!value) {
    showToast(t("keysAddEmpty"), "error");
    return; // never send an empty key
  }
  btn.disabled = true;
  try {
    const resp = await api("POST", "/admin/api/keys", { key: value });
    if (!resp.ok) throw new Error(await readErrorDetail(resp, t("keysAddFailed")));
    const data = await resp.json();
    input.value = ""; // the full key never stays in the DOM
    showToast(t("keysAddToast").replace("{key}", data.key || "****"), "success");
    // Reload from the server: adding may have flipped the pool from a single
    // (unmanaged) key to a managed pool, which changes what every row shows.
    await loadKeys();
  } catch (e) {
    showToast(e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

function buildKeyRow(item) {
  const state = item.state || "ok";
  const unmanaged = state === "unmanaged";
  const manual = item.manual === true;
  const enabled = item.enabled !== false;
  // A cooling key is parked by the scheduler, so it counts as off even when the
  // operator never touched it; an unmanaged key has no scheduler state to show.
  const on = unmanaged ? enabled : enabled && state !== "cooling";

  let badgeKey = "keyStateOk";
  let badgeClass = "ok";
  let badgeExtra = "";
  if (unmanaged) {
    badgeKey = "keyStateUnmanaged";
    badgeClass = "muted";
  } else if (state === "cooling") {
    badgeKey = "keyStateCooling";
    badgeClass = "warn";
    badgeExtra = formatCooldown(item.cooldown_seconds);
  } else if (!enabled) {
    badgeKey = manual ? "keyStateOff" : "keyStateDisabled";
    badgeClass = "err";
  }
  const badgeText = badgeExtra ? `${t(badgeKey)} ${badgeExtra}` : t(badgeKey);
  const credits = item.credits === null || item.credits === undefined ? t("keyUnknown") : item.credits;
  const reason = item.reason ? formatKeyReason(item.reason) : "";

  const row = document.createElement("div");
  row.className = "card key-row";
  row.dataset.suffix = keySuffix(item.key);
  row.innerHTML = `
    <div class="key-row-info">
      <div class="key-row-head">
        <strong class="key-label">${escapeHtml(item.key || "")}</strong>
        <span class="key-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
        ${reason ? `<span class="key-reason">${escapeHtml(reason)}</span>` : ""}
      </div>
      <div class="key-row-metrics">
        <span>${t("keyCredits")}: <strong>${escapeHtml(String(credits))}</strong></span>
        <span>${t("keySessions")}: <strong>${escapeHtml(String(item.sessions || 0))}</strong></span>
        <span>${t("keyFailures")}: <strong>${escapeHtml(String(item.failures || 0))}</strong></span>
      </div>
      ${unmanaged ? `<div class="key-hint">${t("keyUnmanagedHint")}</div>` : ""}
    </div>
    <div class="key-row-actions">
      <button type="button" class="btn btn-danger btn-sm key-delete">${t("keysDelete")}</button>
      <button type="button" class="switch" role="switch" aria-checked="${on ? "true" : "false"}"></button>
    </div>`;

  const btn = row.querySelector(".switch");
  btn.setAttribute("aria-label", `${t("keysSwitchLabel")} ${item.key || ""}`);
  if (unmanaged) {
    btn.disabled = true;
    btn.title = t("keyUnmanagedHint");
  } else {
    btn.title = on ? t("keysSwitchOff") : t("keysSwitchOn");
    const toggle = () => toggleKey(row.dataset.suffix, !on, row);
    btn.onclick = toggle;
    // Explicit Enter/Space support; preventDefault keeps the native button
    // activation from firing a second toggle, and toggleKey() ignores clicks
    // while a request is in flight.
    btn.onkeydown = (e) => {
      if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
      e.preventDefault();
      toggle();
    };
  }

  // Removal stays available for an unmanaged row: with a single configured key
  // the on/off switch has no scheduler to talk to, but the delete button is the
  // only way to take that key out of the config.
  const del = row.querySelector(".key-delete");
  del.title = t("keysDelete");
  del.setAttribute("aria-label", `${t("keysDelete")} ${item.key || ""}`);
  del.onclick = () => deleteKey(row.dataset.suffix, item.key || "", row);
  return row;
}

async function toggleKey(suffix, turnOn, row) {
  const btn = row.querySelector(".switch");
  if (!btn || btn.disabled) return;
  btn.disabled = true; // in-flight guard
  try {
    const action = turnOn ? "enable" : "disable";
    const resp = await api("POST", `/admin/api/keys/${encodeURIComponent(suffix)}/${action}`);
    if (!resp.ok) throw new Error(await readErrorDetail(resp));
    const data = await resp.json();
    const index = keysData.findIndex(k => keySuffix(k.key) === suffix);
    const merged = Object.assign({}, index >= 0 ? keysData[index] : {}, data);
    if (data.enabled === true) merged.manual = false; // an enabled key is never manually off
    if (index >= 0) keysData[index] = merged;
    else keysData.push(merged);
    row.replaceWith(buildKeyRow(merged)); // refresh just this row from the new state
    const toast = turnOn ? t("keysEnabledToast") : t("keysDisabledToast");
    showToast(toast.replace("{key}", merged.key || suffix), "success");
  } catch (e) {
    // Rebuild from the last known server state so the switch cannot stay out of sync.
    const current = keysData.find(k => keySuffix(k.key) === suffix);
    if (current) row.replaceWith(buildKeyRow(current));
    else btn.disabled = false;
    showToast(e.message, "error");
  }
}

async function deleteKey(suffix, label, row) {
  const btn = row.querySelector(".key-delete");
  if (!btn || btn.disabled) return;
  const name = label || suffix;
  if (!window.confirm(t("keysDeleteConfirm").replace("{key}", name))) return;
  btn.disabled = true; // in-flight guard
  try {
    const resp = await api("DELETE", `/admin/api/keys/${encodeURIComponent(suffix)}`);
    if (!resp.ok) throw new Error(await readErrorDetail(resp, t("keysRemoveFailed")));
    const data = await resp.json();
    showToast(t("keysDeleteToast").replace("{key}", data.key || name), "success");
  } catch (e) {
    showToast(e.message, "error");
  } finally {
    // Reload either way: a removal flips the pool size (managed ⇄ single key)
    // and a rejection (unknown suffix / no scheduler) must not leave the row
    // showing scheduler state the server no longer agrees with.
    await loadKeys();
  }
}

// Init
document.addEventListener("DOMContentLoaded", () => {
  // Theme
  applyTheme();
  document.getElementById("theme-toggle").onclick = toggleTheme;

  // Lang
  document.getElementById("lang-switch").value = lang;
  document.getElementById("lang-switch").onchange = (e) => switchLang(e.target.value);

  // Login
  document.getElementById("login-btn").onclick = doLogin;
  document.getElementById("login-password").onkeydown = (e) => {
    if (e.key === "Enter") doLogin();
  };

  // Nav
  document.querySelectorAll(".nav-item").forEach(el => {
    el.onclick = () => switchTab(el.dataset.tab);
  });

  // Check auth on load
  (async () => {
    const resp = await fetch("/admin/api/health", {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (resp.status === 401) {
      showLogin();
    } else if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      showLogin(data.detail || `Server error (${resp.status})`);
    } else {
      renderAll();
    }
  })();
});
