# -*- coding: utf-8 -*-
"""15:05 盘后复盘云任务：跑 review.py → 写 docs/data/review_latest.md → 邮件推送（secrets 存在才发）。"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
sys.path.insert(0, str(ROOT / 'quant'))
from md2html import to_html
import subprocess
import sys
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
r = subprocess.run([sys.executable, str(ROOT / "quant" / "review.py")],
                   capture_output=True, text=True, encoding="utf-8", timeout=600)
md = r.stdout
lines = [l for l in md.splitlines() if not l.startswith(("盘后复盘拉取中", "# 盘后复盘拉取中"))]
md = "\n".join(lines).strip()
today = md[:20]
if "休市" in md[:50]:
    print("休市，无复盘")
    sys.exit(0)
out = ROOT / "docs" / "data" / "review_latest.md"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("# 盘后复盘 · " + md.splitlines()[0].lstrip("# ").strip() + "\n\n" + md, encoding="utf-8")
print("已写入", out)

user, code, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_AUTH_CODE"), os.environ.get("MAIL_TO")
if user and code and to:
    try:
        msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(md, "plain", "utf-8"))
    msg.attach(MIMEText(to_html(md), "html", "utf-8"))
        msg["Subject"] = "主板雷达 · 盘后复盘 " + today[:10] if False else "主板雷达 · 盘后复盘"
        msg["From"], msg["To"] = user, to
        s = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=20)
        s.login(user, code)
        s.sendmail(user, [to], msg.as_string())
        s.quit()
        print("邮件已发送 →", to)
    except Exception as e:
        print("邮件失败:", str(e)[:120])
else:
    print("未配置SMTP secrets，跳过邮件")
