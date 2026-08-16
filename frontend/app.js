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
const errorBody = $("errorBody");
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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nowTime = () =>
  new Date().toLocaleTimeString("zh-CN", { hour12: false });

/* ---------------- UI 重置与状态切换 ---------------- */
function resetUI() {
  timelineEl.innerHTML = "";
  stepEls = new Map();
  sqlBlock.hidden = true;
  sqlCode.textContent = "";
  resultBlock.hidden = true;
  resultTable.innerHTML = "";
  lastResult = null;
  errorAlert.hidden = true;
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

function onStage(rawStage) {
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

function onError(ev) {
  errorAlert.hidden = false;
  errorTitle.textContent = ev.message || "执行失败";
  let body = ev.detail || JSON.stringify(ev, null, 2);
  // 后端未就绪时的友好提示
  if (!healthOk) {
    body += "\n\n提示：当前有后端依赖未就绪，请先启动依赖服务。";
  }
  errorBody.textContent = body;
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
  setRunning(false);
}

/* ---------------- SSE 事件分发 ---------------- */
function onEvent(ev) {
  if (!ev || typeof ev !== "object") return;
  if (ev.type === "error") {
    onError(ev);
    return;
  }
  if (ev.stage) onStage(ev.stage);
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
    const resp = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
      signal: controller.signal,
    });
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
        "SELECT region,\n" +
          "       SUM(order_amount) AS total_amount\n" +
          "FROM fact_order\n" +
          "WHERE YEAR(order_date) = 2025\n" +
          "GROUP BY region\n" +
          "ORDER BY total_amount DESC"
      );
    }
  }
  if (aborted) return;
  await sleep(420);
  onResult([
    { region: "华北", total_amount: 1234500.0 },
    { region: "华东", total_amount: 1183200.5 },
    { region: "华南", total_amount: 982100.0 },
    { region: "西南", total_amount: 651800.0 },
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
    const r = await fetch("/api/health");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    const status = h.status;
    if (status === "ok") {
      healthOk = true;
      healthEl.classList.add("ok");
      healthLabel.textContent = "服务正常";
    } else {
      healthOk = false;
      healthEl.classList.add("warn");
      const deps = h.dependencies || {};
      const bad = Object.keys(deps).filter((k) => deps[k].status !== "ok");
      healthLabel.textContent = bad.length
        ? "部分依赖异常：" + bad.join("、")
        : "服务降级";
      backendWarn.hidden = false;
    }
  } catch (e) {
    healthOk = false;
    healthEl.classList.add("err");
    healthLabel.textContent = "无法连接服务";
    backendWarn.hidden = false;
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

  // 顶栏健康状态点击刷新
  healthEl.addEventListener("click", refreshHealth);

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
refreshHealth();
setInterval(refreshHealth, 30000); // 每 30s 自动探活
