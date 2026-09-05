# -*- coding: utf-8 -*-
"""
盘后复盘 15:30 运行：
  python quant/review.py
输出: markdown 复盘到 stdout + quant/out/YYYYMMDD_review.md
"""
import datetime as dt
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
import emdata as em


def kline_hist(secid, lmt=6, field="f53"):
    """近N日K线某字段（f53收盘 f57成交额）。"""
    p = {"secid": secid, "fields1": "f1,f2,f3", "fields2": f"f51,{field}",
         "klt": 101, "fqt": 1, "end": "20500101", "lmt": lmt}
    try:
        ks = (em._get(em.KLINE, p).get("data") or {}).get("klines") or []
        return [float(k.split(",")[1]) for k in ks]
    except Exception:
        return []


def sentiment_stage(zt_n, dt_n, max_lbc, break_rate, premium):
    """情绪周期五阶段判定（游资视角）。"""
    if zt_n <= 25 and premium is not None and premium < -2:
        return "冰点期", "空仓或只打首板试错，等待情绪反转信号（跌停消失+大长腿）"
    if zt_n <= 35 and break_rate >= 40:
        return "退潮期", "控制仓位≤3成，只做低位新题材首板，回避高位板"
    if zt_n >= 80 and max_lbc >= 6 and break_rate <= 20:
        return "高潮期", "龙头可持有，警惕分歧；次日只做龙一，不追跟风"
    if premium is not None and premium > 2 and zt_n >= 50:
        return "发酵期", "进攻期：主做板块中军+卡位二板，仓位可放到6-7成"
    return "修复/震荡期", "半仓试错，聚焦1-2个主流板块，不做杂毛"


