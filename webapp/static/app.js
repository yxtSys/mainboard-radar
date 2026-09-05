/* 主板雷达 前端 */
const $ = s => document.querySelector(s);
const fmtYi = v => v == null ? "-" : (v / 1e8).toFixed(v / 1e8 >= 10 ? 1 : 2) + "亿";
const esc = s => String(s ?? "").replace(/[<>&"]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));

let PROFILE = JSON.parse(localStorage.getItem("profile") || "null"); // {name,pin,pmin,pmax,watchlist,alerts}
let boardCache = {};   // code -> detail
let curBoard = null, curStrat = "cs", etfGroup = "cs";
let boardsAll = [];

/* ---------- 静默更新：内容没变就不碰DOM，变了也不重播动画 ---------- */
const _lastHtml = new Map();
function setIfChanged(el, html) {
  if (!el) return;
  if (_lastHtml.get(el.id) === html) return;
  _lastHtml.set(el.id, html);
  el.innerHTML = html;
}

/* ---------- 泡泡物理与渲染 ---------- */
class Bubbles {
  constructor(canvas, mode) {
    this.cv = canvas; this.ctx = canvas.getContext("2d");
    this.mode = mode; // 'pct' | 'flow'
    this.nodes = new Map(); this.items = []; this.note = "";
    this.frozen = false; this.tick = 0;
    this.resize(); addEventListener("resize", () => { this.resize(); this.frozen = false; });
    canvas.addEventListener("click", e => this.onClick(e));
    requestAnimationFrame(() => this.loop());
  }
  resize() {
    const r = this.cv.getBoundingClientRect(), d = devicePixelRatio || 1;
    this.cv.width = r.width * d; this.cv.height = r.height * d;
    this.W = r.width; this.H = r.height; this.d = d;
  }
  setData(items, note) {
    this.items = items; this.note = note || "";
    const n = items.length, maxV = Math.max(...items.map(i => Math.abs(this.val(i))), 1e-9);
    const R = Math.min(this.W, this.H) / 2, rMax = R * 0.42 * (this.W < 500 ? 0.76 : 1), rMin = R * 0.15;
    const seen = new Set();
    items.forEach((it, idx) => {
      const id = it.code + "|" + it.type, v = Math.abs(this.val(it));
      const tR = n ? rMin + (rMax - rMin) * Math.sqrt(v / maxV) : 0;
      seen.add(id);
      let nd = this.nodes.get(id);
      if (!nd) {
        const a = Math.random() * Math.PI * 2;
        nd = { x: this.W / 2 + Math.cos(a) * R * 0.2, y: this.H / 2 + Math.sin(a) * R * 0.2, r: 1, vx: 0, vy: 0, tR: 1 };
        this.nodes.set(id, nd);
      }
      nd.it = it; nd.tR = tR; nd.order = idx;
    });
    for (const [id, nd] of this.nodes) if (!seen.has(id)) this.nodes.delete(id);
    this.frozen = false; // 有新数据才唤醒物理
  }
  val(it) { return this.mode === "pct" ? (it.pct ?? it.heat ?? 0) : (it.main_in ?? 0) / 1e8; }
  label(it) {
    if (this.mode === "pct") {
      if (it.pct != null) return (it.pct > 0 ? "+" : "") + it.pct.toFixed(1) + "%";
      if (it.heat != null) return it.heat + "家涨停";
      return "";
    }
    return it.main_in == null ? "" : ((it.main_in > 0 ? "+" : "-") + fmtYi(Math.abs(it.main_in)));
  }
  physics() {
    const nodes = [...this.nodes.values()], cx = this.W / 2;
    nodes.forEach(nd => { nd.r += (nd.tR - nd.r) * 0.12; });
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 0.01, min = a.r + b.r + 2;
      if (d < min) { // 相互推开（质量∝r²），硬实体感
        const push = (min - d) / d * 0.5, ma = a.r * a.r, mb = b.r * b.r, s = ma + mb;
        a.x -= dx * push * (mb / s) * 2; a.y -= dy * push * (mb / s) * 2;
        b.x += dx * push * (ma / s) * 2; b.y += dy * push * (ma / s) * 2;
      }
    }
    nodes.forEach(nd => {
      // 红绿分成两团：流入/上涨聚上方，流出/下跌聚下方（参考收盘资金图版式）
      const up = this.val(nd.it) >= 0, ty = this.H * (up ? 0.36 : 0.70);
      nd.vx = (nd.vx + (cx - nd.x) * 0.004 * (nd.r / 40)) * 0.86;
      nd.vy = (nd.vy + (ty - nd.y) * 0.005 * (nd.r / 40)) * 0.86;
      nd.x += nd.vx; nd.y += nd.vy;
      const m = nd.r;
      nd.x = Math.max(m, Math.min(this.W - m, nd.x));
      nd.y = Math.max(m, Math.min(this.H - m, nd.y));
    });
  }
  draw() {
    const c = this.ctx, t = performance.now() / 1000;
    c.setTransform(this.d, 0, 0, this.d, 0, 0);
    c.clearRect(0, 0, this.W, this.H);
    if (!this.nodes.size) {
      c.fillStyle = "#8a8a8a"; c.font = "13px sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
      c.fillText(this.note || "等待数据…", this.W / 2, this.H / 2); return;
    }
    const nodes = [...this.nodes.values()];
    const king = nodes.reduce((a, b) => Math.abs(this.val(b.it)) > Math.abs(this.val(a.it)) ? b : a);
    for (const nd of nodes) {
      const up = this.val(nd.it) >= 0;
      const rgb = up ? "255,59,48" : "34,224,108";
      // 外发光 + 亮芯暗边渐变
      c.save();
      c.shadowColor = `rgba(${rgb},0.5)`; c.shadowBlur = Math.max(14, nd.r * 0.55);
      const g = c.createRadialGradient(nd.x, nd.y - nd.r * 0.15, nd.r * 0.08, nd.x, nd.y, nd.r);
      g.addColorStop(0, up ? "rgba(255,120,105,.95)" : "rgba(90,245,155,.95)");
      g.addColorStop(0.65, up ? "rgba(215,25,20,.92)" : "rgba(18,185,88,.92)");
      g.addColorStop(1, up ? "rgba(110,6,6,.95)" : "rgba(4,95,45,.95)");
      c.beginPath(); c.arc(nd.x, nd.y, nd.r, 0, 7); c.fillStyle = g; c.fill();
      c.restore();
      c.beginPath(); c.arc(nd.x, nd.y, nd.r, 0, 7);
      c.strokeStyle = "rgba(255,255,255,.10)"; c.lineWidth = 1; c.stroke();
      // 最大泡泡：旋转光环
      if (nd === king) {
        c.save();
        c.shadowColor = `rgba(${rgb},.8)`; c.shadowBlur = 12;
        for (const [k, sp, rr] of [[0, 0.5, 1.18], [1, -0.32, 1.36], [2, 0.22, 1.52]]) {
          c.beginPath();
          c.setLineDash(k === 0 ? [10, 8] : [3, 9]);
          c.arc(nd.x, nd.y, nd.r * rr, t * sp + k, t * sp + k + Math.PI * 1.7);
          c.strokeStyle = `rgba(255,255,255,${0.85 - k * 0.25})`;
          c.lineWidth = k === 0 ? 2 : 1.2; c.stroke();
        }
        c.setLineDash([]); c.restore();
      }
      // 白字
      const fs = Math.max(10, Math.min(15, nd.r / 3));
      c.save();
      c.shadowColor = "rgba(0,0,0,.7)"; c.shadowBlur = 4;
      c.fillStyle = "#fff"; c.textAlign = "center"; c.textBaseline = "middle";
      c.font = `700 ${fs}px -apple-system,'PingFang SC','Microsoft YaHei'`;
      const nm = nd.it.name.length > 6 ? nd.it.name.slice(0, 6) : nd.it.name;
      if (nd.r > 22) {
        c.fillText(nm, nd.x, nd.y - fs * 0.45);
        c.font = `600 ${fs * 0.85}px sans-serif`;
        c.fillText(this.label(nd.it), nd.x, nd.y + fs * 0.62);
      } else if (nd.r > 13) c.fillText(nm, nd.x, nd.y);
      c.restore();
    }
  }
  loop() {
    // 定型后冻结：只有数据变化才重新布局，屏幕不再一直动
    if (!this.frozen) {
      this.physics();
      if (this.tick++ > 30) {
        const nodes = [...this.nodes.values()];
        const energy = nodes.reduce((s, n) => s + Math.abs(n.vx) + Math.abs(n.vy) + Math.abs(n.tR - n.r), 0);
        if (nodes.length && energy < 0.6) this.frozen = true;
      }
    }
    this.draw();
    requestAnimationFrame(() => this.loop());
  }
  onClick(e) {
    const rect = this.cv.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top;
    let best = null, bd = 1e9;
    for (const nd of this.nodes.values()) {
      const d = Math.hypot(nd.x - x, nd.y - y);
      if (d < nd.r && d < bd) { best = nd; bd = d; }
    }
    if (best) openBoard(best.it);
  }
}

let chartPct, chartFlow;
function typeFilter(items) {
  const t = localStorage.getItem("boardType") || "all";
  return items.filter(i => t === "all" || i.type === t || (t === "concept" && i.type === "concept") || (t === "industry" && i.type === "industry"));
}
let lastBoardsSig = "";
function renderCharts(data) {
  boardsAll = data.items || [];
  // 数据没变化就不重排泡泡，屏幕保持安静
  const sig = data.source + "|" + JSON.stringify(boardsAll.map(i => [i.code, i.pct, i.main_in, i.heat]));
  if (sig === lastBoardsSig && chartPct.nodes.size) return;
  lastBoardsSig = sig;
  const limited = data.source === "zt_pool_fallback" || data.source === "offline";
  const note = limited ? "板块接口限流中，自动恢复后立即显示（后台每5秒重试）" : "";
  const mk = chart => {
    if (chart.mode === "pct") {
      const withPct = typeFilter(boardsAll.filter(i => i.pct != null));
      if (withPct.length) chart.setData(withPct.sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct)).slice(0, 13), "");
      else chart.setData(typeFilter(boardsAll.filter(i => i.heat != null)).sort((a, b) => b.heat - a.heat).slice(0, 13),
        limited ? "板块涨幅接口限流：当前按昨日涨停行业热度展示（N家涨停），恢复后自动切回涨跌幅" : "");
    } else {
      const withFlow = typeFilter(boardsAll.filter(i => i.main_in != null));
      chart.setData(withFlow.sort((a, b) => Math.abs(b.main_in) - Math.abs(a.main_in)).slice(0, 13),
        withFlow.length ? "" : "资金流依赖东财接口，限流中，每5秒自动重试");
    }
  };
  mk(chartPct); mk(chartFlow);
}

