# -*- coding: utf-8 -*-
"""东财/新浪公开行情接口封装（分页拉取全市场快照、板块、指数、期指、涨停池）。"""
import json
import math
import time
from pathlib import Path

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
     "Referer": "https://quote.eastmoney.com/"}
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

PUSH2 = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
ULIST = "https://push2.eastmoney.com/api/qt/ulist.np/get"


def _get(url, params, tries=3, timeout=15):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=H, timeout=timeout)
            return r.json()
        except Exception as e:  # 网络抖动/反爬，退避重试
            last = e
            time.sleep(2 + 2 * i)
    raise last


def _num(v):
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def _snapshot_em():
    """东财全市场快照（慢速分页 + 镜像轮换，防反爬）。"""
    rows, page, total = [], 1, None
    hosts = ["push2.eastmoney.com", "1.push2.eastmoney.com", "90.push2.eastmoney.com"]
    while True:
        p = {"pn": page, "pz": 100, "po": 0, "np": 1, "fltt": 2, "invt": 2,
             "fid": "f12",
             "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
             "fields": "f2,f3,f6,f8,f9,f10,f12,f14,f20,f21,f22,f23,f24,f62"}
        host = hosts[(page - 1) % len(hosts)]
        try:
            d = requests.get(f"https://{host}/api/qt/clist/get", params=p, headers=H,
                             timeout=12).json().get("data") or {}
        except Exception:
            time.sleep(3)
            d = _get(PUSH2, p).get("data") or {}
        if not d.get("diff"):
            break
        rows.extend(d["diff"])
        total = d.get("total", len(rows))
        if len(rows) >= total:
            break
        page += 1
        time.sleep(0.35)
    out = []
    for x in rows:
        out.append({
            "code": x.get("f12"), "name": x.get("f14"),
            "price": _num(x.get("f2")), "pct": _num(x.get("f3")),
            "amount": _num(x.get("f6")),
            "turnover": _num(x.get("f8")), "vol_ratio": _num(x.get("f10")),
            "pe": _num(x.get("f9")), "speed": _num(x.get("f22")),
            "pb": _num(x.get("f23")), "chg60": _num(x.get("f24")),
            "mktcap": _num(x.get("f20")), "float_mv": _num(x.get("f21")),
            "main_in": _num(x.get("f62")),
        })
    return out


def _snapshot_sina():
    """新浪全市场快照（东财被反爬时的兜底，无主力净流入/量比字段）。"""
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    page, rows = 1, []
    while True:
        p = {"num": 100, "page": page, "node": "hs_a", "sort": "code", "asc": 1}
        for attempt in range(3):
            try:
                data = requests.get(url, params=p, timeout=15, headers={
                    "User-Agent": H["User-Agent"], "Referer": "https://finance.sina.com.cn"}).json()
                break
            except Exception:
                time.sleep(2 + 2 * attempt)
                data = []
        if not data:
            break
        rows.extend(data)
        if len(data) < 100:
            # 短页可能是网络抖动截断，重试一次确认真到底
            time.sleep(1.2)
            p2 = {**p, "page": page}
            try:
                data2 = requests.get(url, params=p2, timeout=15, headers={
                    "User-Agent": H["User-Agent"], "Referer": "https://finance.sina.com.cn"}).json()
            except Exception:
                data2 = []
            if not data2:
                break
            rows.extend(data2)
            if len(data2) < 100:
                break
        page += 1
        time.sleep(0.45)
    return [{"code": x.get("code"), "name": x.get("name"),
             "price": _num(x.get("trade")), "pct": _num(x.get("changepercent")),
             "amount": _num(x.get("amount")), "turnover": _num(x.get("turnoverratio")),
             "vol_ratio": None, "pe": None, "pb": None, "speed": None, "chg60": None,
             "mktcap": (_num(x.get("mktcap")) or 0) * 1e4,
             "float_mv": (_num(x.get("nmc")) or 0) * 1e4, "main_in": None}
            for x in rows if x.get("code")]


def market_snapshot():
    """全市场沪深京A股快照。9:25-9:30 调用时 price=竞价撮合价、amount=竞价成交额。
    主源东财，失败自动切新浪；返回 (rows, source)。"""
    try:
        rows = _snapshot_em()
        if len(rows) > 3000:
            return rows, "eastmoney"
    except Exception:
        pass
    return _snapshot_sina(), "sina"


