/* ============================================================
 * data-agent 前端逻辑
 * 职责：
 *   1) 解析 /api/query 的 SSE（POST + ReadableStream 手动解析 data: 事件）
 *   2) 阶段时间线推进、SQL 渲染、结果表格渲染、错误展示、[DONE] 收尾
 *   3) /api/health 探活轮询 + 顶部状态条 + 后端未就绪提示
 *   4) 内置「演示（模拟流式）」：无需任何后端依赖即可预览完整界面效果
 *   5) 实用增强：耗时统计、可中止(AbortController)、历史记录(localStorage)、结果导出
 * ============================================================ */

// 阶段原始字符串 -> 展示文案（原始流里有些阶段带后缀，这里统一美化）
const STAGE_LABELS = {
  "提取关键字---哈哈": "提取关键字",
  "召回列数据": "召回列数据",
  "召回指标数据": "召回指标数据",
  "召回字段取值": "召回字段取值",
  "合并召回信息": "合并召回信息",
  "过滤指标": "过滤指标",
  "过滤表": "过滤表",
  "添加额外上下文": "添加额外上下文",
  "生成SQL": "生成 SQL",
  "校验SQL": "校验 SQL",
  "校正SQL": "校正 SQL",
  "执行SQL": "执行 SQL",
};
// 阶段出现的规范顺序（用于时间线按序插入）
const STAGE_ORDER = Object.keys(STAGE_LABELS);

// DOM 引用
const $ = (id) => document.getElementById(id);
const timelineEl = $("timeline");
const sqlBlock = $("sqlBlock");
const sqlCode = $("sqlCode");
const resultBlock = $("resultBlock");
const resultTable = $("resultTable");
const errorAlert = $("errorAlert");
const errorTitle = $("errorTitle");
const errorMsg = $("errorMsg");
const errorDetail = $("errorDetail");
const errorBody = $("errorBody");
const copyError = $("copyError");
const phaseTag = $("phaseTag");
const queryInput = $("queryInput");
const runBtn = $("runBtn");
const stopBtn = $("stopBtn");
const demoBtn = $("demoBtn");
const clearBtn = $("clearBtn");
const reqHint = $("reqHint");
const healthEl = $("health");
const healthLabel = $("healthLabel");
const runbar = $("runbar");
const elapsedEl = $("elapsed");
const rowCountEl = $("rowCount");
const backendWarn = $("backendWarn");
const historyBox = $("historyBox");
const historyChips = $("historyChips");

// 企业外壳相关 DOM 引用
const userTrigger = $("userTrigger");
const userDropdown = $("userDropdown");
const userAvatar = $("userAvatar");
const userName = $("userName");
const ddAvatar = $("ddAvatar");
const ddName = $("ddName");
const ddEmail = $("ddEmail");
const logoutLink = $("logoutLink");
const navEl = $("nav");
const pageTitle = $("pageTitle");
const statQueries = $("statQueries");
const statLatency = $("statLatency");
const statDeps = $("statDeps");
const statDepsTrend = $("statDepsTrend");
const refreshBtn = $("refreshBtn");

// 系统状态页 / 查询历史页 DOM 引用
const statusRefresh = $("statusRefresh");
const ssIc = $("ssIc");
const ssTitle = $("ssTitle");
const ssSub = $("ssSub");
const ssTime = $("ssTime");
const depList = $("depList");
const historyList = $("historyList");
const clearHistoryBtn = $("clearHistoryBtn");

// 运行状态
let running = false;
let finished = false;
let aborted = false;
let stepEls = new Map(); // rawStage -> <li>
let controller = null;   // AbortController（真实请求可中止）
let timerId = null;      // 耗时计时器
let startTime = 0;
let lastResult = null;   // 最近一次结果（用于导出）
let healthOk = false;    // 后端整体是否可用
let serverElapsedMs = null; // 后端链路累计耗时（SSE 透出），优先作为最终耗时

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowTime = () =>
  new Date().toLocaleTimeString("zh-CN", { hour12: false });

