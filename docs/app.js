/* 关机简版：静态 feed.json 渲染 */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[<>&"]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));
const fmtYi = v => v == null ? "-" : (v / 1e8).toFixed(Math.abs(v) / 1e8 >= 10 ? 1 : 2) + "亿";
let FEED = null, etfGroup = "cs";

/* 条形榜（同完整版样式） */
function barRows(el, rows, fmt, clickable) {
  const max = Math.max(...rows.map(r => Math.abs(r.v)), 1e-9);
  el.innerHTML = rows.map((r, i) => `<div class="bar-row"><span class="rank ${i < 3 ? "top" : ""}">${i + 1}</span>
    <span class="btag ${r.up ? "in" : "out"}">${r.label2 || (r.up ? "流入" : "流出")}</span>
    <span class="bname">${esc(r.name)}</span>
    <div class="btrack"><div class="bfill ${r.up ? "red" : "green"}" style="width:${Math.max(4, Math.abs(r.v) / max * 100)}%"></div></div>
    <span class="bval">${fmt(r)}</span></div>`).join("");
}

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
  const withPct = items.filter(i => i.pct != null).sort((a, b) => b.pct - a.pct).slice(0, 12);
  barRows($("#barPct"), withPct.map(i => ({ name: i.name, up: i.pct >= 0, v: i.pct })), r => (r.v > 0 ? "+" : "") + r.v.toFixed(1) + "%");
  const fl = items.filter(i => i.main_in != null).sort((a, b) => b.main_in - a.main_in);
  barRows($("#barFlow"), fl.slice(0, 10).map(i => ({ name: i.name, up: true, v: i.main_in / 1e8, label2: "流入" }))
    .concat(fl.slice(-10).reverse().map(i => ({ name: i.name, up: false, v: i.main_in / 1e8, label2: "流出" }))),
    r => (r.v > 0 ? "+" : "-") + Math.abs(r.v).toFixed(1) + "亿");

  const s = FEED.sentiment || {}, b = FEED.breadth || {};
  $("#envBox").innerHTML = `涨跌家数 ${b.up ?? "-"} / ${b.down ?? "-"} · 成交 ${b.amount_yi ?? "-"} 亿 · 涨停 ${s.zt_n ?? "-"} 家${s.break_rate != null ? ` · 炸板率 ${s.break_rate}%` : ""}${s.premium != null ? ` · 昨涨停溢价 ${s.premium > 0 ? "+" : ""}${s.premium}%` : ""}<br>情绪阶段：<b>${esc(s.stage || "-")}</b> → ${esc(s.advice || "")}
  ${(FEED.rotation || []).map(r => `<br>【${r.pair}】${r.a} vs ${r.b} → ${r.side}`).join("")}`;

  const byStrat = { cs: [], short: [], mid: [], long: [] };
  (FEED.candidates || []).forEach(x => (byStrat[x.strategy] || byStrat.short).push(x));
  $("#candList").innerHTML = ["cs", "short", "mid", "long"].map(k => (byStrat[k] || []).slice(0, 5).map(x => {
    const st = x.strategies || {};
    const ag = x.agents;
    const stratName = { cs: "超短", short: "短线", mid: "中线", long: "长线" }[k];
    const agHtml = ag ? `<div class="st-why">🤖 研判：<b style="color:${ag.verdict === "偏多" ? "#ff8a80" : ag.verdict === "偏空" ? "#5fe8a8" : "#ffd479"}">${ag.verdict}</b>（置信 ${ag.confidence}${ag.llm_enhanced ? "+LLM" : ""}）
      ${Object.entries(ag.roles).map(([k2, v]) => `${k2}:${v.view}`).join(" · ")}
      <br>多头：${esc((ag.bull || []).join("；"))}<br>空头：${esc((ag.bear || []).join("；"))}</div>` : "";
    return `<div class="stock-item"><div class="st-top"><span class="st-name">${esc(x.name)}</span><span class="st-code">${x.code}</span>
    <span class="pct ${x.pct >= 0 ? "up" : "down"}">${x.pct > 0 ? "+" : ""}${(x.pct ?? 0).toFixed(2)}%</span>
    <span class="st-price">${x.price ?? "-"}元</span>
    <span class="score">${stratName} ${st[k]?.score ?? 0}</span></div>
    <div class="st-why">${esc((st[k]?.why || []).join("；"))}</div>
    <div class="st-rf">⚠ ${esc(st[k]?.risk || "")}｜失效：${esc(st[k]?.fail || "")}</div>${agHtml}</div>`;
  }).join("")).join("") || '<div class="empty">本时段无符合条件的候选</div>';

  renderEtf();
  $("#newsList").innerHTML = (FEED.news || []).map(n =>
    `<div class="news-item"><span class="tag ${n.tag}">${{ good: "利好", bad: "利空", mid: "快讯" }[n.tag]}</span><span class="news-title">${esc(n.title)}</span>
    ${(n.sectors || []).map(s => `<span class="tag mid">${esc(s)}</span>`).join("")}</div>`).join("")
    + `<div class="st-rf" style="margin-top:6px">已过滤无关快讯 ${FEED.news_dropped ?? 0} 条 ｜ 板块归类：${Object.keys(FEED.news_by_sector || {}).map(k => `${k}×${(FEED.news_by_sector[k] || []).length}`).join("、") || "暂无"}</div>`;

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
