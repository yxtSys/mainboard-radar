# -*- coding: utf-8 -*-
"""
主板雷达 · 后端服务
- 复用 quant/emdata.py 的多源数据层（东财主源 + 新浪/腾讯兜底）
- 后台线程统一拉数据、缓存后供 3 人共享，手机/电脑各自轮询本服务，不打数据源
- 默认规则不可关闭：仅主板（60x/000/001/002/003），排除 ST/退/北交所；次新与价格区间由前端传入
"""
import datetime as dt
import json
import sys
import threading
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent  # 工作区根目录（quant/ 的上一级）
sys.path.insert(0, str(ROOT / "quant"))
import emdata as em  # noqa: E402
from scoring import score_stock, is_valid_stock, fmt_stock, primary_strategy  # noqa: E402,F401
from factors import FACTORS, compute_factors  # noqa: E402,F401
from agents import analyze  # noqa: E402,F401
import chain as chainmod  # noqa: E402

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

DATA_DIR = ROOT / "webapp" / "data"
DATA_DIR.mkdir(exist_ok=True)
USERS_FILE = DATA_DIR / "users.json"

MAIN_PREFIX = ("600", "601", "603", "605", "000", "001", "002", "003")

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

CACHE = {"snapshot": [], "snapshot_src": "", "snapshot_at": 0, "snapshot_loading": False,
         "boards": [], "boards_src": "", "boards_at": 0,
         "indices": {}, "indices_at": 0,
         "etf": [], "etf_at": 0,
         "zt": [], "zt_date": "", "zt_at": 0}
LOCK = threading.Lock()


def now_s():
    return dt.datetime.now().strftime("%H:%M:%S")


def is_trading_now():
    n = dt.datetime.now()
    if n.weekday() >= 5:
        return False
    t = n.hour * 100 + n.minute
    return (915 <= t <= 1135) or (1255 <= t <= 1505)


def trading_day_str():
    return dt.date.today().strftime("%Y%m%d")


def refresh_boards():
    items, src = [], "eastmoney"
    try:
        cons = em.boards("concept")
        inds = em.boards("industry")
        for b in cons:
            b["type"] = "concept"
        for b in inds:
            b["type"] = "industry"
        items = cons + inds
    except Exception:
        pass
    if not items:
        # 第二兜底：同花顺行业即时资金流（真实净额+涨跌幅）；概念接口单独容错
        try:
            items = em.ths_fund_flow("industry")
            src = "ths_flow"
        except Exception:
            items, src = [], "offline"
        if items:
            try:
                items += em.ths_fund_flow("concept")
            except Exception:
                pass
    if not items:
        # 第三兜底：新浪行业实时涨跌（无资金）
        try:
            items = em.sina_industries()
            src = "sina_industry"
        except Exception:
            items, src = [], "offline"
    if not items:
        # 最终兜底：涨停池行业分布（热度）
        try:
            zt = get_zt()
            cnt = {}
            for z in zt:
                ind = z.get("industry")
                if ind:
                    cnt[ind] = cnt.get(ind, 0) + 1
            items = [{"code": "IND:" + k, "name": k, "pct": None, "main_in": None,
                      "type": "zt_fallback", "zt_n": v, "heat": v} for k, v in cnt.items()]
            src = "zt_pool_fallback"
        except Exception:
            src = "offline"
    with LOCK:
        CACHE["boards"] = items
        CACHE["boards_src"] = src
        CACHE["boards_at"] = time.time()


def refresh_snapshot():
    with LOCK:
        if CACHE["snapshot_loading"]:
            return
        CACHE["snapshot_loading"] = True
    try:
        snap, src = em.market_snapshot()
        with LOCK:
            CACHE["snapshot"] = [s for s in snap if s.get("code") and s.get("price")]
            CACHE["snapshot_src"] = src
            CACHE["snapshot_at"] = time.time()
    finally:
        with LOCK:
            CACHE["snapshot_loading"] = False
    check_alerts()


def refresh_indices():
    try:
        idx = em.index_pct(["sh000001", "sz399001", "sz399006", "sh000016", "sh000300", "sh000852"])
        with LOCK:
            CACHE["indices"] = idx
            CACHE["indices_at"] = time.time()
    except Exception:
        pass


