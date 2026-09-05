# -*- coding: utf-8 -*-
"""
早盘竞价雷达 9:27 运行：
  python quant/radar.py --mode morning
  9:25-9:30 之间运行时拉到的就是竞价撮合数据（盘后运行则显示全天数据，用于测试/复盘）。
输出: markdown 简报到 stdout + quant/out/YYYYMMDD_morning.md + _morning.json
"""
import argparse
import datetime as dt
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))
import emdata as em

CFG = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))


# ---------- 量化打分 ----------
def gap_score(g):
    """高开幅度隶属度：平开0.3，高开2-5%最优=1.0，超高开回落风险，低开弱。"""
    if g is None:
        return 0.0
    if g <= -3:
        return 0.05
    if g <= 0:
        return 0.3
    if 0 < g < 2:
        return 0.3 + 0.35 * (g / 2)
    if 2 <= g <= 5:
        return 1.0
    if 5 < g <= 7:
        return 0.8
    if 7 < g <= 9:
        return 0.5
    return 0.25  # >9% 一字/秒板类型，竞价难上车


def vol_score(turnover_at_auction):
    """竞价换手率（竞价成交额/流通市值）：>0.5%满分。"""
    if turnover_at_auction is None:
        return 0.0
    return min(1.0, turnover_at_auction / 0.5)


def money_score(amount_yi):
    """竞价成交额绝对值：≥1亿满分，权重体现承接力度（大单口径）。"""
    if amount_yi is None:
        return 0.0
    if amount_yi >= 1.0:
        return 1.0
    if amount_yi >= 0.3:
        return 0.7
    if amount_yi >= 0.1:
        return 0.4
    return 0.15


def board_score(stock, snap_by_code, boards_top, concepts_of):
    """板块协同：所属板块在竞价热度榜前N → 加分；同板块高开家数多 → 再加分。"""
    s = 0.0
    for i, b in enumerate(boards_top):
        if stock["code"] in b.get("_member_codes", set()) or b["name"] in concepts_of.get(stock["code"], []):
            s = max(s, 1.0 - 0.12 * i)
            break
    peers = stock.get("_sector_hot_peers", 0)
    return max(s, min(1.0, peers / 5))


def position_score(lbc, is_prev_zt, gap):
    """身位分：昨日涨停(有身份)高开=弱转强加分；连板高度越高越有龙头溢价。"""
    if is_prev_zt:
        base = 0.7 + min(0.3, (lbc or 1) * 0.08)
        if gap is not None and gap > 5:  # 高开过高，兑现风险
            base -= 0.2
        return max(0.0, base)
    return 0.3 if (gap or 0) >= 2 else 0.1


def regime(market, idx_pcts, a50, nq, ysd_premium):
    """大盘环境分(0-100)与系数：A50期指、隔夜纳指、大盘竞价、昨日涨停溢价。
    只用实际拿到的数据加权，缺失项不拖低总分。"""
    parts, notes, wsum = [], [], 0.0
    def add(name, val, w):
        nonlocal wsum
        if val is not None:
            parts.append(max(0.0, min(1.0, val)) * w)
            notes.append(f"{name}: {val:+.2f}%")
            wsum += w
    sh = idx_pcts.get("sh000001", (None, None))[1]
    cyb = idx_pcts.get("sz399006", (None, None))[1]
    up = sum(1 for s in market if (s["pct"] or 0) > 0)
    dn = sum(1 for s in market if (s["pct"] or 0) < 0)
    add("上证竞价", sh / 2.0 if sh is not None else None, 0.25)
    add("创业板竞价", cyb / 2.0 if cyb is not None else None, 0.15)
    add("A50期指", a50, 0.25)
    add("纳指期货", nq, 0.2)
    if ysd_premium is not None:
        p = max(0.0, min(1.0, (ysd_premium + 2) / 6))  # -2%~+4% 映射 0~1
        parts.append(p * 0.15)
        notes.append(f"昨涨停竞价溢价: {ysd_premium:+.2f}%")
        wsum += 0.15
    # 涨跌家数宽度（永远可得）
    breadth = up / (up + dn) if (up + dn) else 0.5
    parts.append(breadth * 0.15)
    notes.append(f"市场宽度(涨占比): {breadth*100:.0f}%")
    wsum += 0.15
    score = int(round(sum(parts) / wsum * 100)) if wsum else 50
    factor = 1.1 if score >= 70 else (0.7 if score <= 35 else 1.0)
    return score, factor, notes