/* ---------- 数据轮询 ---------- */
async function jget(u) { const r = await fetch(u); if (!r.ok) throw new Error(await r.text()); return r.json(); }
async function jpost(u) { const r = await fetch(u, { method: "POST" }); if (!r.ok) throw new Error(await r.text()); return r.json(); }

async function pollStatus() {
  try {
    const s = await jget("/api/status");
    $("#statusDot").className = "dot " + (s.trading ? "live" : "closed");
    $("#statusTxt").textContent = `${s.trading ? "盘中" : "休市"} · 快照${s.snapshot_n}只(${s.snapshot_src}) · 板块${s.boards_src} · ${s.snapshot_loading ? "快照刷新中" : "更新 " + (s.boards_at || "")}`;
  } catch (e) { $("#statusTxt").textContent = "后端未连接"; }
}
async function pollIndices() {
  try {
    const d = await jget("/api/indices");
    $("#ticker").textContent = d.items.map(i => `${i.name} ${i.pct > 0 ? "+" : ""}${i.pct}%`).join("  |  ") || "—";
    $("#fabIdx").textContent = d.items.slice(0, 3).map(i => `${i.name} ${i.pct > 0 ? "+" : ""}${i.pct}%`).join(" / ");
    const sh = d.items.find(i => i.sym === "sh000001" || i.sym === "000001");
    if (sh) {
      $("#hdIdx").textContent = `上证指数 ${sh.pct > 0 ? "▲" : "▼"}${Math.abs(sh.pct)}%`;
      $("#hdIdx").style.color = sh.pct >= 0 ? "#ff6b60" : "#2ee584";
    }
    const n = new Date();
    $("#hdDate").textContent = `${String(n.getMonth() + 1).padStart(2, "0")}月${String(n.getDate()).padStart(2, "0")}日`;
    $("#hdTime").textContent = `${String(n.getHours()).padStart(2, "0")}:${String(n.getMinutes()).padStart(2, "0")}`;
  } catch (e) {}
}
async function pollBoards() {
  try { renderCharts(await jget("/api/boards")); } catch (e) {}
}
async function pollEtf() {
  try {
    const d = await jget("/api/etf");
    const list = (d.items || []).filter(x => x.groups.includes(etfGroup));
    const html = list.map(x => `
      <div class="stock-item">
        <div class="st-top"><span class="st-name">${esc(x.name)}</span><span class="st-code">${x.code}</span>
          <span class="st-price">${x.price ?? "-"}</span>
          <span class="pct ${x.pct >= 0 ? "up" : "down"}">${x.pct == null ? "-" : (x.pct > 0 ? "+" : "") + x.pct + "%"}</span></div>
        <div class="st-why">${esc(x.reason)}</div>
      </div>`).join("") || '<div class="empty">该周期暂无标的</div>';
    setIfChanged($("#etfList"), html);
  } catch (e) {}
}
async function pollNews() {
  try {
    const d = await jget("/api/news");
    $("#newsMeta").textContent = "更新 " + d.updated;
    const html = (d.items || []).map(n => `
      <div class="news-item"><span class="tag ${n.tag}">${{ good: "利好", bad: "利空", mid: "快讯" }[n.tag]}</span>
      <span class="news-title">${esc(n.title)}</span><span class="news-time">${esc((n.time || "").slice(-8, -3))}</span></div>`).join("")
      || '<div class="empty">暂无快讯</div>';
    setIfChanged($("#newsList"), html);
  } catch (e) {}
}
async function pollAlerts() {
  if (!PROFILE) return;
  try {
    const d = await jget(`/api/alerts?name=${encodeURIComponent(PROFILE.name)}&pin=${encodeURIComponent(PROFILE.pin)}`);
    PROFILE.alerts = d.alerts; localStorage.setItem("profile", JSON.stringify(PROFILE));
    const hit = d.alerts.filter(a => a.triggered_at);
    $("#alertBar").classList.toggle("hidden", !hit.length);
    if (hit.length) $("#alertBar").innerHTML = "🔔 提醒触发：" + hit.map(a => `${a.code} ${a.dir === "above" ? "≥" : "≤"} ${a.price} @ ${a.triggered_at}`).join("；");
  } catch (e) {}
}

