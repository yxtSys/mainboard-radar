/* 关机简版：静态 feed.json 渲染 */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[<>&"]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));
const fmtYi = v => v == null ? "-" : (v / 1e8).toFixed(Math.abs(v) / 1e8 >= 10 ? 1 : 2) + "亿";
let FEED = null, etfGroup = "cs";

/* 泡泡（与完整版同款物理+霓虹，精简版） */
class Bubbles {
  constructor(canvas, mode) {
    this.cv = canvas; this.ctx = canvas.getContext("2d"); this.mode = mode;
    this.nodes = new Map(); this.resize();
    addEventListener("resize", () => this.resize());
    canvas.addEventListener("click", e => {
      const r = this.cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      for (const nd of this.nodes.values()) if (Math.hypot(nd.x - x, nd.y - y) < nd.r) {
        alert(`${nd.it.name}\n${this.label(nd.it)}`); return;
      }
    });
    requestAnimationFrame(() => this.loop());
  }
  resize() {
    const r = this.cv.getBoundingClientRect(), d = devicePixelRatio || 1;
    this.cv.width = r.width * d; this.cv.height = r.height * d;
    this.W = r.width; this.H = r.height; this.d = d;
  }
  val(it) { return this.mode === "pct" ? (it.pct ?? it.heat ?? 0) : (it.main_in ?? 0) / 1e8; }
  label(it) {
    if (this.mode === "pct") return it.pct == null ? "" : (it.pct > 0 ? "+" : "") + it.pct.toFixed(1) + "%";
    return it.main_in == null ? "" : ((it.main_in > 0 ? "+" : "-") + fmtYi(Math.abs(it.main_in)));
  }
  setData(items) {
    const maxV = Math.max(...items.map(i => Math.abs(this.val(i))), 1e-9);
    const R = Math.min(this.W, this.H) / 2, rMax = R * 0.42 * (this.W < 500 ? 0.76 : 1), rMin = R * 0.15;
    const seen = new Set();
    items.forEach(it => {
      const id = it.code || it.name, tR = rMin + (rMax - rMin) * Math.sqrt(Math.abs(this.val(it)) / maxV);
      seen.add(id);
      let nd = this.nodes.get(id);
      if (!nd) { nd = { x: this.W / 2, y: this.H / 2, r: 1, vx: 0, vy: 0, tR: 1 }; this.nodes.set(id, nd); }
      nd.it = it; nd.tR = tR;
    });
    for (const [id, nd] of this.nodes) if (!seen.has(id)) this.nodes.delete(id);
  }
  loop() {
    const nodes = [...this.nodes.values()], cx = this.W / 2;
    nodes.forEach(nd => { nd.r += (nd.tR - nd.r) * 0.12; });
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || .01, min = a.r + b.r + 2;
      if (d < min) { const p = (min - d) / d * .5, ma = a.r ** 2, mb = b.r ** 2, s = ma + mb;
        a.x -= dx * p * (mb / s) * 2; a.y -= dy * p * (mb / s) * 2; b.x += dx * p * (ma / s) * 2; b.y += dy * p * (ma / s) * 2; }
    }
    nodes.forEach(nd => {
      const ty = this.H * (this.val(nd.it) >= 0 ? .36 : .70);
      nd.vx = (nd.vx + (cx - nd.x) * .004 * (nd.r / 40)) * .86;
      nd.vy = (nd.vy + (ty - nd.y) * .005 * (nd.r / 40)) * .86;
      nd.x = Math.max(nd.r, Math.min(this.W - nd.r, nd.x + nd.vx));
      nd.y = Math.max(nd.r, Math.min(this.H - nd.r, nd.y + nd.vy));
    });
    const c = this.ctx; c.setTransform(this.d, 0, 0, this.d, 0, 0);
    c.clearRect(0, 0, this.W, this.H);
    for (const nd of nodes) {
      const up = this.val(nd.it) >= 0, rgb = up ? "255,59,48" : "34,224,108";
      c.save(); c.shadowColor = `rgba(${rgb},.5)`; c.shadowBlur = Math.max(14, nd.r * .55);
      const g = c.createRadialGradient(nd.x, nd.y - nd.r * .15, nd.r * .08, nd.x, nd.y, nd.r);
      g.addColorStop(0, up ? "rgba(255,120,105,.95)" : "rgba(90,245,155,.95)");
      g.addColorStop(.65, up ? "rgba(215,25,20,.92)" : "rgba(18,185,88,.92)");
      g.addColorStop(1, up ? "rgba(110,6,6,.95)" : "rgba(4,95,45,.95)");
      c.beginPath(); c.arc(nd.x, nd.y, nd.r, 0, 7); c.fillStyle = g; c.fill(); c.restore();
      const fs = Math.max(10, Math.min(14, nd.r / 3));
      c.save(); c.shadowColor = "rgba(0,0,0,.7)"; c.shadowBlur = 4; c.fillStyle = "#fff";
      c.textAlign = "center"; c.textBaseline = "middle";
      c.font = `700 ${fs}px 'PingFang SC','Microsoft YaHei',sans-serif`;
      const nm = nd.it.name.length > 6 ? nd.it.name.slice(0, 6) : nd.it.name;
      if (nd.r > 22) { c.fillText(nm, nd.x, nd.y - fs * .45); c.font = `600 ${fs * .85}px sans-serif`; c.fillText(this.label(nd.it), nd.x, nd.y + fs * .62); }
      else if (nd.r > 13) c.fillText(nm, nd.x, nd.y);
      c.restore();
    }
    requestAnimationFrame(() => this.loop());
  }
}
let chartPct, chartFlow;

