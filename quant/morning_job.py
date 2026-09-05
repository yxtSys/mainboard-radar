# -*- coding: utf-8 -*-
"""云端9:27早盘引擎（GitHub Actions用）：拉竞价数据→锚定规则→简报→邮件+Pages。
SMTP与收件人从环境变量读取（GitHub Secrets: SMTP_USER/SMTP_AUTH_CODE/MAIL_TO）。"""
import datetime as dt
import os
import smtplib
import sys
import time
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
import md2mail
from newsfilter import filter_and_tag  # noqa: E402

BJ = ZoneInfo("Asia/Shanghai")
now = dt.datetime.now(BJ)
today = now.strftime("%Y%m%d")
L = []


def build():
    force = os.environ.get("FORCE_RUN") == "1"
    if not em.is_trade_date(today) and not force:
        print("非交易日，休市")
        return None
    L.append(f"# 早盘竞价执行简报 {now.strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    prev_day = em.prev_trade_date(today)
    zt_y = []
    try:
        zt_y = em.zt_pool(prev_day)
    except Exception:
        L.append(f"⚠ 昨日涨停池缺源，锚定信号缺失（不编造）")
    snap, src = em.market_snapshot()
    snap = [s for s in snap if s.get("code") and s.get("price")]
    by_code = {s["code"]: s for s in snap}
    up = sum(1 for s in snap if (s["pct"] or 0) > 0)
    dn = sum(1 for s in snap if (s["pct"] or 0) < 0)
    prem = None
    try:
        prev = em.zt_pool_previous(today)
        pcts = [float(p["pct"]) for p in prev if p.get("pct") is not None]
        prem = round(sum(pcts) / len(pcts), 2) if pcts else None
    except Exception:
        pass

    # 零、锚定信号
    signals, note = [], ""
    if zt_y:
        signals, note = morning_rules.morning_signals(zt_y, by_code)
    L.append("## 零、锚定信号（交接书规则，仅推合格票）")
    L.append(f"- {note or '涨停池缺源'}")
    if signals:
        L.append("| 规则(胜率) | 角色 | 名称/代码 | 竞价高开 | 现价 | 操作 |")
        L.append("|---|---|---|---|---|---|")
        for g in signals:
            L.append(f"| {g['rules']} | {g['role']} | {g['name']} {g['code']} | {g['gap']:+.1f}% | {g['price']} | 回踩竞价价买，止损-5% |")
    else:
        L.append("- **今日无合格信号，建议空仓**")
    L.append("")
    env = f"{up}/{up+dn}" if (up + dn) else "-"
    L.append(f"## 一、环境（竞价宽度 {env}，昨溢价 {prem if prem is not None else '缺源'}，数据源 {src}）")
    L.append("- 溢价≤0或宽度<45% → 只防守；溢价>2% → 可进攻")
    L.append("")

    # 情绪周期 + 龙头战法 + 资金流向
    L.append("## 情绪周期与龙头战法")
    prem_s = prem if prem is not None else 0
    stage = "进攻期" if prem_s >= 2 else ("退潮防守期" if prem_s <= -0.5 else "震荡期")
    L.append(f"- 昨涨停溢价 {prem if prem is not None else '缺源'}，阶段=**{stage}**；溢价>0才做接力，≤0只防守")
    L.append("- 角色分工：空间龙头=情绪总锚(断板→高低切)；中军=跟随资金主池(沿均线持有)；卡位=接力锚(高开1.5~3.5%跟)；补涨=只低吸。小弟梯队见锚定信号表解读行")
    try:
        fl = sorted(em.boards("concept"), key=lambda b: -(b.get("main_in") or 0))
        ins = fl[:5]
        outs = sorted(fl, key=lambda b: (b.get("main_in") or 0))[:5]
        L.append("## 资金流向（从哪到哪）")
        L.append("- 流入主力 → " + "；".join(f"{b['name']} +{(b.get('main_in') or 0)/1e8:.1f}亿({b['pct']:+.1f}%)" for b in ins))
        L.append("- 流出主力 → " + "；".join(f"{b['name']} {(b.get('main_in') or 0)/1e8:.1f}亿({b['pct']:+.1f}%)" for b in outs))
        L.append("- 解读：流入侧=次日先看高开承接；流出侧=回避高位股（高低切方向）")
    except Exception:
        L.append("- 板块资金缺源")
    L.append("")

    # 二、消息面（过滤+板块归类）
    L.append("## 二、消息面（金融相关，已过滤）")
    try:
        raw = em.news_cls(30)
        items = [{"title": (n.get("title") or "").strip() or (n.get("content") or "")[:40],
                  "tag": "mid"} for n in raw]
        GOOD = ("利好", "中标", "签订", "订单", "预增", "涨价", "并购", "增持", "回购", "获批", "政策", "降准", "降息")
        BAD = ("减持", "立案", "调查", "预亏", "退市", "违约", "制裁")
        for n in items:
            if any(w in n["title"] for w in BAD):
                n["tag"] = "bad"
            elif any(w in n["title"] for w in GOOD):
                n["tag"] = "good"
        kept, dropped = filter_and_tag(items)
        for n in kept[:12]:
            tag = {"good": "🔴利好", "bad": "🟢利空", "mid": "·"}[n["tag"]]
            sec = ("/".join(n.get("sectors", [])[:2])) or ""
            L.append(f"- [{tag}]{('【' + sec + '】') if sec else ''} {n['title']}")
        L.append(f"- （已过滤无关快讯 {dropped} 条）")
    except Exception:
        L.append("- 财联社电报缺源")
    L.append("")

    # 三、ETF（短/中）
    L.append("## 三、ETF")
    L.append("- 短线：养殖ETF 159865（主线β，高开>2%等回踩，冲3%减半）")
    L.append("- 中线：银行ETF 512800（权重侧跷跷板，回调分批，拿2~3周）")
    L.append("")
    L.append("## 纪律")
    L.append("- 高开>5%放弃；止损-5%硬纪律；最高板断板/炸板率>40% → 高低切低位")
    L.append("- 锚定规则胜率>60%仅代表历史，实时盘面以竞价确认为准，不构成投资建议")
    return "\n".join(L)


text = build()
if text:
    (ROOT / "docs" / "data" / "morning_latest.md").write_text(text, encoding="utf-8")
    print(text)
    user = os.environ.get("SMTP_USER")
    code = os.environ.get("SMTP_AUTH_CODE")
    to = os.environ.get("MAIL_TO", user)
    if user and code:
        import md2mail
        msg = MIMEText(md2mail.render(text), "html", "utf-8")
        msg["Subject"] = Header(f"主板雷达·早盘竞价简报 {now.strftime('%m-%d %H:%M')}", "utf-8")
        msg["From"] = user
        msg["To"] = to
        srv = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=25)
        srv.login(user, code)
        srv.sendmail(user, [to], msg.as_string())
        srv.quit()
        print(f"邮件已发送 → {to}", flush=True)
else:
    print("非交易日，不推送")
