# -*- coding: utf-8 -*-
"""复盘 markdown → 手机友好的 HTML 邮件（卡片式、红涨绿跌）。"""
import html
import re

CSS = """body{background:#0b0e14;color:#e8ecf3;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;margin:0;padding:12px;font-size:14px;line-height:1.6}
h1{font-size:17px;color:#fff} h2{font-size:15px;color:#7fb0ff;border-left:4px solid #4f8cff;padding-left:8px;margin:18px 0 8px}
.card{background:#12161f;border:1px solid #232a38;border-radius:12px;padding:10px 12px;margin:8px 0}
li{margin:3px 0} ul{padding-left:18px;margin:6px 0}
.up{color:#ff6b60;font-weight:700}.dn{color:#3fd68f;font-weight:700}
b{color:#fff} table{width:100%;border-collapse:collapse;font-size:12.5px}
td{padding:3px 4px;border-top:1px solid #1d2432}
.small{color:#8a93a5;font-size:11.5px}"""


def _colorize(s):
    s = re.sub(r"([+\-]?\d+\.?\d*)%", lambda m: f'<span class="{"up" if not m.group(1).startswith("-") else "dn"}">{m.group(1)}%</span>', s)
    return re.sub(r"([+-]\d+\.\d+)亿", lambda m: f'<span class="{"up" if not m.group(1).startswith("-") else "dn"}">{m.group(1)}亿</span>', s)


def to_html(md):
    out, in_list, in_table = ["<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><style>" + CSS + "</style></head><body>"], False, False
    def cl():
        o = ""
        if in_list:
            out.append("</ul>"); return True
        if in_table:
            out.append("</table>"); return True
        return False
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            cl(); in_list = in_table = False
            continue
        if line.startswith("|"):
            if not in_table:
                cl(); in_list = False; in_table = True
                out.append("<table>")
                cells = [c.strip() for c in line.strip("|").split("|")]
                if not all(set(c) <= set("-: ") for c in cells):
                    out.append("<tr>" + "".join(f"<td><b>{_colorize(html.escape(c))}</b></td>" for c in cells) + "</tr>")
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                out.append("<tr>" + "".join(f"<td>{_colorize(html.escape(c))}</td>" for c in cells) + "</tr>")
            continue
        cl(); in_list = in_table = False
        if line.startswith("## "):
            out.append("<h2>" + html.escape(line[3:]) + "</h2>")
        elif line.startswith("# "):
            out.append("<h1>" + html.escape(line[2:]) + "</h1>")
        elif line.startswith("- ") or line.startswith("  · "):
            if not in_list:
                out.append("<ul>"); in_list = True
            txt = _colorize(html.escape(line[2:].strip()))
            out.append(f"<li>{txt}</li>")
        else:
            out.append("<div class='card'>" + _colorize(html.escape(line)) + "</div>")
    out.append("</body></html>")
    return "\n".join(out)
