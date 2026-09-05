# -*- coding: utf-8 -*-
"""
GitHub Actions 每 5 分钟运行：拉数据 → 套用与线上完全相同的量化公式 → 产出静态 feed.json
供 GitHub Pages 的关机简版使用。所有时间均为北京时间。
"""
import datetime as dt
import json
import sys
import warnings
from pathlib import Path
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "quant"))
import emdata as em  # noqa: E402
from scoring import score_stock, is_valid_stock, fmt_stock  # noqa: E402
from review import sentiment_stage  # noqa: E402
from factors import FACTORS, compute_factors  # noqa: E402
from agents import analyze  # noqa: E402
from newsfilter import filter_and_tag  # noqa: E402

BJ = ZoneInfo("Asia/Shanghai")
OUT = ROOT / "docs" / "data"
OUT.mkdir(parents=True, exist_ok=True)

ETF_LIST = [
    ("512480", "半导体ETF", ["cs", "short"], "科技情绪载体，波动大，适合超短情绪周期"),
    ("512000", "券商ETF", ["cs", "short"], "牛市旗手，情绪启动时弹性首选"),
    ("512660", "军工ETF", ["cs"], "事件驱动题材，日内联动性强"),
    ("512400", "有色金属ETF", ["cs", "short"], "跟随商品价格，日内联动明显"),
    ("512100", "中证1000ETF", ["short"], "小盘风格工具，跷跷板小盘侧首选"),
    ("515030", "新能源车ETF", ["short"], "景气赛道波段工具"),
    ("515790", "光伏ETF", ["short"], "产业催化波段工具"),
    ("159865", "养殖ETF", ["short", "mid"], "猪周期主线β，农业集群确认日的替代工具"),
    ("512690", "酒ETF", ["mid"], "消费白马，回调低吸型"),
    ("512170", "医疗ETF", ["mid"], "超跌医药修复逻辑"),
    ("510880", "红利ETF", ["mid", "long"], "高股息防御，弱市底仓"),
    ("512800", "银行ETF", ["mid", "long"], "权重防御，跷跷板大盘侧工具"),
    ("510300", "沪深300ETF", ["long"], "核心宽基，定投型"),
    ("510050", "上证50ETF", ["long"], "大盘蓝筹底仓"),
    ("513050", "中概互联ETF", ["long"], "中国资产长线配置"),
    ("518880", "黄金ETF", ["long"], "避险配置，对冲组合波动"),
]

GOOD = ("利好", "中标", "签订", "订单", "合同", "预增", "涨价", "并购", "收购", "增持", "回购", "获批", "政策", "降准", "降息", "量产")
BAD = ("减持", "立案", "调查", "处罚", "预亏", "退市", "问询", "终止", "跌停", "违约", "制裁", "加征")