// ---------------- 登录态（与真实鉴权后端联动） ----------------
function getSession() {
  // 读取本地会话（含 token + username），解析失败返回 null
  try {
    return JSON.parse(localStorage.getItem("da_session") || "null");
  } catch (_) {
    return null;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------------- 用户菜单（与真实鉴权后端联动） ---------------- */
function renderUserMenu() {
  const s = getSession();
  const initial = s && s.user ? s.user.slice(0, 1).toUpperCase() : "U";
  [userAvatar, ddAvatar].forEach((el) => { if (el) el.textContent = initial; });
  if (userName) userName.textContent = s && s.user ? s.user : "未登录";
  if (ddName) ddName.textContent = s && s.user ? s.user : "访客";
  if (ddEmail) ddEmail.textContent = s && s.token ? "已登录用户" : "";
}

function bindUserMenu() {
  if (userTrigger && userDropdown) {
    userTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = userDropdown.hidden;
      userDropdown.hidden = !open;
      const menu = $("userMenu");
      if (menu) menu.classList.toggle("open", !open);
    });
  }
  document.addEventListener("click", (e) => {
    if (userDropdown && !userDropdown.hidden) {
      const menu = $("userMenu");
      if (menu && !menu.contains(e.target)) {
        userDropdown.hidden = true;
        menu.classList.remove("open");
      }
    }
  });
  if (logoutLink) {
    logoutLink.addEventListener("click", (e) => {
      e.preventDefault();
      try { localStorage.removeItem("da_session"); } catch (_) {}
      renderUserMenu();
      const menu = $("userMenu");
      if (menu) menu.classList.remove("open");
      if (userDropdown) userDropdown.hidden = true;
    });
  }
}

/* ---------------- 侧边栏导航切换 ---------------- */
function bindNav() {
  if (!navEl) return;
  navEl.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      const page = item.dataset.page;
      navEl.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
      item.classList.add("active");
      document.querySelectorAll(".page").forEach((p) => {
        p.hidden = p.dataset.page !== page;
      });
      if (pageTitle) {
        const label = item.querySelector(".nav-label");
        pageTitle.textContent = label ? label.textContent : "智能问数";
      }
      if (page === "history") renderHistoryPage();
      if (page === "status") refreshHealth();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

/* ---------------- 数据资产页 · 子页签切换 ---------------- */
function bindAssetTabs() {
  const tabsEl = $("assetTabs");
  if (!tabsEl) return;
  const tabs = tabsEl.querySelectorAll(".tab");
  const panels = document.querySelectorAll('.tab-panel[data-tab]');
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      tabs.forEach((t) => t.classList.toggle("active", t === tab));
      panels.forEach((p) => {
        p.hidden = p.dataset.tab !== name;
      });
    });
  });
}

/* ---------------- KPI 指标卡 ---------------- */
function updateStats() {
  if (statQueries) statQueries.textContent = String(loadHistory().length);
  if (statLatency && serverElapsedMs != null) {
    statLatency.textContent = (serverElapsedMs / 1000).toFixed(1);
  }
}

