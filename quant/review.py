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




# ---------- 龙头战法作战卡（情绪周期 + 角色识别 + 高低切 + 浓缩推荐） ----------
MAIN = ("600", "601", "603", "605", "000", "001", "002", "003")
ETF_MAP = [  # 板块关键词 → 短线ETF
    ("半导体|芯片|存储|封测", "512480", "半导体ETF"),
    ("白酒|食品|饮料", "512690", "酒ETF"),
    ("养殖|猪|饲料|种业", "159865", "养殖ETF"),
    ("军工|航天|国防", "512660", "军工ETF"),
    ("有色|铜|铝|稀土", "512400", "有色ETF"),
    ("银行", "512800", "银行ETF"),
    ("券商|证券", "512000", "券商ETF"),
    ("医疗|医药|创新药", "512170", "医疗ETF"),
    ("光伏|新能源", "515790", "光伏ETF"),
    ("新能源车|锂电", "515030", "新能源车ETF"),
    ("黄金|贵金属", "518880", "黄金ETF"),
    ("游戏|传媒|短剧", "159869", "游戏动漫ETF"),
]
ETF_MID = [("512800", "银行ETF", "权重防御/跷跷板大盘侧"), ("512100", "中证1000ETF", "小盘题材侧"),
           ("510880", "红利ETF", "高股息底仓"), ("510300", "沪深300ETF", "核心宽基")]


def roles_of(zt, snap_by_code):
    """涨停池角色识别：空间龙头(最高板)/中军(最大成交)/卡位(昨首板今连板)/补涨集群。"""
    if not zt:
        return {"龙头": "-", "中军": "-", "卡位": "-", "补涨": "-"}
    lb = [z for z in zt if str(z.get("lbc", "")).isdigit()]
    max_lbc = max((int(z["lbc"]) for z in lb), default=1)
    lead = [z for z in lb if int(z["lbc"]) == max_lbc]
    zhongjun = sorted(zt, key=lambda z: -(z.get("amount") or 0))[0] if zt else None
    kawei = [z for z in lb if int(z["lbc"]) == 2][:3]
    dipoor = [z for z in zt if int(z.get("lbc") or 1) == 1][:5]
    fmt = lambda z: (f"{z['name']}"
                     f"(主板<20✓)" if str(z.get("code", "")).startswith(MAIN) and (snap_by_code.get(str(z.get("code")), {}).get("price") or 99) < 20
                     else f"{z['name']}(价格超限)") if z else "-"
    return {"龙头": "、".join(fmt(z) for z in lead),
            "中军": fmt(zhongjun) if zhongjun else "-",
            "卡位(昨首板今2板)": "、".join(fmt(z) for z in kawei) or "-",
            "补涨集群(今首板)": "、".join(fmt(z) for z in dipoor) or "-"}


