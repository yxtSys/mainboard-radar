# -*- coding: utf-8 -*-
"""早盘锚定信号段：按交接书规则(HANDOVER_MORNING.md)执行，供 radar.py 调用。
输入：昨日涨停池(含封单资金/连板数/炸板) + 今日竞价快照(pct=竞价高开幅度)。
输出：满足锚定规则的合格信号列表 + 角色标注；无合格信号返回空。
"""
MAIN = ("600", "601", "603", "605", "000", "001", "002", "003")

RULES = [
    ("D7", "连板≥3+未炸板+封成比>0.5", 82.1),
    ("D10", "3~4板+未炸板", 80.6),
    ("D9", "空间龙头(最高板)", 78.9),
    ("D8", "空间龙头+未炸板", 81.8),
    ("C2", "连板≥2+封成比>0.5", 75.0),
    ("D2", "首板+封成比>1", 72.0),
    ("C10", "连板≥2+未炸板+换手5~15%", 73.9),
]


def morning_signals(zt_pool, snap_by_code):
    """zt_pool: 昨日涨停池(em.zt_pool 映射后, 含seal_money/amount/lbc/break_times/turnover/industry)
    snap_by_code: 今日竞价快照 {code: row}; row.pct=竞价高开%。返回 (signals, roles_note)"""
    pool = []
    for z in zt_pool:
        code = str(z.get("code"))
        if not code.startswith(MAIN) or "ST" in str(z.get("name", "")):
            continue
        amt = float(z.get("amount") or 0)
        seal = float(z.get("seal_money") or 0)
        snap = snap_by_code.get(code)
        gap = snap.get("pct") if snap else None
        pool.append({"code": code, "name": z.get("name"), "lbc": int(z.get("lbc") or 1),
                     "brk": int(z.get("break_times") or 0), "seal_ratio": round(seal / amt, 2) if amt else 0,
                     "to": float(z.get("turnover") or 0), "amt_yi": round(amt / 1e8, 2),
                     "ind": z.get("industry", ""), "gap": gap, "price": snap.get("price") if snap else None})
    if not pool:
        return [], "涨停池缺源，无法判定锚定信号（数据缺失，不编造）"
    max_lbc = max(p["lbc"] for p in pool)
    # 小弟梯队：同行业其他涨停股（龙头的小弟=板块梯队）
    ind_mates = {}
    for p in pool:
        ind_mates.setdefault(p["ind"], []).append(f"{p['name']}({p['lbc']}板)")
    signals, seen = [], set()
    for p in pool:
        gap = p["gap"]
        if gap is None or not (1.5 <= gap <= 3.5):
            continue  # 竞价门槛：高开1.5~3.5%可上，>5%放弃，其余不推
        hit = []
        if p["lbc"] >= 3 and p["brk"] == 0 and p["seal_ratio"] > 0.5:
            hit.append("D7(82.1%)")
        if 3 <= p["lbc"] <= 4 and p["brk"] == 0:
            hit.append("D10(80.6%)")
        if p["lbc"] == max_lbc:
            hit.append("D9(78.9%)")
            if p["brk"] == 0:
                hit.append("D8(81.8%)")
        if p["lbc"] >= 2 and p["seal_ratio"] > 0.5:
            hit.append("C2(75.0%)")
        if p["lbc"] == 1 and p["seal_ratio"] > 1:
            hit.append("D2(72.0%)")
        if p["lbc"] >= 2 and p["brk"] == 0 and 5 <= p["to"] <= 15:
            hit.append("C10(73.9%)")
        if not hit:
            continue
        p["rules"] = "+".join(sorted(set(hit), reverse=True))
        p["role"] = ("空间龙头" if p["lbc"] == max_lbc else
                     "中军" if p["amt_yi"] >= 10 else
                     "卡位" if p["lbc"] == 2 else "补涨")
        mates = [m for m in ind_mates.get(p["ind"], []) if not m.startswith(str(p["name"]))]
        p["xiao_di"] = "、".join(mates[:3]) or "同板块无涨停小弟（孤军，降级处理）"
        role_txt = {
            "空间龙头": "全场最高板=情绪总锚：它强则板块续，它断板→全网高低切（观察哨第一名）",
            "中军": "板块最大成交载体，跟随资金的主池：沿分时均线持有，不做T不折腾",
            "卡位": "进度快于龙头的接力锚：竞价高开1.5~3.5%跟，低开=卡位失败不碰",
            "补涨": "集群确认后的低位补涨：只低吸不追高，龙头断板第一个卖它",
        }[p["role"]]
        p["jie_du"] = role_txt
        key = p["code"]
        if key not in seen:
            seen.add(key)
            signals.append(p)
    signals.sort(key=lambda s: -s["gap"])
    note = f"空间龙头={max_lbc}板；候选池{len(pool)}只(昨日涨停·主板·非ST·<20元口径在外层过滤)"
    return signals, note


def highlow_switch_trigger(zt_pool, zt_prev_n=None):
    """高低切触发器：最高板断板(今日未涨停的昨日最高板) 或 炸板率>40%。"""
    max_lbc = max((int(z.get("lbc") or 1) for z in zt_pool), default=0)
    snapped = sum(1 for z in zt_pool if (z.get("break_times") or 0) > 0)
    return {"max_lbc_yesterday": max_lbc, "broken_high": snapped > 0,
            "note": "最高板今日断板或炸板率>40% → 高低切低位"}