def refresh_etf():
    syms = ["sh" + c if c[0] == "5" else "sz" + c for c, _, _, _ in ETF_LIST]
    out = []
    try:
        import requests
        url = "https://qt.gtimg.cn/q=" + ",".join("s_" + s for s in syms)
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.encoding = "gbk"
        by_code = {}
        for line in r.text.strip().splitlines():
            if '"' not in line:
                continue
            f = line.split('"')[1].split("~")
            if len(f) > 5 and f[2]:
                by_code[f[2]] = {"name": f[1], "price": em._num(f[3]), "pct": em._num(f[5])}
        for code, name, groups, reason in ETF_LIST:
            v = by_code.get(code, {})
            out.append({"code": code, "name": name, "groups": groups, "reason": reason,
                        "price": v.get("price"), "pct": v.get("pct")})
        with LOCK:
            CACHE["etf"] = out
            CACHE["etf_at"] = time.time()
    except Exception:
        pass


def get_zt():
    today = trading_day_str()
    with LOCK:
        if CACHE["zt_date"] == today and CACHE["zt_at"] > time.time() - 600:
            return CACHE["zt"]
    try:
        zt = em.zt_pool(today)
        with LOCK:
            CACHE["zt"] = zt
            CACHE["zt_date"] = today
            CACHE["zt_at"] = time.time()
        return zt
    except Exception:
        return []


# ---------- 策略评分 ----------
def score_stock(s):
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

    # 资金/换手缺失时降权提示
    if s.get("main_in") is None:
        for k in res:
            res[k]["score"] = int(res[k]["score"] * 0.9)
    return res


def is_valid_stock(code, name):
    code = str(code)
    if not code.startswith(MAIN_PREFIX):
        return False
    n = name or ""
    if "ST" in n or "退" in n:
        return False
    return True


def board_detail(code, pmin, pmax):
    snap = {s["code"]: s for s in (CACHE.get("snapshot") or [])}

    def build(stocks_raw, limited, note=None):
        out = []
        for s in stocks_raw:
            if not is_valid_stock(s.get("code"), s.get("name")):
                continue
            s = dict(s)
            extra = snap.get(s["code"])
            if extra:
                for k in ("pe", "pb", "chg60", "mktcap", "main_in"):
                    if s.get(k) is None:
                        s[k] = extra.get(k)
            p = s.get("price")
            if p is None or not (pmin <= p <= pmax) or p < 2:
                continue
            s["strategies"] = score_stock(s)
            s["strategy"] = primary_strategy(s["strategies"], s)["strategy"]
            out.append(s)
        out.sort(key=lambda s: -s["strategies"]["cs"]["score"])
        return {"limited": limited, "note": note, "stocks": [fmt_stock(s) for s in out[:40]]}

    # 同花顺行业/概念：成员用涨停池行业匹配 + 新浪行业模糊匹配 + 领涨股
    if code.startswith(("THSI:", "THSC:")):
        ths_name = code.split(":", 1)[1]
        zt = get_zt()
        picks = {str(z["code"]) for z in zt
                 if z.get("industry") and (ths_name in str(z["industry"]) or str(z["industry"]) in ths_name)}
        if len(picks) >= 2:
            stocks = [snap[c] for c in picks if c in snap and is_valid_stock(c, snap[c].get("name"))
                      and pmin <= snap[c]["price"] <= pmax]
            d = build(stocks, limited=True,
                      note=f"成分取自该方向今日涨停/强势成员（同花顺口径：{ths_name}）；主力资金为同花顺数据")
            d["name"] = ths_name
            return d
        try:
            for ind in em.sina_industries():
                if ths_name in ind["name"] or ind["name"] in ths_name:
                    cons = em.sina_node_members(ind["code"][5:])
                    d = build(cons, limited=True,
                              note=f"成分来自新浪行业「{ind['name']}」近似匹配；主力资金为同花顺数据")
                    d["name"] = ths_name
                    return d
        except Exception:
            pass
        lead = [b for b in CACHE["boards"] if b["code"] == code]
        lead_stock = None
        if lead and lead[0].get("leader"):
            lead_stock = snap.get(next((c for c, s in snap.items() if s["name"] == lead[0]["leader"]), ""))
        d = build([lead_stock] if lead_stock else [], limited=True,
                  note=f"「{ths_name}」成分暂缺，仅展示该方向领涨股（同花顺口径）")
        d["name"] = ths_name
        return d
    # 新浪行业成分
    if code.startswith("SINA:"):
        try:
            cons = em.sina_node_members(code[5:])
        except Exception as e:
            raise HTTPException(503, f"新浪成分接口失败：{e}")
        d = build(cons, limited=True, note="东财板块限流中，行业成分来自新浪；主力资金暂缺")
        d["name"] = next((b["name"] for b in CACHE["boards"] if b["code"] == code), code[5:])
        return d
    # 涨停池行业兜底
    if code.startswith("IND:"):
        ind = code[4:]
        zt = get_zt()
        codes = {str(z["code"]) for z in zt if z.get("industry") == ind}
        stocks = [snap[c] for c in codes if c in snap and is_valid_stock(c, snap[c].get("name"))
                  and pmin <= snap[c]["price"] <= pmax]
        stocks.sort(key=lambda s: -(s.get("amount") or 0))
        return {"name": ind, "limited": True,
                "note": "板块行情接口限流，以下为该行业昨日涨停成员（已按你的区间过滤）",
                "stocks": [fmt_stock(s) for s in stocks[:30]]}
    try:
        cons = em.board_cons(code)
    except Exception as e:
        raise HTTPException(503, f"板块成分接口限流：{e}")
    d = build(cons, limited=False)
    d["name"] = cons[0].get("name") if cons else code
    return d


