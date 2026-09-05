# -*- coding: utf-8 -*-
"""
多角色研判（TradingAgents 架构的确定性移植，arXiv 2412.20138）：
技术/资金/消息/情绪 四分析师 + 多空对照 + 风控，全部引用因子数值（可溯源）。
可选 LLM 增强层：设置环境变量 GLM_API_KEY 或 OPENAI_API_KEY 后自动启用大模型复核；
未配置时使用规则引擎输出，同样给出结论与证据链。
"""
import json
import os


def _role(tech, view, evidence):
    return {"view": view, "evidence": evidence}


def analyze(stock, factors, ctx=None):
    """stock: fmt_stock 行；factors: compute_factors 结果；返回五角色研判。"""
    roles, bull, bear = {}, [], []
    pct = factors.get("pct") or 0
    to = factors.get("turnover") or 0
    amt = factors.get("amt_yi") or 0
    mi = factors.get("main_in_yi")
    chg60 = factors.get("chg60")
    pe, pb = factors.get("pe"), factors.get("pb")
    lbc = factors.get("lbc")
    prem = factors.get("zt_premium")
    a50, nq = factors.get("a50"), factors.get("nq")

    # 技术面
    ev = []
    if pct >= 8.5: view = "多"; ev.append(f"涨幅{pct:.1f}% 逼近涨停（pct）")
    elif pct >= 2: view = "多"; ev.append(f"涨幅{pct:+.1f}% 强于大盘（pct）")
    elif pct <= -2: view = "空"; ev.append(f"跌幅{pct:.1f}% 弱势（pct）")
    else: view = "中性"; ev.append(f"涨跌{pct:+.1f}% 波动有限（pct）")
    if 3 <= to <= 25: ev.append(f"换手{to:.1f}% 活跃适中（turnover）")
    elif to > 25: ev.append(f"换手{to:.1f}% 过热注意分歧（turnover）")
    if chg60 is not None and chg60 <= -20: ev.append(f"60日已跌{chg60:.1f}% 处超跌区（chg60）")
    roles["技术面"] = _role("tech", view, ev)

    # 资金面
    ev = []
    if mi is None:
        fview = "中性"; ev.append("主力数据缺源，按中性处理（main_in_yi）")
    elif mi > 0.3: fview = "多"; ev.append(f"主力净流入 {mi:+.2f} 亿（main_in_yi）")
    elif mi < -0.3: fview = "空"; ev.append(f"主力净流出 {mi:+.2f} 亿（main_in_yi）")
    else: fview = "中性"; ev.append(f"主力净额 {mi:+.2f} 亿不明显（main_in_yi）")
    if amt >= 3: ev.append(f"成交 {amt:.1f} 亿 承接充足（amt_yi）")
    roles["资金面"] = _role("fund", fview, ev)
    if fview == "多": bull.append(f"资金面：{mi:+.2f}亿主力净流入")
    if fview == "空": bear.append(f"资金面：{mi:+.2f}亿主力净流出")

    # 消息面（由外部注入 ctx['news_hint']，未命中则中性）
    nview, nev = "中性", ["近2小时电报未命中该股关键词（消息面）"]
    hint = (ctx or {}).get("news_hint", {}).get(stock.get("code"))
    if hint:
        nview, nev = ("多", [f"电报命中利好：{hint}（财联社，已标注）"]) if hint["tag"] == "good" \
            else ("空", [f"电报命中利空：{hint['title'][:30]}（财联社）"])
    roles["消息面"] = _role("news", nview, nev)

    # 情绪面（市场级因子）
    ev = []
    if prem is not None:
        ev.append(f"昨涨停溢价 {prem:+.2f}%（zt_premium）")
        if prem >= 2: sview = "多"; ev.append("接力资金积极（>2% 为进攻期）")
        elif prem <= -2: sview = "空"; ev.append("接力亏损（<-2% 为退潮）")
        else: sview = "中性"; ev.append("情绪中性震荡")
    else:
        sview = "中性"; ev.append("溢价数据缺源，中性（zt_premium）")
    if a50 is not None: ev.append(f"A50期指 {a50:+.2f}%（a50）")
    if nq is not None: ev.append(f"纳指期货 {nq:+.2f}%（nq）")
    roles["情绪面"] = _role("sentiment", sview, ev)

    # 风控
    ev = []
    if pct >= 9: ev.append("已涨停追入风险高，竞价高开>7%放弃")
    if (factors.get("float_yi") or 999) < 20: ev.append("流通市值偏小，波动放大")
    if pe is not None and pe < 0: ev.append("亏损股，基本面免责保护失效")
    if lbc: ev.append(f"昨{lbc}板高位股，注意分歧转一致节奏")
    if not ev: ev.append("无特殊风险标记（按标准纪律执行）")
    roles["风控"] = _role("risk", "提示", ev)

    # 多空对照 + 结论（多=2票以上权重：资金/技术/情绪/消息）
    votes = [roles["技术面"]["view"], roles["资金面"]["view"], roles["消息面"]["view"], roles["情绪面"]["view"]]
    duo, kong = votes.count("多"), votes.count("空")
    verdict = "偏多" if duo - kong >= 2 else ("偏空" if kong - duo >= 2 else "观望")
    conf = min(90, 40 + abs(duo - kong) * 20 + (10 if amt >= 3 else 0))

    out = {"roles": roles, "bull": bull or ["无显著多头证据"], "bear": bear or ["无显著空头证据"],
           "verdict": verdict, "confidence": conf, "llm_enhanced": False}

    # LLM 增强插槽（配置了 key 才启用；失败静默回退规则结果）
    key = os.environ.get("GLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        try:
            out = _llm_refine(out, stock, factors, key) or out
            out["llm_enhanced"] = True
        except Exception:
            pass
    return out


def _llm_refine(out, stock, factors, key):
    """最小 LLM 复核：把规则结论+因子表交给模型重排结论。"""
    glm = os.environ.get("GLM_API_KEY")
    if glm:
        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        model, hdr, keyid = "glm-4-flash", {"Authorization": f"Bearer {glm}"}, glm
    else:
        url = "https://api.openai.com/v1/chat/completions"
        model, hdr, keyid = "gpt-4o-mini", {"Authorization": f"Bearer {key}"}, key
    prompt = ("你是风控复核员。根据以下因子JSON重估结论(偏多/偏空/观望)与置信度(0-100)，"
              "输出JSON：{\"verdict\":\"..\",\"confidence\":..,\"reason\":\"50字内\"}。因子："
              + json.dumps(factors, ensure_ascii=False) + " 规则结论：" + json.dumps(out, ensure_ascii=False))
    import requests
    r = requests.post(url, headers={**hdr, "Content-Type": "application/json"}, timeout=20,
                      json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0})
    txt = r.json()["choices"][0]["message"]["content"]
    js = txt[txt.find("{"): txt.rfind("}") + 1]
    d = json.loads(js)
    out["verdict"], out["confidence"], out["llm_reason"] = d.get("verdict", out["verdict"]), d.get("confidence", out["confidence"]), d.get("reason", "")
    return out