/* ---------------- 系统状态页 / 查询历史页 ---------------- */
// 依赖中文名与图标（与 /api/health 返回的 dependencies 键对应）
const DEP_META = {
  llm:           { name: "大模型 LLM",         icon: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>' },
  mysql_meta:    { name: "元数据库 MySQL",     icon: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>' },
  mysql_dw:      { name: "业务库 MySQL",       icon: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/>' },
  qdrant:        { name: "向量库 Qdrant",      icon: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6v6H9z"/>' },
  elasticsearch: { name: "检索引擎 ES",        icon: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>' },
  embedding:     { name: "向量化 Embedding",   icon: '<path d="M3 12h4l3 8 4-16 3 8h4"/>' },
};

function svgIcon(inner) {
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">' + inner + '</svg>';
}

function renderStatus(h) {
  if (!h || !ssTitle) return;
  const overall = h.status;
  const ok = overall === "ok";
  const degraded = overall === "degraded";
  const cls = ok ? "ok" : (degraded ? "warn" : "err");
  if (ssIc) ssIc.className = "ss-ic " + cls;
  if (ssIc) ssIc.innerHTML = svgIcon(ok
    ? '<path d="M20 6 9 17l-5-5"/>'
    : (degraded ? '<path d="M12 9v4"/><path d="M12 17h.01"/>' : '<path d="M18 6 6 18"/><path d="M6 6l12 12"/>'));
  if (ssTitle) ssTitle.textContent = ok ? "所有核心依赖正常" : (degraded ? "部分依赖异常（服务降级）" : "系统异常");
  if (ssSub) {
    const deps = h.dependencies || {};
    const bad = Object.keys(deps).filter((k) => deps[k].status !== "ok");
    ssSub.textContent = ok ? "下游依赖全部连通" : ("异常依赖：" + bad.join("、"));
  }
  if (ssTime) {
    const t = (h.timestamp || "").replace("T", " ").replace(/\+.*$/, "");
    ssTime.textContent = t ? "更新于 " + t + " UTC" : "";
  }
  if (depList) {
    depList.innerHTML = "";
    const deps = h.dependencies || {};
    Object.keys(deps).forEach((key) => {
      const meta = DEP_META[key] || { name: key, icon: "" };
      const d = deps[key];
      const isOk = d.status === "ok";
      const latency = (d.latency_ms != null) ? d.latency_ms + "ms" : "";
      const note = d.note || d.detail || (d.model ? "模型 " + d.model : "") || (d.provider ? d.provider : "");
      const el = document.createElement("div");
      el.className = "dep";
      el.innerHTML =
        '<div class="dep-ic">' + svgIcon(meta.icon) + '</div>' +
        '<div class="dep-body">' +
          '<div class="dep-name">' + escapeHtml(meta.name) + '</div>' +
          '<div class="dep-meta">' + escapeHtml([latency, note].filter(Boolean).join(" · ")) + '</div>' +
        '</div>' +
        '<div class="dep-status ' + (isOk ? "ok" : "error") + '">' +
          '<span class="dep-dot"></span>' + (isOk ? "正常" : "异常") +
        '</div>';
      depList.appendChild(el);
    });
  }
}

function renderHistoryPage() {
  if (!historyList) return;
  const hist = loadHistory();
  if (!hist.length) {
    historyList.innerHTML = '<div class="hist-empty">暂无历史提问记录</div>';
    return;
  }
  historyList.innerHTML = "";
  hist.forEach((q) => {
    const el = document.createElement("div");
    el.className = "hist-item";
    el.innerHTML =
      '<div class="hist-icon">' + svgIcon('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>') + '</div>' +
      '<div class="hist-text" title="' + escapeHtml(q) + '">' + escapeHtml(q) + '</div>' +
      '<div class="hist-actions"><button class="btn btn-link btn-sm" data-rerun="' + escapeHtml(q) + '">重新提问</button></div>';
    historyList.appendChild(el);
  });
  historyList.querySelectorAll("[data-rerun]").forEach((b) => {
    b.addEventListener("click", () => {
      const q = b.getAttribute("data-rerun");
      switchPage("ask");
      queryInput.value = q;
      runQuery(q);
    });
  });
}

function switchPage(page) {
  const item = navEl && navEl.querySelector('.nav-item[data-page="' + page + '"]');
  if (item) item.click();
}

/* ---------------- UI 重置与状态切换 ---------------- */
function resetUI() {
  timelineEl.innerHTML = "";
  stepEls = new Map();
  sqlBlock.hidden = true;
  sqlCode.textContent = "";
  resultBlock.hidden = true;
  resultTable.innerHTML = "";
  lastResult = null;
  serverElapsedMs = null;
  errorAlert.hidden = true;
  errorMsg.textContent = "";
  errorDetail.hidden = true;
  errorBody.textContent = "";
  finished = false;
  aborted = false;
  phaseTag.textContent = "等待提问…";
  runbar.hidden = true;
  elapsedEl.textContent = "耗时 0.0s";
  rowCountEl.textContent = "";
}

function setRunning(run) {
  running = run;
  runBtn.disabled = run;
  demoBtn.disabled = run;
  stopBtn.disabled = !run;
  runBtn.textContent = run ? "问数中…" : "开始问数";
}

function startTimer() {
  startTime = Date.now();
  runbar.hidden = false;
  elapsedEl.textContent = "耗时 0.0s";
  timerId = setInterval(() => {
    const s = ((Date.now() - startTime) / 1000).toFixed(1);
    elapsedEl.textContent = "耗时 " + s + "s";
  }, 100);
}
function stopTimer() {
  if (timerId) {
    clearInterval(timerId);
    timerId = null;
    const s = ((Date.now() - startTime) / 1000).toFixed(1);
    elapsedEl.textContent = "耗时 " + s + "s";
  }
}

/* ---------------- 时间线 ---------------- */
function ensureStep(rawStage) {
  let li = stepEls.get(rawStage);
  if (li) return li;
  const idx = STAGE_ORDER.indexOf(rawStage);
  li = document.createElement("li");
  li.className = "step";
  li.dataset.stage = rawStage;
  li.innerHTML =
    '<span class="dot"></span>' +
    '<span class="label">' + (STAGE_LABELS[rawStage] || rawStage) + "</span>" +
    '<span class="dur"></span>' +
    '<span class="time"></span>';
  // 按规范顺序插入（保证时间线顺序稳定）
  let inserted = false;
  for (const child of timelineEl.children) {
    const cStage = child.dataset.stage;
    if (STAGE_ORDER.indexOf(cStage) > idx) {
      timelineEl.insertBefore(li, child);
      inserted = true;
      break;
    }
  }
  if (!inserted) timelineEl.appendChild(li);
  stepEls.set(rawStage, li);
  return li;
}

function onStage(rawStage, ev) {
  const li = ensureStep(rawStage);
  // 上一个 active 标记为完成
  document.querySelectorAll(".step.active").forEach((s) => {
    s.classList.remove("active");
    s.classList.add("done");
  });
  li.classList.remove("done", "error");
  li.classList.add("active");
  const t = li.querySelector(".time");
  if (t) t.textContent = nowTime();
  // 展示本阶段耗时（后端 SSE 透出的 delta_ms，近似该节点处理耗时，形成性能基线）
  const d = li.querySelector(".dur");
  if (d) {
    if (ev && ev.delta_ms != null) {
      d.textContent = "耗时 " + ev.delta_ms + "ms";
      d.classList.add("show");
    } else {
      d.textContent = "";
      d.classList.remove("show");
    }
  }
  phaseTag.textContent = STAGE_LABELS[rawStage] || rawStage;
}

/* ---------------- SQL / 结果 / 错误 ---------------- */
function onSql(sql) {
  sqlBlock.hidden = false;
  sqlCode.textContent = sql || "";
}

function renderTable(data) {
  resultTable.innerHTML = "";
  const isRows =
    Array.isArray(data) &&
    data.length > 0 &&
    typeof data[0] === "object" &&
    data[0] !== null;

  if (isRows) {
    const cols = Object.keys(data[0]);
    const table = document.createElement("table");
    table.className = "result";
    const thead = document.createElement("thead");
    const htr = document.createElement("tr");
    cols.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = c;
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    data.forEach((row) => {
      const tr = document.createElement("tr");
      cols.forEach((c) => {
        const td = document.createElement("td");
        const v = row[c];
        td.textContent = v === null || v === undefined ? "" : String(v);
        if (typeof v === "number") td.classList.add("cell-num");
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    resultTable.appendChild(table);
    rowCountEl.textContent = "共 " + data.length + " 行";
  } else {
    // 兜底：非标准行结构时以 JSON 展示
    const pre = document.createElement("pre");
    pre.className = "code";
    pre.style.background = "#f7f9fc";
    pre.style.color = "#1f2d3d";
    pre.textContent = JSON.stringify(data, null, 2);
    resultTable.appendChild(pre);
    rowCountEl.textContent = "";
  }
}

function onResult(result) {
  resultBlock.hidden = false;
  lastResult = result;
  renderTable(result);
}

// 把冗长的技术细节（含 base_url / 代理变量等）提炼为一句话可读结论，技术原文折叠展示
function friendlyError(detail) {
  const d = (detail || "").toLowerCase();
  if (d.includes("502") || d.includes("bad gateway")) {
    return "大模型服务网关异常（502 Bad Gateway），通常是反向代理或网关配置问题，请检查 LLM 网关地址与代理设置。";
  }
  if (d.includes("503") || d.includes("service unavailable")) {
    return "大模型服务暂时不可用（503），请稍后重试或确认服务已启动。";
  }
  if (d.includes("connection refused") || d.includes("actively refused") || d.includes("10061") || d.includes("econnrefused")) {
    return "无法连接大模型服务，请确认服务地址与端口是否正确且已启动。";
  }
  if (d.includes("timeout")) {
    return "请求超时，请检查网络或服务响应是否过慢。";
  }
  if (d.includes("401") || d.includes("unauthorized") || d.includes("api key") || d.includes("apikey") || d.includes("鉴权")) {
    return "鉴权失败，请检查 API Key 或访问凭证是否正确。";
  }
  return "执行过程中出现异常，可展开下方技术详情定位原因。";
}

function onError(ev) {
  errorAlert.hidden = false;
  errorTitle.textContent = ev.message || "执行失败";
  const detail = ev.detail || "";
  // 一句话结论（可读、商务克制）；后端未就绪时优先提示启动依赖
  let msg = friendlyError(detail);
  if (!healthOk) {
    msg = "部分后端依赖未就绪，问数将无法执行。请先启动依赖服务，或点「演示」预览界面。";
  }
  errorMsg.textContent = msg;
  // 长技术细节折叠，避免红色块里堆满 base_url / 代理变量等噪声
  if (detail) {
    errorDetail.hidden = false;
    errorBody.textContent = detail;
  } else {
    errorDetail.hidden = true;
    errorBody.textContent = "";
  }
  const active = timelineEl.querySelector(".step.active");
  if (active) {
    active.classList.remove("active");
    active.classList.add("error");
  }
  phaseTag.textContent = "失败";
}

function onDone() {
  document.querySelectorAll(".step.active").forEach((s) => {
    s.classList.remove("active");
    s.classList.add("done");
  });
  if (phaseTag.textContent !== "失败") phaseTag.textContent = "完成";
  stopTimer();
  // 优先以服务端口径的总耗时展示（更精确，避免客户端往返误差）
  if (serverElapsedMs != null) {
    elapsedEl.textContent = "耗时 " + (serverElapsedMs / 1000).toFixed(1) + "s";
  }
  updateStats();
  setRunning(false);
}

/* ---------------- SSE 事件分发 ---------------- */
function onEvent(ev) {
  if (!ev || typeof ev !== "object") return;
  if (ev.type === "error") {
    onError(ev);
    return;
  }
  // 累计后端链路耗时（SSE 透出），最终以服务端口径为准
  if (ev.elapsed_ms != null) serverElapsedMs = ev.elapsed_ms;
  if (ev.stage) onStage(ev.stage, ev);
  if (ev.sql != null) onSql(ev.sql);
  if (ev.result != null) onResult(ev.result);
}

function handleRaw(raw) {
  const lines = raw
    .split("\n")
    .map((s) => s.trim())
    .filter((s) => s.startsWith("data:"));
  for (const line of lines) {
    const payload = line.slice(5).trim();
    if (payload === "[DONE]") {
      finished = true;
      onDone();
      return;
    }
    let ev;
    try {
      ev = JSON.parse(payload);
    } catch (_) {
      continue; // 忽略非 JSON 行
    }
    onEvent(ev);
  }
}

/* ---------------- 真实问数（SSE） ---------------- */
async function runQuery(q) {
  resetUI();
  setRunning(true);
  startTimer();
  controller = new AbortController();
  try {
    // 携带登录 Token（若已登录），配合后端 require_auth 生产策略
    const s = getSession();
    const headers = { "Content-Type": "application/json" };
    if (s && s.token) headers["Authorization"] = "Bearer " + s.token;
    const resp = await fetch("/api/query", {
      method: "POST",
      headers: headers,
      body: JSON.stringify({ query: q }),
      signal: controller.signal,
    });
    if (resp.status === 401) {
      // 未登录或 Token 失效：提示并引导登录
      onError({
        message: "需要登录",
        detail: "当前接口需要登录后才能问数，请先登录或注册账户。",
      });
      window.location.href = "/ui/login.html";
      stopTimer();
      setRunning(false);
      return;
    }
    if (!resp.ok) {
      onError({
        message: "请求失败",
        detail: "HTTP " + resp.status + " —— 请确认服务已启动且 /api/query 可用",
      });
      stopTimer();
      setRunning(false);
      return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const raw = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        handleRaw(raw);
      }
    }
    if (buf.trim()) handleRaw(buf); // 兜底：无结尾空行
    if (!finished && !aborted) onDone();
  } catch (e) {
    if (e && e.name === "AbortError") {
      phaseTag.textContent = "已停止";
    } else {
      onError({
        message: "网络或请求异常",
        detail: e && e.message ? e.message : String(e),
      });
    }
  } finally {
    stopTimer();
    setRunning(false);
    controller = null;
  }
}

/* ---------------- 演示模式（模拟流式，无需后端） ---------------- */
async function runDemo() {
  resetUI();
  setRunning(true);
  startTimer();
  aborted = false;
  const stages = [
    "提取关键字---哈哈",
    "召回列数据",
    "召回指标数据",
    "召回字段取值",
    "合并召回信息",
    "过滤指标",
    "过滤表",
    "添加额外上下文",
    "生成SQL",
    "校验SQL",
    "执行SQL",
  ];
  for (const s of stages) {
    if (aborted) return;
    await sleep(360);
    if (aborted) return;
    onStage(s);
    if (s === "生成SQL") {
      await sleep(320);
      onSql(
        "SELECT tea_category,\n" +
          "       SUM(sales_amount) AS total_amount\n" +
          "FROM fact_order\n" +
          "WHERE YEAR(order_date) = 2025\n" +
          "GROUP BY tea_category\n" +
          "ORDER BY total_amount DESC"
      );
    }
  }
  if (aborted) return;
  await sleep(420);
  onResult([
    { "茶类": "绿茶", "销售额": 1234500.0 },
    { "茶类": "红茶", "销售额": 1183200.5 },
    { "茶类": "乌龙茶", "销售额": 982100.0 },
    { "茶类": "白茶", "销售额": 651800.0 },
    { "茶类": "黑茶", "销售额": 523400.0 },
    { "茶类": "花茶", "销售额": 412300.0 },
  ]);
  await sleep(280);
  finished = true;
  onDone();
}

/* ---------------- 历史记录（localStorage） ---------------- */
const HISTORY_KEY = "da_query_history";
const HISTORY_MAX = 8;

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  } catch (_) {
    return [];
  }
}
function saveHistory(list) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(list));
  } catch (_) {}
}
function pushHistory(q) {
  let list = loadHistory().filter((x) => x !== q);
  list.unshift(q);
  if (list.length > HISTORY_MAX) list = list.slice(0, HISTORY_MAX);
  saveHistory(list);
  renderHistory();
}
function renderHistory() {
  const list = loadHistory();
  if (!list.length) {
    historyBox.hidden = true;
    return;
  }
  historyBox.hidden = false;
  historyChips.innerHTML = "";
  list.forEach((q) => {
    const b = document.createElement("button");
    b.className = "chip";
    b.textContent = q;
    b.title = "重新提问：" + q;
    b.addEventListener("click", () => {
      queryInput.value = q;
      runQuery(q);
    });
    historyChips.appendChild(b);
  });
}

/* ---------------- 结果导出 ---------------- */
function downloadFile(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// 复制文本到剪贴板的降级方案（隐私模式或旧浏览器无 navigator.clipboard 时）
function fallbackCopy(text, done) {
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    done();
  } catch (_) { /* 复制失败静默忽略 */ }
}
function exportCsv() {
  if (!Array.isArray(lastResult) || !lastResult.length) return;
  const cols = Object.keys(lastResult[0]);
  const escape = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [cols.join(",")];
  lastResult.forEach((row) => {
    lines.push(cols.map((c) => escape(row[c])).join(","));
  });
  downloadFile("data_agent_result.csv", "﻿" + lines.join("\n"), "text/csv;charset=utf-8");
}
function exportJson() {
  if (!lastResult) return;
  downloadFile(
    "data_agent_result.json",
    JSON.stringify(lastResult, null, 2),
    "application/json"
  );
}

/* ---------------- 健康状态 ---------------- */
async function refreshHealth() {
  healthEl.classList.remove("ok", "warn", "err");
  healthLabel.textContent = "检测中…";
  backendWarn.hidden = true;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    const r = await fetch("/api/health", { signal: ctrl.signal });
    clearTimeout(timer);
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    const status = h.status;
    if (status === "ok") {
      healthOk = true;
      healthEl.classList.add("ok");
      healthLabel.textContent = "服务正常";
      if (statDeps) statDeps.textContent = Object.keys(h.dependencies || {}).length || "--";
      if (statDepsTrend) statDepsTrend.textContent = "全部正常";
    } else {
      healthOk = false;
      healthEl.classList.add("warn");
      const deps = h.dependencies || {};
      const bad = Object.keys(deps).filter((k) => deps[k].status !== "ok");
      healthLabel.textContent = bad.length
        ? "部分依赖异常：" + bad.join("、")
        : "服务降级";
      backendWarn.hidden = false;
      if (statDeps) {
        const okCount = Object.values(deps).filter((d) => d.status === "ok").length;
        const total = Object.keys(deps).length;
        statDeps.textContent = total ? (okCount + "/" + total) : "--";
      }
      if (statDepsTrend) statDepsTrend.textContent = "部分异常";
    }
    renderStatus(h);
  } catch (e) {
    healthOk = false;
    healthEl.classList.add("err");
    healthLabel.textContent = (e && e.name === "AbortError") ? "服务响应超时" : "无法连接服务";
    backendWarn.hidden = false;
    if (statDeps) statDeps.textContent = "--";
    if (statDepsTrend) statDepsTrend.textContent = "未知";
    // 同步状态页摘要（探活失败/超时兜底，避免卡在「检测中…」）
    if (ssIc) { ssIc.className = "ss-ic err"; ssIc.innerHTML = svgIcon('<path d="M18 6 6 18"/><path d="M6 6l12 12"/>'); }
    if (ssTitle) ssTitle.textContent = "探活失败";
    if (ssSub) ssSub.textContent = (e && e.name === "AbortError") ? "依赖探活超时（可能下游服务未启动）" : "无法连接健康接口";
    if (ssTime) ssTime.textContent = "";
    if (depList) depList.innerHTML = '<div class="hist-empty">暂无可展示的依赖信息</div>';
  }
}

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  runBtn.addEventListener("click", () => {
    const q = queryInput.value.trim();
    if (!q) {
      reqHint.textContent = "请先输入一个问题";
      reqHint.classList.add("err");
      return;
    }
    reqHint.textContent = "";
    reqHint.classList.remove("err");
    pushHistory(q);
    runQuery(q);
  });

  stopBtn.addEventListener("click", () => {
    aborted = true;
    if (controller) controller.abort();
  });

  demoBtn.addEventListener("click", () => {
    reqHint.textContent = "";
    runDemo();
  });

  clearBtn.addEventListener("click", () => {
    queryInput.value = "";
    resetUI();
    reqHint.textContent = "";
  });

  // 示例问题：点击即填入并直接问数
  document.querySelectorAll(".chip").forEach((chip) => {
    // 历史 chips 单独绑定，这里只处理示例 chips（带 data-q）
    if (!chip.dataset.q) return;
    chip.addEventListener("click", () => {
      const q = chip.dataset.q;
      queryInput.value = q;
      pushHistory(q);
      runQuery(q);
    });
  });

  // 复制 SQL
  const copySql = $("copySql");
  if (copySql) {
    copySql.addEventListener("click", () => {
      const text = sqlCode.textContent;
      if (!text) return;
      navigator.clipboard
        .writeText(text)
        .then(() => {
          copySql.textContent = "已复制";
          setTimeout(() => (copySql.textContent = "复制 SQL"), 1500);
        })
        .catch(() => (copySql.textContent = "复制失败"));
    });
  }

  // 导出
  const exCsv = $("exportCsv");
  if (exCsv) exCsv.addEventListener("click", exportCsv);
  const exJson = $("exportJson");
  if (exJson) exJson.addEventListener("click", exportJson);

  // 复制错误信息（结论 + 技术详情，便于反馈排查）
  if (copyError) {
    copyError.addEventListener("click", () => {
      const title = errorTitle.textContent || "执行失败";
      const msg = errorMsg.textContent || "";
      const detail = errorDetail.hidden ? "" : (errorBody.textContent || "");
      const text = [title, msg, detail].filter(Boolean).join("\n\n");
      if (!text.trim()) return;
      const markDone = () => {
        const old = copyError.textContent;
        copyError.textContent = "已复制";
        copyError.classList.add("done");
        setTimeout(() => {
          copyError.textContent = old;
          copyError.classList.remove("done");
        }, 1500);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(markDone).catch(() => fallbackCopy(text, markDone));
      } else {
        fallbackCopy(text, markDone);
      }
    });
  }

  // 顶栏健康状态点击刷新
  healthEl.addEventListener("click", refreshHealth);
  // 顶部「刷新依赖状态」
  if (refreshBtn) refreshBtn.addEventListener("click", refreshHealth);
  // 系统状态页「刷新状态」
  if (statusRefresh) statusRefresh.addEventListener("click", refreshHealth);
  // 查询历史页「清空历史」
  if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", () => {
      try { localStorage.removeItem(HISTORY_KEY); } catch (_) {}
      renderHistory();       // 同步刷新问数页的历史 chips
      renderHistoryPage();    // 同步刷新历史页列表
    });
  }

  // Ctrl/Cmd + Enter 提交
  queryInput.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !running) {
      runBtn.click();
    }
  });
}

/* ---------------- 启动 ---------------- */
bindEvents();
renderHistory();
renderUserMenu();
bindUserMenu();
bindNav();
bindAssetTabs();
updateStats();
renderHistoryPage();
refreshHealth();
setInterval(refreshHealth, 30000); // 每 30s 自动探活