def fmt_stock(s):
    return {"code": s["code"], "name": s["name"], "price": s.get("price"),
            "pct": s.get("pct"), "amount": s.get("amount"), "turnover": s.get("turnover"),
            "main_in": s.get("main_in"), "float_mv": s.get("float_mv"),
            "pe": s.get("pe"), "pb": s.get("pb"), "chg60": s.get("chg60"),
            "strategies": s.get("strategies") or score_stock(s)}


# ---------- 用户档案（3 人白名单） ----------
def load_users():
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def save_users(u):
    USERS_FILE.write_text(json.dumps(u, ensure_ascii=False, indent=1), encoding="utf-8")


def auth(name, pin):
    u = load_users()
    if name not in u or str(u[name].get("pin")) != str(pin):
        raise HTTPException(401, "昵称或口令不对")
    return u[name]


def check_alerts():
    users = load_users()
    snap = {s["code"]: s for s in (CACHE.get("snapshot") or [])}
    changed = False
    for nm, prof in users.items():
        for a in prof.get("alerts", []):
            if a.get("triggered_at"):
                continue
            s = snap.get(a["code"])
            if not s or not s.get("price"):
                continue
            hit = (a["dir"] == "above" and s["price"] >= a["price"]) or \
                  (a["dir"] == "below" and s["price"] <= a["price"])
            if hit:
                a["triggered_at"] = now_s()
                a["trigger_price"] = s["price"]
                changed = True
    if changed:
        save_users(users)


# ---------- 后台刷新线程（交易时段 10 秒级；休市期间行情不变，降频省请求） ----------
def refresher():
    last_snap = 0
    while True:
        try:
            trading = is_trading_now()
            if trading:
                if time.time() - last_snap > 60:
                    refresh_snapshot()
                    last_snap = time.time()
                refresh_boards()
                refresh_indices()
                refresh_etf()
                time.sleep(10)
            else:
                if time.time() - last_snap > 600:
                    refresh_snapshot()
                    last_snap = time.time()
                refresh_boards()
                refresh_indices()
                refresh_etf()
                time.sleep(60)
        except Exception:
            time.sleep(10)


app = FastAPI(title="主板雷达")
threading.Thread(target=refresher, daemon=True).start()


