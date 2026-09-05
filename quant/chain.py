# -*- coding: utf-8 -*-
"""
产业链图谱（可溯源）：内置主流链条模板（上游/中游/下游 + 锚定概念），
个股按"主营构成关键词 + 所属行业 + 名称"定位链条位置；同行公司取自
东财概念成分（云端可用）或本机降级（涨停池同行业+快照关键词匹配）。
来源：主营构成=东方财富数据中心(F10)；成分=东财 push2/涨停池。
"""
import time

CHAINS = {
    "半导体": {"anchors": ["半导体", "芯片概念", "国家大基金持股"], "industry_kw": ["半导体", "电子"],
              "stages": [
                  {"pos": "上游(设备/材料)", "kws": ["硅片", "光刻", "电子化学", "气体", "靶材", "设备", "抛光", "掩膜"]},
                  {"pos": "中游(设计/制造/封测)", "kws": ["芯片", "晶圆", "代工", "封测", "存储", "功率", "设计", "图像传感"]},
                  {"pos": "下游(应用)", "kws": ["消费电子", "汽车电子", "服务器", "手机", "模组", "安防"]}]},
    "AI算力": {"anchors": ["算力", "CPO", "光模块", "数据中心"], "industry_kw": ["通信", "计算机", "IT服务"],
              "stages": [
                  {"pos": "上游(光器件/PCB)", "kws": ["光模块", "光器件", "PCB", "覆铜板", "连接器", "电源"]},
                  {"pos": "中游(服务器/整机)", "kws": ["服务器", "整机", "数据中心", "IDC", "交换机"]},
                  {"pos": "下游(应用)", "kws": ["大模型", "软件", "云计算", "游戏", "传媒"]}]},
    "新能源车/锂电": {"anchors": ["新能源汽车", "锂电池", "新能源整车"], "industry_kw": ["汽车", "电池", "能源"],
              "stages": [
                  {"pos": "上游(资源/材料)", "kws": ["锂", "钴", "镍", "正极", "负极", "隔膜", "电解液", "矿产"]},
                  {"pos": "中游(电池/零部件)", "kws": ["电池", "电芯", "电机", "电控", "零部件", "热管理"]},
                  {"pos": "下游(整车/运营)", "kws": ["整车", "汽车", "充电桩", "换电"]}]},
    "光伏": {"anchors": ["光伏", "HIT电池", "太阳能"], "industry_kw": ["光伏", "电力", "能源"],
              "stages": [
                  {"pos": "上游(硅料/硅片)", "kws": ["硅料", "多晶硅", "硅片", "硅"]},
                  {"pos": "中游(电池/组件)", "kws": ["电池片", "组件", "逆变器", "支架", "HJT"]},
                  {"pos": "下游(电站)", "kws": ["电站", "运营", "EPC", "分布式"]}]},
    "医药医疗": {"anchors": ["创新药", "医疗器械", "CXO"], "industry_kw": ["医药", "医疗", "生物"],
              "stages": [
                  {"pos": "上游(原料/耗材)", "kws": ["原料药", "中间体", "耗材", "化学制药", "生物制品"]},
                  {"pos": "中游(研发/制造)", "kws": ["创新药", "疫苗", "器械", "CXO", "诊断", "制药"]},
                  {"pos": "下游(流通/服务)", "kws": ["流通", "药店", "医院", "服务"]}]},
    "白酒/食品": {"anchors": ["白酒概念", "食品饮料", "预制菜"], "industry_kw": ["白酒", "食品", "饮料"],
              "stages": [
                  {"pos": "上游(原料)", "kws": ["包装", "粮食", "种植", "玻璃", "农牧"]},
                  {"pos": "中游(酿造/加工)", "kws": ["白酒", "啤酒", "乳制品", "调味", "食品", "预制菜", "酒", "茅台", "酿造"]},
                  {"pos": "下游(渠道)", "kws": ["商业", "零售", "连锁", "经销商"]}]},
    "养殖农业": {"anchors": ["养殖业", "饲料", "转基因", "猪肉"], "industry_kw": ["养殖", "农业", "饲料", "种植"],
              "stages": [
                  {"pos": "上游(种源/饲料)", "kws": ["种业", "饲料", "疫苗", "动保", "转基因"]},
                  {"pos": "中游(养殖/种植)", "kws": ["养殖", "生猪", "水产", "种植", "大豆"]},
                  {"pos": "下游(加工)", "kws": ["食品", "屠宰", "加工", "预制"]}]},
    "军工": {"anchors": ["军工", "大飞机", "军贸"], "industry_kw": ["军工", "航天", "航空", "国防"],
              "stages": [
                  {"pos": "上游(材料/元器件)", "kws": ["钛合金", "碳纤维", "电子元件", "红外", "特种"]},
                  {"pos": "中游(分系统/制造)", "kws": ["航发", "雷达", "导弹", "锻件", "船舶"]},
                  {"pos": "下游(主机厂)", "kws": ["飞机", "舰船", "整车", "主机"]}]},
    "金融": {"anchors": ["券商", "银行", "保险"], "industry_kw": ["证券", "银行", "保险", "多元金融"],
              "stages": [
                  {"pos": "上游(资金/基础设施)", "kws": ["银行", "指数", "信息"]},
                  {"pos": "中游(机构)", "kws": ["券商", "证券", "保险", "信托", "期货"]},
                  {"pos": "下游(服务)", "kws": ["财富", "资管", "科技"]}]},
}

