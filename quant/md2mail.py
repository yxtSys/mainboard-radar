# -*- coding: utf-8 -*-
"""简报 Markdown → 手机深色卡片 HTML（QQ邮箱直接渲染，无##和表格线残留）。"""
import html as _html
import re


def _inline(s):
    s = _html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b class='w'>\1</b>", s)
    s = s.replace("🔴利好", "<span class='tag r'>利好</span>").replace("🟢利空", "<span class='tag g'>利空</span>")
    s = s.replace("🔴", "<span class='dot r'></span>").replace("🟢", "<span class='dot g'></span>")
    s = re.sub(r"([+\-]\d+\.?\d*)%", lambda m: f"<b class=\"{'up' if not m.group(1).startswith('-') else 'dn'}\">{m.group(1)}%</b>", s)
    s = re.sub(r"(?<![\d%])([+\-]\d+\.?\d*亿)", lambda m: f"<b class=\"{'up' if not m.group(1).startswith('-') else 'dn'}\">{m.group(1)}</b>", s)
    return s


def render(md_text, title=""):
    lines = md_text.splitlines()
    out, i = [], 0
    h1 = ""
    while i < len(lines):
        l = lines[i]
        if l.startswith("# "):
            h1 = l[2:].strip(); i += 1; continue
        if l.startswith("## "):
            out.append(f"<h2>{_inline(l[3:].strip())}</h2>"); i += 1; continue
        if l.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]*", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                hdr = rows[0]
                body = rows[1:]
                out.append("<div class='tbl'>")
                for r in body:
                    cells_html = "".join(
                        f"<div class='kv'><span class='k'>{_inline(h)}</span><span class='v'>{_inline(v)}</span></div>"
                        for h, v in zip(hdr, r) if v)
                    out.append(f"<div class='tcard'>{cells_html}</div>")
                out.append("</div>")
            continue
        if l.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(lines[i][2:].strip()); i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
            continue
        if l.strip():
            out.append(f"<p>{_inline(l.strip())}</p>")
        i += 1
    body = "\n".join(out)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#050507;color:#e8ecf4;font:15px/1.65 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:14px">
<div style="max-width:640px;margin:0 auto">
<div style="background:linear-gradient(135deg,#1a1220,#0b0b14);border:1px solid #2a2a3a;border-radius:16px;padding:16px;margin-bottom:12px">
<div style="font-size:20px;font-weight:800;color:#fff">🀄 {title or _html.escape(h1)}</div>
<div style="font-size:11px;color:#8a8a9a;margin-top:2px">主板雷达 · 自动推送 · 不构成投资建议</div></div>
<style>
h2{{font-size:16px;color:#fff;margin:18px 0 8px;padding-left:10px;border-left:4px solid #5b8cff;background:rgba(91,140,255,.08);border-radius:4px;padding:6px 10px}}
p{{margin:6px 0;color:#c9cfda}}
ul{{list-style:none;padding:0;margin:6px 0}}
li{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:8px 10px;margin:6px 0}}
.tag{{padding:1px 7px;border-radius:6px;font-size:12px;font-weight:700}}
.tag.r{{background:#3a1516;color:#ff8a80;border:1px solid rgba(255,59,48,.4)}}
.tag.g{{background:#0f2f22;color:#5fe8a8;border:1px solid rgba(34,224,108,.4)}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px}}
.dot.r{{background:#ff3b30}}.dot.g{{background:#22e06c}}
.w{{color:#fff}}
.up{{color:#ff7a70}}.dn{{color:#5fe8a8}}
.tbl{{display:grid;gap:8px}}
.tcard{{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);border-radius:12px;padding:10px}}
.kv{{display:flex;justify-content:space-between;gap:8px;padding:2px 0;font-size:13px}}
.k{{color:#8a8a9a;flex:0 0 auto}}
.v{{text-align:right}}
b{{font-weight:700}}
</style></div></body></html>"""