@app.get("/api/status")
def status():
    trading = is_trading_now()
    with LOCK:
        return {"now": now_s(), "trading": trading,
                "snapshot_src": CACHE["snapshot_src"], "snapshot_n": len(CACHE["snapshot"]),
                "snapshot_at": CACHE["snapshot_at"] and dt.datetime.fromtimestamp(CACHE["snapshot_at"]).strftime("%H:%M:%S"),
                "snapshot_loading": CACHE["snapshot_loading"],
                "boards_src": CACHE["boards_src"],
                "boards_at": CACHE["boards_at"] and dt.datetime.fromtimestamp(CACHE["boards_at"]).strftime("%H:%M:%S")}


@app.get("/api/indices")
def indices():
    with LOCK:
        return {"updated": dt.datetime.fromtimestamp(CACHE["indices_at"]).strftime("%H:%M:%S") if CACHE["indices_at"] else "",
                "items": [{"sym": k, "name": v[0], "pct": v[1]} for k, v in CACHE["indices"].items()]}


@app.get("/api/boards")
def boards():
    with LOCK:
        items = CACHE["boards"]
        src = CACHE["boards_src"]
        at = CACHE["boards_at"]
    return {"source": src,
            "updated": dt.datetime.fromtimestamp(at).strftime("%H:%M:%S") if at else "",
            "items": [{k: b.get(k) for k in ("code", "name", "pct", "main_in", "type", "zt_n", "heat")} for b in items]}


@app.get("/api/board/{code}")
def board(code: str, pmin: float = 0, pmax: float = 10000, mode: str = ""):
    d = board_detail(code, pmin, pmax)
    if mode in ("cs", "short", "mid", "long"):
        same = [s for s in d["stocks"] if s.get("strategy") == mode]
        if same:
            d["stocks"] = same
            d["mode_filtered"] = True
    return d


@app.get("/api/etf")
def etf():
    with LOCK:
        items, at = CACHE["etf"], CACHE["etf_at"]
    return {"updated": dt.datetime.fromtimestamp(at).strftime("%H:%M:%S") if at else "",
            "items": items}


@app.post("/api/profile")
def profile_upsert(name: str = Query(...), pin: str = Query(...),
                   pmin: float = 0, pmax: float = 20):
    users = load_users()
    prof = users.get(name)
    if prof and str(prof.get("pin")) != str(pin):
        raise HTTPException(401, "该昵称已存在且口令不符")
    prof = prof or {"watchlist": [], "alerts": []}
    prof.update({"pin": str(pin), "pmin": pmin, "pmax": pmax})
    users[name] = prof
    save_users(users)
    return {"ok": True, "profile": {k: prof.get(k) for k in ("pmin", "pmax", "watchlist", "alerts")}}


@app.get("/api/profile")
def profile_get(name: str = Query(...), pin: str = Query(...)):
    prof = auth(name, pin)
    return {"name": name, "pmin": prof.get("pmin", 0), "pmax": prof.get("pmax", 20),
            "watchlist": prof.get("watchlist", []), "alerts": prof.get("alerts", []),
            "mode": prof.get("mode", "short"), "activity": prof.get("activity", [])[:20],
            "last": prof.get("last")}


@app.post("/api/watchlist")
def watchlist(name: str = Query(...), pin: str = Query(...), code: str = Query(...), action: str = "add"):
    prof = auth(name, pin)
    wl = prof.setdefault("watchlist", [])
    if action == "add" and code not in wl:
        wl.append(code)
    if action == "del" and code in wl:
        wl.remove(code)
    save_users(load_users() | {name: prof})
    return {"ok": True, "watchlist": wl}


@app.post("/api/alert")
def alert_add(name: str = Query(...), pin: str = Query(...), code: str = Query(...),
              price: float = Query(...), direction: str = Query("above")):
    prof = auth(name, pin)
    prof.setdefault("alerts", []).append(
        {"code": code, "price": price, "dir": direction, "created": now_s(), "triggered_at": None})
    save_users(load_users() | {name: prof})
    return {"ok": True}


