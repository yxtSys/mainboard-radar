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
    if not em.is_trade_date(today):
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
    L.append("## 二、观察哨（不买，只看信号）")
    L.append(f"- 空间龙头={max_lbc}板：它开盘强弱=全网情绪锚（它断板→高低切低位）")
    L.append("- 9:25 集合竞价：农业/昨日主线集群高开家数≥4 → 主线确认")
    L.append("- 大盘宽度：竞价红盘家数 <40% → 只防守")
    L.append("")
    L.append("## 三、竞价前检查单")
    L.append("- ☐ 隔夜美股/中概/A50 期指方向（红涨绿跌影响开盘意愿）")
    L.append("- ☐ 财联社盘前电报有无黑天鹅/重大政策（利好利空标注）")
    L.append("- ☐ 昨日持仓票有无利空（集合竞价异常低开先减后看）")
    L.append("")
    L.append("## 四、纪律")
    L.append("- 9:20 前的挂单可撤=有假；9:20~9:25 才是真竞价")
    L.append("- 本简报只给计划，确认信号以 9:27 竞价简报为准（竞价完自动推送）")
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
