@echo off
chcp 65001 >nul
cd /d %~dp0
echo ============================================
echo   主板雷达 启动中...
echo   本地访问: http://127.0.0.1:8787
echo   局域网手机访问: http://本机IP:8787 (如 192.168.1.10:8787)
echo ============================================
start "radar-server" cmd /k python server.py
timeout /t 3 >nul
start "radar-tunnel" cmd /k cloudflared.exe tunnel --url http://127.0.0.1:8787 --no-autoupdate
echo.
echo 已启动两个窗口。
echo   1) radar-server 窗口 = 网站服务
echo   2) radar-tunnel 窗口 = 公网链接，等约10秒后窗口里会出现
echo      https://xxxx.trycloudflare.com  这就是全平台可访问的链接
echo 注意: 公网链接每次重启会变化；电脑关机则链接失效。
pause