@app.post("/api/activity")
def activity(name: str = Query(...), pin: str = Query(...), kind: str = Query(...), label: str = Query(""), code: str = Query("")):
    prof = auth(name, pin)
    rec = {"t": now_s(), "kind": kind, "label": label[:60], "code": code[:12]}
    if kind == "mode" and label in ("cs", "short", "mid", "long"):
        prof["mode"] = label
    if kind in ("board", "stock", "chain"):
        prof["last"] = rec
    acts = prof.setdefault("activity", [])
    acts.insert(0, rec)
    del acts[60:]
    save_users(load_users() | {name: prof})
    return {"ok": True, "mode": prof.get("mode", "short"), "last": prof.get("last")}


@app.get("/api/alerts")
def alerts(name: str = Query(...), pin: str = Query(...)):
    prof = auth(name, pin)
    return {"alerts": prof.get("alerts", [])}


NEWS_CACHE = {"at": 0.0, "items": []}


@app.get("/api/news")
def news():
    """财联社电报 + 关键词利好利空标注（60秒缓存）。"""
    if NEWS_CACHE["at"] > time.time() - 60:
        return {"updated": dt.datetime.fromtimestamp(NEWS_CACHE["at"]).strftime("%H:%M:%S"),
                "items": NEWS_CACHE["items"]}
    items = []
    try:
        raw = em.news_cls(20)
    except Exception:
        raw = []
    try:
        cfg = json.loads((ROOT / "quant" / "config.json").read_text(encoding="utf-8"))
        gw, bw = set(cfg.get("good_words", [])), set(cfg.get("bad_words", []))
    except Exception:
        gw, bw = set(), set()
    for n in raw:
        title = (n.get("title") or "").strip()
        content = (n.get("content") or "").strip()
        if not title:
            title = content[:40]
        if not title:
            continue
        tag = "mid"
        if any(w in (title + content) for w in bw):
            tag = "bad"
        elif any(w in (title + content) for w in gw):
            tag = "good"
        items.append({"title": title, "tag": tag, "time": str(n.get("time", ""))})
    with LOCK:
        NEWS_CACHE.update({"at": time.time(), "items": items})
    return {"updated": now_s(), "items": items}