/* ---------- 板块详情 ---------- */
function chipBtns(el, key, storeKey) {
  el.innerHTML = ["all", "concept", "industry"].map(t =>
    `<button data-t="${t}" class="${t === (localStorage.getItem(storeKey) || "all") ? "on" : ""}">${{ all: "全部", concept: "概念", industry: "行业" }[t]}</button>`).join("");
  el.querySelectorAll("button").forEach(b => b.onclick = () => {
    localStorage.setItem(storeKey, b.dataset.t); chipBtns(el, key, storeKey); pollBoards();
  });
}
function stockRow(s) {
  const st = s.strategies?.[curStrat] || { score: 0, why: [], risk: "", fail: "" };
  const starred = PROFILE?.watchlist?.includes(s.code);
  return `<div class="stock-item" data-code="${s.code}">
    <div class="st-top">
      <button class="star ${starred ? "on" : ""}" onclick="toggleStar('${s.code}',this)">★</button>
      <span class="st-name">${esc(s.name)}</span><span class="st-code">${s.code}</span>
      <span class="pct ${s.pct >= 0 ? "up" : "down"}">${s.pct == null ? "-" : (s.pct > 0 ? "+" : "") + s.pct.toFixed(2) + "%"}</span>
      <span class="st-price">${s.price ?? "-"} 元</span>
      <span class="score">${{ cs: "超短", short: "短线", mid: "中线", long: "长线" }[curStrat]} ${st.score}</span>
    </div>
    <div class="st-mid"><span>成交 ${fmtYi(s.amount)}</span><span>换手 ${s.turnover != null ? s.turnover.toFixed(1) + "%" : "-"}</span>
      ${s.main_in != null ? `<span>主力 ${fmtYi(s.main_in)}</span>` : ""}${s.pe ? `<span>PE ${s.pe.toFixed(0)}</span>` : ""}${s.chg60 != null ? `<span>60日 ${s.chg60 > 0 ? "+" : ""}${s.chg60.toFixed(1)}%</span>` : ""}</div>
    <div class="st-why">入选：${esc((st.why || []).join("；"))}</div>
    <div class="st-rf">⚠ ${esc(st.risk)}｜失效：${esc(st.fail)}
      <a href="javascript:void(0)" onclick="quickAlert('${s.code}',${s.price ?? 0})" style="margin-left:8px">🔔提醒</a></div>
  </div>`;
}
async function openBoard(it) {
  curStrat = "cs"; curBoard = it.code;
  $("#drawer").classList.remove("hidden");
  $("#dwTitle").textContent = it.name;
  $("#dwMeta").textContent = "仅显示：主板 · 非ST · " + (PROFILE ? `${PROFILE.pmin}~${PROFILE.pmax}元` : "全部价格（先去【我的】设定区间）");
  $("#dwList").innerHTML = '<div class="empty">加载成分股…</div>';
  const key = PROFILE ? PROFILE.pmin + "-" + PROFILE.pmax : "0-99999";
  try {
    const d = await jget(`/api/board/${encodeURIComponent(it.code)}?pmin=${PROFILE?.pmin ?? 0}&pmax=${PROFILE?.pmax ?? 99999}`);
    boardCache[it.code] = d;
    $("#dwNote").textContent = d.note || (d.limited ? "数据源限流中，成分可能不全" : `共 ${d.stocks.length} 只符合条件`);
    renderBoardList();
  } catch (e) {
    $("#dwList").innerHTML = `<div class="empty">加载失败：${esc(e.message).slice(0, 120)}</div>`;
  }
}
function renderBoardList() {
  const d = curBoard ? boardCache[curBoard] : null; if (!d) return;
  const arr = [...d.stocks].sort((a, b) => (b.strategies?.[curStrat]?.score || 0) - (a.strategies?.[curStrat]?.score || 0));
  $("#dwList").innerHTML = arr.map(stockRow).join("") || '<div class="empty">没有符合你价格区间的股票，试试放宽区间</div>';
}
$("#stratTabs").addEventListener("click", e => {
  if (e.target.dataset.s) {
    curStrat = e.target.dataset.s;
    $("#stratTabs").querySelectorAll("button").forEach(b => b.classList.toggle("on", b === e.target));
    renderBoardList();
  }
});
$("#dwClose").onclick = () => $("#drawer").classList.add("hidden");