def main():
    today = dt.date.today().strftime("%Y%m%d")
    if not em.is_trade_date(today):
        print(f"## {today} 非交易日，休市。\n")
        return

    L = [f"# 盘后复盘 {dt.date.today()}"]
    print("# 盘后复盘拉取中…", flush=True)

    # 1) 涨停/跌停/炸板
    zt, dt_, zb, prev = [], [], [], []
    try:
        zt = em.zt_pool(today)
    except Exception as e:
        L.append(f"涨停池获取失败: {e}")
    try:
        dt_ = em.dt_pool(today)
    except Exception:
        pass
    try:
        prev = em.zt_pool_previous(today)
    except Exception:
        pass

    lbc_list = [int(z["lbc"]) for z in zt if str(z.get("lbc", "")).isdigit()]
    max_lbc = max(lbc_list) if lbc_list else 0
    ladders = {}
    for n in sorted(set(lbc_list), reverse=True):
        names = [f"{z['name']}({z['industry']})" for z in zt if str(z.get("lbc")) == str(n)]
        ladders[n] = names

    # 炸板池
    break_rate = None
    try:
        import akshare as ak
        df = ak.stock_zt_pool_zbgc_em(date=today)
        zb_n = len(df)
        break_rate = round(zb_n / (zb_n + len(zt)) * 100, 1) if (zb_n + len(zt)) else None
    except Exception:
        pass

    pcts = [p["pct"] for p in prev if p.get("pct") is not None]
    premium = sum(pcts) / len(pcts) if pcts else None

    # 2) 市场总量
    snap, src = em.market_snapshot()
    snap = [s for s in snap if s["code"] and s["price"] is not None]
    up = sum(1 for s in snap if (s["pct"] or 0) > 0)
    dn = sum(1 for s in snap if (s["pct"] or 0) < 0)
    amt_today = sum(s["amount"] or 0 for s in snap) / 1e8
    amt_sh_hist = kline_hist("1.000001", 6, "f57")
    amt_sz_hist = kline_hist("0.399001", 6, "f57")
    amt_prev = None
    if amt_sh_hist and amt_sz_hist:
        # 今天是最后一天，前一天的沪深合计
        amt_prev = (amt_sh_hist[-2] + amt_sz_hist[-2]) / 1e8

    # 3) 板块资金（东财限流时用涨停池行业分布兜底）
    top_in, top_out, board_src = [], [], "东财板块资金"
    try:
        cb = em.boards("concept")
        if cb:
            top_in = sorted(cb, key=lambda b: -(b.get("main_in") or 0))[:5]
            top_out = sorted(cb, key=lambda b: (b.get("main_in") or 0))[:5]
    except Exception:
        pass
    if not top_in:
        ind_cnt = {}
        for z in zt:
            ind = z.get("industry")
            if ind:
                ind_cnt[ind] = ind_cnt.get(ind, 0) + 1
        top_in = sorted(ind_cnt.items(), key=lambda kv: -kv[1])[:8]
        board_src = "涨停池行业分布（板块资金接口限流）"

    # 4) 情绪判定与明日策略
    stage, advice = sentiment_stage(len(zt), len(dt_), max_lbc, break_rate or 100, premium)

    # 5) 主力净流入排名（新浪源无该字段时降级为成交额活跃榜）
    has_main = any(s.get("main_in") for s in snap)
    if has_main:
        movers = sorted(snap, key=lambda s: -(s.get("main_in") or 0))[:10]
        mover_title, mover_col = "主力净流入个股 TOP10（明日关注线索）", "主力净流入(亿)"
        rows_m = [(s["code"], s["name"], s["pct"], (s["main_in"] or 0) / 1e8) for s in movers]
        head_m = f"| 代码 | 名称 | 涨幅% | {mover_col} | 成交额(亿) |"
        amt_by_code = {s["code"]: (s["amount"] or 0) / 1e8 for s in snap}
        rows_fmt = [f"| {c} | {n} | {p:+.2f} | {m:+.2f} | {amt_by_code.get(c, 0):.1f} |" for c, n, p, m in rows_m]
    else:
        movers = sorted(snap, key=lambda s: -(s["amount"] or 0))[:10]
        mover_title, mover_col = "成交额活跃个股 TOP10（资金动向代理，主力字段缺源）", "成交额(亿)"
        rows_m = [(s["code"], s["name"], s["pct"], (s["amount"] or 0) / 1e8) for s in movers]
        head_m = f"| 代码 | 名称 | 涨幅% | {mover_col} |"
        rows_fmt = [f"| {c} | {n} | {p:+.2f} | {m:.1f} |" for c, n, p, m in rows_m]

    L += ["", "## 一、市场全景",
          f"- 涨跌家数：{up} 涨 / {dn} 跌；两市成交 {amt_today:.0f} 亿"
          + (f"（昨日 {amt_prev:.0f} 亿，{'放量' if amt_today > amt_prev else '缩量'} {(amt_today/amt_prev-1)*100:+.1f}%）" if amt_prev else ""),
          f"- 涨停 {len(zt)} 家 / 跌停 {len(dt_)} 家，炸板率 {break_rate}%" if break_rate is not None else "",
          f"- 最高连板：{max_lbc} 板",
          f"- 昨日涨停今日平均溢价：{premium:+.2f}%" if premium is not None else "",
          "",
          "## 二、连板梯队",
          *[f"- {n}板[{len(names)}]：" + "、".join(names[:8]) for n, names in ladders.items()],
          "",
          "## 三、板块资金流向" + (f"（来源：{board_src}）" if board_src else ""),
          "- 净流入/涨停集中 TOP：" + "；".join(
              (f"{n} 涨停{c}家" for n, c in top_in) if top_in and isinstance(top_in[0], tuple)
              else (f"{b['name']} {(b['main_in'] or 0)/1e8:+.1f}亿({b['pct']:+.1f}%)" for b in top_in)) if top_in else "- 板块数据暂缺",
          "- 净流出 TOP：" + "；".join(f"{b['name']} {(b['main_in'] or 0)/1e8:+.1f}亿({b['pct']:+.1f}%)" for b in top_out) if top_out else "",
          "",
          "## 四、情绪周期判定",
          f"- 当前阶段：**{stage}** → {advice}",
          "",
          f"## 五、{mover_title}",
          head_m,
          "|---|---|---|---|" if not has_main else "|---|---|---|---|---|",
          *rows_fmt,
          "",
          "## 六、明日打法建议",
          f"- 情绪处于{stage}，{advice}",
          "- 明早 9:27 竞价简报重点核对：①昨日涨停溢价是否延续；②今日净流入 TOP 板块是否竞价高开；③A50/纳指期货方向",
          "- 提醒：复盘为量化辅助信号，不构成投资建议。"]
    text = "\n".join(x for x in L if x != "")
    print(text)
    em.save(f"{today}_review.md", text)


if __name__ == "__main__":
    main()
