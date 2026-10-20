import {setupChatControls} from "./chat-controls.js";
import {setupVoice} from "./voice-input.js";
import { setupSources } from "./source.js";
import { setupWorkbench } from "./layout.js";
const $ = (selector) => document.querySelector(selector);
const state = { token: "", run: null, serverId: "", dataJob: null };

function esc(value) {
  return String(value ?? "—").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function api(path, options = {}) {
  const headers = { "X-Agent-Token": state.token, ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers };
  const response = await fetch(path, { ...options, headers });
  const content = response.headers.get("content-type") || "";
  const body = content.includes("application/json") ? await response.json() : {};
  if (!response.ok) throw new Error(body.error || `请求失败 (${response.status})`);
  return body;
}

function notice(message, type = "") {
  const box = $("#notice"); box.textContent = message; box.className = `notice ${type}`;
}

function humanBytes(value) {
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

async function connect() {
  const health = await fetch("/api/health").then((response) => response.json());
  state.token = health.token; state.serverId = health.server_id;
  $("#connection-label").textContent = "本地引擎已连接";
  const { datasets } = await api("/api/datasets");
  const picker = $("#dataset");
  picker.replaceChildren();
  for (const item of datasets) {
    const option = document.createElement("option"); option.value = item.id;
    option.textContent = `${item.name} · ${humanBytes(item.bytes)}`; option.dataset.bytes = item.bytes; picker.append(option);
  }
  if (!datasets.length) {
    const option = document.createElement("option"); option.textContent = "项目目录中没有数据文件"; picker.append(option);
    sources.setCsvAvailable(false); notice("请选择 CSV / XLSX 文件或输入绝对路径。", "error"); return;
  }
  sources.setCsvAvailable(true);
  await sources.selectProject();
  $("#source-meta").textContent = `${datasets.length} 个项目文件可用 · 可另选 CSV / XLSX 文件`;
  notice("本地 Agent 已连接。请选择数据集并运行完整分析。", "success");
}

function fmt(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function dateFmt(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function table(el, rows, columns) {
  const target = $(el);
  if (!rows?.length) { target.innerHTML = "<tbody><tr><td>无记录</td></tr></tbody>"; return; }
  target.innerHTML = `<thead><tr>${columns.map(([key, label]) => `<th>${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map(([key]) => `<td>${esc(formatCell(row[key]))}</td>`).join("")}</tr>`).join("")}</tbody>`;
}

function formatCell(value) {
  if (value == null) return "—";
  if (typeof value === "number") return fmt(value, 3);
  if (String(value).includes("T") && String(value).includes(":")) return dateFmt(value);
  return value;
}

function renderKpis(data) {
  const top = data.descriptive.top_level;
  const anomalyRows = data.diagnostic.event_record_count;
  const items = [
    ["采样记录", fmt(top.rows, 0), "所选范围的记录行数"],
    ["资产分组", fmt(top.asset_groups, 0), "依据现有设备/站点字段"],
    ["异常筛查快照", fmt(anomalyRows, 0), "逐行计数，不等同故障次数"],
    ["数据时间窗", `${fmt(top.window_hours, 2)} h`, "按源时间戳计算"],
  ];
  $("#kpis").innerHTML = items.map(([label, value, sub]) => `<article class="kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${esc(value)}</div><div class="kpi-sub">${esc(sub)}</div></article>`).join("");
}

function renderCharts(charts) {
  const colors = ["#007bc0", "#006c3a", "#9e2896", "#725b00"];
  $("#charts").innerHTML = charts.length ? charts.map((chart, index) => {
    const pts = chart.points || [];
    const series = ["median", "max"].map((key) => pts.map((point) => Number(point[key])).filter(Number.isFinite));
    const values = series.flat(); const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
    const width = 620, height = 150, left = 35, right = 8, top = 8, bottom = 22;
    const coords = series.map((valuesForKey) => {
      const every = Math.max(1, Math.ceil(valuesForKey.length / 100));
      return valuesForKey.filter((_, i) => i % every === 0).map((value, j, arr) => {
        const x = left + (arr.length < 2 ? 0 : j * (width - left - right) / (arr.length - 1));
        const y = top + (max - value) / span * (height - top - bottom);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
    });
    const first = pts[0]?.time, last = pts.at(-1)?.time;
    return `<article class="chart-card"><h4>${esc(chart.label)}</h4><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(chart.label)}趋势图"><line x1="${left}" y1="${height - bottom}" x2="${width - right}" y2="${height - bottom}" stroke="#dfe5e5"/><line x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}" stroke="#dfe5e5"/><text x="2" y="${top + 8}" fill="#758184" font-size="9">${esc(fmt(max))}</text><text x="2" y="${height - bottom}" fill="#758184" font-size="9">${esc(fmt(min))}</text><polyline fill="none" stroke="${colors[index % colors.length]}" stroke-width="2" points="${coords[0] || ""}"/><polyline fill="none" stroke="${colors[index % colors.length]}" stroke-width="1.2" stroke-dasharray="4 3" opacity=".6" points="${coords[1] || ""}"/><text x="${left}" y="${height - 4}" fill="#758184" font-size="9">${esc(dateFmt(first))}</text><text x="${width - right}" y="${height - 4}" text-anchor="end" fill="#758184" font-size="9">${esc(dateFmt(last))}</text></svg><div class="chart-legend"><span><i class="legend-dot" style="background:${colors[index % colors.length]}"></i>中位数</span><span><i class="legend-dot" style="background:${colors[index % colors.length]};opacity:.55"></i>最大值</span></div></article>`;
  }).join("") : "<div class='callout'>没有可用的时序字段。</div>";
}

function renderOverview(data) {
  renderKpis(data); renderCharts(data.descriptive.charts);
  $("#data-line").textContent = `数据源 · ${data.dataset}`;
  $("#window-label").textContent = `${dateFmt(data.descriptive.top_level.first_timestamp)} — ${dateFmt(data.descriptive.top_level.last_timestamp)}`;
  const rows = data.descriptive.assets;
  const cols = Object.keys(rows[0] || {}).filter((key) => ["asset_key", "records", "acttorque_median", "acttorque_p95", "position_error_median", "position_error_p95", "acttime_ms_median", "movetotbastime_ms_median", "movetoworktime_ms_median", "movementcounter_max", "diagnostic_assertions", "lifecycle_state"].includes(key));
  const names = { asset_key: "资产/站点", records: "记录数", acttorque_median: "转矩中位数", acttorque_p95: "转矩 P95", position_error_median: "目标/实际位置差中位数", position_error_p95: "目标/实际位置差 P95", acttime_ms_median: "伺服动作时间 ms", movetotbastime_ms_median: "气缸回程 ms", movetoworktime_ms_median: "气缸工作行程 ms", movementcounter_max: "累计动作计数", diagnostic_assertions: "诊断位快照数", lifecycle_state: "筛查状态" };
  table("#asset-table", rows, cols.map((key) => [key, names[key] || key]));
  const q = data.descriptive.quality;
  const qualityItems = [["重复行", q.duplicate_rows], ["缺失时间戳", q.timestamp_missing], ["时间戳中位间隔", `${fmt(q.timestamp_interval_median_seconds, 3)} s`], ["时间戳间隔 P95", `${fmt(q.timestamp_interval_p95_seconds, 3)} s`], ["采样窗口", `${fmt(q.time_window_hours, 2)} h`], ["可见字段数", data.dictionary.length || "参数字典不可用"]];
  $("#quality").innerHTML = qualityItems.map(([k, v]) => `<div class="quality-item"><b>${esc(k)}</b><br>${esc(v ?? "—")}</div>`).join("");
  const dict = data.dictionary || [];
  const colsDict = [["partname", "部件"], ["tagname", "参数 Tag"], ["type", "类型"], ["sampling interval", "采样间隔"], ["value(example)", "示例"]];
  table("#dictionary", dict.map((row) => Object.fromEntries(Object.entries(row).map(([k,v]) => [k.toLowerCase(),v]))), colsDict);
}

function renderDiagnostics(data) {
  const flags = data.diagnostic.flag_counts;
  $("#flags").innerHTML = flags.length ? flags.map((item) => `<article class="flag-card"><strong>${esc(item.flag)}</strong><span>${fmt(item.records, 0)}</span><small>${fmt(item.share * 100, 2)}% 的总快照出现该标记</small></article>`).join("") : "<div class='callout'>本数据窗没有触发已配置的异常筛查规则。</div>";
  $("#diag-notes").innerHTML = `<ul>${data.diagnostic.notes.map((note) => `<li>${esc(note)}</li>`).join("")}</ul>`;
  const events = data.diagnostic.events;
  const preferred = [["msg_timestamp", "时间"], ["asset_key", "资产"], ["anomaly_flags", "筛查标记"], ["acttorque", "实际转矩"], ["actvel", "实际速度"], ["position_error", "目标/实际位置差"], ["acttime_ms", "伺服动作 ms"], ["movetotbastime_ms", "气缸回程 ms"], ["movetoworktime_ms", "气缸工作 ms"], ["diagno", "DiagNo"], ["movementcounter", "动作计数"]];
  table("#events-table", events, preferred.filter(([key]) => events.some((row) => key in row)));
}

function renderLifecycle(data) {
  const states = { normal: "正常", watch: "关注", degradation: "劣化线索", critical: "高风险线索" };
  $("#health-cards").innerHTML = data.lifecycle.assets.map((asset) => `<article class="health-card"><strong>${esc(asset.asset_key)}</strong><div class="health-score">${fmt(asset.signal_score, 1)}<small>/100</small></div><span class="state-pill ${esc(asset.state)}">${esc(states[asset.state] || asset.state)}</span><div class="health-bar"><span class="${esc(asset.state)}" style="width:${Math.max(0,Math.min(100,asset.signal_score))}%"></span></div><small>异常标记快照比例 ${fmt(asset.screened_record_rate * 100, 2)}% · 观察 ${fmt(asset.observation_hours, 2)} 小时</small></article>`).join("") || "<div class='callout'>缺少可分组的资产信息。</div>";
  $("#health-method").textContent = `${data.lifecycle.method} ${data.lifecycle.notes.join(" ")}`;
}

function renderPredictive(data) {
  const item = data.predictive; const ready = item.status !== "not_ready";
  $("#rul-status").className = `rul-card ${ready ? "ready" : ""}`;
  $("#rul-status").innerHTML = `<div class="rul-title"><h3>${ready ? "数据具备进入 RUL 模型评审的最低条件" : "当前不输出剩余寿命数值"}</h3><span class="state-pill ${ready ? "" : "watch"}">${ready ? "待验证" : "数据准备中"}</span></div><p>${esc(item.message)}</p><p><b>当前缺口</b></p><ul>${item.reasons.map((reason) => `<li>${esc(reason)}</li>`).join("")}</ul><p>已识别设备数 ${fmt(item.distinct_assets,0)} · 确认事件记录 ${fmt(item.confirmed_event_rows,0)}</p>`;
  $("#models").innerHTML = item.candidate_models.map((model) => `<article class="model-card"><h4>${esc(model.model)}</h4><p><b>所需数据：</b>${esc(model.requires)}</p></article>`).join("");
}

function render(data) {
  state.run = data; $("#empty").hidden = true; $("#results").hidden = false;
  renderOverview(data); renderDiagnostics(data); renderLifecycle(data); renderPredictive(data);
  $("#footer-state").textContent = `本地运行 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  $("#answer").hidden = true;
  $("#answer-engine").hidden = true;
  $("#question").disabled = false; $("#ask-submit").disabled = voice.active || composer.busy;
  $("#question").placeholder = "例如：哪些异常最需要复核？";
  workbench.showResults();
  $("#agent-context").textContent = `当前分析：${data.dataset}。可询问异常、设备状态或剩余寿命准备度。`;
}

async function pollJob(jobId, progress = notice) {
  while (true) {
    await new Promise((resolve) => setTimeout(resolve, 700));
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (job.status === 'succeeded') return job.result;
    if (job.status === 'failed') throw new Error(job.error || '任务失败');
    if (job.error) throw new Error(job.error);
    progress(job.stage || '任务排队中…');
  }
}

async function analyze() {
  try {
    const {path, body} = sources.request();
    sources.setBusy(true); $("#footer-state").textContent = "分析中";
    notice(path.includes('clickhouse') ? '正在读取 ClickHouse 查询范围并分析…' : '正在读取并分析本地文件…');
    const {job_id} = await api(path, {method:'POST',body:JSON.stringify(body)});
    state.dataJob=job_id; $("#cancel-data-job").hidden=false;
    const result = await pollJob(job_id);
    render(result);
    notice(`全量分析完成：${fmt(result.descriptive.top_level.rows,0)} 条记录全部参与统计。异常为筛查结果，请结合设备定义复核。`,'success');
  } catch (error) { notice(error.message,'error'); $("#footer-state").textContent = "分析未完成"; }
  finally { sources.setBusy(false); state.dataJob=null; $("#cancel-data-job").hidden=true; }
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((panel) => { const active = panel.id === `panel-${name}`; panel.hidden = !active; panel.classList.toggle("active", active); });

}

async function ask(event) {
  event.preventDefault();
  if (!state.run || composer.busy || voice.active) return;
  const prompt = $("#question").value.trim(); if (!prompt) return;
  const runId = state.run.run_id;
  const answer = $("#answer");
  try {
    const selected = composer.request();
    voice.cancel(); composer.setBusy(true); $("#ask-submit").disabled = true;
    answer.hidden = false; answer.textContent = selected.settings.model === 'local-statistical-v1' ? '正在根据本地分析结果整理…' : '所选模型正在回答…';
    let result = await api('/api/ask',{method:'POST',body:JSON.stringify({run_id:runId,question:prompt,...selected})});
    if (result.job_id) result = await pollJob(result.job_id,(message)=>{answer.textContent=message;});
    if (state.run?.run_id !== runId) return;
    const details = result.evidence;
    answer.textContent = result.answer + (details ? '\n\n'+JSON.stringify(details,null,2) : '') + (result.notes ? '\n\n'+result.notes.join('\n') : '');
    $("#answer-engine").textContent = result.engine === 'codex' ? `${result.settings.model} · ${result.settings.effort} · ${result.settings.speed}` : '本地统计问答';
    $("#answer-engine").hidden = false;
  } catch (error) { answer.hidden=false; answer.textContent = error.message; }
  finally {composer.setBusy(false); $("#ask-submit").disabled = !state.run;}
}

document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => activateTab(button.dataset.tab)));
$("#analyze").addEventListener("click", analyze);
$("#cancel-data-job").addEventListener('click',async()=>{
  if(!state.dataJob)return;
  try{await api(`/api/jobs/${state.dataJob}/cancel`,{method:'POST',body:'{}'});notice('正在取消分析，已生成的旧结果保留。');}
  catch(error){notice(error.message,'error');}
});
$("#ask-form").addEventListener("submit", ask);
const workbench = setupWorkbench();
const sources = setupSources({api, pollJob, notice});
const composer = setupChatControls({api,pollJob});
const voice = setupVoice((active)=>{$('#ask-submit').disabled=active||!state.run||composer.busy;});
composer.initialize().catch(()=>{});
connect().catch((error) => { $("#connection-label").textContent = "未连接"; notice(`连接失败：${error.message}`, "error"); });
