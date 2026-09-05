# -*- coding: utf-8 -*-
"""
快讯过滤与板块归类（可溯源）：仿 news-stock-selector / 东财快讯的做法——
只保留金融相关条目，按板块关键词归类，命中个股标注代码。来源：财联社电报。
"""
SECTOR_MAP = {
    "半导体": ["半导体", "芯片", "晶圆", "光刻", "存储", "封测"],
    "白酒": ["白酒", "酒企", "茅台", "五粮液"],
    "养殖农业": ["养殖", "生猪", "猪价", "种业", "转基因", "粮食", "饲料", "农业"],
    "军工": ["军工", "国防", "导弹", "航发", "军贸"],
    "银行保险": ["银行", "保险", "券商", "证券", "金融"],
    "医药医疗": ["医药", "创新药", "医疗", "疫苗", "CXO", "中药"],
    "光伏": ["光伏", "组件", "硅料", "硅片", "电池片"],
    "新能源车": ["新能源车", "锂电", "电池", "充电桩", "车企", "智能驾驶", "固态电池"],
    "有色": ["有色", "铜", "铝", "锂", "稀土", "工业金属"],
    "煤炭石油": ["煤炭", "原油", "石油", "油气", "WTI", "布伦特"],
    "电力": ["电力", "电网", "核电", "水电", "电价"],
    "地产基建": ["地产", "房地产", "基建", "保障房", "城投"],
    "计算机AI": ["AI", "人工智能", "算力", "数据中心", "软件", "信创", "大模型", "英伟达"],
    "传媒游戏": ["游戏", "传媒", "影视", "版号", "短剧"],
    "通信": ["通信", "光模块", "5G", "6G", "卫星"],
    "机械": ["机械", "机器人", "机床", "工程机械"],
    "化工": ["化工", "纯碱", "树脂", "氟化工", "磷"],
    "航运交运": ["航运", "港口", "集运", "运价", "航空", "高铁"],
    "消费旅游": ["旅游", "免税", "消费", "零售", "餐饮"],
    "黄金": ["黄金", "金价", "贵金属", "白银"],
    "钢铁建材": ["钢铁", "水泥", "玻璃", "建材"],
    "家电纺服": ["家电", "白电", "纺织", "服装"],
}
MACRO_WORDS = ["美联储", "央行", "降准", "降息", "LPR", "CPI", "PPI", "PMI", "社融", "GDP",
               "国常会", "证监会", "交易所", "IPO", "注册制", "关税", "出口管制", "汇率", "人民币",
               "北向", "融资余额", "两市成交", "沪指", "深成指", "创业板", "A股", "美股", "港股",
               "日经", "韩国", "纳指", "标普", "涨跌", "涨停", "成交额"]
NOISE_WORDS = ["台风", "地震", "袭击", "空难", "爆炸", "遇难", "火灾", "洪水", "劫持", "婚礼", "离婚", "演唱会", "世界杯"]


def _hits(text, words):
    return [w for w in words if w in text]


def filter_and_tag(items, board_names=None, name2code=None):
    """items: [{title, tag, time}] → 只留金融相关，打板块/个股标签。
    返回 (kept, dropped_count)。kept 增加字段: sectors, stock_hits, source。"""
    board_names = board_names or []
    name2code = name2code or {}
    kept, dropped = [], 0
    for n in items:
        text = n.get("title", "") + " " + n.get("content", "")
        if not n.get("title"):
            dropped += 1
            continue
        sectors = []
        for sec, kws in SECTOR_MAP.items():
            if _hits(text, kws):
                sectors.append(sec)
        # 板块名直接命中（用实时板块名做二次归类）
        for bn in board_names:
            if len(bn) >= 2 and bn in text and bn not in sectors:
                sectors.append(bn)
        # 个股命中
        stock_hits = []
        for nm, code in name2code.items():
            if len(nm) >= 3 and nm in text:
                stock_hits.append({"code": code, "name": nm})
                if len(stock_hits) >= 3:
                    break
        macro = _hits(text, MACRO_WORDS)
        noisy = _hits(text, NOISE_WORDS)
        if not sectors and not macro and not stock_hits:
            dropped += 1
            continue  # 与金融无关 → 丢弃
        if noisy and not sectors and not stock_hits and len(macro) == 0:
            dropped += 1
            continue
        kept.append({**n, "sectors": sectors[:3] or (["宏观/海外"] if macro else []),
                     "macro": macro[:3], "stock_hits": stock_hits, "source": "财联社电报"})
    return kept, dropped
