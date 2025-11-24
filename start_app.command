#!/bin/bash
# 获取当前脚本所在目录
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# 激活虚拟环境 (确保这里 venv 名字和你的一样)
source venv/bin/activate

# 运行 Streamlit，并自动打开浏览器
echo "正在启动跟读助手..."
streamlit run app.py