def boards(kind="concept"):
    """板块列表：f3涨跌幅 f62主力净流入 f104上涨家数 f105下跌家数 f128领涨股 f136领涨股涨幅。"""
    fs = "m:90 t:2" if kind == "concept" else "m:90 t:1"
    p = {"pn": 1, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
         "fs": fs, "fields": "f3,f12,f14,f62,f104,f105,f128,f136"}
    diff = (_get(PUSH2, p).get("data") or {}).get("diff") or []
    return [{"code": x.get("f12"), "name": x.get("f14"), "pct": _num(x.get("f3")),
             "main_in": _num(x.get("f62")), "up": _num(x.get("f104")),
             "down": _num(x.get("f105")), "leader": x.get("f128"),
             "leader_pct": _num(x.get("f136"))} for x in diff]


def board_cons(board_code):
    """板块成分股（首页按涨幅降序，500只足够看梯队）。"""
    p = {"pn": 1, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fid": "f3",
         "fs": f"b:{board_code}", "fields": "f2,f3,f6,f8,f12,f14,f20,f21,f62"}
    diff = (_get(PUSH2, p).get("data") or {}).get("diff") or []
    return [{"code": x.get("f12"), "name": x.get("f14"), "pct": _num(x.get("f3")),
             "amount": _num(x.get("f6")), "float_mv": _num(x.get("f21")),
             "main_in": _num(x.get("f62"))} for x in diff]


def sina_quotes(symbols):
    """新浪行情批量（带重试）：A/指数格式返回 [名称,今开,昨收,最新,最高,最低,...]; 期指 hf_ 返回 [最新,..,时间,昨结,...]"""
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    last = None
    for i in range(3):
        try:
            r = requests.get(url, headers={"Referer": "https://finance.sina.com.cn", **H},
                             timeout=10)
            r.encoding = "gbk"
            break
        except Exception as e:
            last = e
            time.sleep(2 + 2 * i)
    else:
        raise last
    out = {}
    for line in r.text.strip().splitlines():
        if "=" not in line:
            continue
        sym = line.split("=")[0].replace("var hq_str_", "").strip()
        f = line.split('"')[1].split(",") if '"' in line else []
        if sym.startswith("hf_"):
            out[sym] = {"price": _num(f[0]), "high": _num(f[4]), "low": _num(f[5]),
                        "time": f[6], "prev": _num(f[7]), "open": _num(f[8]),
                        "name": f[13] if len(f) > 13 else sym}
        elif f and f[0]:
            out[sym] = {"name": f[0], "open": _num(f[1]), "prev": _num(f[2]),
                        "price": _num(f[3]), "high": _num(f[4]), "low": _num(f[5])}
    return out


SINA_KLINE = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
              "CN_MarketData.getKLineData")


def tencent_index_pct(symbols):
    """腾讯指数行情：q=s_sh000001 → name~code~price~chg~pct~...。返回 {sym: (名称, 涨跌幅%)}"""
    url = "https://qt.gtimg.cn/q=" + ",".join("s_" + s for s in symbols)
    for i in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": H["User-Agent"]}, timeout=10)
            r.encoding = "gbk"
            break
        except Exception:
            time.sleep(1.5 * (i + 1))
    else:
        return {}
    out = {}
    for line in r.text.strip().splitlines():
        if '"' not in line:
            continue
        f = line.split('"')[1].split("~")
        if len(f) > 5 and f[2]:
            out[f[2]] = (f[1], _num(f[5]))
    return out


def index_pct(symbols):
    """A股指数涨跌幅：腾讯主源，新浪 hq 兜底。返回 {symbol: (名称, 涨跌幅%)}"""
    res = tencent_index_pct(symbols)
    if res:
        return res
    q = sina_quotes(symbols)
    res = {}
    for s, v in q.items():
        price, prev = v.get("price"), v.get("prev")
        if price and prev:
            res[s] = (v.get("name", s), round((price / prev - 1) * 100, 2))
    return res


def sina_kline_closes(symbol, datalen=7):
    """新浪指数日K收盘序列（东财K线限流时的兜底）。symbol 如 sh000016。"""
    p = {"symbol": symbol, "scale": 240, "ma": "no", "datalen": datalen}
    for i in range(3):
        try:
            data = requests.get(SINA_KLINE, params=p, headers={
                "Referer": "https://finance.sina.com.cn", **H}, timeout=10).json()
            return [float(d["close"]) for d in data]
        except Exception:
            time.sleep(1.5 * (i + 1))
    return []