# ---------- 板块归属：用行业涨停池 + 板块成分股交集近似 ----------
def build_concept_map(boards_list, snap):
    code2names = {}
    name2code = {s["name"]: s["code"] for s in snap}
    for b in boards_list:
        b["_member_codes"] = set()
        b["_hot_peers"] = {}
    return code2names, name2code


def peers_hot(cons, gap_min=2.0):
    """成分股中竞价涨幅>=gap_min 的家数。"""
    n = 0
    for c in cons:
        if (c["pct"] or 0) >= gap_min:
            n += 1
    return n


def tactic(s, is_prev_zt, lbc):
    """一句话打法。"""
    g, amt = s.get("pct"), s.get("amount")
    yi = (amt or 0) / 1e8
    if g is None:
        return "数据缺失，观望"
    if g >= 9:
        return "一字/顶一字，竞价难成交；开盘看封单决定是否排板"
    if is_prev_zt and 2 <= g <= 6 and yi >= 0.3:
        return f"弱转强标准形态(昨{lbc}板今高开{g:.1f}%+竞价{yi:.1f}亿)，可竞价/开盘半路，破分时均线止损"
    if 2 <= g <= 6 and yi >= 0.3:
        return "竞价高开放量，开盘回踩不破竞价价可低吸，追高不超3%"
    if 0 <= g < 2 and yi >= 0.3:
        return "平开放量，等开盘第一波分时确认再动手，不抢跑"
    if g < 0:
        return "低开，除非急杀承接放量，否则观望"
    return "高开但量能一般，看开盘量比再定"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["morning"], default="morning")
    args = ap.parse_args()
    today = dt.date.today().strftime("%Y%m%d")
    now_t = dt.datetime.now()

    if not em.is_trade_date(today):
        print(f"## {today} 非交易日，休市。\n")
        return

    print("竞价数据拉取中（约1-2分钟）…\n", flush=True)

    # 1) 全市场快照（东财主源，失败自动切新浪）
    snap, src = em.market_snapshot()
    snap = [s for s in snap if s["code"] and s["price"] is not None]
    up = sum(1 for s in snap if (s["pct"] or 0) > 0)
    dn = sum(1 for s in snap if (s["pct"] or 0) < 0)
    total_amt = sum(s["amount"] or 0 for s in snap) / 1e8

    # 2) 指数 & 期指
    idx = em.index_pct(["sh000001", "sz399001", "sz399006", "sh000016", "sh000300", "sh000852"])
    fut = em.sina_quotes(["hf_CHA50CFD", "hf_NQ", "hf_YM"])
    a50_pct = (fut.get("hf_CHA50CFD", {}).get("price") / fut.get("hf_CHA50CFD", {}).get("prev") - 1) * 100 \
        if fut.get("hf_CHA50CFD", {}).get("prev") else None
    nq_pct = (fut.get("hf_NQ", {}).get("price") / fut.get("hf_NQ", {}).get("prev") - 1) * 100 \
        if fut.get("hf_NQ", {}).get("prev") else None

    # 3) 全球指数
    g = em.global_indices()
    gl = {x["name"]: x["pct"] for x in g}

    # 4) 昨日涨停今天表现 → 溢价 & 身位
    prev_day = em.prev_trade_date(today)
    prev_zt, ysd_premium = [], None
    try:
        prev_zt = em.zt_pool_previous(today)
        pcts = [z["pct"] for z in prev_zt if z.get("pct") is not None]
        if pcts:
            ysd_premium = sum(pcts) / len(pcts)
        for z in prev_zt:
            z["_lbc"] = z.get("lbc")
    except Exception:
        pass
    prev_map = {z["code"]: z for z in prev_zt}

    # 5) 板块热度（概念+行业，按涨幅排序取前12，并统计成分股竞价高开家数；东财限流时用涨停池行业分布兜底）
    boards_top = []
    try:
        concepts = em.boards("concept")
        industries = em.boards("industry")
        for b in concepts[:12] + industries[:8]:
            try:
                cons = em.board_cons(b["code"])
                b["_hot_peers"] = peers_hot(cons)
            except Exception:
                b["_hot_peers"] = 0
            time.sleep(0.2)
        boards_top = sorted(concepts + industries, key=lambda b: (b.get("_hot_peers", 0), b["pct"] or 0), reverse=True)[:12]
    except Exception:
        pass
    if not boards_top:
        # 兜底：用昨日涨停池行业分布近似板块热度
        ind_cnt = {}
        for z in prev_zt:
            ind = z.get("industry")
            if ind:
                ind_cnt[ind] = ind_cnt.get(ind, 0) + 1
        boards_top = [{"name": k, "pct": None, "main_in": None, "leader": "",
                       "leader_pct": None, "_hot_peers": v}
                      for k, v in sorted(ind_cnt.items(), key=lambda kv: -kv[1])[:8]]
        board_src = "涨停池行业分布（板块接口限流）"
    else:
        board_src = "东财板块"

    # 6) 环境分（算一次）+ 候选：竞价涨幅、金额过滤 + 打分
    env_s, env_f, env_notes = regime(snap, idx, a50_pct, nq_pct, ysd_premium)
    watch = set(CFG.get("watchlist", []))
    min_gap = CFG["min_gap_pct"]
    min_amt = CFG["min_amount_wan"] * 1e4
    cands = [s for s in snap
             if (s["pct"] or 0) >= min_gap
             and (s["amount"] or 0) >= min_amt
             and (s["float_mv"] or 0) > 2e9]  # 流通市值>20亿，过滤壳票
    for s in cands:
        s["_gap_s"] = gap_score(s["pct"])
        s["_vol_s"] = vol_score((s["amount"] or 0) / (s["float_mv"] or 1) * 100)
        s["_money_s"] = money_score((s["amount"] or 0) / 1e8)
        pv = prev_map.get(s["code"])
        s["_pos_s"] = position_score(pv.get("lbc") if pv else None, pv is not None, s["pct"])
        peer = 0
        for b in boards_top:
            if s["name"] and b.get("leader") == s["name"]:
                peer = max(peer, b.get("_hot_peers", 0))
        s["_peer_n"] = peer
        s["_board_s"] = board_score(s, snap, boards_top, {})
        s["_score"] = round(100 * env_f * (0.30 * s["_gap_s"] + 0.20 * s["_vol_s"] +
                                           0.20 * s["_money_s"] + 0.15 * s["_board_s"] +
                                           0.15 * s["_pos_s"]), 1)
        s["_why"] = f"昨{pv['lbc']}板" if pv else ""
        if s["name"] and any(b.get("leader") == s["name"] for b in boards_top):
            s["_why"] += " 板块领涨"
    cands.sort(key=lambda s: (-s["_score"], -(s["amount"] or 0)))
    cands = cands[:CFG["max_candidates"]]

    # 7) 消息面
    news = []
    try:
        news = em.news_cls(18)
    except Exception:
        pass
    if not news:
        try:
            news = em.news_breakfast(15)
        except Exception:
            pass
    gw, bw = set(CFG["good_words"]), set(CFG["bad_words"])
    def tag(t):
        if any(w in t for w in bw):
            return "⚠️"
        if any(w in t for w in gw):
            return "🔴利好"
        return "·"
    tagged = []
    for n in news:
        title = (n["title"] or "").strip() or (n.get("content") or "").strip()[:40]
        if not title or title == "None":
            continue  # 跳过空标题电报
        tagged.append((tag(title + n.get("content", "")), title))

    # 8) 跷跷板轮动（东财K线优先，新浪K线兜底）
    big = em.pct5_dual("1.000016", "sh000016")    # 上证50
    small = em.pct5_dual("1.000852", "sh000852")  # 中证1000
    hs300 = em.pct5_dual("1.000300", "sh000300")
    cyb5 = em.pct5_dual("0.399006", "sz399006")
    rot = []
    if big is not None and small is not None:
        d = big - small
        rot.append(("大小盘", f"上证50近5日 {big:+.1f}% vs 中证1000 {small:+.1f}%",
                    "大盘/权重占优 → 关注50成分、银行煤炭等红利" if d > 0 else "小盘/题材占优 → 关注中小票、题材连板"))
    if hs300 is not None and cyb5 is not None:
        d = cyb5 - hs300
        rot.append(("主板vs成长", f"创业板指近5日 {cyb5:+.1f}% vs 沪深300 {hs300:+.1f}%",
                    "成长/创业板占优 → 偏科技成长" if d > 0 else "价值/主板占优 → 偏白马红利"))

    # ---------- 输出 ----------
    L = []
    L.append(f"# 早盘竞价简报 {now_t.strftime('%Y-%m-%d %H:%M')}")
    L.append("")
    verdict = "强" if env_s >= 70 else ("弱" if env_s <= 35 else "中")
    L.append(f"## 一、大盘环境（{env_s}/100，定性：{verdict}，仓位系数 x{env_f}）〔数据源:{src}〕")
    L.append(f"- 竞价概况：上涨 {up} 家 / 下跌 {dn} 家，竞价成交合计 {total_amt:.0f} 亿")
    if idx:
        L.append("- 指数竞价：" + "，".join(f"{v[0]} {v[1]:+.2f}%" for v in idx.values()))
    if a50_pct is not None:
        L.append(f"- 期指：A50 {a50_pct:+.2f}%，纳指期货 {nq_pct:+.2f}%" if nq_pct is not None else f"- 期指：A50 {a50_pct:+.2f}%")
    if gl:
        items = [f"{k} {v:+.2f}%" for k, v in gl.items() if v is not None]
        L.append("- 隔夜/外围：" + "，".join(items))
    if ysd_premium is not None:
        L.append(f"- 昨日涨停股今日竞价平均溢价：{ysd_premium:+.2f}%（{'情绪进攻期' if ysd_premium > 2 else '分歧/退潮期' if ysd_premium < 0 else '震荡期'}）")
    L.append("")
    L.append("## 二、消息面要点")
    for t, title in tagged[:12]:
        L.append(f"- [{t}] {title}")
    L.append("")
    L.append(f"## 三、板块主攻方向（竞价热度 Top，来源：{board_src}）")
    for b in boards_top[:8]:
        bp = b.get("pct")
        L.append(f"- {b['name']} {bp:+.2f}%｜高开≥2%家数 {b.get('_hot_peers',0)}｜主力净流入 {(b.get('main_in') or 0)/1e8:+.1f}亿｜领涨 {b.get('leader') or '-'} {(b.get('leader_pct') or 0):+.1f}%"
                 if bp is not None else
                 f"- {b['name']}｜昨日涨停家数 {b.get('_hot_peers',0)}（板块行情接口限流）")
    L.append("")
    L.append("## 四、跷跷板轮动判断")
    for nm, ev, sug in rot:
        L.append(f"- 【{nm}】{ev} → {sug}")
    if not rot:
        L.append("- 轮动数据暂缺")
    L.append("")
    L.append(f"## 五、竞价关注池 Top{len(cands)}（综合分 = 竞价形态30% + 量能20% + 承接20% + 板块15% + 身位15%，再乘环境系数）")
    L.append("")
    L.append("| 排名 | 代码 | 名称 | 竞价涨幅% | 竞价金额 | 流通市值(亿) | 身位 | 板块 | 综合分 | 打法 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(cands, 1):
        amt_yi = (s["amount"] or 0) / 1e8
        L.append(f"| {i} | {s['code']} | {s['name']} | {s['pct']:+.2f} | {amt_yi:.2f}亿 | "
                 f"{(s['float_mv'] or 0)/1e8:.0f} | {s['_why'] or '首板/普通'} | - | **{s['_score']}** | {tactic(s, s['code'] in prev_map, prev_map.get(s['code'],{}).get('lbc'))} |")
    L.append("")
    L.append("## 六、今日打法与风控")
    if env_s >= 70:
        L.append("- 环境强：可进攻，按关注池前5名半路/低吸，单票仓位≤2成，总仓位≤7成")
    elif env_s <= 35:
        L.append("- 环境弱：防守，仅做前3名弱转强+板块效应强的一进二，仓位≤3成，其余观望")
    else:
        L.append("- 环境中：试错仓，只打板块龙头卡位/首板低吸，单票≤1.5成")
    L.append("- 信号确认：①9:30后第一分钟量比>3 且不破竞价低点 → 可加；②竞价金额/板块同响 应共振；③大盘翻绿+关注票炸板 → 无条件减仓")
    L.append("- 提醒：简报为量化辅助信号，不构成投资建议，买卖自行决策。")
    text = "\n".join(L)
    print(text)

    em.save(f"{today}_morning.md", text)
    em.save(f"{today}_morning.json", json.dumps(
        {"date": today, "env_score": env_s, "regime_notes": env_notes,
         "boards": [{k: v for k, v in b.items() if k != "_member_codes"} for b in boards_top],
         "candidates": cands[:len(cands)]}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