/* ---------- 我的 ---------- */
function openMe() {
  $("#fabPanel").classList.add("hidden");
  $("#me").classList.remove("hidden");
  if (PROFILE) { $("#pfName").value = PROFILE.name; $("#pfPin").value = PROFILE.pin; $("#pfMin").value = PROFILE.pmin; $("#pfMax").value = PROFILE.pmax; renderMe(); }
}
$("#meClose").onclick = () => $("#me").classList.add("hidden");
$("#btnMe").onclick = openMe;
$("#pfSave").onclick = async () => {
  const name = $("#pfName").value.trim(), pin = $("#pfPin").value.trim(),
    pmin = parseFloat($("#pfMin").value || 0), pmax = parseFloat($("#pfMax").value || 20);
  if (!name || pin.length < 4) { $("#pfMsg").textContent = "需要昵称+至少4位口令"; return; }
  try {
    await jpost(`/api/profile?name=${encodeURIComponent(name)}&pin=${encodeURIComponent(pin)}&pmin=${pmin}&pmax=${pmax}`);
    PROFILE = { ...(PROFILE || {}), name, pin, pmin, pmax };
    localStorage.setItem("profile", JSON.stringify(PROFILE));
    const d = await jget(`/api/profile?name=${encodeURIComponent(name)}&pin=${encodeURIComponent(pin)}`);
    PROFILE.watchlist = d.watchlist; PROFILE.alerts = d.alerts;
    localStorage.setItem("profile", JSON.stringify(PROFILE));
    $("#pfMsg").textContent = `已保存：${pmin}~${pmax}元，主板池自动过滤`;
    renderMe(); toast("设定已保存");
  } catch (e) { $("#pfMsg").textContent = "保存失败：" + e.message.slice(0, 80); }
};
function renderMe() {
  if (!PROFILE) return;
  $("#meWatch").innerHTML = (PROFILE.watchlist || []).map(c =>
    `<div class="stock-item st-top"><span class="st-name">${c}</span><button class="ghost-btn" onclick="delWatch('${c}')">移除</button></div>`).join("") || '<div class="note">还没有自选股，在板块详情里点 ★ 收藏</div>';
  $("#meAlerts").innerHTML = (PROFILE.alerts || []).map(a =>
    `• ${a.code} ${a.dir === "above" ? "≥" : "≤"} ${a.price} ${a.triggered_at ? `<b style="color:#ffd479">已触发@${a.triggered_at}</b>` : "监控中"}`).join("<br>") || "暂无提醒";
}
async function toggleStar(code, btn) {
  if (!PROFILE) { toast("先在【我的】保存昵称与口令"); return; }
  const add = !PROFILE.watchlist?.includes(code);
  try {
    await jpost(`/api/watchlist?name=${encodeURIComponent(PROFILE.name)}&pin=${encodeURIComponent(PROFILE.pin)}&code=${code}&action=${add ? "add" : "del"}`);
    PROFILE.watchlist = add ? [...(PROFILE.watchlist || []), code] : (PROFILE.watchlist || []).filter(c => c !== code);
    localStorage.setItem("profile", JSON.stringify(PROFILE));
    btn.classList.toggle("on", add); renderMe();
  } catch (e) { toast("失败：" + e.message.slice(0, 60)); }
}
async function delWatch(code) {
  await jpost(`/api/watchlist?name=${encodeURIComponent(PROFILE.name)}&pin=${encodeURIComponent(PROFILE.pin)}&code=${code}&action=del`);
  PROFILE.watchlist = PROFILE.watchlist.filter(c => c !== code);
  localStorage.setItem("profile", JSON.stringify(PROFILE)); renderMe();
}
async function quickAlert(code, price) {
  if (!PROFILE) { toast("先在【我的】保存昵称与口令"); return; }
  const p = prompt(`提醒价（当前 ${price}）：`, price);
  if (!p) return;
  const dir = parseFloat(p) >= price ? "above" : "below";
  await jpost(`/api/alert?name=${encodeURIComponent(PROFILE.name)}&pin=${encodeURIComponent(PROFILE.pin)}&code=${code}&price=${p}&direction=${dir}`);
  toast("提醒已加，盘中自动检测"); pollAlerts();
}
$("#alAdd").onclick = async () => {
  const code = $("#alCode").value.trim(), price = parseFloat($("#alPrice").value), dir = $("#alDir").value;
  if (!code || !price || !PROFILE) { toast("先保存设定并填写代码/价格"); return; }
  await jpost(`/api/alert?name=${encodeURIComponent(PROFILE.name)}&pin=${encodeURIComponent(PROFILE.pin)}&code=${code}&price=${price}&direction=${dir}`);
  pollAlerts(); renderMe(); toast("已加提醒");
};

