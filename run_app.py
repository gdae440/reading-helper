import os
import subprocess
import socket
import time
import sys
import signal

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# 获取本机 IP
ip = get_local_ip()

print("=" * 50)
print(f"🚀 正在启动跟读助手 Pro ...")
print(f"📡 本机 IP 地址: {ip}")
print("=" * 50)

# 定义命令
# 后端：绑定 0.0.0.0 允许外部访问
backend_cmd = f"uvicorn backend:app --reload --host 0.0.0.0 --port 8000"
# 前端：绑定 0.0.0.0
frontend_cmd = f"npm run dev -- --host"

print(f"1️⃣  启动后端 (API): http://{ip}:8000")
# 使用 shell=True 在新进程中运行，但这在 VS Code 终端里会占用当前窗口
# 为了方便，我们建议用户分别运行，或者我们尝试用 subprocess 开启

print("-" * 50)
print("⚠️  请务必执行以下操作：")
print(f"❌ 关闭所有正在运行的终端 (Ctrl+C)")
print("-" * 50)
print("👉 请新建两个终端窗口，分别运行以下命令：")
print("")
print(f"【终端 1 (后端)】:  {backend_cmd}")
print("")
print(f"【终端 2 (前端)】:  cd frontend && {frontend_cmd}")
print("")
print("-" * 50)
print(f"📱 手机访问地址:  http://{ip}:5173")
print("=" * 50)