#!/bin/bash
cd "$(dirname "$0")"
echo "🚀 正在启动后端..."
echo "📡 激活虚拟环境..."
source venv/bin/activate || { echo "❌ 虚拟环境激活失败，请检查 venv 文件夹"; exit 1; }
echo "🌐 开放局域网访问 (0.0.0.0:8000)"
uvicorn backend:app --reload --host 0.0.0.0 --port 8000