def ops_card(zt, dt_, break_rate, premium, stage, advice, max_lbc, snap, top_in, movers):
    """浓缩作战卡：短线打法 / 中线推荐 / ETF短中期。全部主板+价格<20 过滤（股票）。"""
    L = ["", "## 🎯 明日作战卡（浓缩版）"]
    by_code = {s["code"]: s for s in snap}
    roles = roles_of(zt, by_code)
    L.append(f"- 情绪定位：**{stage}**｜涨停{len(zt)} 炸板率{break_rate}% 昨溢价{premium:+.2f}%｜最高板{max_lbc}")
    L.append(f"- 角色识别：龙头 **{roles['龙头']}**｜中军 **{roles['中军']}**｜卡位 {roles['卡位(昨首板今2板)']}｜补涨 {roles['补涨集群(今首板)']}")
    # 短线打法（按情绪周期给锚定动作）
    if "高潮" in stage:
        play = "只做龙一，不追跟风；锚定：龙一分时均价线，破线减半；分歧日（首阴/炸板）低吸而非追高"
    elif "发酵" in stage:
        play = "主攻卡位+中军：卡位股竞价高开1.5~3.5%可上，中军沿分时均线持有；买在分歧（首次开板回封）"
    elif "退潮" in stage:
        play = f"高低切：高位板({max_lbc}板)兑现风险大，切低位首板/二板新题材；只做龙头首阴反包或空仓等冰点"
    elif "冰点" in stage:
        play = "空仓等右侧，只打首板试错；冰点次日首个涨停潮=新周期信号"
    else:
        play = "震荡试错：半仓跟主流板块，锚定中军分时均线"
    L.append(f"- 短线锚定打法：{play}｜铁律：买在分歧、卖在一致")
    L.append("- 个股操作卡（明天竞价直接照做）：")
    picks = []
    seen = set()
    for z in sorted(zt, key=lambda z: -int(z.get("lbc") or 1)):
        c = str(z.get("code", ""))
        if c in seen or not c.startswith(MAIN):
            continue
        s = by_code.get(c)
        if not s:
            continue
        pr = s.get("price")
        if pr is None or not (2 <= pr <= 20):
            continue
        lb = int(z.get("lbc") or 1)
        role = "龙头" if lb == max_lbc else ("卡位" if lb >= 2 else "补涨")
        if role == "补涨" and len([x for x in picks if x == "补涨"]) >= 2:
            continue
        seen.add(c)
        g1, g2, gmax = round(pr * 1.015, 2), round(pr * 1.035, 2), round(pr * 1.05, 2)
        b1, b2, stop = round(pr * 0.98, 2), round(pr * 0.96, 2), round(pr * 0.95, 2)
        L.append(f"  · {z['name']} {c} {pr:.2f}元 {lb}板【{role}】｜高开{g1}~{g2}→跟(半路)；高开>{gmax}或低开→不跟｜买{b1}/{b2}｜止损{stop}｜全仓")
        picks.append(role)
        if len(picks) >= 6:
            break
    # 中线推荐（主板<20 + 中线分）
    mids = []
    for s in snap:
        c = str(s.get("code", ""))
        if not c.startswith(MAIN) or "ST" in s.get("name", ""):
            continue
        p = s.get("price")
        if p is None or not (2 <= p <= 20) or (s["pct"] or 0) > 3:
            continue
        chg60, pe, pb = s.get("chg60"), s.get("pe"), s.get("pb")
        mi = s.get("main_in") or 0
        sc = 0
        if chg60 is not None and -30 <= chg60 <= -5: sc += 35
        if mi > 0: sc += 20
        if pe is not None and 0 < pe < 40: sc += 15
        if pb is not None and 0 < pb < 2: sc += 10
        if sc >= 45:
            mids.append((sc, s["name"], c, p, chg60, (s["amount"] or 0) / 1e8))
    mids.sort(reverse=True)
    L.append("- 中线推荐（主板<20，超跌+有承接，量化区间分批）：")
    for sc, nm, c, pr, c60, am in mids[:5]:
        buy1, buy2 = round(pr * 0.97, 2), round(pr * 0.94, 2)
        L.append(f"  · {nm}({c}) {pr:.2f}元 60日{c60:+.0f}% 成交{am:.1f}亿 → 区间 {buy1}~{buy2} 分2批，破{round(pr*0.9,2)}止损（评分{sc}）")
    if not mids:
        L.append("  · 本日无达标标的（条件：超跌+主力承接+低估值）")
    # ETF 短期/中期
    kw_text = " ".join(f"{z.get('industry','')}" for z in zt) + " " + " ".join(str(b) for b in top_in) + " " + " ".join(str(m) for m in movers)
    etf_short, seen = [], set()
    import re as _re
    for pat, code, name in ETF_MAP:
        if _re.search(pat, kw_text) and code not in seen:
            etf_short.append(f"{name}({code})"); seen.add(code)
        if len(etf_short) >= 3:
            break
    L.append(f"- ETF短期（跟主线情绪，T+0思路≤3天）：{'、'.join(etf_short) if etf_short else '今日板块分散，无集中方向'}"
             f" → 操作：主线发酵日开盘买、高潮日兑现，仓位随情绪阶段（{stage}={ {'冰点期':'1成试','退潮期':'2成','修复/震荡期':'3成','发酵期':'5成','高潮期':'4成持有'}[stage] }）")
    big_small = "大盘/权重" if (roles and False) else "按跷跷板"
    L.append(f"- ETF中期（3~10周）：{ETF_MID[0][1]}({ETF_MID[0][0]}) {ETF_MID[0][2]} / {ETF_MID[2][1]}({ETF_MID[2][0]}) {ETF_MID[2][2]} → 周定投+偏离止盈，方向跟随大小盘轮动（详见上方轮动判断）")
    return L

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

    # 🎯 明日作战卡（龙头战法浓缩）
    max_lbc_card = max([int(z.get("lbc") or 1) for z in zt] or [0]) if zt else 0
    try:
        L += ops_card(zt, dt_, break_rate, premium or 0, stage, advice, max_lbc_card, snap, top_in, movers)
    except Exception as e:
        L.append("")
        L.append("## 🎯 明日作战卡")
        L.append(f"- 生成失败: {e}")
    text = "\n".join(x for x in L if x != "")
    print(text)
    em.save(f"{today}_review.md", text)


if __name__ == "__main__":
    main()