def pct5_dual(secid, sina_symbol):
    """近5日涨跌幅：东财K线优先，新浪兜底。"""
    v = kline_pct5(secid)
    if v is not None:
        return v
    closes = sina_kline_closes(sina_symbol)
    if len(closes) >= 6:
        return round((closes[-1] / closes[-6] - 1) * 100, 2)
    return None


def kline_pct5(secid):
    """近5日涨跌幅（用于跷跷板相对强弱）。"""
    p = {"secid": secid, "fields1": "f1,f2,f3", "fields2": "f51,f53",
         "klt": 101, "fqt": 1, "end": "20500101", "lmt": 7}
    try:
        ks = (_get(KLINE, p).get("data") or {}).get("klines") or []
        closes = [float(k.split(",")[1]) for k in ks]
        if len(closes) >= 6:
            return round((closes[-1] / closes[-6] - 1) * 100, 2)
    except Exception:
        pass
    return None


def global_indices():
    """全球指数：日经/韩国KOSPI/恒生/隔夜美股三大指。"""
    p = {"secids": "100.N225,100.KS11,100.HSI,100.DJIA,100.SPX,100.NDX",
         "fields": "f2,f3,f4,f12,f14", "fltt": 2, "invt": 2, "np": 1}
    try:
        diff = (_get(ULIST, p).get("data") or {}).get("diff") or []
        return [{"code": x.get("f12"), "name": x.get("f14"), "price": _num(x.get("f2")),
                 "pct": _num(x.get("f3"))} for x in diff]
    except Exception:
        return []


SINA_NODE = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
             "Market_Center.getHQNodeData")


def sina_industries():
    """新浪行业板块实时涨跌（东财板块限流时的第二兜底，含领涨股）。"""
    r = requests.get("https://money.finance.sina.com.cn/q/view/newFLJK.php",
                     params={"param": "industry"},
                     headers={"User-Agent": H["User-Agent"], "Referer": "https://finance.sina.com.cn"},
                     timeout=12)
    r.encoding = "gbk"
    body = r.text.split("=", 1)[1].strip().rstrip(";")
    data = json.loads(body)
    out = []
    for v in data.values():
        f = v.split(",")
        if len(f) < 5:
            continue
        out.append({"code": "SINA:" + f[0], "name": f[1], "pct": _num(f[4]),
                    "main_in": None, "type": "industry",
                    "leader": f[12] if len(f) > 12 else "",
                    "leader_pct": _num(f[9]) if len(f) > 9 else None})
    return out


def sina_node_members(node):
    """新浪板块成分股（配合 sina_industries 的 SINA:xx 代码）。"""
    page, rows = 1, []
    while page <= 6:
        p = {"num": 80, "page": page, "node": node, "sort": "amount", "asc": 0}
        for i in range(3):
            try:
                data = requests.get(SINA_NODE, params=p, timeout=15, headers={
                    "User-Agent": H["User-Agent"], "Referer": "https://finance.sina.com.cn"}).json()
                break
            except Exception:
                time.sleep(1.5 * (i + 1))
                data = []
        if not data:
            break
        rows.extend(data)
        if len(data) < 80:
            break
        page += 1
        time.sleep(0.4)
    return [{"code": x.get("code"), "name": x.get("name"),
             "price": _num(x.get("trade")), "pct": _num(x.get("changepercent")),
             "amount": _num(x.get("amount")), "turnover": _num(x.get("turnoverratio")),
             "float_mv": (_num(x.get("nmc")) or 0) * 1e4, "main_in": None}
            for x in rows if x.get("code")]


_THS_CACHE = {"at": 0.0, "data": None, "kind": None}


