# -*- coding: utf-8 -*-
"""策略评分公共模块：server.py 与 feed_job.py 共用，保证线上线下同一套公式。"""


def is_valid_stock(code, name):
    """主板白名单：60x/000/001/002/003，排除 ST/退市。不可关闭的默认规则。"""
    code = str(code)
    if not code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return False
    n = name or ""
    return "ST" not in n and "退" not in n


def score_stock(s):
    """四周期评分。s 需含 pct/amount/turnover/main_in/float_mv/(pe,pb,chg60 可缺)。"""
    pct = s.get("pct") or 0.0
    amt = (s.get("amount") or 0) / 1e8
    to = s.get("turnover") or 0.0
    mi = (s.get("main_in") or 0) / 1e8
    mv = (s.get("float_mv") or 0) / 1e8
    pe, pb, chg60 = s.get("pe"), s.get("pb"), s.get("chg60")
    res = {}

    sc, why = 0, []
    if pct >= 8.5:
        sc += 50; why.append(f"涨幅{pct:.1f}% 逼近/封住涨停")
    elif pct >= 5:
        sc += 35; why.append(f"盘中异动 {pct:+.1f}%")
    elif pct >= 2:
        sc += 15; why.append(f"温和上攻 {pct:+.1f}%")
    if amt >= 5:
        sc += 15; why.append(f"成交 {amt:.1f} 亿承接足")
    elif amt >= 1:
        sc += 8
    if 3 <= to <= 25:
        sc += 10
    if mi > 0:
        sc += 10; why.append("主力净流入为正")
    res["cs"] = {"score": sc, "why": why or [f"涨幅{pct:+.1f}% 成交{amt:.1f}亿"],
                 "risk": "涨停附近追入次日溢价不确定；竞价高开>7%放弃",
                 "fail": "跌破分时均价线或当日-5%无条件离场"}

    sc, why = 0, []
    if 2 <= pct <= 8:
        sc += 30; why.append(f"短线强势 {pct:+.1f}%")
    if amt >= 3:
        sc += 20; why.append(f"成交 {amt:.1f} 亿")
    if 2 <= to <= 20:
        sc += 15
    if mi > 0:
        sc += 15; why.append("资金流入配合")
    if mv >= 50:
        sc += 10
    res["short"] = {"score": sc, "why": why or ["量价一般，等放量确认"],
                    "risk": "隔日回撤风险，忌追连续大涨第三天",
                    "fail": "收盘跌破买入日最低价即离场"}

    sc, why = 0, []
    if chg60 is not None and -30 <= chg60 <= -5:
        sc += 35; why.append(f"60日已回调 {chg60:.1f}%，进入低吸观察区")
    if mi > 0:
        sc += 20; why.append("今日有承接资金")
    if pe is not None and 0 < pe < 40:
        sc += 15; why.append(f"PE {pe:.0f} 倍估值合理")
    if pb is not None and 0 < pb < 2:
        sc += 10
    if pct is not None and -3 <= pct <= 1:
        sc += 10; why.append("当日缩量回调，位置安全")
    if not why:
        why = ["等待回调至量化区间，暂不追高"]
    res["mid"] = {"score": sc, "why": why,
                  "risk": "产业逻辑证伪风险；仓位分批，不一次打满",
                  "fail": "跌破买入区间下沿 8% 或核心逻辑被证伪即止损"}

    sc, why = 0, []
    if mv >= 300:
        sc += 30; why.append(f"流通 {mv:.0f} 亿，体量稳健")
    if pe is not None and 0 < pe < 25:
        sc += 25; why.append(f"PE {pe:.0f} 倍，价值区间")
    if pb is not None and 0 < pb < 1.5:
        sc += 20; why.append(f"PB {pb:.2f}，安全边际高")
    if chg60 is not None and chg60 < 0:
        sc += 10; why.append("近 60 日回调充分")
    res["long"] = {"score": sc, "why": why or ["估值中等，持有等待"],
                   "risk": "价值陷阱风险；需跟踪季报与分红",
                   "fail": "基本面恶化（业绩连续两季下滑/分红取消）即调出"}

    if s.get("main_in") is None:
        for k in res:
            res[k]["score"] = int(res[k]["score"] * 0.9)
    return res


def fmt_stock(s):
    return {"code": s["code"], "name": s["name"], "price": s.get("price"),
            "pct": s.get("pct"), "amount": s.get("amount"), "turnover": s.get("turnover"),
            "main_in": s.get("main_in"), "float_mv": s.get("float_mv"),
            "pe": s.get("pe"), "pb": s.get("pb"), "chg60": s.get("chg60"),
            "strategies": s.get("strategies") or score_stock(s)}