async function load() {
  try {
    FEED = await (await fetch("data/feed.json?t=" + Date.now())).json();
  } catch (e) { $("#meta").textContent = "feed 加载失败，稍后自动重试"; return; }
  const n = new Date();
  $("#hdDate").textContent = `${String(n.getMonth() + 1).padStart(2, "0")}月${String(n.getDate()).padStart(2, "0")}日`;
  $("#hdGen").textContent = FEED.generated ? FEED.generated.slice(11) : "--";
  const sh = (FEED.indices || []).find(i => i.name && i.name.includes("上证"));
  $("#hdIdx").textContent = sh ? `上证指数 ${sh.pct > 0 ? "▲" : "▼"}${Math.abs(sh.pct)}%` : "";
  $("#hdIdx").style.color = sh && sh.pct >= 0 ? "#ff6b60" : "#2ee584";
  $("#meta").textContent = `数据时间 ${FEED.generated}${FEED.trade_day ? "（交易日）" : "（休市）"} · 来源 ${JSON.stringify(FEED.sources)} · 云端每5分钟自动更新`;

  const items = (FEED.boards || []);
  chartPct.setData(items.filter(i => i.pct != null).sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct)).slice(0, 13));
  chartFlow.setData(items.filter(i => i.main_in != null).sort((a, b) => Math.abs(b.main_in) - Math.abs(a.main_in)).slice(0, 13));

  const s = FEED.sentiment || {}, b = FEED.breadth || {};
  $("#envBox").innerHTML = `涨跌家数 ${b.up ?? "-"} / ${b.down ?? "-"} · 成交 ${b.amount_yi ?? "-"} 亿 · 涨停 ${s.zt_n ?? "-"} 家${s.break_rate != null ? ` · 炸板率 ${s.break_rate}%` : ""}${s.premium != null ? ` · 昨涨停溢价 ${s.premium > 0 ? "+" : ""}${s.premium}%` : ""}<br>情绪阶段：<b>${esc(s.stage || "-")}</b> → ${esc(s.advice || "")}
  ${(FEED.rotation || []).map(r => `<br>【${r.pair}】${r.a} vs ${r.b} → ${r.side}`).join("")}`;

  $("#candList").innerHTML = (FEED.candidates || []).map(x => {
    const st = x.strategies || {};
    const ag = x.agents;
    const agHtml = ag ? `<div class="st-why">🤖 研判：<b style="color:${ag.verdict === "偏多" ? "#ff8a80" : ag.verdict === "偏空" ? "#5fe8a8" : "#ffd479"}">${ag.verdict}</b>（置信 ${ag.confidence}${ag.llm_enhanced ? "+LLM" : ""}）
      ${Object.entries(ag.roles).map(([k, v]) => `${k}:${v.view}`).join(" · ")}
      <br>多头：${esc((ag.bull || []).join("；"))}<br>空头：${esc((ag.bear || []).join("；"))}</div>` : "";
    return `<div class="stock-item"><div class="st-top"><span class="st-name">${esc(x.name)}</span><span class="st-code">${x.code}</span>
    <span class="pct ${x.pct >= 0 ? "up" : "down"}">${x.pct > 0 ? "+" : ""}${(x.pct ?? 0).toFixed(2)}%</span>
    <span class="st-price">${x.price ?? "-"}元</span>
    <span class="score">超${st.cs?.score ?? 0} 短${st.short?.score ?? 0} 中${st.mid?.score ?? 0} 长${st.long?.score ?? 0}</span></div>
    <div class="st-why">${esc((st.cs?.why || []).join("；"))}</div>
    <div class="st-rf">⚠ ${esc(st.cs?.risk || "")}｜失效：${esc(st.cs?.fail || "")}</div>${agHtml}</div>`;
  }).join("") || '<div class="empty">本时段无符合条件的候选</div>';

  renderEtf();
  $("#newsList").innerHTML = (FEED.news || []).map(n =>
    `<div class="news-item"><span class="tag ${n.tag}">${{ good: "利好", bad: "利空", mid: "快讯" }[n.tag]}</span><span class="news-title">${esc(n.title)}</span></div>`).join("");

  // 因子公式表 + 溯源（全部可追究原文）
  const fr = FEED.factors_registry || [];
  const pv = FEED.provenance || {};
  if (!$("#factorBox")) {
    const det = document.createElement("details");
    det.className = "card"; det.innerHTML = `<summary style="cursor:pointer"><b>📐 因子库与数据溯源（点开）</b></summary><div id="factorBox"></div><div id="provBox" class="st-rf"></div>`;
    document.querySelector("main").appendChild(det);
  }
  $("#factorBox").innerHTML = `<table style="width:100%;font-size:11.5px;border-collapse:collapse">` +
    `<tr style="color:var(--sub)"><td style="padding:3px">因子</td><td>公式</td><td>来源</td></tr>` +
    fr.map(f => `<tr style="border-top:1px solid var(--line)"><td style="padding:3px">${esc(f.name)}</td><td>${esc(f.formula)}</td><td style="color:var(--sub)">${esc(f.source)}</td></tr>`).join("") + `</table>`;
  $("#provBox").innerHTML = "溯源：" + Object.entries(pv).map(([k, v]) => `${k}=${esc(v)}`).join(" · ");
}
function renderEtf() {
  const list = (FEED.etf || []).filter(x => x.groups.includes(etfGroup));
  $("#etfList").innerHTML = list.map(x => `<div class="stock-item"><div class="st-top"><span class="st-name">${esc(x.name)}</span><span class="st-code">${x.code}</span>
  <span class="st-price">${x.price ?? "-"}</span><span class="pct ${x.pct >= 0 ? "up" : "down"}">${x.pct == null ? "-" : (x.pct > 0 ? "+" : "") + x.pct + "%"}</span></div>
  <div class="st-why">${esc(x.reason)}</div></div>`).join("");
}
$("#etfTabs").addEventListener("click", e => {
  if (e.target.dataset.g) { etfGroup = e.target.dataset.g;
    $("#etfTabs").querySelectorAll("button").forEach(b => b.classList.toggle("on", b === e.target)); renderEtf(); }
});
chartPct = new Bubbles($("#cvPct"), "pct");
chartFlow = new Bubbles($("#cvFlow"), "flow");
load(); setInterval(load, 60000);
