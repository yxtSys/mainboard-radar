# -*- coding: utf-8 -*-
"""邮件推送：python quant/mail_push.py <主题> <正文文件路径>。读取 quant/MAIL_CONFIG.json。"""
import json
import smtplib
import sys
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path

cfg = json.loads((Path(__file__).parent / "MAIL_CONFIG.json").read_text(encoding="utf-8"))
subject = sys.argv[1] if len(sys.argv) > 1 else "量化简报"
body_file = sys.argv[2] if len(sys.argv) > 2 else None
body = Path(body_file).read_text(encoding="utf-8") if (body_file and body_file != "-") else sys.stdin.read()

sys.path.insert(0, str(Path(__file__).parent))
import md2mail
msg = MIMEMultipart("alternative")
msg.attach(MIMEText(body, "plain", "utf-8"))
msg.attach(MIMEText(md2mail.render(body), "html", "utf-8"))
msg["Subject"] = Header(subject, "utf-8")
msg["From"] = cfg["sender"]
msg["To"] = ", ".join(cfg["recipients"])

srv = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=20)
srv.login(cfg["sender"], cfg["auth_code"])
srv.sendmail(cfg["sender"], cfg["recipients"], msg.as_string())
srv.quit()
print(f"邮件已发送: {subject} → {cfg['recipients']}")