_cache = {}


def locate_chain(zygc_rows, industry, name):
    """按主营构成关键词→行业→名称 逐级定位，返回命中的链条与位置。"""
    text_parts = []
    for r in zygc_rows or []:
        text_parts.append(str(r.get("构成", "")))
    text_parts.append(str(industry or ""))
    text_parts.append(str(name or ""))
    text = " ".join(text_parts)
    hits = []
    for cname, c in CHAINS.items():
        best = None
        for st in c["stages"]:
            for kw in st["kws"]:
                if kw in text:
                    if best is None:
                        best = st["pos"]
                    hits.append({"chain": cname, "pos": st["pos"], "matched": kw})
                    break
    # 去重同链条取第一个命中位置
    seen, result = set(), []
    for h in hits:
        if h["chain"] not in seen:
            seen.add(h["chain"])
            result.append(h)
    return result[:3]


def _chain_peers_em(chain, exclude_code):
    """东财概念成分（本机可能限流；Actions 环境通常可用）。"""
    import akshare as ak
    import pandas as pd
    out, pos_map = [], {}
    for anchor in CHAINS[chain]["anchors"]:
        try:
            df = ak.stock_board_concept_cons_em(symbol=anchor)
            for _, r in df.iterrows():
                code = str(r.get("代码") or r.get("code"))
                if code == exclude_code:
                    continue
                pos_map.setdefault(code, {"code": code, "name": str(r.get("名称") or r.get("name")), "mv": float(r.get("流通市值") or 0)})
        except Exception:
            continue
    if pos_map:
        top = sorted(pos_map.values(), key=lambda x: -x["mv"])[:12]
        return [{"code": x["code"], "name": x["name"], "src": "东财概念成分"} for x in top]
    return []


def _chain_peers_fallback(chain, snap, zt):
    """降级：名称/主营关键词匹配快照 + 涨停池同方向，按成交额排序。"""
    kws = [kw for st in CHAINS[chain]["stages"] for kw in st["kws"]]
    out = []
    for s in snap:
        nm = str(s.get("name") or "")
        if s["code"] and any(kw in nm for kw in kws):
            out.append({"code": s["code"], "name": nm, "amt": s.get("amount") or 0, "src": "关键词匹配"})
    for z in zt:
        if chain in str(z.get("industry", "")) or any(kw in str(z.get("industry", "")) for kw in kws):
            out.append({"code": str(z["code"]), "name": z["name"], "amt": z.get("amount") or 0, "src": "涨停池"})
    dedup = {}
    for x in out:
        dedup.setdefault(x["code"], x)
    top = sorted(dedup.values(), key=lambda x: -x["amt"])[:12]
    return [{"code": x["code"], "name": x["name"], "src": x["src"]} for x in top]


def chain_profile(code, zygc_rows, industry, name, snap=None, zt=None):
    """主入口：该股的产业链定位 + 同链条公司。"""
    key = f"{code}"
    hit = _cache.get(key)
    if hit and time.time() - hit["at"] < 1800:
        return hit["data"]
    locs = locate_chain(zygc_rows, industry, name)
    peers = []
    for loc in locs:
        if len(peers) >= 2:
            break
        p = _chain_peers_em(loc["chain"], code)
        if not p:
            p = _chain_peers_fallback(loc["chain"], snap or [], zt or [])
        if p:
            peers.append({"chain": loc["chain"], "position": loc["pos"], "companies": p[:10]})
    data = {"positions": locs, "peers": peers, "chains_known": list(CHAINS.keys())}
    _cache[key] = {"at": time.time(), "data": data}
    return data