def main():
    now = dt.datetime.now(BJ)
    today = now.strftime("%Y%m%d")
    feed = {"generated": now.strftime("%Y-%m-%d %H:%M:%S"), "sources": {}, "trade_day": False}
    trade_day = em.is_trade_date(today)
    feed["trade_day"] = trade_day

    # 指数 + 期指
    try:
        idx = em.index_pct(["sh000001", "sz399001", "sz399006", "sh000016", "sh000300", "sh000852"])
        feed["indices"] = [{"name": v[0], "pct": v[1]} for v in idx.values()]
        feed["sources"]["indices"] = "tencent"
    except Exception:
        feed["indices"] = []
    try:
        fut = em.sina_quotes(["hf_CHA50CFD", "hf_NQ"])
        futs = []
        for k, v in fut.items():
            if v.get("price") and v.get("prev"):
                futs.append({"name": v.get("name", k), "pct": round((v["price"] / v["prev"] - 1) * 100, 2)})
        feed["futures"] = futs
    except Exception:
        feed["futures"] = []

    # 全市场快照 + 候选
    snap, src = [], "offline"
    try:
        snap, src = em.market_snapshot()
        feed["sources"]["snapshot"] = src
    except Exception:
        pass
    snap = [s for s in snap if s.get("code") and s.get("price")]
    feed["breadth"] = {"up": sum(1 for s in snap if (s["pct"] or 0) > 0),
                       "down": sum(1 for s in snap if (s["pct"] or 0) < 0),
                       "amount_yi": round(sum(s["amount"] or 0 for s in snap) / 1e8)}

    # 涨停池 & 情绪
    zt, ladders, premium, stage, advice = [], {}, None, "修复/震荡期", "半仓试错，聚焦主流板块"
    try:
        zt = em.zt_pool(today)
        for z in zt:
            n = int(z.get("lbc") or 1)
            ladders.setdefault(n, []).append(f"{z['name']}({z.get('industry','')})")
    except Exception:
        pass
    try:
        prev = em.zt_pool_previous(today)
        pcts = [p["pct"] for p in prev if p.get("pct") is not None]
        if pcts:
            premium = round(sum(pcts) / len(pcts), 2)
    except Exception:
        pass
    break_rate = None
    try:
        import akshare as ak
        df = ak.stock_zt_pool_zbgc_em(date=today)
        zb = len(df)
        break_rate = round(zb / (zb + len(zt)) * 100, 1) if (zb + len(zt)) else None
    except Exception:
        pass
    if zt or premium is not None:
        stage, advice = sentiment_stage(len(zt), 0, max([int(z.get("lbc") or 1) for z in zt] or [0]),
                                        break_rate or 100, premium)
    feed["sentiment"] = {"zt_n": len(zt), "break_rate": break_rate, "premium": premium,
                         "stage": stage, "advice": advice,
                         "ladders": {str(n): v[:8] for n, v in sorted(ladders.items(), reverse=True)}}

    # 外围期指（供研判 ctx）
    a50 = nq = None
    try:
        fut2 = em.sina_quotes(["hf_CHA50CFD", "hf_NQ"])
        for k, tag in [("hf_CHA50CFD", "a50"), ("hf_NQ", "nq")]:
            v = fut2.get(k)
            if v and v.get("price") and v.get("prev"):
                if tag == "a50": a50 = round((v["price"] / v["prev"] - 1) * 100, 2)
                else: nq = round((v["price"] / v["prev"] - 1) * 100, 2)
    except Exception:
        pass
    prev_zt_map = {}
    try:
        for z in em.zt_pool_previous(today):
            prev_zt_map[str(z["code"])] = z.get("lbc")
    except Exception:
        pass
    ctx = {"prev_zt": prev_zt_map, "zt_premium": premium, "break_rate": break_rate, "a50": a50, "nq": nq}

    # 未来事件窗口（跟随资金提前埋伏的时间锚）：距季报披露窗/期指交割日的剩余天数
    import calendar as _cal
    def _event_days(now):
        days = []
        for m in [now.month, now.month + 1 if now.month < 12 else 1]:
            yr = now.year if m == now.month else (now.year + (1 if now.month == 12 else 0))
            last = _cal.monthrange(yr, m)[1]
            days.append((dt.date(yr, m, last) - now.date()).days)  # 月末=季报/月度数据窗口
        third_fri = [d for d in range(16, 23) if dt.date(now.year, now.month, d).weekday() == 4][0]
        days.append((dt.date(now.year, now.month, third_fri) - now.date()).days)  # 期指交割(当月第3个周五)
        return min(abs(d) for d in days)
    try:
        ctx["event_days"] = _event_days(now)
    except Exception:
        pass

    # 板块（东财 → 同花顺 → 新浪）
    boards, bsrc = [], "offline"
    try:
        cb = em.boards("concept"); ib = em.boards("industry")
        for b in cb: b["type"] = "concept"
        for b in ib: b["type"] = "industry"
        boards = cb + ib; bsrc = "eastmoney"
    except Exception:
        try:
            boards = em.ths_fund_flow("industry"); bsrc = "ths_flow"
        except Exception:
            try:
                boards = em.sina_industries(); bsrc = "sina_industry"
            except Exception:
                boards = []
    feed["sources"]["boards"] = bsrc
    feed["boards"] = [{k: b.get(k) for k in ("code", "name", "pct", "main_in", "type")} for b in boards][:60]

    # 候选打分（主板、非ST、价格<20 默认区间）
    by_code = {s["code"]: s for s in snap}
    cands = []
    for s in snap:
        if not is_valid_stock(s["code"], s.get("name")):
            continue
        p = s.get("price")
        if p is None or not (2 <= p <= 20):
            continue
        if (s["pct"] or 0) < 1 or (s["amount"] or 0) < 8e6 or (s["float_mv"] or 0) < 2e9:
            continue
        s2 = dict(s)
        s2["strategies"] = score_stock(s2)
        s2["strategy"] = primary_strategy(s2["strategies"], s2)["strategy"]
        fvals = compute_factors(s2, ctx)
        # 埋伏资金轨迹代理分：低位+有承接+温和换手 = 有人提前埋伏的特征组合
        amb = 0
        if (fvals.get("chg60") or 0) <= -15: amb += 40
        if (fvals.get("main_in_yi") or 0) > 0: amb += 30
        if 5 <= (fvals.get("turnover") or 0) <= 15: amb += 20
        if (fvals.get("pct") or 99) <= 3: amb += 10
        fvals["ambush"] = amb
        fvals["event_days"] = ctx.get("event_days")
        if s["code"] in prev_zt_map:
            fvals["lbc"] = prev_zt_map[s["code"]]
            s2["why"] = f"昨{prev_zt_map[s['code']]}板"
        s2["factors"] = fvals
        cands.append(fmt_stock(s2) | {"factors": fvals})
    cands.sort(key=lambda s: -s["strategies"]["cs"]["score"])

    # 消息命中表（个股名 → 电报条目）
    # 消息面：只留金融相关 + 板块归类 + 个股命中
    news = []
    try:
        for n in em.news_cls(30):
            t = (n.get("title") or "").strip() or (n.get("content") or "").strip()[:40]
            if not t:
                continue
            full = t + (n.get("content") or "")
            tag = "bad" if any(w in full for w in BAD) else ("good" if any(w in full for w in GOOD) else "mid")
            news.append({"title": t, "tag": tag, "time": str(n.get("time", ""))})
    except Exception:
        pass
    from scoring import mi_ok  # noqa
    name2code = {s["name"]: s["code"] for s in snap if s.get("name")}
    board_names = [b["name"] for b in boards]
    news, dropped = filter_and_tag(news, board_names, name2code)
    feed["news_dropped"] = dropped
    by_sector = {}
    for n in news:
        for sec in n.get("sectors", []):
            by_sector.setdefault(sec, []).append({"title": n["title"], "tag": n["tag"]})
    feed["news_by_sector"] = {k: v[:3] for k, v in sorted(by_sector.items(), key=lambda kv: -len(kv[1]))[:10]}
    news_hint = {}
    for n in news:
        if n["tag"] == "mid":
            continue
        for h in n.get("stock_hits", []):
            news_hint[h["code"]] = {"title": n["title"], "tag": n["tag"]}
    feed["news_hint"] = news_hint

    # 多角色研判（TradingAgents 架构，确定性证据链）——给超短分前8名
    for s in cands[:8]:
        try:
            s["agents"] = analyze(s, s.get("factors"), {**ctx, "news_hint": news_hint})
        except Exception:
            pass
    feed["candidates"] = cands[:15]

    # ETF 行情
    try:
        import requests
        syms = ["sh" + c if c[0] == "5" else "sz" + c for c, _, _, _ in ETF_LIST]
        r = requests.get("https://qt.gtimg.cn/q=" + ",".join("s_" + s for s in syms),
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.encoding = "gbk"
        by_code = {}
        for line in r.text.strip().splitlines():
            if '"' in line:
                f = line.split('"')[1].split("~")
                if len(f) > 5 and f[2]:
                    by_code[f[2]] = (em._num(f[3]), em._num(f[5]))
        feed["etf"] = [{"code": c, "name": n, "groups": g, "reason": w,
                        "price": by_code.get(c, (None, None))[0], "pct": by_code.get(c, (None, None))[1]}
                       for c, n, g, w in ETF_LIST]
    except Exception:
        feed["etf"] = [{"code": c, "name": n, "groups": g, "reason": w, "price": None, "pct": None}
                       for c, n, g, w in ETF_LIST]

    # 轮动（5日相对强弱）
    rot = []
    big, small = em.pct5_dual("1.000016", "sh000016"), em.pct5_dual("1.000852", "sh000852")
    hs, cyb = em.pct5_dual("1.000300", "sh000300"), em.pct5_dual("0.399006", "sz399006")
    if big is not None and small is not None:
        rot.append({"pair": "大小盘", "a": f"上证50 {big:+.1f}%", "b": f"中证1000 {small:+.1f}%",
                    "side": "大盘/权重占优" if big - small > 0 else "小盘/题材占优"})
    if hs is not None and cyb is not None:
        rot.append({"pair": "价值成长", "a": f"沪深300 {hs:+.1f}%", "b": f"创业板指 {cyb:+.1f}%",
                    "side": "价值占优" if cyb - hs < 0 else "成长占优"})
    feed["rotation"] = rot

    # 因子库 + 溯源
    feed["factors_registry"] = FACTORS
    feed["provenance"] = {
        "snapshot": feed["sources"].get("snapshot", "offline"),
        "boards": feed["sources"].get("boards", "offline"),
        "indices": feed["sources"].get("indices", "offline"),
        "futures": "新浪 hf_ 期指",
        "news": "财联社电报（akshare stock_info_global_cls）",
        "zt_pool": "东方财富 push2ex（akshare）",
        "quotes_etf": "腾讯 qt.gtimg.cn",
        "formulas": "quant/factors.py + quant/scoring.py v1",
        "agents_arch": "TradingAgents 架构移植（arXiv 2412.20138）",
    }

    out = ROOT / "docs" / "data" / "feed.json"
    out.write_text(json.dumps(feed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"feed.json 写入完成：{out}，{out.stat().st_size // 1024}KB，来源 {feed['sources']}")


if __name__ == "__main__":
    main()
