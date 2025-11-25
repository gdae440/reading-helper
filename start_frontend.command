#!/bin/bash
cd "$(dirname "$0")/frontend"
echo "🚀 正在启动前端..."
echo "🌐 开放局域网访问..."
npm run dev -- --host