/* ---------- ETF ---------- */
$("#etfTabs").addEventListener("click", e => {
  if (e.target.dataset.g) {
    etfGroup = e.target.dataset.g;
    $("#etfTabs").querySelectorAll("button").forEach(b => b.classList.toggle("on", b === e.target));
    pollEtf();
  }
});

/* ---------- 悬浮窗 ---------- */
$("#fab").onclick = () => $("#fabPanel").classList.toggle("hidden");
function jump(sel) { $("#fabPanel").classList.add("hidden"); document.querySelector(sel).scrollIntoView({ behavior: "smooth" }); }
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 2600);
}

/* ---------- 登录门 ---------- */
async function requireLogin() {
  if (PROFILE) {
    try {
      const d = await jget(`/api/profile?name=${encodeURIComponent(PROFILE.name)}&pin=${encodeURIComponent(PROFILE.pin)}`);
      PROFILE.pmin = d.pmin; PROFILE.pmax = d.pmax;
      PROFILE.watchlist = d.watchlist; PROFILE.alerts = d.alerts;
      localStorage.setItem("profile", JSON.stringify(PROFILE));
      applyProfileUI();
      return true;
    } catch (e) { PROFILE = null; localStorage.removeItem("profile"); }
  }
  $("#login").classList.remove("hidden");
  return false;
}
function applyProfileUI() {
  $("#btnMe").textContent = "我的·" + PROFILE.name;
  $("#pfName").value = PROFILE.name; $("#pfPin").value = PROFILE.pin;
  $("#pfMin").value = PROFILE.pmin; $("#pfMax").value = PROFILE.pmax;
  if (!localStorage.getItem("introSeen")) {
    $("#intro").classList.remove("hidden");
    localStorage.setItem("introSeen", "1");
    setTimeout(() => $("#intro").classList.add("hidden"), 15000);
  }
}
$("#lgGo").onclick = async () => {
  const name = $("#lgName").value.trim(), pin = $("#lgPin").value.trim();
  if (!name || !pin) { $("#lgMsg").textContent = "请填昵称和口令"; return; }
  try {
    const d = await jget(`/api/profile?name=${encodeURIComponent(name)}&pin=${encodeURIComponent(pin)}`);
    PROFILE = { name, pin, pmin: d.pmin, pmax: d.pmax, watchlist: d.watchlist, alerts: d.alerts };
    localStorage.setItem("profile", JSON.stringify(PROFILE));
    $("#login").classList.add("hidden");
    applyProfileUI(); renderMe(); pollAlerts();
    toast(`欢迎，${name}｜区间 ${d.pmin}~${d.pmax} 元`);
  } catch (e) { $("#lgMsg").textContent = "登录失败：昵称或口令不对"; }
};
$("#lgPin").addEventListener("keydown", e => { if (e.key === "Enter") $("#lgGo").click(); });
$("#pfLogout").onclick = () => {
  PROFILE = null; localStorage.removeItem("profile"); localStorage.removeItem("introSeen");
  $("#btnMe").textContent = "我的";
  $("#me").classList.add("hidden");
  $("#login").classList.remove("hidden");
};
$("#intro").onclick = () => $("#intro").classList.add("hidden");

/* ---------- 启动 ---------- */
chartPct = new Bubbles($("#cvPct"), "pct");
chartFlow = new Bubbles($("#cvFlow"), "flow");
chipBtns($("#typeChips1"), "pct", "boardType");
chipBtns($("#typeChips2"), "flow", "boardType");
pollStatus(); pollIndices(); pollBoards(); pollEtf(); pollNews();
requireLogin();          // 有档案则静默校验并恢复，无档案弹登录门
setInterval(pollStatus, 10000);
setInterval(pollIndices, 10000);
setInterval(pollBoards, 10000);
setInterval(pollEtf, 10000);
setInterval(pollNews, 30000);
setInterval(pollAlerts, 30000);