@app.get("/api/stock/{code}")
def stock_detail(code: str):
    """个股深拆：公司资料 + 主营业务构成 + 多角色研判 + 操作风格建议（拿住 vs 做T）。"""
    snap = {s["code"]: s for s in (CACHE.get("snapshot") or [])}
    s = snap.get(code)
    if not s:
        raise HTTPException(404, "快照中无此股（可能停牌/非主板）")
    profile, zygc, zsrc = {}, [], []
    sym = ("SH" if code[0] == "6" else "SZ") + code
    try:
        import akshare as ak
        try:
            pf = ak.stock_profile_cninfo(symbol=sym)
            if pf is not None and len(pf):
                row = pf.iloc[0]
                profile = {k: str(row[k]) for k in ("公司名称", "英文名称", "简介", "主要产品及业务", "所属行业", "成立日期") if k in pf.columns}
                zsrc.append("巨潮资讯")
        except Exception:
            pass
        try:
            df = None
            for attempt in range(2):
                try:
                    df = ak.stock_zygc_em(symbol=sym)
                    if df is not None and len(df):
                        break
                except Exception:
                    time.sleep(2)
                    df = None
            if df is not None and len(df):
                latest = df["报告日期"].max()
                sub = df[df["报告日期"] == latest].head(14)
                def _pct(v):
                    try:
                        v = float(v)
                        return round(v * 100, 1) if v <= 1.5 else round(v, 1)
                    except Exception:
                        return None
                zygc = [{"类型": str(r.get("分类类型", "")), "构成": str(r["主营构成"]),
                         "收入(亿)": round(float(r["主营收入"]) / 1e8, 2) if r["主营收入"] == r["主营收入"] else None,
                         "占比%": _pct(r["收入比例"]),
                         "毛利率%": _pct(r["毛利率"]) if "毛利率" in df.columns else None}
                        for _, r in sub.iterrows()]
                zsrc.append("东方财富数据中心(F10主营构成)")
        except Exception:
            pass
    except Exception:
        pass
    strategies = score_stock(s)
    strategy = primary_strategy(strategies, s)
    factors = compute_factors(s, {})
    agents_res = analyze(s, factors, {})
    # 股东结构（十大股东，来源：东财数据中心）
    holders = []
    try:
        import akshare as ak
        df = ak.stock_gdfx_top_10_em(symbol=sym, date=f"{dt.date.today().year}0630")
        holders = [{"name": str(r["股东名称"]), "pct": round(float(r["占总股本持股比例"]), 2)}
                   for _, r in df.head(5).iterrows() if r.get("占总股本持股比例") == r.get("占总股本持股比例")]
    except Exception:
        pass
    # 产业链定位 + 同链条公司
    try:
        chain_data = chainmod.chain_profile(code, zygc, (profile or {}).get("所属行业", ""), s.get("name", ""), list(snap.values()), get_zt())
    except Exception:
        chain_data = {"positions": [], "peers": [], "chains_known": list(chainmod.CHAINS.keys())}
    # —— 量化操作建议：全部由因子推导，每个数字可复算 ——
    to = s.get("turnover") or 0
    pct = s.get("pct") or 0
    amt = (s.get("amount") or 0) / 1e8
    mi = (s.get("main_in") or 0) / 1e8
    chg60 = s.get("chg60")
    mv = (s.get("float_mv") or 0) / 1e8
    t_score = int(min(100, to * 4 + abs(pct or 0) * 5 + (min(amt, 20) if amt else 0)))          # 做T适合度
    hold_score = int(min(100, (30 if (chg60 is not None and chg60 > -5) else 10) + (25 if mi > 0 else 5) + strategy["score"] * 0.4))  # 拿住适合度
    price = s.get("price") or 0
    lvl = {"buy1": round(price * 0.98, 2), "buy2": round(price * 0.96, 2),
           "reduce1": round(price * 1.03, 2), "reduce2": round(price * 1.05, 2),
           "stop": round(price * 0.95, 2)}
    pos = "全仓（用户自定）"
    if t_score >= 70:
        style, how = "适合做T/波段（量化T分 %d/100）" % t_score, f"锚1=竞价价(9:25撮合价)：回踩不破低吸；锚2=分时均价线：线上持有线下停T；冲高3~5%（{lvl['reduce1']}~{lvl['reduce2']}）减一份"
    elif t_score >= 45:
        style, how = "底仓拿住 + 2~3成做T（T分 %d/100）" % t_score, "锚=分时均价线与昨收价之间高抛低吸；破均价线当日停T"
    else:
        style, how = "适合拿住（T分 %d/100，做T磨损大于收益）" % t_score, f"锚=量化买入区间：分批于{lvl['buy1']}/{lvl['buy2']}，跌破{lvl['stop']}止损（-5%硬纪律）"
    ops = {"t_score": t_score, "hold_score": hold_score, "levels": lvl, "position": pos,
           "style": style, "how": how,
           "anchors": ["竞价价(9:25撮合)", "分时均价线", "板块领涨股(锚定龙头不动手弱跟风)", "大盘环境分"],
           "buy": f"买1 {lvl['buy1']}（回踩2%）；买2 {lvl['buy2']}（深回踩4%）；突破减仓位 {lvl['reduce1']} 不追",
           "stop": f"止损 {lvl['stop']}（-5%硬纪律）；跌破竞价价且反抽不过均价线先减半"}
    def _clean(v):
        if isinstance(v, dict):
            return {k: _clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_clean(x) for x in v]
        if isinstance(v, float) and v != v:
            return None
        return v

    return _clean({"code": code, "name": s["name"], "price": s.get("price"), "pct": s.get("pct"),
            "strategy": strategy["strategy"], "strategy_score": strategy["score"],
            "strategies": strategies, "factors": factors, "agents": agents_res,
            "profile": profile, "zygc": zygc, "zygc_source": zsrc,
            "chain": chain_data, "holders": holders,
            "ops": ops, "float_yi": round(mv, 1), "chg60": chg60,
            "source": {"行情": "东财/新浪快照", "公司资料": zsrc or "未取到", "研判": "quant/agents.py 规则链+因子数值",
                       "产业链": "quant/chain.py 模板+主营构成关键词（东财概念成分/涨停池降级）"}})


app.mount("/", StaticFiles(directory=str(ROOT / "webapp" / "static"), html=True))


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", "8787"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
