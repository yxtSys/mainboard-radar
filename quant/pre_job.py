# -*- coding: utf-8 -*-
"""9:12 竞价前简报（云端）：昨日涨停池角色分类 + 计划锚定区间 + 消息面 + 纪律。无竞价数据。"""
import datetime as dt
import os
import smtplib
import sys
import warnings
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "quant"))
import emdata as em  # noqa: E402
import morning_rules  # noqa: E402

BJ = ZoneInfo("Asia/Shanghai")
now = dt.datetime.now(BJ)
today = now.strftime("%Y%m%d")
MAIN = ("600", "601", "603", "605", "000", "001", "002", "003")
L = []


def build():
    force = os.environ.get("FORCE_RUN") == "1"
    if not em.is_trade_date(today) and not force:
        print("非交易日，休市")
        return None
    prev_day = em.prev_trade_date(today)
    L.append(f"# 竞价前作战计划 {now.strftime('%Y-%m-%d %H:%M')}（9:25 前看完）")
    L.append("")
    try:
        zt = em.zt_pool(prev_day)
    except Exception:
        L.append("⚠ 涨停池缺源，今日计划降级为观察模式")
        zt = []
    max_lbc = max((int(z.get("lbc") or 1) for z in zt), default=0)
    rows = []
    for z in zt:
        code = str(z.get("code"))
        if not code.startswith(MAIN) or "ST" in str(z.get("name", "")):
            continue
        lbc = int(z.get("lbc") or 1)
        amt = float(z.get("amount") or 0)
        seal = float(z.get("seal_money") or 0)
        fc = round(seal / amt, 2) if amt else 0
        brk = int(z.get("break_times") or 0)
        role = "空间龙头" if lbc == max_lbc else ("中军" if amt / 1e8 >= 10 else "卡位/补涨")
        rows.append({"code": code, "name": z.get("name"), "lbc": lbc, "fc": fc, "brk": brk,
                     "amt": round(amt / 1e8, 2), "ind": z.get("industry", ""), "role": role})
    hit, watch = [], []
    for r in rows:
        tags = []
        if r["lbc"] >= 3 and r["brk"] == 0 and r["fc"] > 0.5:
            tags.append("D7(82.1%)")
        if 3 <= r["lbc"] <= 4 and r["brk"] == 0:
            tags.append("D10(80.6%)")
        if r["lbc"] == max_lbc:
            tags.append("D9(78.9%)")
        if r["lbc"] >= 2 and r["fc"] > 0.5:
            tags.append("C2(75.0%)")
        if r["lbc"] == 1 and r["fc"] > 1:
            tags.append("D2(72.0%)")
        if r["lbc"] >= 2 and r["brk"] == 0 and 5 <= (r["amt"] * 1e8 / max(r["amt"], 1)) and False:
            pass
        r["tags"] = "+".join(tags)
        (hit if tags else watch).append(r)
    L.append("## 一、锚定候选（昨日涨停池，9:25 竞价验证这些票）")
    if hit:
        L.append("| 规则(胜率) | 角色 | 名称/代码 | 板数 | 板块 | 计划 |")
        L.append("|---|---|---|---|---|---|")
        for r in hit[:10]:
            L.append(f"| {r['tags']} | {r['role']} | {r['name']} {r['code']} | {r['lbc']}板 | {r['ind']} | 高开1.5~3.5%可上；>5%放弃 |")
    else:
        L.append("- 无满足锚定的候选 → 竞价若无新主线，执行空仓预案")
    L.append("")
    L.append("## 二、隔夜与盘前环境")
    prem = None
    try:
        prev = em.zt_pool_previous(today)
        pcts = [float(x["pct"]) for x in prev if x.get("pct") is not None]
        prem = round(sum(pcts) / len(pcts), 2) if pcts else None
    except Exception:
        pass
    stage = "进攻期" if (prem or 0) >= 2 else ("退潮防守期" if (prem or 0) <= -0.5 else "震荡期")
    L.append(f"- 情绪周期：昨涨停溢价 {prem if prem is not None else '缺源'}，阶段=**{stage}**（溢价>0才接力；最高板断板→高低切）")
    try:
        fut = em.sina_quotes(["hf_CHA50CFD", "hf_NQ"])
        for k, nm in [("hf_CHA50CFD", "A50期指"), ("hf_NQ", "纳指期货")]:
            v = fut.get(k)
            if v and v.get("price") and v.get("prev"):
                pct = (v["price"] / v["prev"] - 1) * 100
                L.append(f"- {nm} {pct:+.2f}%（{'偏多' if pct > 0.3 else '偏空' if pct < -0.3 else '中性'}）")
    except Exception:
        L.append("- 期指数据缺源")
    try:
        idx = em.index_pct(["sh000001", "sz399006"])
        L.append("- 昨收：" + "，".join(f"{v[0]} {v[1]:+.2f}%" for v in idx.values()))
    except Exception:
        pass
    L.append("")
    L.append("## 三、昨日板块热度（延续性观察）")
    try:
        fl = em.boards("concept") if em else []
        fl = sorted(fl, key=lambda b: -(b.get("main_in") or 0))[:5]
        for b in fl:
            L.append(f"- {b['name']} {b['pct']:+.1f}% 主力{(b.get('main_in') or 0)/1e8:+.1f}亿 领涨{b.get('leader')}")
    except Exception:
        L.append("- 板块数据缺源")
    L.append("")
    L.append("## 四、消息面（财联社，已过滤无关）")
    try:
        from newsfilter import filter_and_tag
        raw = em.news_cls(30)
        items = []
        for n in raw:
            t = (n.get("title") or "").strip() or (n.get("content") or "")[:40]
            if not t:
                continue
            full = t + (n.get("content") or "")
            tag = "bad" if any(w in full for w in ("减持", "立案", "调查", "预亏", "退市", "违约", "制裁")) else \
                ("good" if any(w in full for w in ("利好", "中标", "签订", "订单", "预增", "涨价", "并购", "增持", "回购", "获批", "政策", "降准", "降息")) else "mid")
            items.append({"title": t, "tag": tag, "content": full})
        kept, dropped = filter_and_tag(items)
        for n in kept[:12]:
            tag = {"good": "🔴利好", "bad": "🟢利空", "mid": "·"}[n["tag"]]
            sec = ("/".join(n.get("sectors", [])[:2])) or ""
            L.append(f"- [{tag}]{('【' + sec + '】') if sec else ''} {n['title']}")
        L.append(f"- （已过滤无关快讯 {dropped} 条）")
    except Exception:
        L.append("- 电报缺源")
    L.append("")
    L.append("## 五、ETF 计划")
    L.append("- ETF 短线：养殖ETF 159865（农业主线β，高开>2%等回踩，冲3%减半）")
    L.append("- ETF 中线：银行ETF 512800（权重侧跷跷板，回调分批，拿2~3周）")
    L.append("")
    L.append("## 七、观察哨（不买，只看信号）")
    L.append(f"- 空间龙头={max_lbc}板：它开盘强弱=全网情绪锚（它断板→高低切低位）")
    L.append("- 9:25 集合竞价：农业/昨日主线集群高开家数≥4 → 主线确认")
    L.append("- 大盘宽度：竞价红盘家数 <40% → 只防守")
    L.append("")
    L.append("## 八、竞价前检查单")
    L.append("- ☐ 隔夜美股/中概/A50 期指方向（红涨绿跌影响开盘意愿）")
    L.append("- ☐ 财联社盘前电报有无黑天鹅/重大政策（利好利空标注）")
    L.append("- ☐ 昨日持仓票有无利空（集合竞价异常低开先减后看）")
    L.append("")
    L.append("## 九、纪律")
    L.append("- 9:20 前的挂单可撤=有假；9:20~9:25 才是真竞价")
    L.append("- 本简报为全量计划（仅缺竞价确认数据），确认信号以 9:27 竞价简报为准（自动推送）")
    L.append("- 锚定规则胜率>60%仅代表历史，不构成投资建议")
    return "\n".join(L)


text = build()
if text:
    (ROOT / "docs" / "data" / "pre_latest.md").write_text(text, encoding="utf-8")
    print(text)
    user = os.environ.get("SMTP_USER")
    code = os.environ.get("SMTP_AUTH_CODE")
    to = os.environ.get("MAIL_TO", user)
    if user and code:
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = Header(f"主板雷达·竞价前作战计划 {now.strftime('%m-%d %H:%M')}", "utf-8")
        msg["From"] = user
        msg["To"] = to
        srv = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=25)
        srv.login(user, code)
        srv.sendmail(user, [to], msg.as_string())
        srv.quit()
        print(f"邮件已发送 → {to}", flush=True)
else:
    print("非交易日，不推送")
