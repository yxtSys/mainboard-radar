# -*- coding: utf-8 -*-
"""
因子库（可溯源）：每个因子 = 名称 + 公式 + 数据来源 + 计算值。
所有策略评分、多角色研判都从这里取数，禁止黑箱。
来源缩写: EM=东方财富行情接口 THS=同花顺资金流 SINA=新浪行情 GT=腾讯行情 CLS=财联社电报
"""
FACTORS = [
    {"key": "pct",        "name": "当日涨跌幅",     "formula": "(现价/昨收-1)*100",                    "source": "EM/新浪快照"},
    {"key": "turnover",   "name": "换手率",         "formula": "成交量/流通股本*100",                  "source": "EM/新浪快照"},
    {"key": "amt_yi",     "name": "成交额(亿)",     "formula": "当日累计成交金额/1e8",                 "source": "EM/新浪快照"},
    {"key": "main_in_yi", "name": "主力净流入(亿)", "formula": "大单+特大单净额/1e8",                  "source": "EM f62 / THS"},
    {"key": "chg60",      "name": "60日涨跌幅",     "formula": "(现价/60日前收盘-1)*100",              "source": "EM f24"},
    {"key": "pe",         "name": "市盈率PE(动)",   "formula": "总市值/滚动净利",                      "source": "EM f9"},
    {"key": "pb",         "name": "市净率PB",       "formula": "股价/每股净资产",                      "source": "EM f23"},
    {"key": "float_yi",   "name": "流通市值(亿)",   "formula": "流通股本*现价/1e8",                    "source": "EM/新浪快照"},
    {"key": "zt_premium", "name": "昨涨停溢价",     "formula": "昨日涨停股今日涨幅均值",               "source": "EM push2ex"},
    {"key": "break_rate", "name": "炸板率",         "formula": "炸板数/(炸板数+涨停数)*100",           "source": "EM push2ex"},
    {"key": "a50",        "name": "A50期指",        "formula": "(期指现价/昨结-1)*100",                "source": "新浪 hf_CHA50CFD"},
    {"key": "nq",         "name": "纳指期货",       "formula": "(期指现价/昨结-1)*100",                "source": "新浪 hf_NQ"},
    {"key": "lbc",        "name": "连板身位",       "formula": "昨日涨停池连板数",                     "source": "EM push2ex"},
    {"key": "event_days", "name": "事件窗口天数",   "formula": "距季报披露窗/期指交割/重大会议的剩余自然日", "source": "交易日历(可溯源,免费)"},
    {"key": "ambush",     "name": "埋伏资金分",     "formula": "低位(chg60<-15)+主力净流入为正+换手5~15% → 吸筹轨迹代理分0~100", "source": "EM f24/f62派生"},
]


def compute_factors(s, ctx=None):
    """从快照行计算因子值；缺数据记 None（不伪造）。"""
    ctx = ctx or {}
    f = {
        "pct": s.get("pct"),
        "turnover": s.get("turnover"),
        "amt_yi": round((s.get("amount") or 0) / 1e8, 2) if s.get("amount") else None,
        "main_in_yi": round((s.get("main_in") or 0) / 1e8, 2) if s.get("main_in") is not None else None,
        "chg60": s.get("chg60"),
        "pe": s.get("pe"),
        "pb": s.get("pb"),
        "float_yi": round((s.get("float_mv") or 0) / 1e8, 1) if s.get("float_mv") else None,
        "lbc": (ctx.get("prev_zt") or {}).get(str(s.get("code"))),
        "zt_premium": ctx.get("zt_premium"),
        "break_rate": ctx.get("break_rate"),
        "a50": ctx.get("a50"),
        "nq": ctx.get("nq"),
    }
    return f
