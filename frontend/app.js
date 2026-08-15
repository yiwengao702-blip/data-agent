/* ============================================================
 * data-agent 前端逻辑
 * 职责：
 *   1) 解析 /api/query 的 SSE（POST + ReadableStream 手动解析 data: 事件）
 *   2) 阶段时间线推进、SQL 渲染、结果表格渲染、错误展示、[DONE] 收尾
 *   3) /api/health 探活轮询 + 顶部状态条
 *   4) 内置「演示（模拟流式）」：无需任何后端依赖即可预览完整界面效果
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
const demoBtn = $("demoBtn");
const clearBtn = $("clearBtn");
const reqHint = $("reqHint");
const healthEl = $("health");
const healthLabel = $("healthLabel");

// 运行状态
let running = false;
let finished = false;
let stepEls = new Map(); // rawStage -> <li>

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
  errorAlert.hidden = true;
  finished = false;
  phaseTag.textContent = "等待提问…";
}

function setRunning(run) {
  running = run;
  runBtn.disabled = run;
  demoBtn.disabled = run;
  runBtn.textContent = run ? "问数中…" : "开始问数";
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
  } else {
    // 兜底：非标准行结构时以 JSON 展示
    const pre = document.createElement("pre");
    pre.className = "code";
    pre.style.background = "#f7f9fc";
    pre.style.color = "#1f2d3d";
    pre.textContent = JSON.stringify(data, null, 2);
    resultTable.appendChild(pre);
  }
}

function onResult(result) {
  resultBlock.hidden = false;
  renderTable(result);
}

function onError(ev) {
  errorAlert.hidden = false;
  errorTitle.textContent = ev.message || "执行失败";
  errorBody.textContent = ev.detail || JSON.stringify(ev, null, 2);
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
  try {
    const resp = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
    });
    if (!resp.ok) {
      onError({
        message: "请求失败",
        detail: "HTTP " + resp.status + " —— 请确认服务已启动且 /api/query 可用",
      });
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
    if (!finished) onDone();
  } catch (e) {
    onError({
      message: "网络或请求异常",
      detail: e && e.message ? e.message : String(e),
    });
    setRunning(false);
  }
}

/* ---------------- 演示模式（模拟流式，无需后端） ---------------- */
async function runDemo() {
  resetUI();
  setRunning(true);
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
    await sleep(360);
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

/* ---------------- 健康状态 ---------------- */
async function refreshHealth() {
  healthEl.classList.remove("ok", "warn", "err");
  healthLabel.textContent = "检测中…";
  try {
    const r = await fetch("/api/health");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const h = await r.json();
    const status = h.status;
    if (status === "ok") {
      healthEl.classList.add("ok");
      healthLabel.textContent = "服务正常";
    } else {
      healthEl.classList.add("warn");
      // 列出异常依赖，便于定位
      const deps = h.dependencies || {};
      const bad = Object.keys(deps).filter((k) => deps[k].status !== "ok");
      healthLabel.textContent = bad.length
        ? "部分依赖异常：" + bad.join("、")
        : "服务降级";
    }
  } catch (e) {
    healthEl.classList.add("err");
    healthLabel.textContent = "无法连接服务";
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
    runQuery(q);
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
    chip.addEventListener("click", () => {
      const q = chip.dataset.q;
      queryInput.value = q;
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
refreshHealth();
setInterval(refreshHealth, 30000); // 每 30s 自动探活