def ths_fund_flow(kind="industry", ttl=25):
    """同花顺行业/概念即时资金流（东财限流时的主力资金源，单位亿元，带TTL节流防封）。"""
    now = time.time()
    if _THS_CACHE["data"] is not None and _THS_CACHE["kind"] == kind and now - _THS_CACHE["at"] < ttl:
        return _THS_CACHE["data"]
    import akshare as ak
    if kind == "industry":
        df = ak.stock_fund_flow_industry(symbol="即时")
        nm, lead = "行业", "领涨股"
    else:
        df = ak.stock_fund_flow_concept(symbol="即时")
        nm, lead = "概念", "领涨股"
    out = []
    for _, row in df.iterrows():
        try:
            out.append({
                "code": f"THS{kind[0].upper()}:{row[nm]}",
                "name": str(row[nm]),
                "pct": _num(row.get(f"{nm}-涨跌幅") if f"{nm}-涨跌幅" in df.columns else row.get("行业-涨跌幅")),
                "main_in": (_num(row.get("净额")) or 0) * 1e8,
                "type": kind,
                "leader": str(row.get(lead) or ""),
                "leader_pct": _num(row.get(f"{lead}-涨跌幅")),
            })
        except Exception:
            continue
    _THS_CACHE.update({"at": now, "data": out, "kind": kind})
    return out


def zt_pool(date):
    """东财涨停股池，含连板数/炸板次数/涨停统计/所属行业。"""
    import akshare as ak
    df = ak.stock_zt_pool_em(date=date)
    cols = {"代码": "code", "名称": "name", "涨跌幅": "pct", "成交额": "amount",
            "流通市值": "float_mv", "换手率": "turnover", "封板资金": "seal_money",
            "炸板次数": "break_times", "涨停统计": "zt_stat", "连板数": "lbc",
            "所属行业": "industry"}
    return [ {v: row[k] for k, v in cols.items() if k in df.columns}
             for _, row in df.iterrows() ]


def zt_pool_previous(date):
    """昨日涨停股池今日表现（盘中/竞价阶段=竞价涨幅，可算昨日涨停溢价）。"""
    import akshare as ak
    df = ak.stock_zt_pool_previous_em(date=date)
    cols = {"代码": "code", "名称": "name", "涨跌幅": "pct", "成交额": "amount",
            "换手率": "turnover", "昨日连板数": "lbc", "连板数": "lbc",
            "涨停统计": "zt_stat", "所属行业": "industry"}
    return [ {v: row[k] for k, v in cols.items() if k in df.columns}
             for _, row in df.iterrows() ]


def dt_pool(date):
    """跌停股池。"""
    import akshare as ak
    df = ak.stock_zt_pool_dtgc_em(date=date)
    cols = {"代码": "code", "名称": "name", "涨跌幅": "pct", "成交额": "amount",
            "流通市值": "float_mv", "换手率": "turnover", "封单资金": "seal_money",
            "连板数": "lbc", "所属行业": "industry"}
    return [ {v: row[k] for k, v in cols.items() if k in df.columns}
             for _, row in df.iterrows() ]


def is_trade_date(today_str):
    """交易日判断，读本地缓存（每日更新一次）。"""
    import akshare as ak
    cache = OUT / "trade_dates.json"
    today = today_str
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
    else:
        data = {}
    if data.get("fetched") != today:
        hist = ak.tool_trade_date_hist_sina()
        days = [str(d)[0:10].replace("-", "") for d in hist["trade_date"].tolist()]
        data = {"fetched": today, "days": days}
        cache.write_text(json.dumps(data), encoding="utf-8")
    return today in data["days"]


def prev_trade_date(today_str):
    cache = OUT / "trade_dates.json"
    if cache.exists():
        days = json.loads(cache.read_text(encoding="utf-8")).get("days", [])
    else:
        is_trade_date(today_str)
        days = json.loads(cache.read_text(encoding="utf-8")).get("days", [])
    past = [d for d in days if d < today_str]
    return past[-1] if past else None


def news_cls(limit=18):
    """财联社电报（最新优先）。"""
    import akshare as ak
    df = ak.stock_info_global_cls(symbol="全部")
    items = []
    for _, row in df.head(limit).iterrows():
        items.append({"time": f"{row['发布日期']}{row['发布时间']}" if "发布日期" in df.columns else str(row.get("发布时间", "")),
                      "title": str(row["标题"]), "content": str(row.get("内容", ""))[:120]})
    return items


def news_breakfast(limit=15):
    """东财财经早餐/要闻。"""
    import akshare as ak
    df = ak.stock_info_cjzc_em()
    return [{"time": str(row["发布时间"]), "title": str(row["标题"]),
             "content": str(row.get("摘要", ""))[:100]}
            for _, row in df.head(limit).iterrows()]


def save(name, text):
    p = OUT / name
    p.write_text(text, encoding="utf-8")
    return p
